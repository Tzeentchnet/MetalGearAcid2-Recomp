from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
ROOT = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))

from benchmark_common import (
    BenchmarkCase,
    clean_runtime_environment,
    copy_memstick_fixture,
    find_input_event,
    parse_runtime_profile,
    require_arena_save,
    require_file,
)
from validate_vulkan import PpmImage, read_ppm


def validate_scene(image: PpmImage) -> None:
    if (image.width, image.height) != (480, 272):
        raise ValueError(f"unexpected capture size: {image.width}x{image.height}")
    colors: set[bytes] = set()
    bright = 0
    for offset in range(0, len(image.pixels), 3):
        color = image.pixels[offset : offset + 3]
        colors.add(color)
        if max(color) > 16:
            bright += 1
    if bright * 10 < image.width * image.height or len(colors) < 64:
        raise ValueError("capture is black or lacks scene detail")


def validate_main_menu(image: PpmImage) -> None:
    validate_scene(image)
    white = 0
    for y in range(24, 40):
        for x in range(56, 232):
            offset = (y * image.width + x) * 3
            if min(image.pixels[offset : offset + 3]) > 200:
                white += 1
    if white * 2 < (232 - 56) * (40 - 24):
        raise ValueError("capture does not show the selected main-menu entry")


def validate_arena_progress(stderr: str, pulse: int) -> None:
    case = BenchmarkCase("startup-arena", 0, 0, 0, input_pulse=pulse)
    if find_input_event(stderr, case) is None:
        raise ValueError("Arena confirmation input was not observed")
    request = re.search(
        r"^SavedataInitStart param=.* mode=4 gameName='ULUS10077' "
        r"saveName='003' result=0x00000000\s*$",
        stderr,
        flags=re.MULTILINE,
    )
    if request is None:
        raise ValueError("Arena save-load request was not observed")
    completed = re.search(
        r"^SavedataUpdate: FINISHED result=0x00000000\b",
        stderr[request.end() :],
        flags=re.MULTILINE,
    )
    if completed is None:
        raise ValueError("Arena save did not finish loading successfully")
    after_load = stderr[request.end() + completed.end() :]
    if not re.search(
        r"^module loader: mgp_stage .* size=11100\b", after_load, re.MULTILINE
    ):
        raise ValueError("Arena stage did not load after the save")


def arena_replay(skip_startup: bool) -> str:
    lines = ["# psp-recomp pad script v3"]
    if skip_startup:
        # Scripted input replaces the runtime's automatic START pulses.
        starts = range(60, 4000, 60)
        downs = range(4200, 4801, 150)
        confirms = (4950, 5250)
    else:
        starts = (7200,)
        downs = (9200, 9500, 9800, 10100, 10400)
        confirms = (11000, 11400)
    for frame in starts:
        width = 4 if skip_startup else 20
        lines.append(f"{frame} {frame} 0008 4 {width}")
    for frame in downs:
        lines.append(f"{frame} {frame} 0040 4 20")
    for frame in confirms:
        lines.append(f"{frame} {frame} 2000 4 20")
    return "\n".join(lines) + "\n"


