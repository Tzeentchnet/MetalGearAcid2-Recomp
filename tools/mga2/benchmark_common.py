#!/usr/bin/env python3
"""Shared helpers for deterministic Metal Gear Acid 2 benchmarks."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "out" / "build" / "clang-cl"
FIXED_GRAPHICS_PROFILE = {
    "renderer": "d3d12",
    "internal_resolution": "4",
    "texture_scale": "2",
    "d3d12_full_rate": "1",
}
PERFORMANCE_COLUMNS = (
    "flip",
    "present",
    "frame_ms",
    "frontend_ms",
    "backend_ms",
    "gpu_ms",
)
CLEARED_ENVIRONMENT = (
    "SR_D3D12_FRAMEBUFFER_SAFE",
    "SR_D3D12_DISABLE_FEEDBACK_ALIASES",
    "SR_D3D12_LEGACY_DEPTH_UPLOADS",
    "SR_D3D12_LEGACY_FEEDBACK_SNAPSHOTS",
    "SR_NOVBPACE",
)


@dataclass(frozen=True)
class PerformanceThresholds:
    minimum_fps: float = 59.0
    maximum_p95_ms: float = 18.0
    maximum_frame_ms: float = 33.4
    maximum_gpu_ms: float = 16.68
    maximum_readbacks: int = 4


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    start: int
    required_present: int
    exit_after: int
    warmup_presentations: int = 0


def require_file(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{description} does not exist: {resolved}")
    return resolved


def read_graphics_profile(
    executable: Path,
    required: dict[str, str] | None = FIXED_GRAPHICS_PROFILE,
) -> dict[str, str]:
    path = executable.with_name("graphics.ini")
    if not path.is_file():
        raise ValueError(f"graphics configuration does not exist: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="ascii").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"invalid graphics setting in {path}: {line}")
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    if required is not None:
        mismatches = [
            f"{name}={values.get(name)!r} (expected {expected!r})"
            for name, expected in required.items()
            if values.get(name) != expected
        ]
        if mismatches:
            raise ValueError(
                f"{path} does not contain the required benchmark profile: "
                + ", ".join(mismatches)
            )
    return values


def percentile(sorted_values: list[float], percentage: float) -> float:
    if not sorted_values:
        raise ValueError("cannot calculate a percentile without samples")
    if percentage <= 0.0 or percentage > 1.0:
        raise ValueError("percentile must be in (0, 1]")
    return sorted_values[math.ceil(len(sorted_values) * percentage) - 1]


def load_samples(path: Path, window: int) -> list[dict[str, float]]:
    if window <= 0:
        raise ValueError("sample window must be positive")
    with path.open("r", encoding="ascii", newline="") as file:
        lines = (line for line in file if not line.startswith("#"))
        rows = list(csv.DictReader(lines))
    if len(rows) < window:
        raise ValueError(
            f"performance log contains {len(rows)} samples, expected {window}"
        )
    parsed: list[dict[str, float]] = []
    for row in rows:
        try:
            sample = {
                name: float(value)
                for name, value in row.items()
                if name is not None and value is not None and value != ""
            }
            for name in PERFORMANCE_COLUMNS:
                if name not in sample:
                    raise KeyError(name)
            if not all(math.isfinite(value) for value in sample.values()):
                raise ValueError("non-finite value")
            parsed.append(sample)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid performance row: {row}") from error
    samples = parsed[:window]
    if any("gpu_source_flip" in sample for sample in parsed):
        gpu_by_flip = {
            int(sample["gpu_source_flip"]): sample["gpu_ms"]
            for sample in parsed
            if sample.get("gpu_source_flip", 0.0) > 0.0
            and sample["gpu_ms"] >= 0.0
        }
        for sample in samples:
            sample["gpu_ms"] = gpu_by_flip.get(
                int(sample["flip"]),
                -1.0,
            )
    return samples


def summarize(
    samples: list[dict[str, float]],
    required_present: int,
) -> dict[str, object]:
    if not samples:
        raise ValueError("performance sample is empty")
    frames = sorted(sample["frame_ms"] for sample in samples)
    average = sum(frames) / len(frames)
    first_present = int(min(sample["present"] for sample in samples))
    last_present = int(max(sample["present"] for sample in samples))
    if not first_present <= required_present <= last_present:
        raise ValueError(
            f"sample {first_present}-{last_present} does not include "
            f"required presentation {required_present}"
        )
    gpu_values = [
        sample["gpu_ms"] for sample in samples if sample["gpu_ms"] >= 0.0
    ]
    extra_columns = sorted(
        set.intersection(*(set(sample) for sample in samples))
        - set(PERFORMANCE_COLUMNS)
    )
    extra_metrics = {
        name: {
            "average": sum(sample[name] for sample in samples) / len(samples),
            "maximum": max(sample[name] for sample in samples),
        }
        for name in extra_columns
    }
    return {
        "samples": len(samples),
        "first_present": first_present,
        "last_present": last_present,
        "required_present": required_present,
        "fps": 1000.0 / average,
        "average_ms": average,
        "p50_ms": percentile(frames, 0.50),
        "p95_ms": percentile(frames, 0.95),
        "p99_ms": percentile(frames, 0.99),
        "maximum_ms": frames[-1],
        "frontend_average_ms": sum(
            sample["frontend_ms"] for sample in samples
        )
        / len(samples),
        "backend_average_ms": sum(
            sample["backend_ms"] for sample in samples
        )
        / len(samples),
        "gpu_average_ms": (
            sum(gpu_values) / len(gpu_values) if gpu_values else -1.0
        ),
        "gpu_maximum_ms": max(gpu_values) if gpu_values else -1.0,
        "gpu_samples": len(gpu_values),
        "extra_metrics": extra_metrics,
    }


def parse_framebuffer_stats(stderr: str) -> dict[str, int]:
    matches = re.findall(
        r"ged3d12: framebuffer cache [^\r\n]*?readbacks=(\d+) "
        r"aliases=(\d+)[^\r\n]*?feedback_snapshots=(\d+)",
        stderr,
    )
    if not matches:
        raise ValueError("D3D12 framebuffer statistics are missing")
    readbacks, aliases, feedback_snapshots = matches[-1]
    return {
        "readbacks": int(readbacks),
        "aliases": int(aliases),
        "feedback_snapshots": int(feedback_snapshots),
    }


def validate(
    summary: dict[str, object],
    thresholds: PerformanceThresholds,
) -> list[str]:
    failures: list[str] = []
    fps = float(summary["fps"])
    p95_ms = float(summary["p95_ms"])
    maximum_ms = float(summary["maximum_ms"])
    gpu_maximum_ms = float(summary["gpu_maximum_ms"])
    readbacks = int(summary["readbacks"])
    aliases = int(summary["aliases"])
    feedback_snapshots = int(summary["feedback_snapshots"])
    if fps < thresholds.minimum_fps:
        failures.append(
            f"FPS {fps:.2f} is below {thresholds.minimum_fps:.2f}"
        )
    if p95_ms > thresholds.maximum_p95_ms:
        failures.append(
            f"p95 {p95_ms:.2f} ms exceeds "
            f"{thresholds.maximum_p95_ms:.2f} ms"
        )
    if maximum_ms > thresholds.maximum_frame_ms:
        failures.append(
            f"maximum frame {maximum_ms:.2f} ms exceeds "
            f"{thresholds.maximum_frame_ms:.2f} ms"
        )
    if gpu_maximum_ms < 0.0:
        failures.append("GPU timing samples are missing")
    elif gpu_maximum_ms > thresholds.maximum_gpu_ms:
        failures.append(
            f"maximum GPU time {gpu_maximum_ms:.2f} ms exceeds "
            f"{thresholds.maximum_gpu_ms:.2f} ms"
        )
    if readbacks > thresholds.maximum_readbacks:
        failures.append(
            f"{readbacks} framebuffer readbacks exceed "
            f"{thresholds.maximum_readbacks}"
        )
    if aliases <= 0:
        failures.append("no framebuffer texture aliases were used")
    if feedback_snapshots <= 0:
        failures.append("no framebuffer feedback snapshots were used")
    return failures


def run_benchmark_case(
    *,
    case: BenchmarkCase,
    executable: Path,
    image: Path,
    iso: Path,
    memstick: Path,
    pad_script: Path,
    output: Path,
    profile: dict[str, str],
    thresholds: PerformanceThresholds,
    window: int,
    timeout: float,
    validate_result: bool = True,
    unpaced: bool = False,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=False)
    perf_path = output / "perf.csv"
    stdout_path = output / "stdout.log"
    stderr_path = output / "stderr.log"
    environment = os.environ.copy()
    for name in CLEARED_ENVIRONMENT:
        environment.pop(name, None)
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_MEMSTICK": str(memstick),
            "SR_INPUT_CONFIG": "0",
            "SR_INPUT_HOT_RELOAD": "0",
            "SR_PADSCRIPT": str(pad_script),
            "SR_FAST_FORWARD_PRESENT": str(
                max(0, case.start - case.warmup_presentations)
            ),
            "SR_PERF_START": str(case.start),
            "SR_PERF_WINDOW": str(window),
            "SR_PERF_FILE": str(perf_path),
            "SR_EXIT_AFTER_PRESENT": str(case.exit_after),
            "SR_D3D12_STAGE_LOG": "1",
            "SR_D3D12_VERTEX_LOG": "1",
            "SR_D3D12_TEXTURE_LOG": "1",
            "SR_D3D12_FRAMEBUFFER_LOG": "1",
        }
    )
    if unpaced:
        environment["SR_NOVBPACE"] = "1"
    if extra_environment:
        environment.update(extra_environment)
    command = [
        str(executable),
        "--boot",
        str(image),
        "08804000",
        "08804128",
        "none",
        "--gui",
    ]
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=False,
        )
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if result.returncode:
        tail = "\n".join(stderr_text.splitlines()[-20:])
        raise RuntimeError(
            f"{case.name} runtime exited with {result.returncode}\n{tail}"
        )
    summary = summarize(
        load_samples(perf_path, window),
        case.required_present,
    )
    summary.update(parse_framebuffer_stats(stderr_text))
    summary.update(
        {
            "case": case.name,
            "mode": "unpaced" if unpaced else "paced",
            "profile": profile,
            "executable": str(executable),
            "pad_script": str(pad_script),
        }
    )
    failures = validate(summary, thresholds) if validate_result else []
    summary["validated"] = validate_result
    summary["passed"] = not failures if validate_result else None
    summary["failures"] = failures
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="ascii",
    )
    return summary
