#!/usr/bin/env python3
"""Run and validate the deterministic opening-tutorial performance sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from time import strftime

from benchmark_common import (
    BenchmarkCase,
    DEFAULT_BUILD,
    PerformanceThresholds,
    ROOT,
    read_graphics_profile,
    require_file,
    run_benchmark_case,
)

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
        thresholds = PerformanceThresholds(
            minimum_fps=args.minimum_fps,
            maximum_p95_ms=args.maximum_p95_ms,
            maximum_frame_ms=args.maximum_frame_ms,
            maximum_gpu_ms=args.maximum_gpu_ms,
            maximum_readbacks=args.maximum_readbacks,
        )
        summary = run_benchmark_case(
            case=BenchmarkCase(
                name="tutorial",
                start=args.start,
                required_present=args.pulse,
                exit_after=args.exit,
            ),
            executable=executable,
            image=image,
            iso=iso,
            memstick=args.memstick.resolve(),
            pad_script=pad_script,
            output=output,
            profile=profile,
            thresholds=thresholds,
            window=args.window,
            timeout=args.timeout,
        )
        print(json.dumps(summary, indent=2))
        print(f"artifacts: {output}")
        if summary["failures"]:
            for failure in summary["failures"]:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
