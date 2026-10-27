#!/usr/bin/env python3
"""Run and validate the completed-save Arena Easy performance samples."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
from time import strftime

from benchmark_common import (
    ARENA_REPLAY_SHA256,
    BenchmarkCase,
    DEFAULT_BUILD,
    FIXED_GRAPHICS_PROFILE,
    PerformanceThresholds,
    ROOT,
    ensure_output_outside_fixture,
    read_graphics_profile,
    replay_sha256,
    require_arena_save,
    require_file,
    run_benchmark_case,
    validate_run_options,
)


ARENA_CASES = (
    BenchmarkCase("dead-cell", 27_900, 28_000, 28_800, 120, 26_000),
    BenchmarkCase("fortune", 29_280, 29_307, 30_000, 480, 26_000),
    BenchmarkCase("gameplay", 37_900, 38_000, 38_800, 120, 26_000),
)
DEFAULT_WINDOW = 120
CASE_CHOICES = ("all", "both", *(case.name for case in ARENA_CASES))


def select_cases(selection: str) -> tuple[BenchmarkCase, ...]:
    if selection == "all":
        return ARENA_CASES
    if selection == "both":
        return tuple(
            case
            for case in ARENA_CASES
            if case.name in ("dead-cell", "gameplay")
        )
    return tuple(case for case in ARENA_CASES if case.name == selection)


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
            "memory-stick root containing the completed Acid 2 "
            "ULUS10077003 save; each case uses an isolated copy"
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
        choices=CASE_CHOICES,
        default="both",
    )
    parser.add_argument(
        "--renderer",
        choices=("d3d12", "vulkan"),
        default="d3d12",
        help="renderer used by the executable; Vulkan is diagnostic only",
    )
    parser.add_argument(
        "--fast-forward",
        action="store_true",
        help=(
            "turbo to the case warm-up point; diagnostic only because it "
            "skips normal audio playback and changes cache/timing history"
        ),
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
    parser.add_argument(
        "--tail-presents",
        type=int,
        default=0,
        help="continue this many presentations past each case exit bound",
    )
    parser.add_argument(
        "--fortune-window",
        type=int,
        default=None,
        help="sample window for Fortune (runtime maximum is 600)",
    )
    parser.add_argument(
        "--fortune-extra-presents",
        type=int,
        default=0,
        help="extend Fortune's diagnostic run without changing its start",
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=(
            "set a runtime environment variable for every case (repeatable); "
            "diagnostic overrides, recorded in each summary"
        ),
    )
    parser.add_argument(
        "--alternate",
        default=None,
        metavar="PATHS",
        help=(
            "switch comma-separated optimization paths (texdecode, merge, "
            "memo, indexed) off every other --alternate-presents guest "
            "presentations and report the on/off split; diagnostic only. "
            "Use a long --window (up to 600) so both sides have samples"
        ),
    )
    parser.add_argument(
        "--alternate-presents",
        type=int,
        default=60,
        help="presentations per on/off half of an alternating run",
    )
    parser.add_argument(
        "--pso-keys",
        type=Path,
        default=None,
        help=(
            "read and write this persistent PSO key list (benchmarks start "
            "with no key list otherwise)"
        ),
    )
    parser.add_argument(
        "--minimum-fps",
        type=float,
        default=59.0,
        help="minimum host display-flip rate",
    )
    parser.add_argument("--minimum-delivered-fps", type=float, default=29.0)
    parser.add_argument("--maximum-p95-ms", type=float, default=18.0)
    parser.add_argument("--maximum-frame-ms", type=float, default=33.4)
    parser.add_argument("--maximum-delivered-p95-ms", type=float, default=35.0)
    parser.add_argument("--maximum-delivered-frame-ms", type=float, default=50.0)
    parser.add_argument("--maximum-gpu-ms", type=float, default=16.68)
    parser.add_argument("--maximum-readbacks", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=600.0)
    return parser.parse_args(argv)


def build_extra_environment(args: argparse.Namespace) -> dict[str, str]:
    environment: dict[str, str] = {}
    for item in args.env:
        name, separator, value = item.partition("=")
        if not name or not separator:
            raise ValueError(f"--env expects NAME=VALUE, got {item!r}")
        environment[name] = value
    if args.alternate:
        if args.alternate_presents <= 0:
            raise ValueError("--alternate-presents must be positive")
        environment["SR_PERF_ALTERNATE"] = args.alternate
        environment["SR_PERF_ALTERNATE_PRESENTS"] = str(
            args.alternate_presents
        )
    if args.pso_keys is not None:
        environment["SR_D3D12_PSO_KEYS"] = str(args.pso_keys.resolve())
    return environment


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
        validate_run_options(args.window, args.timeout)
        if args.fortune_window is not None:
            validate_run_options(args.fortune_window, args.timeout)
        if args.tail_presents < 0:
            raise ValueError("--tail-presents cannot be negative")
        if args.fortune_extra_presents < 0:
            raise ValueError("--fortune-extra-presents cannot be negative")
        thresholds = PerformanceThresholds(
            minimum_fps=args.minimum_fps,
            minimum_delivered_fps=args.minimum_delivered_fps,
            maximum_p95_ms=args.maximum_p95_ms,
            maximum_frame_ms=args.maximum_frame_ms,
            maximum_delivered_p95_ms=args.maximum_delivered_p95_ms,
            maximum_delivered_frame_ms=args.maximum_delivered_frame_ms,
            maximum_gpu_ms=args.maximum_gpu_ms,
            maximum_readbacks=args.maximum_readbacks,
        )
        executable = require_file(args.executable, "executable")
        image = require_file(args.image, "generated image")
        iso = require_file(args.iso, "game ISO")
        pad_script = require_file(args.pad_script, "pad script")
        memstick = require_arena_save(args.memstick)
        extra_environment = build_extra_environment(args)
        fixed_profile = (
            not args.allow_nonstandard_profile
            and not args.fast_forward
            and not extra_environment
            and thresholds == PerformanceThresholds()
            and args.window == DEFAULT_WINDOW
            and args.fortune_window in (None, DEFAULT_WINDOW)
            and args.tail_presents == 0
            and args.fortune_extra_presents == 0
            and replay_sha256(pad_script) == ARENA_REPLAY_SHA256
        )
        profile = read_graphics_profile(executable, required=None)
        expected = {**FIXED_GRAPHICS_PROFILE, "renderer": args.renderer}
        profile_matches = all(
            profile.get(name) == value for name, value in expected.items()
        )
        if fixed_profile and not profile_matches:
            read_graphics_profile(executable)
        fixed_profile = fixed_profile and profile_matches and args.renderer == "d3d12"
        output = (
            args.output.resolve()
            if args.output
            else ROOT
            / "out"
            / "benchmarks"
            / f"arena-{strftime('%Y%m%d-%H%M%S')}"
        )
        ensure_output_outside_fixture(output, memstick)
        output.mkdir(parents=True, exist_ok=False)
        selected = select_cases(args.case)
        results: list[dict[str, object]] = []
        for case in selected:
            case_window = args.window
            case_tail = args.tail_presents
            case_to_run = case
            if case.name == "fortune":
                case_window = args.fortune_window or args.window
                case_to_run = replace(
                    case,
                    exit_after=case.exit_after + args.fortune_extra_presents,
                )
            results.append(
                run_benchmark_case(
                    case=case_to_run,
                    executable=executable,
                    image=image,
                    iso=iso,
                    memstick=memstick,
                    pad_script=pad_script,
                    output=output / case.name,
                    profile=profile,
                    thresholds=thresholds,
                    window=case_window,
                    timeout=args.timeout,
                    renderer=args.renderer,
                    tail_presents=case_tail,
                    validate_result=fixed_profile,
                    fast_forward=args.fast_forward,
                    extra_environment=extra_environment,
                )
            )
            if args.include_unpaced:
                results.append(
                    run_benchmark_case(
                        case=case_to_run,
                        executable=executable,
                        image=image,
                        iso=iso,
                        memstick=memstick,
                        pad_script=pad_script,
                        output=output / f"{case.name}-unpaced",
                        profile=profile,
                        thresholds=thresholds,
                        window=case_window,
                        timeout=args.timeout,
                        renderer=args.renderer,
                        tail_presents=case_tail,
                        validate_result=False,
                        unpaced=True,
                        fast_forward=args.fast_forward,
                        extra_environment=extra_environment,
                    )
                )
        combined = combine_results(results, fixed_profile)
        (output / "summary.json").write_text(
            json.dumps(combined, indent=2) + "\n",
            encoding="ascii",
        )
        print(json.dumps(combined, indent=2))
        print(f"artifacts: {output}")
        if not fixed_profile:
            print("Diagnostic run only; no fixed-profile acceptance result.")
        for failure in combined["failures"]:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1 if combined["passed"] is False else 0
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
