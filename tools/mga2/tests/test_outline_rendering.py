from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))

from benchmark_common import (
    clean_runtime_environment,
    copy_memstick_fixture,
    require_arena_save,
    require_file,
)
from validate_vulkan import PpmImage, crop_image, image_metric, read_ppm
from tools.mga2.tests.test_startup_shortcut import arena_replay


@dataclass(frozen=True)
class OutlineDetail:
    original_pixels: int
    sharper_pixels: int
    changed_pixels: int
    original_partial_blocks: int
    sharper_partial_blocks: int


def outline_detail(
    original: PpmImage,
    sharper: PpmImage,
    off: PpmImage,
    scale: int,
    region: tuple[int, int, int, int],
) -> OutlineDetail:
    if scale < 1:
        raise ValueError("scale must be positive")
    if any(
        image.width != original.width or image.height != original.height
        or len(image.pixels) != image.width * image.height * 3
        for image in (original, sharper, off)
    ):
        raise ValueError("capture dimensions or pixel lengths differ")
    left, top, right, bottom = region
    if (
        left < 0 or top < 0 or right <= left or bottom <= top
        or right * scale > original.width
        or bottom * scale > original.height
    ):
        raise ValueError("outline region is outside the captures")

    original_pixels = sharper_pixels = changed_pixels = 0
    original_partial = sharper_partial = 0
    a, b, c = original.pixels, sharper.pixels, off.pixels
    for y in range(top, bottom):
        for x in range(left, right):
            original_block = sharper_block = 0
            for sy in range(scale):
                offset = ((y * scale + sy) * original.width + x * scale) * 3
                for sx in range(scale):
                    i = offset + sx * 3
                    is_original = (
                        a[i] != c[i] or a[i + 1] != c[i + 1]
                        or a[i + 2] != c[i + 2]
                    )
                    is_sharper = (
                        b[i] != c[i] or b[i + 1] != c[i + 1]
                        or b[i + 2] != c[i + 2]
                    )
                    original_block += is_original
                    sharper_block += is_sharper
                    changed_pixels += (
                        a[i] != b[i] or a[i + 1] != b[i + 1]
                        or a[i + 2] != b[i + 2]
                    )
            original_pixels += original_block
            sharper_pixels += sharper_block
            original_partial += 0 < original_block < scale * scale
            sharper_partial += 0 < sharper_block < scale * scale
    return OutlineDetail(
        original_pixels, sharper_pixels, changed_pixels,
        original_partial, sharper_partial,
    )


class OutlineDetailTests(unittest.TestCase):
    def test_partial_blocks_measure_subpixel_outline_detail(self) -> None:
        scale = 4
        width, height = 8, 4
        off = bytes(width * height * 3)
        original = bytearray(off)
        sharper = bytearray(off)
        for y in range(height):
            for x in range(width):
                offset = (y * width + x) * 3
                if x < 4:
                    original[offset] = 255
                if x < 2 or 4 <= x < 6:
                    sharper[offset] = 255
        result = outline_detail(
            PpmImage(width, height, bytes(original)),
            PpmImage(width, height, bytes(sharper)),
            PpmImage(width, height, off),
            scale, (0, 0, 2, 1),
        )
        self.assertEqual(result, OutlineDetail(16, 16, 16, 0, 2))

    def test_rejects_malformed_captures_and_regions(self) -> None:
        image = PpmImage(4, 4, bytes(4 * 4 * 3))
        with self.assertRaisesRegex(ValueError, "scale"):
            outline_detail(image, image, image, 0, (0, 0, 1, 1))
        with self.assertRaisesRegex(ValueError, "dimensions"):
            outline_detail(image, PpmImage(4, 4, b""), image, 4, (0, 0, 1, 1))
        with self.assertRaisesRegex(ValueError, "region"):
            outline_detail(image, image, image, 4, (0, 0, 2, 1))


