from __future__ import annotations

import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))

import export_cards
from benchmark_common import (
    clean_runtime_environment,
    copy_memstick_fixture,
    require_arena_save,
    require_file,
)
from validate_vulkan import PpmImage, read_ppm
from tools.mga2.tests.test_startup_shortcut import arena_replay


CARD_NAME = "it_011_00922a43.png"
ART_REGIONS = ((96, 220, 544, 508), (128, 824, 352, 968))


def changed_pixels(
    original: PpmImage, replacement: PpmImage,
    regions: tuple[tuple[int, int, int, int], ...],
) -> tuple[tuple[int, ...], int]:
    if (
        original.width != replacement.width
        or original.height != replacement.height
        or len(original.pixels) != original.width * original.height * 3
        or len(replacement.pixels) != len(original.pixels)
    ):
        raise ValueError("capture dimensions or pixel lengths differ")
    for left, top, right, bottom in regions:
        if (
            left < 0 or top < 0 or right <= left or bottom <= top
            or right > original.width or bottom > original.height
        ):
            raise ValueError("art region is outside the captures")

    counts = [0] * len(regions)
    outside = 0
    for y in range(original.height):
        for x in range(original.width):
            offset = (y * original.width + x) * 3
            if original.pixels[offset : offset + 3] == replacement.pixels[offset : offset + 3]:
                continue
            for index, (left, top, right, bottom) in enumerate(regions):
                if left <= x < right and top <= y < bottom:
                    counts[index] += 1
                    break
            else:
                outside += 1
    return tuple(counts), outside


def stripe_classes(image: PpmImage, x: int, y: int, count: int) -> list[int]:
    if (
        x < 0 or y < 0 or count <= 0 or x + count > image.width
        or y >= image.height or len(image.pixels) != image.width * image.height * 3
    ):
        raise ValueError("stripe sample is outside the capture")
    result = []
    for offset in range((y * image.width + x) * 3, (y * image.width + x + count) * 3, 3):
        red, green, blue = image.pixels[offset : offset + 3]
        if red > 180 and green < 80 and blue < 80:
            result.append(0)
        elif red < 80 and green > 180 and blue > 180:
            result.append(1)
        else:
            result.append(-1)
    return result


class CardCaptureTests(unittest.TestCase):
    def test_counts_changes_inside_and_outside_art_regions(self) -> None:
        original = PpmImage(8, 4, bytes(8 * 4 * 3))
        pixels = bytearray(original.pixels)
        for x, y in ((1, 1), (6, 2), (7, 0)):
            pixels[(y * 8 + x) * 3] = 255
        replacement = PpmImage(8, 4, bytes(pixels))
        self.assertEqual(
            changed_pixels(original, replacement, ((0, 0, 4, 4), (4, 2, 8, 4))),
            ((1, 1), 1),
        )
        with self.assertRaisesRegex(ValueError, "outside"):
            changed_pixels(original, replacement, ((0, 0, 9, 4),))

    def test_identifies_subpixel_stripes(self) -> None:
        pixels = bytes((255, 8, 24)) * 2 + bytes((8, 247, 255)) * 2
        image = PpmImage(4, 1, pixels)
        self.assertEqual(stripe_classes(image, 0, 0, 4), [0, 0, 1, 1])
        with self.assertRaisesRegex(ValueError, "outside"):
            stripe_classes(image, 1, 0, 4)


