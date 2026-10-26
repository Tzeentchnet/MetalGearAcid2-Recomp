#!/usr/bin/env python3
"""Capture and compare the Vulkan Arena checkpoints against software output."""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
from time import strftime


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

CLEARED_ENVIRONMENT = (
    "SR_D3D12_SCALE",
    "SR_EXIT_AFTER_PRESENT",
    "SR_FAST_FORWARD_PRESENT",
    "SR_FBCAPTURE_PRESENTS",
    "SR_GPU",
    "SR_GPU_GE",
    "SR_GPU_SAFE",
    "SR_MEMSTICK",
    "SR_NOVBPACE",
    "SR_PADSCRIPT",
)


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
        "width": actual.width,
        "height": actual.height,
        "whole": asdict(whole),
        "regions": region_metrics,
    }


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


def require_file(path: Path, description: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"{description} does not exist: {resolved}")
    return resolved


def require_memstick(path: Path) -> Path:
    resolved = path.resolve()
    save = resolved / "PSP" / "SAVEDATA" / "ULUS10077003"
    data = save / "00000000.000"
    parameter = save / "PARAM.SFO"
    if not parameter.is_file() or not data.is_file():
        raise ValueError(
            "memory stick must contain PSP/SAVEDATA/ULUS10077003"
        )
    if data.stat().st_size != 48_800:
        raise ValueError(
            f"Arena save has size {data.stat().st_size}, expected 48800"
        )
    return resolved


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
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    run_memstick = output / "memstick"
    shutil.copytree(memstick, run_memstick)
    environment = os.environ.copy()
    for name in CLEARED_ENVIRONMENT:
        environment.pop(name, None)
    environment.update(
        {
            "PSP_ISO": str(iso),
            "SR_MEMSTICK": str(run_memstick),
            "SR_INPUT_CONFIG": "0",
            "SR_INPUT_HOT_RELOAD": "0",
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
    if result.returncode:
        tail = "\n".join(
            stderr_path.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines()[-30:]
        )
        raise RuntimeError(
            f"{renderer} exited with {result.returncode}\n{tail}"
        )
    for presentation in PRESENTATIONS:
        capture = output / f"capture_present_{presentation}.ppm"
        if not capture.is_file():
            raise RuntimeError(
                f"{renderer} did not write required capture {capture.name}"
            )


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
    parser.add_argument("--memstick", type=Path, required=True)
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
        executable = require_file(args.executable, "executable")
        image = require_file(args.image, "recompiled image")
        iso = require_file(args.iso, "ISO")
        pad_script = require_file(args.pad_script, "Arena input replay")
        memstick = require_memstick(args.memstick)
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
        output.mkdir(parents=True, exist_ok=False)

        if args.reference_dir:
            reference_dir = args.reference_dir.resolve()
        else:
            reference_dir = output / "software"
            run_renderer(
                renderer="sw",
                executable=executable,
                image=image,
                iso=iso,
                memstick=memstick,
                pad_script=pad_script,
                output=reference_dir,
                timeout=args.timeout,
            )

        if args.vulkan_dir:
            vulkan_dir = args.vulkan_dir.resolve()
        else:
            vulkan_dir = output / "vulkan"
            run_renderer(
                renderer="vk",
                executable=executable,
                image=image,
                iso=iso,
                memstick=memstick,
                pad_script=pad_script,
                output=vulkan_dir,
                timeout=args.timeout,
            )

        renderer_dirs = {"vulkan": vulkan_dir}
        if args.include_d3d12 or args.d3d12_dir:
            if args.d3d12_dir:
                d3d12_dir = args.d3d12_dir.resolve()
            else:
                d3d12_dir = output / "d3d12"
                run_renderer(
                    renderer="d3d12",
                    executable=executable,
                    image=image,
                    iso=iso,
                    memstick=memstick,
                    pad_script=pad_script,
                    output=d3d12_dir,
                    timeout=args.timeout,
                )
            renderer_dirs["d3d12"] = d3d12_dir

        comparisons: dict[str, dict[str, object]] = {}
        failures: list[str] = []
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
                failures.extend(
                    metric_failures(
                        renderer,
                        presentation,
                        comparison,
                        maximum_whole_mae=args.maximum_whole_mae,
                        maximum_whole_rmse=args.maximum_whole_rmse,
                        maximum_region_mae=args.maximum_region_mae,
                        maximum_region_rmse=args.maximum_region_rmse,
                    )
                )
            comparisons[renderer] = renderer_comparisons

        summary = {
            "passed": not failures,
            "reference_dir": str(reference_dir),
            "thresholds": {
                "maximum_whole_mae": args.maximum_whole_mae,
                "maximum_whole_rmse": args.maximum_whole_rmse,
                "maximum_region_mae": args.maximum_region_mae,
                "maximum_region_rmse": args.maximum_region_rmse,
            },
            "comparisons": comparisons,
            "failures": failures,
        }
        summary_path = output / "summary.json"
        summary_path.write_text(
            json.dumps(summary, indent=2) + "\n",
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
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            print(f"wrote {summary_path}", file=sys.stderr)
            return 1
        print(f"Vulkan visual validation passed; wrote {summary_path}")
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
