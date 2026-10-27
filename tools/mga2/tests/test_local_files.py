from __future__ import annotations

from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from local_files import is_link_or_reparse_point


class LocalFileTests(unittest.TestCase):
    def test_detects_windows_reparse_points_without_python_312(self) -> None:
        for mode, attributes, expected in (
            (stat.S_IFREG, 0, False),
            (stat.S_IFREG, 0x400, True),
            (stat.S_IFLNK, 0, True),
        ):
            path = SimpleNamespace(
                lstat=lambda: SimpleNamespace(
                    st_mode=mode, st_file_attributes=attributes
                )
            )
            with self.subTest(mode=mode, attributes=attributes):
                self.assertEqual(is_link_or_reparse_point(path), expected)


if __name__ == "__main__":
    unittest.main()