@unittest.skipUnless(
    os.environ.get("MGA2_CARD_RENDER_MEMSTICK"),
    "set MGA2_CARD_RENDER_MEMSTICK to run the recorded card-rendering tests",
)
class CardRenderingIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = require_arena_save(
            Path(os.environ["MGA2_CARD_RENDER_MEMSTICK"])
        )
        executable = require_file(
            Path(os.environ.get(
                "MGA2_CARD_RENDER_EXE",
                str(ROOT / "out" / "build" / "clang-cl" / "mga2.exe"),
            )),
            "executable",
        )
        cls.image = require_file(executable.with_name("mga2_image.bin"), "boot image")
        cls.iso = require_file(
            Path(os.environ.get(
                "MGA2_CARD_RENDER_ISO", str(ROOT / "Metal Gear Acid 2 (USA).iso")
            )),
            "ISO",
        )
        cls.renderers = tuple(
            value.strip() for value in os.environ.get(
                "MGA2_CARD_RENDERERS", "d3d12,vk"
            ).split(",")
        )
        if not cls.renderers or any(value not in ("d3d12", "vk") for value in cls.renderers):
            raise ValueError("MGA2_CARD_RENDERERS must contain d3d12 and/or vk")
        cls.temporary = tempfile.TemporaryDirectory(prefix="mga2-card-render-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        cls.replay = cls.root / "quick-arena.pad"
        cls.replay.write_text(
            arena_replay(True) + "6000 6000 2000 4 20\n", encoding="ascii"
        )
        for name in ("baseline", "modded"):
            target = cls.root / name
            target.mkdir()
            shutil.copy2(executable, target / "mga2.exe")
            shutil.copy2(require_file(executable.with_name("SDL3.dll"), "SDL3 DLL"), target)
            for directory in ("assets", "font"):
                shutil.copytree(executable.parent / directory, target / directory)

        cards = cls.root / "modded" / "mods" / "cards"
        if export_cards.main([str(cls.iso), "--out", str(cards)]) != 0:
            raise RuntimeError("could not export card templates")
        template = (cards / "templates" / CARD_NAME).read_bytes()
        width, height = struct.unpack_from(">II", template, 16)
        if (width, height) != (112, 72):
            raise ValueError("unexpected recorded card-art dimensions")
        width *= 4
        height *= 4
        row = b"".join(
            bytes((255, 12, 24, 255)) if (x // 2) % 2 == 0
            else bytes((12, 240, 255, 255))
            for x in range(width)
        )
        (cards / CARD_NAME).write_bytes(export_cards.png_rgba(width, height, row * height))

    def capture(self, renderer: str, modded: bool) -> tuple[PpmImage, str]:
        mode = "modded" if modded else "baseline"
        output = self.root / f"{renderer}-{mode}"
        output.mkdir()
        memstick = output / "memstick"
        copy_memstick_fixture(self.fixture, memstick)
        config = output / "graphics.ini"
        config.write_text(
            f"renderer = {renderer}\n"
            "internal_resolution = 4\n"
            "texture_scale = 1\n"
            "d3d12_full_rate = 1\n"
            "anti_aliasing = off\n"
            "skip_startup = on\n"
            "outlines = original\n",
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
            "SR_PADSCRIPT": str(self.replay),
            "SR_GPU": renderer,
            "SR_GPU_SAFE": "1",
            "SR_NOVBPACE": "1",
            "SR_NOAUDIO": "1",
            "SR_FAST_FORWARD_PRESENT": "12001",
            "SR_FBCAPTURE_PRESENTS": "12000",
            "SR_EXIT_AFTER_PRESENT": "12001",
            "SR_D3D12_CAPTURE_INTERNAL": "1",
            "SR_D3D12_NO_PSO_KEYS": "1",
            "SR_D3D12_VERIFY_TEXTURE_DECODE": "1",
            "SR_VK_CAPTURE_INTERNAL": "1",
        })
        if renderer == "vk" and os.environ.get("MGA2_CARD_RENDER_VALIDATION") == "1":
            environment["SR_VK_VALIDATION"] = "1"
        result = subprocess.run(
            [
                str(self.root / mode / "mga2.exe"), "--boot", str(self.image),
                "08804000", "08804128", "none", "--gui",
            ],
            cwd=output, env=environment, capture_output=True,
            timeout=900, check=False,
        )
        stderr = result.stderr.decode("utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, "\n".join(stderr.splitlines()[-30:]))
        self.assertIn(f"gui_init: GE backend {renderer}", stderr)
        if renderer == "vk" and os.environ.get("MGA2_CARD_RENDER_VALIDATION") == "1":
            self.assertIn("sdl3vk: Vulkan validation enabled", stderr)
        self.assertNotIn("background texture decode differs", stderr)
        self.assertNotIn("sdl3vk validation error:", stderr)
        if modded:
            self.assertIn(f"card mods: applying {CARD_NAME}", stderr)
        else:
            self.assertNotIn("card mods: loaded", stderr)
        return read_ppm(output / "capture_present_12000.ppm"), stderr

    def test_replacements_keep_card_bounds_and_high_resolution(self) -> None:
        for renderer in self.renderers:
            with self.subTest(renderer=renderer):
                original, _ = self.capture(renderer, False)
                replacement, _ = self.capture(renderer, True)
                self.assertEqual((replacement.width, replacement.height), (1920, 1088))
                counts, outside = changed_pixels(original, replacement, ART_REGIONS)
                self.assertEqual(outside, 0, "replacement changed pixels outside card art")
                for count, (left, top, right, bottom) in zip(counts, ART_REGIONS):
                    self.assertGreater(count, (right - left) * (bottom - top) // 2)
                self.assertEqual(
                    stripe_classes(replacement, 120, 240, 32),
                    [0, 0, 1, 1] * 8,
                    "two-pixel stripes must survive within four-pixel PSP texels",
                )


if __name__ == "__main__":
    unittest.main()
