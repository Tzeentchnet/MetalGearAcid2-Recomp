#!/usr/bin/env python3
"""Shared helpers for deterministic Metal Gear Acid 2 benchmarks."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from time import perf_counter

from local_files import is_link_or_reparse_point


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "out" / "build" / "clang-cl"
ARENA_REPLAY_SHA256 = "89c976f6cbee3cff7976c835803f02ea3eb95058cfcae9bf1d80903b8a8979ba"
FIXED_GRAPHICS_PROFILE = {
    "renderer": "d3d12",
    "internal_resolution": "4",
    "texture_scale": "2",
    "d3d12_full_rate": "1",
    "anti_aliasing": "off",
    "skip_startup": "off",
}
PERFORMANCE_COLUMNS = (
    "flip",
    "present",
    "frame_ms",
    "frontend_ms",
    "backend_ms",
    "gpu_ms",
)
# Written by the runtime for host flips whose frame straddled an alternation change.
ALTERNATE_TRANSITION_BIT = 0x80000000


@dataclass(frozen=True)
class PerformanceThresholds:
    minimum_fps: float = 59.0
    minimum_delivered_fps: float = 29.0
    maximum_p95_ms: float = 18.0
    maximum_frame_ms: float = 33.4
    maximum_delivered_p95_ms: float = 35.0
    maximum_delivered_frame_ms: float = 50.0
    maximum_gpu_ms: float = 16.68
    maximum_readbacks: int = 4
    maximum_audio_underruns: int = 0
    maximum_audio_padding_transitions: int = 1

    def __post_init__(self) -> None:
        counters = {
            "maximum_readbacks",
            "maximum_audio_underruns",
            "maximum_audio_padding_transitions",
        }
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value < 0 or (
                name not in counters and value == 0
            ):
                raise ValueError(f"invalid benchmark threshold {name}: {value}")


@dataclass(frozen=True)
class BenchmarkCase:
    name: str
    start: int
    required_present: int
    exit_after: int
    warmup_presentations: int = 0
    input_pulse: int | None = None
    input_mask: int = 0x2000
    input_width: int = 20


def validate_run_options(window: int, timeout: float) -> None:
    if not 2 <= window <= 600:
        raise ValueError("sample window must be between 2 and 600 host flips")
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and positive")


def replay_sha256(path: Path) -> str:
    # Git may check out the same replay with either LF or CRLF line endings.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def ensure_output_outside_fixture(output: Path, source: Path) -> None:
    output = output.resolve()
    source = source.resolve()
    if output == source or source in output.parents:
        raise ValueError(
            f"output directory cannot be inside the memory-stick fixture: {output}"
        )


def copy_memstick_fixture(source: Path, destination: Path) -> str:
    """Copy a fixture without leaving links back to the user's writable data."""
    ensure_output_outside_fixture(destination, source)
    if is_link_or_reparse_point(source):
        raise ValueError(f"memory-stick fixture cannot be a link: {source}")
    if source.exists():
        if not source.is_dir():
            raise ValueError(f"memory-stick fixture is not a directory: {source}")
        def raise_walk_error(error: OSError) -> None:
            raise error

        for parent, directories, files in os.walk(
            source, followlinks=False, onerror=raise_walk_error
        ):
            for name in directories + files:
                path = Path(parent) / name
                if is_link_or_reparse_point(path):
                    raise ValueError(
                        f"memory-stick fixture contains a link: {path}"
                    )
        shutil.copytree(source, destination)
    else:
        destination.mkdir(parents=True)

    digest = hashlib.sha256()
    for path in sorted(destination.rglob("*")):
        name = path.relative_to(destination).as_posix().encode("utf-8")
        if path.is_dir():
            digest.update(b"D")
        elif path.is_file():
            digest.update(b"F")
        else:
            raise ValueError(f"unsupported memory-stick fixture entry: {path}")
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        if path.is_file():
            digest.update(path.stat().st_size.to_bytes(8, "big"))
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def clean_runtime_environment() -> dict[str, str]:
    return {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(("SR_", "PSP_"))
    }


