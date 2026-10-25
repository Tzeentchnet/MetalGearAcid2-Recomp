#!/usr/bin/env python3
"""Run and validate the deterministic opening-tutorial performance sample."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from time import strftime


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "out" / "build" / "clang-cl"
DEFAULT_START = 30_900
DEFAULT_PULSE = 31_000
DEFAULT_EXIT = 31_400
DEFAULT_WINDOW = 120


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the opening tutorial dialog at the fixed D3D12 "
            "4x/2x/full-rate profile."
        )
    )
    parser.add_argument(
        "--executable",
        type=Path,
        default=DEFAULT_BUILD / "mga2.exe",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=DEFAULT_BUILD / "mga2_image.bin",
    )
    parser.add_argument(
        "--iso",
        type=Path,
        default=ROOT / "Metal Gear Acid 2 (USA).iso",
    )
    parser.add_argument(
        "--memstick",
        type=Path,
        default=ROOT / "memstick",
    )
    parser.add_argument(
        "--pad-script",
        type=Path,
        default=ROOT / "tools" / "mga2" / "new_game_runtime.pad",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="new output directory (default: out/benchmarks/tutorial-TIMESTAMP)",
    )
    parser.add_argument("--start", type=int, default=DEFAULT_START)
    parser.add_argument("--pulse", type=int, default=DEFAULT_PULSE)
    parser.add_argument("--exit", type=int, default=DEFAULT_EXIT)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--minimum-fps", type=float, default=59.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=18.0)
    parser.add_argument("--maximum-frame-ms", type=float, default=33.4)
    parser.add_argument("--maximum-gpu-ms", type=float, default=16.68)
    parser.add_argument("--maximum-readbacks", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args(argv)


def require_file(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{description} does not exist: {resolved}")
    return resolved


def read_graphics_profile(executable: Path) -> dict[str, str]:
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
    required = {
        "renderer": "d3d12",
        "internal_resolution": "4",
        "texture_scale": "2",
        "d3d12_full_rate": "1",
    }
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
    return sorted_values[math.ceil(len(sorted_values) * percentage) - 1]


def load_samples(path: Path, window: int) -> list[dict[str, float]]:
    with path.open("r", encoding="ascii", newline="") as file:
        lines = (line for line in file if not line.startswith("#"))
        rows = list(csv.DictReader(lines))
    if len(rows) < window:
        raise ValueError(
            f"performance log contains {len(rows)} samples, expected {window}"
        )
    samples: list[dict[str, float]] = []
    for row in rows[:window]:
        try:
            samples.append(
                {
                    "flip": float(row["flip"]),
                    "present": float(row["present"]),
                    "frame_ms": float(row["frame_ms"]),
                    "frontend_ms": float(row["frontend_ms"]),
                    "backend_ms": float(row["backend_ms"]),
                    "gpu_ms": float(row["gpu_ms"]),
                }
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid performance row: {row}") from error
    return samples


def summarize(
    samples: list[dict[str, float]], pulse: int
) -> dict[str, float | int]:
    frames = sorted(sample["frame_ms"] for sample in samples)
    average = sum(frames) / len(frames)
    first_present = int(min(sample["present"] for sample in samples))
    last_present = int(max(sample["present"] for sample in samples))
    if not first_present <= pulse <= last_present:
        raise ValueError(
            f"sample {first_present}-{last_present} does not include "
            f"the input pulse at presentation {pulse}"
        )
    return {
        "samples": len(samples),
        "first_present": first_present,
        "last_present": last_present,
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
        "gpu_average_ms": sum(sample["gpu_ms"] for sample in samples)
        / len(samples),
        "gpu_maximum_ms": max(sample["gpu_ms"] for sample in samples),
    }


def parse_framebuffer_stats(stderr: str) -> dict[str, int]:
    matches = re.findall(
        r"ged3d12: framebuffer cache .*?readbacks=(\d+) "
        r"aliases=(\d+).*?feedback_snapshots=(\d+)",
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
    summary: dict[str, float | int],
    args: argparse.Namespace,
) -> list[str]:
    failures: list[str] = []
    if summary["fps"] < args.minimum_fps:
        failures.append(
            f"FPS {summary['fps']:.2f} is below {args.minimum_fps:.2f}"
        )
    if summary["p95_ms"] > args.maximum_p95_ms:
        failures.append(
            f"p95 {summary['p95_ms']:.2f} ms exceeds "
            f"{args.maximum_p95_ms:.2f} ms"
        )
    if summary["maximum_ms"] > args.maximum_frame_ms:
        failures.append(
            f"maximum frame {summary['maximum_ms']:.2f} ms exceeds "
            f"{args.maximum_frame_ms:.2f} ms"
        )
    if summary["gpu_maximum_ms"] > args.maximum_gpu_ms:
        failures.append(
            f"maximum GPU time {summary['gpu_maximum_ms']:.2f} ms exceeds "
            f"{args.maximum_gpu_ms:.2f} ms"
        )
    if summary["readbacks"] > args.maximum_readbacks:
        failures.append(
            f"{summary['readbacks']} framebuffer readbacks exceed "
            f"{args.maximum_readbacks}"
        )
    if summary["aliases"] <= 0:
        failures.append("no framebuffer texture aliases were used")
    if summary["feedback_snapshots"] <= 0:
        failures.append("no framebuffer feedback snapshots were used")
    return failures


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        if args.window <= 0:
            raise ValueError("--window must be positive")
        if args.start >= args.pulse or args.pulse >= args.exit:
            raise ValueError("--start, --pulse, and --exit must be increasing")
        executable = require_file(args.executable, "executable")
        image = require_file(args.image, "generated image")
        iso = require_file(args.iso, "game ISO")
        pad_script = require_file(args.pad_script, "pad script")
        profile = read_graphics_profile(executable)
        args.memstick.resolve().mkdir(parents=True, exist_ok=True)
        output = (
            args.output.resolve()
            if args.output
            else ROOT
            / "out"
            / "benchmarks"
            / f"tutorial-{strftime('%Y%m%d-%H%M%S')}"
        )
        output.mkdir(parents=True, exist_ok=False)

        perf_path = output / "perf.csv"
        stdout_path = output / "stdout.log"
        stderr_path = output / "stderr.log"
        environment = os.environ.copy()
        for name in (
            "SR_D3D12_FRAMEBUFFER_SAFE",
            "SR_D3D12_DISABLE_FEEDBACK_ALIASES",
            "SR_D3D12_LEGACY_DEPTH_UPLOADS",
            "SR_D3D12_LEGACY_FEEDBACK_SNAPSHOTS",
            "SR_NOVBPACE",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "PSP_ISO": str(iso),
                "SR_MEMSTICK": str(args.memstick.resolve()),
                "SR_INPUT_CONFIG": "0",
                "SR_INPUT_HOT_RELOAD": "0",
                "SR_PADSCRIPT": str(pad_script),
                "SR_FAST_FORWARD_PRESENT": str(args.start),
                "SR_PERF_START": str(args.start),
                "SR_PERF_WINDOW": str(args.window),
                "SR_PERF_FILE": str(perf_path),
                "SR_PERF_MIN_FPS": str(args.minimum_fps),
                "SR_EXIT_AFTER_PRESENT": str(args.exit),
                "SR_D3D12_STAGE_LOG": "1",
                "SR_D3D12_TEXTURE_LOG": "1",
                "SR_D3D12_FRAMEBUFFER_LOG": "1",
            }
        )
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
                timeout=args.timeout,
                check=False,
            )
        stderr_text = stderr_path.read_text(
            encoding="utf-8", errors="replace"
        )
        if result.returncode:
            tail = "\n".join(stderr_text.splitlines()[-20:])
            raise RuntimeError(
                f"runtime exited with {result.returncode}\n{tail}"
            )

        summary = summarize(load_samples(perf_path, args.window), args.pulse)
        summary.update(parse_framebuffer_stats(stderr_text))
        summary["profile"] = profile
        summary["executable"] = str(executable)
        summary["pad_script"] = str(pad_script)
        failures = validate(summary, args)
        summary["passed"] = not failures
        summary["failures"] = failures
        (output / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n",
            encoding="ascii",
        )
        print(json.dumps(summary, indent=2))
        print(f"artifacts: {output}")
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
