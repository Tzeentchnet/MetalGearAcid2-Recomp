from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import validate_vulkan
from benchmark_common import ARENA_REPLAY_SHA256, copy_memstick_fixture
from validate_vulkan import (
    PpmImage,
    compare_capture,
    crop_image,
    image_metric,
    metric_failures,
    read_ppm,
)


def write_ppm(
    path: Path, width: int, height: int, pixels: bytes
) -> None:
    path.write_bytes(
        f"P6\n# test image\n{width} {height}\n255\n".encode("ascii")
        + pixels
    )


class ValidateVulkanTests(unittest.TestCase):
    def test_reads_binary_ppm_with_comment(self) -> None:
        pixels = bytes((0, 1, 2, 253, 254, 255))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.ppm"
            write_ppm(path, 2, 1, pixels)
            image = read_ppm(path)
        self.assertEqual((image.width, image.height), (2, 1))
        self.assertEqual(image.pixels, pixels)

    def test_rejects_truncated_ppm(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.ppm"
            write_ppm(path, 2, 1, bytes((0, 1, 2)))
            with self.assertRaisesRegex(ValueError, "expected 6 pixel bytes"):
                read_ppm(path)

    def test_crops_rows_without_changing_channels(self) -> None:
        image = PpmImage(
            3,
            2,
            bytes(
                (
                    1,
                    2,
                    3,
                    4,
                    5,
                    6,
                    7,
                    8,
                    9,
                    10,
                    11,
                    12,
                    13,
                    14,
                    15,
                    16,
                    17,
                    18,
                )
            ),
        )
        cropped = crop_image(image, (1, 0, 3, 2))
        self.assertEqual((cropped.width, cropped.height), (2, 2))
        self.assertEqual(
            cropped.pixels,
            bytes((4, 5, 6, 7, 8, 9, 13, 14, 15, 16, 17, 18)),
        )

    def test_computes_mae_and_rmse(self) -> None:
        actual = PpmImage(2, 1, bytes((0, 10, 20, 30, 40, 50)))
        reference = PpmImage(2, 1, bytes(6))
        metric = image_metric(actual, reference)
        self.assertAlmostEqual(metric.mae, 25.0)
        self.assertAlmostEqual(metric.rmse, math.sqrt(5500 / 6))

    def test_compares_whole_frame_and_named_region(self) -> None:
        reference_pixels = bytes(2 * 2 * 3)
        actual_pixels = bytearray(reference_pixels)
        actual_pixels[9:12] = bytes((3, 6, 9))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / "actual.ppm"
            reference = root / "reference.ppm"
            write_ppm(actual, 2, 2, bytes(actual_pixels))
            write_ppm(reference, 2, 2, reference_pixels)
            comparison = compare_capture(
                actual, reference, {"bottom": (0, 1, 2, 2)}
            )
        whole = comparison["whole"]
        regions = comparison["regions"]
        self.assertIsInstance(whole, dict)
        self.assertIsInstance(regions, dict)
        assert isinstance(whole, dict)
        assert isinstance(regions, dict)
        self.assertAlmostEqual(float(whole["mae"]), 1.5)
        bottom = regions["bottom"]
        self.assertIsInstance(bottom, dict)
        assert isinstance(bottom, dict)
        self.assertAlmostEqual(float(bottom["mae"]), 3.0)

    def test_reports_threshold_failures(self) -> None:
        comparison = {
            "whole": {"mae": 3.0, "rmse": 6.0},
            "regions": {
                "map_preview": {"mae": 4.0, "rmse": 7.0},
            },
        }
        failures = metric_failures(
            "vulkan",
            38_000,
            comparison,
            maximum_whole_mae=2.0,
            maximum_whole_rmse=5.0,
            maximum_region_mae=3.0,
            maximum_region_rmse=6.0,
        )
        self.assertEqual(len(failures), 4)
        self.assertTrue(
            any("map_preview MAE" in failure for failure in failures)
        )

    def test_rejects_nonfinite_and_negative_limits(self) -> None:
        comparison = {"whole": {"mae": 0.0, "rmse": 0.0}, "regions": {}}
        for value in (float("nan"), float("inf"), -1.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                metric_failures(
                    "vulkan", 28000, comparison,
                    maximum_whole_mae=value,
                    maximum_whole_rmse=1.0,
                    maximum_region_mae=1.0,
                    maximum_region_rmse=1.0,
                )

    def test_rejects_self_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "image.ppm"
            write_ppm(path, 1, 1, b"\0\0\0")
            with self.assertRaisesRegex(ValueError, "against itself"):
                compare_capture(path, path, {})

    def test_existing_identical_images_are_only_a_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference"
            vulkan = root / "vulkan"
            reference.mkdir()
            vulkan.mkdir()
            for presentation in validate_vulkan.PRESENTATIONS:
                for directory in (reference, vulkan):
                    write_ppm(
                        directory / f"capture_present_{presentation}.ppm",
                        480, 272, bytes(480 * 272 * 3),
                    )
            output = root / "result"
            with mock.patch.dict(os.environ, {"SR_VK_VALIDATION": "0"}):
                with redirect_stdout(StringIO()) as stdout, redirect_stderr(StringIO()):
                    result = validate_vulkan.main([
                        "--reference-dir", str(reference),
                        "--vulkan-dir", str(vulkan),
                        "--output", str(output),
                    ])
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertTrue(summary["comparison_passed"])
            self.assertFalse(summary["validated"])
            self.assertIsNone(summary["passed"])
            self.assertEqual(summary["scene_identity"], "unverified")
            self.assertIn("scene validation is not established", stdout.getvalue())

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(validate_vulkan.main([
                    "--reference-dir", str(reference),
                    "--vulkan-dir", str(reference),
                    "--output", str(root / "same"),
                ]), 2)

    def test_validation_errors_and_missing_layer_confirmation_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference"
            vulkan = root / "vulkan"
            reference.mkdir()
            vulkan.mkdir()
            for presentation in validate_vulkan.PRESENTATIONS:
                for directory in (reference, vulkan):
                    write_ppm(
                        directory / f"capture_present_{presentation}.ppm",
                        480, 272, bytes(480 * 272 * 3),
                    )
            log = vulkan / "stderr.log"
            log.write_text(
                "sdl3vk: Vulkan validation enabled\n"
                "sdl3vk validation warning: warning\n"
                "sdl3vk validation error: synthetic error\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"SR_VK_VALIDATION": "1"}):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    result = validate_vulkan.main([
                        "--reference-dir", str(reference), "--vulkan-dir", str(vulkan),
                        "--output", str(root / "with-error"),
                    ])
                    log.unlink()
                    missing = validate_vulkan.main([
                        "--reference-dir", str(reference), "--vulkan-dir", str(vulkan),
                        "--output", str(root / "missing-log"),
                    ])
            self.assertEqual(result, 1)
            self.assertEqual(missing, 1)
            summary = json.loads(
                (root / "with-error" / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["vulkan_validation"]["error_count"], 1)
            self.assertEqual(summary["vulkan_validation"]["warning_count"], 1)

    def test_live_capture_requires_attested_reference_and_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            reference = root / "reference"
            reference.mkdir()
            hashes = {}
            for presentation in validate_vulkan.PRESENTATIONS:
                path = reference / f"capture_present_{presentation}.ppm"
                write_ppm(path, 480, 272, bytes(480 * 272 * 3))
                hashes[str(presentation)] = hashlib.sha256(path.read_bytes()).hexdigest()

            memstick = root / "memstick"
            save = memstick / "PSP" / "SAVEDATA" / "ULUS10077003"
            save.mkdir(parents=True)
            (save / "PARAM.SFO").write_bytes(b"sfo")
            (save / "00000000.000").write_bytes(b"\0" * 48_800)
            fixture_hash = copy_memstick_fixture(memstick, root / "fixture-copy")
            manifest = root / "reference.json"
            manifest.write_text(json.dumps({
                "schema": 1,
                "scene_verified": True,
                "captures": hashes,
                "memstick_sha256": fixture_hash,
                "replay_sha256": ARENA_REPLAY_SHA256,
            }), encoding="utf-8")
            for name in ("game.exe", "image.bin", "disc.iso"):
                (root / name).touch()

            def fake_renderer(**kwargs):
                output = kwargs["output"]
                output.mkdir()
                for presentation in validate_vulkan.PRESENTATIONS:
                    write_ppm(
                        output / f"capture_present_{presentation}.ppm",
                        480, 272, bytes(480 * 272 * 3),
                    )
                return {
                    "memstick_sha256": fixture_hash,
                    "input_event": {"frame": 26000},
                    "renderer_confirmed": True,
                    "validation": {
                        "requested": False, "enabled": False,
                        "error_count": 0, "warning_count": 0,
                        "log": str(output / "stderr.log"),
                    },
                }

            output = root / "result"
            with mock.patch.dict(os.environ, {"SR_VK_VALIDATION": "0"}), mock.patch.object(
                validate_vulkan, "run_renderer", side_effect=fake_renderer
            ), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                result = validate_vulkan.main([
                    "--reference-dir", str(reference),
                    "--reference-manifest", str(manifest),
                    "--memstick", str(memstick),
                    "--executable", str(root / "game.exe"),
                    "--image", str(root / "image.bin"),
                    "--iso", str(root / "disc.iso"),
                    "--output", str(output),
                ])
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertTrue(summary["validated"])
            self.assertTrue(summary["passed"])
            self.assertEqual(summary["scene_identity"], "user-attested")

    def test_run_renderer_surfaces_validation_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            memstick = root / "memstick"
            memstick.mkdir()
            (memstick / "save.bin").write_bytes(b"fixture")

            def fake_run(command, *, cwd, env, stdout, stderr, timeout, check):
                self.assertNotIn("SR_GEDUMP", env)
                self.assertEqual(env["SR_VK_VALIDATION"], "1")
                stderr.write(
                    b"sdl3vk: Vulkan validation enabled\n"
                    b"sdl3vk: init ok (synthetic)\n"
                    b"sdl3vk validation error: synthetic error\n"
                )
                for presentation in validate_vulkan.PRESENTATIONS:
                    (cwd / f"capture_present_{presentation}.ppm").touch()
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ, {"SR_GEDUMP": "1", "SR_VK_VALIDATION": "1"}
            ), mock.patch.object(
                validate_vulkan.subprocess, "run", side_effect=fake_run
            ):
                result = validate_vulkan.run_renderer(
                    renderer="vk",
                    executable=root / "game.exe",
                    image=root / "image.bin",
                    iso=root / "disc.iso",
                    memstick=memstick,
                    pad_script=root / "replay.pad",
                    output=root / "output",
                    timeout=30.0,
                )
            self.assertEqual(result["validation"]["error_count"], 1)
            self.assertTrue(result["renderer_confirmed"])
            with self.assertRaisesRegex(ValueError, "inside the memory-stick"):
                validate_vulkan.run_renderer(
                    renderer="vk",
                    executable=root / "game.exe",
                    image=root / "image.bin",
                    iso=root / "disc.iso",
                    memstick=memstick,
                    pad_script=root / "replay.pad",
                    output=memstick / "bad-output",
                    timeout=30.0,
                )
            self.assertFalse((memstick / "bad-output").exists())


if __name__ == "__main__":
    unittest.main()