def require_file(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{description} does not exist: {resolved}")
    return resolved


def require_arena_save(memstick: Path) -> Path:
    if is_link_or_reparse_point(memstick):
        raise ValueError(f"memory-stick fixture cannot be a link: {memstick}")
    root = memstick.resolve()
    save = root / "PSP" / "SAVEDATA" / "ULUS10077003"
    for name, expected_size in {"PARAM.SFO": None, "00000000.000": 48_800}.items():
        path = save / name
        if not path.is_file():
            raise ValueError(f"Arena save file does not exist: {path}")
        if expected_size is not None and path.stat().st_size != expected_size:
            raise ValueError(
                f"Arena save file has size {path.stat().st_size}, "
                f"expected {expected_size}: {path}"
            )
    return root


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
        if not line or line.startswith(("#", ";")):
            continue
        if "=" not in line:
            raise ValueError(f"invalid graphics setting in {path}: {line}")
        name, value = line.split("=", 1)
        name = name.strip().lower()
        value = value.strip().lower()
        if not name or not value or name in values:
            raise ValueError(f"invalid or duplicate graphics setting in {path}: {line}")
        values[name] = value
    values.setdefault("anti_aliasing", "off")
    values.setdefault("skip_startup", "off")
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


def load_samples(
    path: Path,
    window: int,
    *,
    keep_all: bool = False,
    require_gpu_sources: bool = False,
) -> list[dict[str, float]]:
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
            if sample["frame_ms"] <= 0:
                raise ValueError("non-positive frame time")
            if any(
                sample[name] < 0 or not sample[name].is_integer()
                for name in ("flip", "present")
            ):
                raise ValueError("invalid flip or presentation")
            if "gpu_source_flip" in sample and (
                sample["gpu_source_flip"] < 0
                or not sample["gpu_source_flip"].is_integer()
            ):
                raise ValueError("invalid GPU source flip")
            parsed.append(sample)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid performance row: {row}") from error
    if any(
        later["flip"] <= earlier["flip"]
        or later["present"] < earlier["present"]
        for earlier, later in zip(parsed, parsed[1:])
    ):
        raise ValueError("performance rows are not in presentation order")
    samples = parsed if keep_all else parsed[:window]
    if require_gpu_sources and not all(
        "gpu_source_flip" in sample for sample in parsed
    ):
        raise ValueError("GPU source-flip identities are missing")
    if any("gpu_source_flip" in sample for sample in parsed):
        source_flips = [
            int(sample["gpu_source_flip"])
            for sample in parsed
            if sample.get("gpu_source_flip", 0.0) > 0.0
            and sample["gpu_ms"] >= 0.0
        ]
        if len(source_flips) != len(set(source_flips)):
            raise ValueError("duplicate GPU source-flip identities")
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


def describe(samples: list[dict[str, float]]) -> dict[str, float]:
    """Frame statistics for an arbitrary set of rows (no acceptance meaning)."""
    if not samples:
        raise ValueError("cannot describe an empty sample")
    frames = sorted(sample["frame_ms"] for sample in samples)
    average = sum(frames) / len(frames)
    return {
        "samples": len(samples),
        "host_flip_fps": 1000.0 / average,
        "average_ms": average,
        "p50_ms": percentile(frames, 0.50),
        "p95_ms": percentile(frames, 0.95),
        "maximum_ms": frames[-1],
        "frontend_average_ms": sum(s["frontend_ms"] for s in samples)
        / len(samples),
        "backend_average_ms": sum(s["backend_ms"] for s in samples)
        / len(samples),
    }


def describe_delivery(samples: list[dict[str, float]]) -> dict[str, float | int]:
    """Describe newly delivered guest frames rather than repeated host flips."""
    if len(samples) < 2:
        raise ValueError("cannot describe delivery with fewer than two samples")
    intervals: list[float] = []
    elapsed_ms = 0.0
    repeated_flips = 0
    previous_present = int(samples[0]["present"])
    for sample in samples[1:]:
        elapsed_ms += sample["frame_ms"]
        present = int(sample["present"])
        if present == previous_present:
            repeated_flips += 1
            continue
        intervals.append(elapsed_ms)
        elapsed_ms = 0.0
        previous_present = present
    if not intervals:
        return {
            "delivered_frames": 0,
            "repeated_host_flips": repeated_flips,
            "delivered_fps": 0.0,
            "delivered_average_ms": -1.0,
            "delivered_p50_ms": -1.0,
            "delivered_p95_ms": -1.0,
            "delivered_maximum_ms": -1.0,
            "terminal_delivery_interval_ms": elapsed_ms,
        }
    sorted_intervals = sorted(intervals)
    observation_ms = sum(intervals) + elapsed_ms
    return {
        "delivered_frames": len(intervals),
        "repeated_host_flips": repeated_flips,
        "delivered_fps": 1000.0 * len(intervals) / observation_ms,
        "delivered_average_ms": observation_ms / len(intervals),
        "delivered_p50_ms": percentile(sorted_intervals, 0.50),
        "delivered_p95_ms": percentile(sorted_intervals, 0.95),
        "delivered_maximum_ms": sorted_intervals[-1],
        "terminal_delivery_interval_ms": elapsed_ms,
    }


def split_alternation(
    samples: list[dict[str, float]],
) -> dict[str, object] | None:
    """Split rows of a SR_PERF_ALTERNATE run into paths-on and paths-off.

    Rows whose frame straddled a change (the runtime sets the high bit of
    ``alt_off``) belong to neither side. Returns None for a log without the
    ``alt_off`` column, and omits a side that has no rows.
    """
    if not samples or "alt_off" not in samples[0]:
        return None
    groups: dict[str, list[dict[str, float]]] = {"on": [], "off": []}
    discarded = 0
    for sample in samples:
        mask = int(sample["alt_off"])
        if mask & ALTERNATE_TRANSITION_BIT:
            discarded += 1
        elif mask:
            groups["off"].append(sample)
        else:
            groups["on"].append(sample)
    result: dict[str, object] = {"discarded": discarded}
    for name, rows in groups.items():
        if rows:
            result[name] = describe(rows)
    if "on" in result and "off" in result:
        on, off = result["on"], result["off"]
        result["delta"] = {
            "average_ms": off["average_ms"] - on["average_ms"],
            "p95_ms": off["p95_ms"] - on["p95_ms"],
            "frontend_average_ms": off["frontend_average_ms"]
            - on["frontend_average_ms"],
        }
    return result


def summarize(
    samples: list[dict[str, float]],
    required_present: int,
) -> dict[str, object]:
    if not samples:
        raise ValueError("performance sample is empty")
    frames = sorted(sample["frame_ms"] for sample in samples)
    average = sum(frames) / len(frames)
    presentations = [int(sample["present"]) for sample in samples]
    first_present = presentations[0]
    last_present = presentations[-1]
    if any(later < earlier for earlier, later in zip(
        presentations, presentations[1:]
    )):
        raise ValueError("performance presentations are not in order")
    observed = required_present in presentations
    crossed = any(
        earlier < required_present < later
        for earlier, later in zip(presentations, presentations[1:])
    )
    if not observed and not crossed:
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
        "checkpoint_evidence": "observed" if observed else "crossed",
        "sample_duration_ms": sum(sample["frame_ms"] for sample in samples),
        "host_flip_fps": 1000.0 / average,
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
        **describe_delivery(samples),
    }


