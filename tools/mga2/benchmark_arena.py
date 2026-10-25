#!/usr/bin/env python3
"""Run and validate the completed-save Arena Easy performance samples."""

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


ARENA_CASES = (
    BenchmarkCase("dead-cell", 27_900, 28_000, 28_800, 120),
    BenchmarkCase("gameplay", 37_900, 38_000, 38_800, 120),
)
DEFAULT_WINDOW = 120


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the completed-save Arena Easy route at the fixed "
            "D3D12 4x/2x/full-rate profile."
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
        required=True,
        help=(
            "isolated memory-stick root containing the completed Acid 2 "
            "ULUS10077003 save"
        ),
    )
    parser.add_argument(
        "--pad-script",
        type=Path,
        default=ROOT / "tools" / "mga2" / "arena_runtime.pad",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="new output directory (default: out/benchmarks/arena-TIMESTAMP)",
    )
    parser.add_argument(
        "--case",
        choices=("both", "dead-cell", "gameplay"),
        default="both",
    )
    parser.add_argument(
        "--include-unpaced",
        action="store_true",
        help="also run non-gating SR_NOVBPACE=1 diagnostic samples",
    )
    parser.add_argument(
        "--allow-nonstandard-profile",
        action="store_true",
        help=(
            "allow a non-4x/2x/full-rate profile for diagnostics; "
            "results will not be accepted as passing"
        ),
    )
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--minimum-fps", type=float, default=59.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=18.0)
    parser.add_argument("--maximum-frame-ms", type=float, default=33.4)
    parser.add_argument("--maximum-gpu-ms", type=float, default=16.68)
    parser.add_argument("--maximum-readbacks", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args(argv)


def require_arena_save(memstick: Path) -> Path:
    root = memstick.resolve()
    save = root / "PSP" / "SAVEDATA" / "ULUS10077003"
    required = {
        "PARAM.SFO": None,
        "00000000.000": 48_800,
    }
    for name, expected_size in required.items():
        path = save / name
        if not path.is_file():
            raise ValueError(f"Arena save file does not exist: {path}")
        if expected_size is not None and path.stat().st_size != expected_size:
            raise ValueError(
                f"Arena save file has size {path.stat().st_size}, "
                f"expected {expected_size}: {path}"
            )
    return root


def combine_results(
    results: list[dict[str, object]],
    fixed_profile: bool,
) -> dict[str, object]:
    acceptance = [
        result for result in results if bool(result["validated"])
    ]
    passed = (
        all(bool(result["passed"]) for result in acceptance)
        if acceptance
        else None
    )
    failures = [
        f"{result['case']}: {failure}"
        for result in acceptance
        for failure in result["failures"]
    ]
    return {
        "fixed_profile": fixed_profile,
        "passed": passed,
        "failures": failures,
        "results": results,
    }


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        executable = require_file(args.executable, "executable")
        image = require_file(args.image, "generated image")
        iso = require_file(args.iso, "game ISO")
        pad_script = require_file(args.pad_script, "pad script")
        memstick = require_arena_save(args.memstick)
        if args.window <= 0:
            raise ValueError("--window must be positive")
        fixed_profile = not args.allow_nonstandard_profile
        profile = read_graphics_profile(executable, required=None)
        expected = {
            "renderer": "d3d12",
            "internal_resolution": "4",
            "texture_scale": "2",
            "d3d12_full_rate": "1",
        }
        profile_matches = all(
            profile.get(name) == value for name, value in expected.items()
        )
        if fixed_profile and not profile_matches:
            read_graphics_profile(executable)
        fixed_profile = fixed_profile and profile_matches
        output = (
            args.output.resolve()
            if args.output
            else ROOT
            / "out"
            / "benchmarks"
            / f"arena-{strftime('%Y%m%d-%H%M%S')}"
        )
        output.mkdir(parents=True, exist_ok=False)
        thresholds = PerformanceThresholds(
            minimum_fps=args.minimum_fps,
            maximum_p95_ms=args.maximum_p95_ms,
            maximum_frame_ms=args.maximum_frame_ms,
            maximum_gpu_ms=args.maximum_gpu_ms,
            maximum_readbacks=args.maximum_readbacks,
        )
        selected = [
            case
            for case in ARENA_CASES
            if args.case == "both" or args.case == case.name
        ]
        results: list[dict[str, object]] = []
        for case in selected:
            results.append(
                run_benchmark_case(
                    case=case,
                    executable=executable,
                    image=image,
                    iso=iso,
                    memstick=memstick,
                    pad_script=pad_script,
                    output=output / case.name,
                    profile=profile,
                    thresholds=thresholds,
                    window=args.window,
                    timeout=args.timeout,
                    validate_result=fixed_profile,
                )
            )
            if args.include_unpaced:
                results.append(
                    run_benchmark_case(
                        case=case,
                        executable=executable,
                        image=image,
                        iso=iso,
                        memstick=memstick,
                        pad_script=pad_script,
                        output=output / f"{case.name}-unpaced",
                        profile=profile,
                        thresholds=thresholds,
                        window=args.window,
                        timeout=args.timeout,
                        validate_result=False,
                        unpaced=True,
                    )
                )
        combined = combine_results(results, fixed_profile)
        (output / "summary.json").write_text(
            json.dumps(combined, indent=2) + "\n",
            encoding="ascii",
        )
        print(json.dumps(combined, indent=2))
        print(f"artifacts: {output}")
        for failure in combined["failures"]:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1 if combined["passed"] is False else 0
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
