#!/usr/bin/env python3
"""Capture and compare the Vulkan Arena checkpoints against software output."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from time import strftime

from benchmark_common import (
    ARENA_REPLAY_SHA256,
    BenchmarkCase,
    clean_runtime_environment,
    copy_memstick_fixture,
    ensure_output_outside_fixture,
    find_input_event,
    replay_sha256,
    require_arena_save,
    require_file,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BUILD = ROOT / "out" / "build" / "clang-cl"
PRESENTATIONS = (28_000, 38_000)
REGIONS = {
    28_000: {
        "character": (70, 0, 360, 272),
    },
    38_000: {
        "stage_player": (140, 0, 360, 220),
        "map_preview": (360, 0, 480, 96),
        "card_ui": (0, 190, 480, 272),
    },
}

# Calibrated at native internal resolution against the accepted software route.
# The current D3D12 cross-check reaches 2.66 whole-frame MAE and 3.27 region
# MAE; Vulkan is held to the same bounds rather than a renderer-specific waiver.
MAXIMUM_WHOLE_MAE = 2.66
MAXIMUM_WHOLE_RMSE = 5.55
MAXIMUM_REGION_MAE = 3.27
MAXIMUM_REGION_RMSE = 6.17

@dataclass(frozen=True)
class PpmImage:
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True)
class ImageMetric:
    mae: float
    rmse: float


def _ppm_token(data: bytes, offset: int) -> tuple[bytes, int]:
    while offset < len(data):
        if data[offset] == ord("#"):
            newline = data.find(b"\n", offset)
            if newline < 0:
                raise ValueError("unterminated PPM comment")
            offset = newline + 1
        elif chr(data[offset]).isspace():
            offset += 1
        else:
            break
    start = offset
    while offset < len(data) and not chr(data[offset]).isspace():
        if data[offset] == ord("#"):
            break
        offset += 1
    if start == offset:
        raise ValueError("missing PPM header token")
    return data[start:offset], offset


def read_ppm(path: Path) -> PpmImage:
    data = path.read_bytes()
    magic, offset = _ppm_token(data, 0)
    width_value, offset = _ppm_token(data, offset)
    height_value, offset = _ppm_token(data, offset)
    maximum_value, offset = _ppm_token(data, offset)
    if magic != b"P6":
        raise ValueError(f"{path}: expected binary P6 PPM")
    try:
        width = int(width_value)
        height = int(height_value)
        maximum = int(maximum_value)
    except ValueError as error:
        raise ValueError(f"{path}: invalid PPM header") from error
    if width <= 0 or height <= 0 or maximum != 255:
        raise ValueError(
            f"{path}: unsupported PPM geometry or maximum value"
        )
    if offset >= len(data) or not chr(data[offset]).isspace():
        raise ValueError(f"{path}: missing PPM pixel separator")
    if data[offset] == ord("\r") and data[offset : offset + 2] == b"\r\n":
        offset += 2
    else:
        offset += 1
    expected = width * height * 3
    pixels = data[offset:]
    if len(pixels) != expected:
        raise ValueError(
            f"{path}: expected {expected} pixel bytes, got {len(pixels)}"
        )
    return PpmImage(width, height, pixels)


def crop_image(
    image: PpmImage, box: tuple[int, int, int, int]
) -> PpmImage:
    left, top, right, bottom = box
    if (
        left < 0
        or top < 0
        or right > image.width
        or bottom > image.height
        or right <= left
        or bottom <= top
    ):
        raise ValueError(f"invalid crop {box} for {image.width}x{image.height}")
    row_bytes = image.width * 3
    cropped_row_bytes = (right - left) * 3
    pixels = bytearray()
    for y in range(top, bottom):
        start = y * row_bytes + left * 3
        pixels.extend(image.pixels[start : start + cropped_row_bytes])
    return PpmImage(right - left, bottom - top, bytes(pixels))


def image_metric(actual: PpmImage, reference: PpmImage) -> ImageMetric:
    if (
        actual.width != reference.width
        or actual.height != reference.height
    ):
        raise ValueError(
            "image dimensions differ: "
            f"{actual.width}x{actual.height} versus "
            f"{reference.width}x{reference.height}"
        )
    absolute = 0
    squared = 0
    for actual_value, reference_value in zip(
        actual.pixels, reference.pixels, strict=True
    ):
        difference = abs(actual_value - reference_value)
        absolute += difference
        squared += difference * difference
    samples = len(actual.pixels)
    return ImageMetric(
        mae=absolute / samples,
        rmse=math.sqrt(squared / samples),
    )


def compare_capture(
    actual_path: Path,
    reference_path: Path,
    regions: dict[str, tuple[int, int, int, int]],
) -> dict[str, object]:
    if actual_path.resolve() == reference_path.resolve() or os.path.samefile(
        actual_path, reference_path
    ):
        raise ValueError("cannot compare a capture against itself")
    actual = read_ppm(actual_path)
    reference = read_ppm(reference_path)
    whole = image_metric(actual, reference)
    region_metrics = {
        name: asdict(
            image_metric(
                crop_image(actual, box),
                crop_image(reference, box),
            )
        )
        for name, box in regions.items()
    }
    return {
        "actual": str(actual_path),
        "reference": str(reference_path),
        "actual_sha256": hashlib.sha256(actual_path.read_bytes()).hexdigest(),
        "reference_sha256": hashlib.sha256(reference_path.read_bytes()).hexdigest(),
        "width": actual.width,
        "height": actual.height,
        "whole": asdict(whole),
        "regions": region_metrics,
    }


def validate_metric_limits(
    *,
    maximum_whole_mae: float,
    maximum_whole_rmse: float,
    maximum_region_mae: float,
    maximum_region_rmse: float,
) -> None:
    for name, value in {
        "maximum_whole_mae": maximum_whole_mae,
        "maximum_whole_rmse": maximum_whole_rmse,
        "maximum_region_mae": maximum_region_mae,
        "maximum_region_rmse": maximum_region_rmse,
    }.items():
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")


def metric_failures(
    renderer: str,
    presentation: int,
    comparison: dict[str, object],
    *,
    maximum_whole_mae: float,
    maximum_whole_rmse: float,
    maximum_region_mae: float,
    maximum_region_rmse: float,
) -> list[str]:
    validate_metric_limits(
        maximum_whole_mae=maximum_whole_mae,
        maximum_whole_rmse=maximum_whole_rmse,
        maximum_region_mae=maximum_region_mae,
        maximum_region_rmse=maximum_region_rmse,
    )
    failures: list[str] = []
    whole = comparison["whole"]
    assert isinstance(whole, dict)
    whole_mae = float(whole["mae"])
    whole_rmse = float(whole["rmse"])
    if whole_mae > maximum_whole_mae:
        failures.append(
            f"{renderer} presentation {presentation} whole-frame MAE "
            f"{whole_mae:.4f} exceeds {maximum_whole_mae:.4f}"
        )
    if whole_rmse > maximum_whole_rmse:
        failures.append(
            f"{renderer} presentation {presentation} whole-frame RMSE "
            f"{whole_rmse:.4f} exceeds {maximum_whole_rmse:.4f}"
        )
    regions = comparison["regions"]
    assert isinstance(regions, dict)
    for name, values in regions.items():
        assert isinstance(values, dict)
        mae = float(values["mae"])
        rmse = float(values["rmse"])
        if mae > maximum_region_mae:
            failures.append(
                f"{renderer} presentation {presentation} {name} MAE "
                f"{mae:.4f} exceeds {maximum_region_mae:.4f}"
            )
        if rmse > maximum_region_rmse:
            failures.append(
                f"{renderer} presentation {presentation} {name} RMSE "
                f"{rmse:.4f} exceeds {maximum_region_rmse:.4f}"
            )
    return failures


def load_reference_manifest(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as stream:
        manifest = json.load(stream)
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or manifest.get("scene_verified") is not True
        or not isinstance(manifest.get("captures"), dict)
    ):
        raise ValueError(
            "reference manifest must have schema 1, scene_verified=true, "
            "and a captures object"
        )
    hashes = {}
    for presentation in PRESENTATIONS:
        value = manifest["captures"].get(str(presentation))
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError(f"reference manifest needs a SHA-256 for {presentation}")
        hashes[presentation] = value.lower()
    identity = {}
    for name in ("memstick_sha256", "replay_sha256"):
        value = manifest.get(name)
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raise ValueError(f"reference manifest needs a SHA-256 for {name}")
        identity[name] = value.lower()
    return {"captures": hashes, **identity}


def validation_report(stderr: str, *, requested: bool, log: Path) -> dict[str, object]:
    return {
        "requested": requested,
        "enabled": "sdl3vk: Vulkan validation enabled" in stderr,
        "error_count": len(re.findall(
            r"^sdl3vk validation error:", stderr, flags=re.MULTILINE
        )),
        "warning_count": len(re.findall(
            r"^sdl3vk validation warning:", stderr, flags=re.MULTILINE
        )),
        "log": str(log),
    }


def run_renderer(
    *,
    renderer: str,
    executable: Path,
    image: Path,
    iso: Path,
    memstick: Path,
    pad_script: Path,
    output: Path,
    timeout: float,
) -> dict[str, object]:
    ensure_output_outside_fixture(output, memstick)
    output.mkdir(parents=True, exist_ok=False)
    run_memstick = output / "memstick"
    fixture_sha256 = copy_memstick_fixture(memstick, run_memstick)
    environment = clean_runtime_environment()
    validation_value = os.environ.get("SR_VK_VALIDATION", "")
    validation_requested = renderer == "vk" and validation_value not in ("", "0")
    if validation_requested:
        environment["SR_VK_VALIDATION"] = validation_value
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_MEMSTICK": str(run_memstick),
            "SR_INPUT_CONFIG": "0",
            "SR_INPUT_HOT_RELOAD": "0",
            "SR_PADLOG": "1",
            "SR_PADSCRIPT": str(pad_script),
            "SR_GPU": renderer,
            "SR_FAST_FORWARD_PRESENT": "27800",
            "SR_FBCAPTURE_PRESENTS": ",".join(
                str(value) for value in PRESENTATIONS
            ),
            "SR_EXIT_AFTER_PRESENT": str(max(PRESENTATIONS) + 1),
            "SR_NOVBPACE": "1",
        }
    )
    if renderer == "vk":
        environment["SR_GPU_SAFE"] = "1"
        environment["SR_VK_SCALE"] = "1"
    elif renderer == "d3d12":
        environment["SR_D3D12_SCALE"] = "1"
    command = [
        str(executable),
        "--boot",
        str(image),
        "08804000",
        "08804128",
        "none",
        "--gui",
    ]
    stdout_path = output / "stdout.log"
    stderr_path = output / "stderr.log"
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        result = subprocess.run(
            command,
            cwd=output,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            timeout=timeout,
            check=False,
        )
    stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace")
    if result.returncode:
        tail = "\n".join(stderr_text.splitlines()[-30:])
        raise RuntimeError(
            f"{renderer} exited with {result.returncode}\n{tail}"
        )
    for presentation in PRESENTATIONS:
        capture = output / f"capture_present_{presentation}.ppm"
        if not capture.is_file():
            raise RuntimeError(
                f"{renderer} did not write required capture {capture.name}"
            )
    return {
        "memstick_sha256": fixture_sha256,
        "input_event": find_input_event(
            stderr_text,
            BenchmarkCase("arena", 0, 0, 0, input_pulse=26_000),
        ),
        "renderer_confirmed": (
            "sdl3vk: init ok " in stderr_text if renderer == "vk" else None
        ),
        "validation": validation_report(
            stderr_text, requested=validation_requested, log=stderr_path
        ) if renderer == "vk" else None,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture Vulkan Arena frames and compare the cinematic, "
            "gameplay, map preview, and UI against software output."
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
        "--memstick", type=Path, help="Arena save fixture; required when capturing"
    )
    parser.add_argument(
        "--pad-script",
        type=Path,
        default=ROOT / "tools" / "mga2" / "arena_runtime.pad",
    )
    parser.add_argument(
        "--reference-dir",
        type=Path,
        default=None,
        help=(
            "existing software capture directory; software is run when "
            "this is omitted"
        ),
    )
    parser.add_argument(
        "--reference-manifest",
        type=Path,
        default=None,
        help=(
            "local hashes and manual scene attestation for the software reference; "
            "without it the result is comparison-only"
        ),
    )
    parser.add_argument(
        "--vulkan-dir",
        type=Path,
        default=None,
        help="existing Vulkan capture directory; skip the Vulkan run",
    )
    parser.add_argument(
        "--include-d3d12",
        action="store_true",
        help="also capture and gate native-resolution D3D12",
    )
    parser.add_argument(
        "--d3d12-dir",
        type=Path,
        default=None,
        help="existing D3D12 capture directory; implies --include-d3d12",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="new output directory beneath out/validation by default",
    )
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument(
        "--maximum-whole-mae", type=float, default=MAXIMUM_WHOLE_MAE
    )
    parser.add_argument(
        "--maximum-whole-rmse", type=float, default=MAXIMUM_WHOLE_RMSE
    )
    parser.add_argument(
        "--maximum-region-mae", type=float, default=MAXIMUM_REGION_MAE
    )
    parser.add_argument(
        "--maximum-region-rmse", type=float, default=MAXIMUM_REGION_RMSE
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    try:
        thresholds = {
            "maximum_whole_mae": args.maximum_whole_mae,
            "maximum_whole_rmse": args.maximum_whole_rmse,
            "maximum_region_mae": args.maximum_region_mae,
            "maximum_region_rmse": args.maximum_region_rmse,
        }
        validate_metric_limits(**thresholds)
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        manifest_path = (
            require_file(args.reference_manifest, "reference manifest")
            if args.reference_manifest else None
        )
        reference_manifest = (
            load_reference_manifest(manifest_path) if manifest_path else None
        )
        need_d3d12 = args.include_d3d12 or args.d3d12_dir is not None
        needs_capture = (
            args.reference_dir is None
            or args.vulkan_dir is None
            or (need_d3d12 and args.d3d12_dir is None)
        )
        executable = image = iso = pad_script = memstick = None
        if needs_capture:
            if args.memstick is None:
                raise ValueError("--memstick is required when capturing")
            executable = require_file(args.executable, "executable")
            image = require_file(args.image, "recompiled image")
            iso = require_file(args.iso, "ISO")
            pad_script = require_file(args.pad_script, "Arena input replay")
            memstick = require_arena_save(args.memstick)
        output = (
            args.output.resolve()
            if args.output
            else (
                ROOT
                / "out"
                / "validation"
                / f"vulkan-{strftime('%Y%m%d-%H%M%S')}"
            )
        )
        if memstick is not None:
            ensure_output_outside_fixture(output, memstick)
        output.mkdir(parents=True, exist_ok=False)
        runs: dict[str, dict[str, object]] = {}

        def capture(renderer: str, directory: Path) -> dict[str, object]:
            assert executable is not None
            assert image is not None
            assert iso is not None
            assert pad_script is not None
            assert memstick is not None
            return run_renderer(
                renderer=renderer,
                executable=executable,
                image=image,
                iso=iso,
                memstick=memstick,
                pad_script=pad_script,
                output=directory,
                timeout=args.timeout,
            )

        if args.reference_dir:
            reference_dir = args.reference_dir.resolve()
        else:
            reference_dir = output / "software"
            runs["software"] = capture("sw", reference_dir)

        if args.vulkan_dir:
            vulkan_dir = args.vulkan_dir.resolve()
        else:
            vulkan_dir = output / "vulkan"
            runs["vulkan"] = capture("vk", vulkan_dir)

        renderer_dirs = {"vulkan": vulkan_dir}
        if need_d3d12:
            if args.d3d12_dir:
                d3d12_dir = args.d3d12_dir.resolve()
            else:
                d3d12_dir = output / "d3d12"
                runs["d3d12"] = capture("d3d12", d3d12_dir)
            renderer_dirs["d3d12"] = d3d12_dir

        comparisons: dict[str, dict[str, object]] = {}
        failures: list[str] = []
        pixel_failures: list[str] = []
        replay_hash = replay_sha256(pad_script) if pad_script else None
        for renderer, run in runs.items():
            if replay_hash == ARENA_REPLAY_SHA256 and run["input_event"] is None:
                failures.append(f"{renderer}: required Arena replay input was not observed")
            if renderer == "vulkan" and not run["renderer_confirmed"]:
                failures.append("Vulkan renderer initialization was not confirmed")
            if reference_manifest and (
                run["memstick_sha256"] != reference_manifest["memstick_sha256"]
                or replay_hash != reference_manifest["replay_sha256"]
            ):
                failures.append(f"{renderer}: fixture or replay differs from reference manifest")

        validation_requested = os.environ.get("SR_VK_VALIDATION", "") not in ("", "0")
        if "vulkan" in runs:
            validation = runs["vulkan"]["validation"]
        else:
            log = vulkan_dir / "stderr.log"
            validation = (
                validation_report(
                    log.read_text(encoding="utf-8", errors="replace"),
                    requested=validation_requested,
                    log=log,
                )
                if log.is_file()
                else {
                    "requested": validation_requested,
                    "enabled": None,
                    "error_count": None,
                    "warning_count": None,
                    "log": str(log),
                }
            )
        assert isinstance(validation, dict)
        if validation_requested and validation["enabled"] is not True:
            failures.append("Vulkan validation was requested but not confirmed in the log")
        if validation["error_count"]:
            failures.append(
                f"Vulkan validation reported {validation['error_count']} error(s); "
                f"see {validation['log']}"
            )

        for renderer, capture_dir in renderer_dirs.items():
            renderer_comparisons: dict[str, object] = {}
            for presentation in PRESENTATIONS:
                comparison = compare_capture(
                    capture_dir / f"capture_present_{presentation}.ppm",
                    reference_dir
                    / f"capture_present_{presentation}.ppm",
                    REGIONS[presentation],
                )
                renderer_comparisons[str(presentation)] = comparison
                if (comparison["width"], comparison["height"]) != (480, 272):
                    pixel_failures.append(
                        f"{renderer} presentation {presentation} is not 480x272"
                    )
                if reference_manifest:
                    hashes = reference_manifest["captures"]
                    assert isinstance(hashes, dict)
                    if comparison["reference_sha256"] != hashes[presentation]:
                        failures.append(
                            f"reference presentation {presentation} differs "
                            "from the attested manifest"
                        )
                pixel_failures.extend(
                    metric_failures(
                        renderer,
                        presentation,
                        comparison,
                        **thresholds,
                    )
                )
            comparisons[renderer] = renderer_comparisons

        failures.extend(pixel_failures)
        diagnostic_reasons = []
        if reference_manifest is None:
            diagnostic_reasons.append("reference scene identity is not attested")
        if args.vulkan_dir is not None:
            diagnostic_reasons.append("existing Vulkan captures have unverified provenance")
        if args.d3d12_dir is not None:
            diagnostic_reasons.append("existing D3D12 captures have unverified provenance")
        if replay_hash != ARENA_REPLAY_SHA256:
            diagnostic_reasons.append("canonical Arena replay was not verified")
        if thresholds != {
            "maximum_whole_mae": MAXIMUM_WHOLE_MAE,
            "maximum_whole_rmse": MAXIMUM_WHOLE_RMSE,
            "maximum_region_mae": MAXIMUM_REGION_MAE,
            "maximum_region_rmse": MAXIMUM_REGION_RMSE,
        }:
            diagnostic_reasons.append("comparison limits differ from the fixed contract")
        validated = not diagnostic_reasons
        summary = {
            "validated": validated,
            "passed": not failures if validated else None,
            "comparison_passed": not pixel_failures,
            "scene_identity": "user-attested" if reference_manifest else "unverified",
            "diagnostic_reasons": diagnostic_reasons,
            "reference_dir": str(reference_dir),
            "reference_manifest": str(manifest_path) if manifest_path else None,
            "replay_sha256": replay_hash,
            "thresholds": thresholds,
            "runs": runs,
            "vulkan_validation": validation,
            "comparisons": comparisons,
            "failures": failures,
        }
        summary_path = output / "summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        for renderer, renderer_comparisons in comparisons.items():
            for presentation, comparison in renderer_comparisons.items():
                whole = comparison["whole"]
                assert isinstance(whole, dict)
                print(
                    f"{renderer} {presentation}: "
                    f"MAE {float(whole['mae']):.4f}, "
                    f"RMSE {float(whole['rmse']):.4f}"
                )
        if validation["warning_count"]:
            print(
                f"Vulkan validation reported {validation['warning_count']} warning(s); "
                f"see {validation['log']}"
            )
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            print(f"wrote {summary_path}", file=sys.stderr)
            return 1
        if validated:
            print(f"Vulkan visual validation passed against the attested reference; wrote {summary_path}")
        else:
            print(
                "Pixel comparison passed, but scene validation is not established: "
                + "; ".join(diagnostic_reasons)
            )
            print(f"wrote {summary_path}")
        return 0
    except (
        OSError,
        RuntimeError,
        subprocess.TimeoutExpired,
        ValueError,
    ) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