def parse_framebuffer_stats(
    stderr: str,
    *,
    required: bool = True,
) -> dict[str, int]:
    matches = re.findall(
        r"ged3d12: framebuffer cache [^\r\n]*?readbacks=(\d+) "
        r"aliases=(\d+)[^\r\n]*?feedback_snapshots=(\d+)",
        stderr,
    )
    if not matches and required:
        raise ValueError("D3D12 framebuffer statistics are missing")
    if not matches:
        return {
            "readbacks": 0,
            "aliases": 0,
            "feedback_snapshots": 0,
        }
    readbacks, aliases, feedback_snapshots = matches[-1]
    return {
        "readbacks": int(readbacks),
        "aliases": int(aliases),
        "feedback_snapshots": int(feedback_snapshots),
    }


def parse_audio_stats(stderr: str) -> dict[str, object]:
    matches = re.findall(
        r"audio: XAudio2 shutdown played=(\d+) frames "
        r"\(([-+0-9.]+) ms\), clock_drift=([-+0-9.]+) ms, "
        r"device_buffers=(\d+)\.\.(\d+), max_guest_queue=(\d+), "
        r"dropped=(\d+), resynced=(\d+), silent_blocks=(\d+), "
        r"underruns=(\d+), padding_blocks=(\d+), "
        r"padding_transitions=(\d+)(, voice_error)?",
        stderr,
    )
    if not matches:
        raise ValueError("XAudio2 shutdown statistics are missing")
    (
        played_frames,
        played_ms,
        clock_drift_ms,
        minimum_device_buffers,
        maximum_device_buffers,
        maximum_guest_queue,
        dropped_frames,
        resynced_frames,
        silent_blocks,
        underruns,
        padding_blocks,
        padding_transitions,
        voice_error,
    ) = matches[-1]
    result = {
        "audio_played_frames": int(played_frames),
        "audio_played_ms": float(played_ms),
        "audio_clock_drift_ms": float(clock_drift_ms),
        "audio_minimum_device_buffers": int(minimum_device_buffers),
        "audio_maximum_device_buffers": int(maximum_device_buffers),
        "audio_maximum_guest_queue": int(maximum_guest_queue),
        "audio_dropped_frames": int(dropped_frames),
        "audio_resynced_frames": int(resynced_frames),
        "audio_silent_blocks": int(silent_blocks),
        "audio_underruns": int(underruns),
        "audio_padding_blocks": int(padding_blocks),
        "audio_padding_transitions": int(padding_transitions),
        "audio_voice_error": bool(voice_error),
    }
    if not all(math.isfinite(float(result[name])) for name in (
        "audio_played_ms",
        "audio_clock_drift_ms",
    )):
        raise ValueError("XAudio2 shutdown statistics contain non-finite values")
    return result