@unittest.skipUnless(
    os.environ.get("MGA2_OUTLINE_TEST_MEMSTICK"),
    "set MGA2_OUTLINE_TEST_MEMSTICK to run the recorded Arena tests",
)
class OutlineRenderingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = require_arena_save(
            Path(os.environ["MGA2_OUTLINE_TEST_MEMSTICK"])
        )
        cls.executable = require_file(
            Path(os.environ.get(
                "MGA2_OUTLINE_TEST_EXE",
                str(ROOT / "out" / "build" / "clang-cl" / "mga2.exe"),
            )),
            "executable",
        )
        cls.image = require_file(cls.executable.with_name("mga2_image.bin"), "boot image")
        cls.iso = require_file(
            Path(os.environ.get(
                "MGA2_OUTLINE_TEST_ISO", str(ROOT / "Metal Gear Acid 2 (USA).iso")
            )),
            "ISO",
        )
        cls.replay = require_file(TOOLS / "arena_runtime.pad", "Arena replay")
        cls.validation = os.environ.get("MGA2_OUTLINE_TEST_VALIDATION") == "1"

    def capture(
        self, renderer: str, mode: str, scale: int, *, scene: str = "arena"
    ) -> dict[int, PpmImage]:
        if scene == "arena":
            frames = (28_000, 38_000)
        elif scene == "tutorial":
            frames = (14_000,)
        elif scene == "quick-arena":
            frames = (6_500,)
        else:
            raise ValueError(f"unknown outline test scene: {scene}")
        with tempfile.TemporaryDirectory(prefix="mga2-outline-test-") as temporary:
            output = Path(temporary)
            memstick = output / "memstick"
            if scene == "tutorial":
                memstick.mkdir()
                replay = require_file(TOOLS / "new_game_runtime.pad", "tutorial replay")
            else:
                copy_memstick_fixture(self.fixture, memstick)
                replay = self.replay
                if scene == "quick-arena":
                    replay = output / "quick-arena.pad"
                    replay.write_text(
                        arena_replay(True) + "6000 6000 2000 4 20\n",
                        encoding="ascii",
                    )
            config = output / "graphics.ini"
            config.write_text(
                f"renderer = {renderer}\n"
                f"internal_resolution = {scale}\n"
                "texture_scale = 1\n"
                "d3d12_full_rate = 1\n"
                "anti_aliasing = off\n"
                f"skip_startup = {'on' if scene == 'quick-arena' else 'off'}\n"
                f"outlines = {mode}\n",
                encoding="ascii",
            )
            environment = clean_runtime_environment()
            environment.update({
                "PSP_ISO": str(self.iso),
                "SR_MEMSTICK": str(memstick),
                "SR_GRAPHICS_CONFIG": str(config),
                "SR_INPUT_CONFIG": "0",
                "SR_INPUT_HOT_RELOAD": "0",
                "SR_PADLOG": "1",
                "SR_PADSCRIPT": str(replay),
                "SR_GPU": renderer,
                "SR_NOVBPACE": "1",
                "SR_NOAUDIO": "1",
                "SR_FBCAPTURE_PRESENTS": ",".join(map(str, frames)),
                "SR_EXIT_AFTER_PRESENT": str(frames[-1] + 1),
                "SR_D3D12_CAPTURE_INTERNAL": "1",
                "SR_D3D12_NO_PSO_KEYS": "1",
                "SR_VK_CAPTURE_INTERNAL": "1",
            })
            if renderer == "vk" and self.validation:
                environment["SR_VK_VALIDATION"] = "1"
            result = subprocess.run(
                [
                    str(self.executable), "--boot", str(self.image),
                    "08804000", "08804128", "none", "--gui",
                ],
                cwd=output, env=environment, capture_output=True,
                timeout=900, check=False,
            )
            stderr = result.stderr.decode("utf-8", errors="replace")
            self.assertEqual(
                result.returncode, 0,
                "\n".join(stderr.splitlines()[-30:]),
            )
            self.assertIn(f"gui_init: GE backend {renderer}", stderr)
            self.assertIn(f"outlines {mode})", stderr)
            pulse = {"arena": 26_002, "tutorial": 12_002, "quick-arena": 5_252}[scene]
            self.assertRegex(
                stderr, rf"PADSCRIPT clock=present frame={pulse} .*mask=0x2000"
            )
            self.assertIn(
                f"presentation limit reached at present {frames[-1] + 1}", stderr
            )
            if renderer == "vk" and self.validation:
                self.assertIn("sdl3vk: Vulkan validation enabled", stderr)
                self.assertNotRegex(
                    stderr, r"(?m)^sdl3vk validation (?:error|warning):"
                )
            captures = {
                frame: read_ppm(output / f"capture_present_{frame}.ppm")
                for frame in frames
            }
        for capture in captures.values():
            self.assertEqual((capture.width, capture.height), (480 * scale, 272 * scale))
        return captures

    def assert_unmodified_ui(
        self, original: PpmImage, changed: PpmImage, scale: int
    ) -> None:
        for box in ((360, 0, 480, 96), (0, 190, 480, 272)):
            scaled = tuple(value * scale for value in box)
            self.assertEqual(
                crop_image(original, scaled).pixels,
                crop_image(changed, scaled).pixels,
            )

    def test_arena_4x_modes_and_backend_parity(self) -> None:
        captures = {}
        for renderer in ("d3d12", "vk"):
            captures[renderer] = {}
            for mode in ("original", "sharper", "off"):
                captures[renderer][mode] = self.capture(renderer, mode, 4)
            original = captures[renderer]["original"][38_000]
            sharper = captures[renderer]["sharper"][38_000]
            off = captures[renderer]["off"][38_000]
            detail = outline_detail(original, sharper, off, 4, (210, 100, 280, 160))
            self.assertGreater(detail.original_pixels, 2_000, detail)
            self.assertGreater(detail.changed_pixels, 300, detail)
            self.assertGreater(detail.original_partial_blocks, 100, detail)
            self.assertGreater(
                detail.sharper_partial_blocks * 10,
                detail.original_partial_blocks * 13,
                detail,
            )
            self.assert_unmodified_ui(original, sharper, 4)
            self.assert_unmodified_ui(original, off, 4)
        for mode in ("original", "sharper", "off"):
            for frame in (28_000, 38_000):
                metric = image_metric(
                    captures["vk"][mode][frame],
                    captures["d3d12"][mode][frame],
                )
                self.assertLess(metric.mae, 0.1, (mode, frame, metric))

    def test_sharper_preserves_native_resolution(self) -> None:
        for renderer in ("d3d12", "vk"):
            with self.subTest(renderer=renderer):
                original = self.capture(renderer, "original", 1)
                sharper = self.capture(renderer, "sharper", 1)
                for frame in (28_000, 38_000):
                    self.assertEqual(original[frame].pixels, sharper[frame].pixels)

    def test_tutorial_4x_modes_and_backend_parity(self) -> None:
        original = self.capture("d3d12", "original", 4, scene="tutorial")[14_000]
        captures = {}
        for renderer in ("d3d12", "vk"):
            captures[renderer] = {
                mode: self.capture(renderer, mode, 4, scene="tutorial")[14_000]
                for mode in ("sharper", "off")
            }
            sharper = captures[renderer]["sharper"]
            off = captures[renderer]["off"]
            detail = outline_detail(
                original, sharper, off, 4, (190, 60, 315, 272)
            )
            self.assertGreater(detail.original_pixels, 10_000, detail)
            self.assertGreater(detail.changed_pixels, 1_000, detail)
            self.assertGreater(
                detail.sharper_partial_blocks * 10,
                detail.original_partial_blocks * 13,
                detail,
            )
            for changed in (sharper, off):
                for box in ((0, 0, 180, 272), (330, 0, 480, 272)):
                    scaled = tuple(value * 4 for value in box)
                    self.assertEqual(
                        crop_image(original, scaled).pixels,
                        crop_image(changed, scaled).pixels,
                    )
        for mode in ("sharper", "off"):
            metric = image_metric(captures["vk"][mode], captures["d3d12"][mode])
            self.assertLess(metric.mae, 0.1, (mode, metric))

    def test_software_outline_off(self) -> None:
        original = self.capture("sw", "original", 1, scene="quick-arena")[6_500]
        off = self.capture("sw", "off", 1, scene="quick-arena")[6_500]
        changed = sum(
            original.pixels[i : i + 3] != off.pixels[i : i + 3]
            for i in range(0, len(original.pixels), 3)
        )
        self.assertGreater(changed, 500)

    def initialization_failure(
        self, config_text: str, overrides: dict[str, str]
    ) -> str:
        with tempfile.TemporaryDirectory(prefix="mga2-outline-init-") as temporary:
            output = Path(temporary)
            config = output / "graphics.ini"
            config.write_text(config_text, encoding="ascii")
            environment = clean_runtime_environment()
            environment.update({
                "PSP_ISO": str(self.iso),
                "SR_MEMSTICK": str(output / "memstick"),
                "SR_GRAPHICS_CONFIG": str(config),
                "SR_INPUT_CONFIG": "0",
                "SR_NOAUDIO": "1",
                **overrides,
            })
            result = subprocess.run(
                [
                    str(self.executable), "--boot", str(self.image),
                    "08804000", "08804128", "none", "--gui",
                ],
                cwd=output, env=environment, capture_output=True,
                timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 2)
            return result.stderr.decode("utf-8", errors="replace")

    def test_sharper_rejects_software_renderer_override(self) -> None:
        stderr = self.initialization_failure(
            "renderer=d3d12\ninternal_resolution=4\n"
            "texture_scale=1\nanti_aliasing=off\noutlines=sharper\n",
            {"SR_GPU": "sw"},
        )
        self.assertIn(
            "sharper outlines require the D3D12 or Vulkan renderer", stderr
        )

    def test_vulkan_invalid_scale_cleans_up(self) -> None:
        stderr = self.initialization_failure(
            "renderer=vk\ninternal_resolution=4\n"
            "texture_scale=1\nanti_aliasing=off\noutlines=sharper\n",
            {"SR_GPU": "vk", "SR_VK_SCALE": "9", "SR_VK_VALIDATION": "1"},
        )
        self.assertIn("Vulkan validation enabled", stderr)
        self.assertIn("SR_VK_SCALE must be an integer from 1 to 8", stderr)
        self.assertIn("Vulkan GE backend initialization failed", stderr)
        self.assertNotRegex(
            stderr, r"(?m)^sdl3vk validation (?:error|warning):"
        )


if __name__ == "__main__":
    unittest.main()
