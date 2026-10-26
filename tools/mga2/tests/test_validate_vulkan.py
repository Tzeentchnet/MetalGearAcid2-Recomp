from __future__ import annotations

import math
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

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


if __name__ == "__main__":
    unittest.main()