def find_input_event(stderr: str, case: BenchmarkCase) -> dict[str, int] | None:
    if case.input_pulse is None:
        return None
    for frame, present, vblank, mask in re.findall(
        r"^PADSCRIPT clock=present frame=(\d+) present=(\d+) "
        r"vblank=(\d+) mask=0x([0-9a-fA-F]+)\s*$",
        stderr,
        flags=re.MULTILINE,
    ):
        frame_value = int(frame)
        mask_value = int(mask, 16)
        if (
            case.input_pulse <= frame_value < case.input_pulse + case.input_width
            and mask_value & case.input_mask == case.input_mask
        ):
            return {
                "frame": frame_value,
                "present": int(present),
                "vblank": int(vblank),
                "mask": mask_value,
            }
    return None


def parse_runtime_profile(stderr: str) -> dict[str, str] | None:
    matches = re.findall(
        r"graphics: loaded [^\r\n]* \(renderer ([^,]+), "
        r"internal resolution (\d+)x, texture scale (\d+)x, "
        r"D3D12 full-rate (on|off), anti-aliasing ([^,]+), "
        r"startup skip (on|off)\)",
        stderr,
    )
    if not matches:
        return None
    renderer, resolution, texture_scale, full_rate, anti_aliasing, skip = matches[-1]
    return {
        "renderer": renderer,
        "internal_resolution": resolution,
        "texture_scale": texture_scale,
        "d3d12_full_rate": "1" if full_rate == "on" else "0",
        "anti_aliasing": anti_aliasing,
        "skip_startup": skip,
    }