class StartupShortcutValidationTests(unittest.TestCase):
    def test_black_capture_is_rejected(self) -> None:
        image = PpmImage(480, 272, bytes(480 * 272 * 3))
        with self.assertRaisesRegex(ValueError, "black"):
            validate_scene(image)

    def test_main_menu_requires_its_selected_entry(self) -> None:
        palette = b"".join(bytes((128, value, value)) for value in range(128))
        pixels = bytearray(palette * (480 * 272 // 128))
        image = PpmImage(480, 272, bytes(pixels))
        validate_scene(image)
        with self.assertRaisesRegex(ValueError, "main-menu"):
            validate_main_menu(image)
        for y in range(24, 40):
            start = (y * 480 + 56) * 3
            pixels[start : start + 176 * 3] = bytes((255, 255, 255)) * 176
        validate_main_menu(PpmImage(480, 272, bytes(pixels)))

    def test_save_and_arena_stage_must_both_complete(self) -> None:
        log = (
            "PADSCRIPT clock=present frame=5252 present=5252 "
            "vblank=3052 mask=0x2000\n"
            "SavedataInitStart param=0x1 size=1536 mode=4 "
            "gameName='ULUS10077' saveName='003' result=0x00000000\n"
            "SavedataUpdate: FINISHED result=0x00000000 written to 0x2\n"
            "module loader: mgp_stage uid=0x1 base=09a0b500 size=11100 "
            "entry=09a0b534\n"
        )
        validate_arena_progress(log, 5250)
        with self.assertRaisesRegex(ValueError, "did not finish"):
            validate_arena_progress(log.replace("FINISHED", "FAILED"), 5250)
        with self.assertRaisesRegex(ValueError, "stage did not load"):
            validate_arena_progress(log.replace("size=11100", "size=800"), 5250)
        with self.assertRaisesRegex(ValueError, "confirmation input"):
            validate_arena_progress(log, 5200)
        with self.assertRaisesRegex(ValueError, "save-load request"):
            validate_arena_progress(log.replace("saveName='003'", "saveName='000'"), 5250)


@unittest.skipUnless(
    os.environ.get("MGA2_STARTUP_TEST_MEMSTICK"),
    "set MGA2_STARTUP_TEST_MEMSTICK to run the save-based startup tests",
)
class StartupShortcutIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.memstick = require_arena_save(Path(os.environ["MGA2_STARTUP_TEST_MEMSTICK"]))
        cls.executable = require_file(
            Path(
                os.environ.get(
                    "MGA2_STARTUP_TEST_EXE",
                    str(ROOT / "out" / "build" / "clang-cl" / "mga2.exe"),
                )
            ),
            "executable",
        )
        cls.image = require_file(cls.executable.with_name("mga2_image.bin"), "boot image")
        cls.iso = require_file(
            Path(
                os.environ.get(
                    "MGA2_STARTUP_TEST_ISO",
                    str(ROOT / "Metal Gear Acid 2 (USA).iso"),
                )
            ),
            "ISO",
        )

    def run_capture(
        self,
        *,
        skip_startup: bool,
        capture: int,
        stop: int,
        replay: str | None,
        empty_memstick: bool = False,
    ) -> tuple[str, PpmImage]:
        with tempfile.TemporaryDirectory(prefix="mga2-startup-test-") as temporary:
            output = Path(temporary)
            memstick = output / "memstick"
            if empty_memstick:
                memstick.mkdir()
            else:
                copy_memstick_fixture(self.memstick, memstick)
            config = output / "graphics.ini"
            config.write_text(
                "renderer = d3d12\n"
                "internal_resolution = 4\n"
                "texture_scale = 1\n"
                "d3d12_full_rate = 1\n"
                "anti_aliasing = smaa\n"
                f"skip_startup = {'on' if skip_startup else 'off'}\n",
                encoding="ascii",
            )
            environment = clean_runtime_environment()
            environment.update(
                {
                    "PSP_ISO": str(self.iso),
                    "SR_MEMSTICK": str(memstick),
                    "SR_GRAPHICS_CONFIG": str(config),
                    "SR_INPUT_CONFIG": "0",
                    "SR_INPUT_HOT_RELOAD": "0",
                    "SR_D3D12_NO_PSO_KEYS": "1",
                    "SR_DLGLOG": "1",
                    "SR_MODULE_LOG": "1",
                    "SR_PADLOG": "1",
                    "SR_FBCAPTURE_PRESENTS": str(capture),
                    "SR_EXIT_AFTER_PRESENT": str(stop),
                }
            )
            if replay is None:
                environment["SR_PAD"] = "0"
            else:
                pad = output / "arena.pad"
                pad.write_text(replay, encoding="ascii")
                environment["SR_PADSCRIPT"] = str(pad)
            command = [
                str(self.executable),
                "--boot",
                str(self.image),
                "08804000",
                "08804128",
                "none",
                "--gui",
            ]
            result = subprocess.run(
                command,
                cwd=output,
                env=environment,
                capture_output=True,
                timeout=300,
                check=False,
            )
            stderr = result.stderr.decode("utf-8", errors="replace")
            if result.returncode:
                tail = "\n".join(stderr.splitlines()[-30:])
                self.fail(f"runtime exited with {result.returncode}\n{tail}")
            self.assertIn(f"presentation limit reached at present {stop}", stderr)
            profile = parse_runtime_profile(stderr)
            self.assertIsNotNone(profile)
            self.assertEqual(profile["renderer"], "d3d12")
            self.assertEqual(profile["skip_startup"], "on" if skip_startup else "off")
            image = read_ppm(output / f"capture_present_{capture}.ppm")
            return stderr, image

    def test_automatic_startup_reaches_main_menu(self) -> None:
        for empty in (False, True):
            with self.subTest(empty_memstick=empty):
                stderr, image = self.run_capture(
                    skip_startup=True,
                    capture=4100,
                    stop=4250,
                    replay=None,
                    empty_memstick=empty,
                )
                self.assertIn("input: startup skip button 0x0008", stderr)
                self.assertIn("scheduler: fast-forwarding to presentation 4000", stderr)
                self.assertIn("scheduler: real-time pacing enabled", stderr)
                validate_main_menu(image)

    def test_arena_with_startup_shortcut(self) -> None:
        stderr, image = self.run_capture(
            skip_startup=True,
            capture=6500,
            stop=7000,
            replay=arena_replay(True),
        )
        validate_arena_progress(stderr, 5250)
        validate_scene(image)

    def test_arena_with_normal_startup(self) -> None:
        stderr, image = self.run_capture(
            skip_startup=False,
            capture=12900,
            stop=13000,
            replay=arena_replay(False),
        )
        validate_arena_progress(stderr, 11400)
        validate_scene(image)


if __name__ == "__main__":
    unittest.main()
