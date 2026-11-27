from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import recomplauncher


def progress_lines(lines: list[str]) -> list[str]:
    tracker = recomplauncher.InstallProgress()
    output = StringIO()
    with redirect_stdout(output):
        for line in lines:
            tracker.line(line)
    return output.getvalue().splitlines()


def make_project(root: Path) -> None:
    for name in recomplauncher.BUILD_INPUT_FILES:
        (root / name).write_text(name, encoding="utf-8")
    for directory in ("cmake", "config", "tools/mga2/tests"):
        (root / directory).mkdir(parents=True)
    (root / "config" / "mga2.toml").write_text("[disc]\n", encoding="utf-8")
    (root / "tools" / "mga2" / "gen.py").write_text("gen", encoding="utf-8")


class ArgumentTests(unittest.TestCase):
    def test_prepare_and_play_need_a_game(self) -> None:
        for mode in ("--prepare", "--play"):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                recomplauncher.parse_args([mode])

    def test_play_forwards_unknown_options_to_the_game(self) -> None:
        args, extra = recomplauncher.parse_args(
            ["--play", "--game", "g.iso", "--data", "d", "--trace-start=8804128"]
        )
        self.assertTrue(args.play)
        self.assertEqual(extra, ["--trace-start=8804128"])

    def test_prepare_rejects_play_options(self) -> None:
        for option in ("--show-setup", "--unknown"):
            with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                recomplauncher.parse_args(["--prepare", "--game", "g.iso", option])


class ProgressTests(unittest.TestCase):
    def test_install_steps_become_progress_lines(self) -> None:
        lines = progress_lines([
            "Checking installation prerequisites...",
            "[1/6] Verifying and extracting the supported ISO...",
            "[2/6] Generating native game code...",
            "[6/6] Installation complete.",
        ])
        self.assertEqual(lines, [
            "progress 0.04 Checking the build tools",
            "progress 0.06 Checking and unpacking your disc",
            "progress 0.12 Generating the game's code",
            "progress 0.98 Finishing",
        ])

    def test_ninja_status_is_reported_only_while_compiling(self) -> None:
        lines = progress_lines([
            "[1/2] Configuring something",
            "[4/6] Building Metal Gear Acid 2...",
            "[1/4] Building C object a.obj",
            "[1/4] Building C object b.obj",
            "[4/4] Linking C executable mga2.exe",
            "[5/6] Staging the runnable installation...",
            "[2/3] Not ninja any more",
        ])
        self.assertEqual(lines, [
            "progress 0.35 Compiling the game",
            "progress 0.49 Compiling the game (25%)",
            "progress 0.92 Compiling the game (100%)",
            "progress 0.93 Installing the game",
        ])


class BuildStampTests(unittest.TestCase):
    def test_stamp_matches_until_a_build_input_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_project(root)
            installation = recomplauncher.install_directory("clang-cl", root)
            installation.mkdir(parents=True)
            (installation / "mga2.exe").write_bytes(b"exe")
            (installation / "mga2_image.bin").write_bytes(b"image")
            stamp = recomplauncher.expected_stamp("clang-cl", root)
            (installation / recomplauncher.STAMP_NAME).write_text(
                json.dumps(stamp), encoding="utf-8"
            )
            self.assertTrue(recomplauncher.is_current_build("clang-cl", root))

            (root / "tools" / "mga2" / "tests" / "t.py").write_text("x", "utf-8")
            self.assertTrue(recomplauncher.is_current_build("clang-cl", root))

            (root / "tools" / "mga2" / "gen.py").write_text("changed", "utf-8")
            self.assertFalse(recomplauncher.is_current_build("clang-cl", root))

    def test_missing_executable_is_not_a_current_build(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            make_project(root)
            self.assertFalse(recomplauncher.is_current_build("clang-cl", root))


class PathTests(unittest.TestCase):
    def test_batch_command_keeps_quoted_paths_intact(self) -> None:
        command = recomplauncher.batch_command(
            Path("C:/Games/MGA2/install.bat"),
            ["--iso", "C:/Games/Metal Gear Acid 2 (USA).iso"],
        )
        self.assertTrue(command.startswith('cmd.exe /d /s /c "'))
        self.assertIn('"C:/Games/Metal Gear Acid 2 (USA).iso""', command)

    def test_wrong_size_iso_is_refused_with_the_expected_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            iso = Path(temporary) / "game.iso"
            iso.write_bytes(b"short")
            with self.assertRaises(recomplauncher.LauncherError) as caught:
                recomplauncher.check_iso(iso, 917307392, 121)
            self.assertEqual(caught.exception.code, 121)
            self.assertIn("917,307,392", str(caught.exception))

    def test_non_ascii_iso_path_is_refused(self) -> None:
        with self.assertRaises(recomplauncher.LauncherError) as caught:
            recomplauncher.check_iso(Path("C:/Jeux/m\u00e9tal.iso"), 1, 121)
        self.assertEqual(caught.exception.code, 121)

    def test_logs_rotate_and_keep_the_newest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            logs = Path(temporary) / "logs"
            for run in range(recomplauncher.KEPT_LOGS + 2):
                current = recomplauncher.rotate_logs(logs)
                current.write_text(str(run), encoding="utf-8")
            names = sorted(path.name for path in logs.iterdir())
            self.assertEqual(len(names), recomplauncher.KEPT_LOGS + 1)
            self.assertEqual(
                (logs / "mga2.1.log").read_text("utf-8"),
                str(recomplauncher.KEPT_LOGS),
            )


if __name__ == "__main__":
    unittest.main()