def validate(
    summary: dict[str, object],
    thresholds: PerformanceThresholds,
) -> list[str]:
    failures: list[str] = []
    fps = float(summary["host_flip_fps"])
    delivered_fps = float(summary["delivered_fps"])
    p95_ms = float(summary["p95_ms"])
    maximum_ms = float(summary["maximum_ms"])
    delivered_p95_ms = float(summary["delivered_p95_ms"])
    delivered_maximum_ms = float(summary["delivered_maximum_ms"])
    gpu_maximum_ms = float(summary["gpu_maximum_ms"])
    readbacks = int(summary["readbacks"])
    aliases = int(summary["aliases"])
    feedback_snapshots = int(summary["feedback_snapshots"])
    if fps < thresholds.minimum_fps:
        failures.append(
            f"host flip FPS {fps:.2f} is below {thresholds.minimum_fps:.2f}"
        )
    if delivered_fps < thresholds.minimum_delivered_fps:
        failures.append(
            f"delivered FPS {delivered_fps:.2f} is below "
            f"{thresholds.minimum_delivered_fps:.2f}"
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
    if delivered_p95_ms < 0.0:
        failures.append("delivered frame timing samples are missing")
    elif delivered_p95_ms > thresholds.maximum_delivered_p95_ms:
        failures.append(
            f"delivered p95 {delivered_p95_ms:.2f} ms exceeds "
            f"{thresholds.maximum_delivered_p95_ms:.2f} ms"
        )
    if delivered_maximum_ms > thresholds.maximum_delivered_frame_ms:
        failures.append(
            f"maximum delivered frame {delivered_maximum_ms:.2f} ms exceeds "
            f"{thresholds.maximum_delivered_frame_ms:.2f} ms"
        )
    terminal_ms = float(summary["terminal_delivery_interval_ms"])
    if terminal_ms > thresholds.maximum_delivered_frame_ms:
        failures.append(
            f"ongoing terminal delivery interval {terminal_ms:.2f} ms exceeds "
            f"{thresholds.maximum_delivered_frame_ms:.2f} ms"
        )
    if int(summary["gpu_samples"]) != int(summary["samples"]):
        failures.append(
            f"GPU timing coverage is {int(summary['gpu_samples'])}/"
            f"{int(summary['samples'])} samples"
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
    if (
        int(summary["audio_played_frames"]) <= 0
        or float(summary["audio_played_ms"]) < float(summary["sample_duration_ms"])
    ):
        failures.append("insufficient XAudio2 playback for the sample duration")
    if summary["required_input_event"] is None:
        failures.append("required replay input event was not observed")
    if summary["runtime_profile"] != FIXED_GRAPHICS_PROFILE:
        failures.append("effective runtime graphics profile is missing or nonstandard")
    if int(summary["audio_dropped_frames"]) > 0:
        failures.append(
            f"audio dropped {int(summary['audio_dropped_frames'])} frames"
        )
    if int(summary["audio_underruns"]) > thresholds.maximum_audio_underruns:
        failures.append(
            f"{int(summary['audio_underruns'])} audio underruns exceed "
            f"{thresholds.maximum_audio_underruns}"
        )
    if (
        int(summary["audio_padding_transitions"])
        > thresholds.maximum_audio_padding_transitions
    ):
        failures.append(
            f"{int(summary['audio_padding_transitions'])} audio padding "
            f"transitions exceed "
            f"{thresholds.maximum_audio_padding_transitions}"
        )
    if bool(summary["audio_voice_error"]):
        failures.append("XAudio2 reported a voice error")
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
    renderer: str = "d3d12",
    tail_presents: int = 0,
    validate_result: bool = True,
    unpaced: bool = False,
    fast_forward: bool = False,
    extra_environment: dict[str, str] | None = None,
) -> dict[str, object]:
    validate_run_options(window, timeout)
    if validate_result and (unpaced or fast_forward or extra_environment):
        raise ValueError("diagnostic runtime overrides cannot validate acceptance")
    if validate_result and case.input_pulse is None:
        raise ValueError("acceptance requires a replay input checkpoint")
    ensure_output_outside_fixture(output, memstick)
    output.mkdir(parents=True, exist_ok=False)
    perf_path = output / "perf.csv"
    stdout_path = output / "stdout.log"
    stderr_path = output / "stderr.log"
    alternating = bool(
        extra_environment and extra_environment.get("SR_PERF_ALTERNATE")
    )
    environment = clean_runtime_environment()
    # Production writes and reads a persistent PSO key list; benchmarks start cold unless a
    # list is requested, so runs stay comparable with the historical results.
    environment["SR_D3D12_NO_PSO_KEYS"] = "1"
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_INPUT_CONFIG": "0",
            "SR_INPUT_HOT_RELOAD": "0",
            "SR_PADLOG": "1",
            "SR_PADSCRIPT": str(pad_script),
            "SR_PERF_START": str(case.start),
            "SR_PERF_WINDOW": str(window),
            "SR_PERF_FILE": str(perf_path),
            "SR_EXIT_AFTER_PRESENT": str(case.exit_after + tail_presents),
        }
    )
    if fast_forward:
        environment["SR_FAST_FORWARD_PRESENT"] = str(
            max(1, case.start - case.warmup_presentations)
        )
    if renderer == "d3d12":
        environment.update(
            {
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
        if extra_environment.get("SR_D3D12_PSO_KEYS"):
            environment.pop("SR_D3D12_NO_PSO_KEYS", None)
    command = [
        str(executable),
        "--boot",
        str(image),
        "08804000",
        "08804128",
        "none",
        "--gui",
    ]
    with tempfile.TemporaryDirectory(prefix="mga2-benchmark-") as temporary:
        isolated_memstick = Path(temporary) / "memstick"
        fixture_sha256 = copy_memstick_fixture(memstick, isolated_memstick)
        environment["SR_MEMSTICK"] = str(isolated_memstick)
        started = perf_counter()
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
        wall_seconds = perf_counter() - started
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if result.returncode:
        tail = "\n".join(stderr_text.splitlines()[-20:])
        raise RuntimeError(
            f"{case.name} runtime exited with {result.returncode}\n{tail}"
        )
    summary = summarize(
        load_samples(perf_path, window, require_gpu_sources=validate_result),
        case.required_present,
    )
    if alternating:
        summary["alternation"] = split_alternation(
            load_samples(perf_path, window, keep_all=True)
        )
    summary.update(
        parse_framebuffer_stats(stderr_text, required=renderer == "d3d12")
    )
    summary.update(parse_audio_stats(stderr_text))
    summary["required_input_event"] = find_input_event(stderr_text, case)
    summary["runtime_profile"] = parse_runtime_profile(stderr_text)
    summary.update(
        {
            "case": case.name,
            "mode": "unpaced" if "SR_NOVBPACE" in environment else "paced",
            "startup": (
                "fast-forward"
                if environment.get("SR_FAST_FORWARD_PRESENT", "") not in ("", "0")
                else "real-time"
            ),
            "renderer": renderer,
            "wall_seconds": wall_seconds,
            "tail_presents": tail_presents,
            "profile": profile,
            "executable": str(executable),
            "pad_script": str(pad_script),
            "pad_script_sha256": replay_sha256(pad_script),
            "memstick_source": str(memstick),
            "memstick_sha256": fixture_sha256,
            "audio_window_verified": False,
            "thresholds": asdict(thresholds),
            "window": window,
            "effective_runtime_environment": {
                name: value
                for name, value in environment.items()
                if name.upper().startswith(("SR_", "PSP_"))
            },
            "extra_environment": dict(extra_environment or {}),
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
