from __future__ import annotations

from pathlib import Path
import sys
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from check_release_contents import protected_path


class ReleaseContentsTests(unittest.TestCase):
    def test_rejects_protected_paths_case_insensitively(self) -> None:
        for path in (
            "game.IsO",
            "tools/BOOT.BIN",
            "PSP/SAVEDATA/ULUS10077003/00000000.000",
            "nested/memstick/save",
            "nested/build/mga2/source.c",
            "snap_123.png",
            "mga2_recomp_000.c",
            "modules/mga2_x_recomp_register.c",
            "mga2_recomp.h",
            "nested/archive.ZIP",
        ):
            with self.subTest(path=path):
                self.assertTrue(protected_path(path))

    def test_allows_project_sources_and_docs(self) -> None:
        for path in (
            "README.md",
            "config/mga2.toml",
            "tools/mga2/gen.py",
            "tools/mga2/module_policy.c",
            "tools/mga2/new_game_runtime.pad",
        ):
            with self.subTest(path=path):
                self.assertFalse(protected_path(path))


if __name__ == "__main__":
    unittest.main()
