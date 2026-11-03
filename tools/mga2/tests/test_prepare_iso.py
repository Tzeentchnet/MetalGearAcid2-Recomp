from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import prepare_iso


class IsoPreparationTests(unittest.TestCase):
    def test_direct_iso_is_returned_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            iso = Path(temporary) / "game.iso"
            iso.write_bytes(b"iso")

            result = prepare_iso.prepare_iso(iso, expected_size=3)

            self.assertEqual(result, iso.resolve())

    def test_zip_extracts_its_only_iso_beside_archive_and_reuses_it(self) -> None:
        iso_bytes = b"supported iso"
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "game.iso.zip"
            with zipfile.ZipFile(
                archive_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                archive.writestr("nested/readme.txt", "ignored")
                archive.writestr("nested/disc.ISO", iso_bytes)

            with redirect_stdout(StringIO()):
                first = prepare_iso.prepare_iso(
                    archive_path, expected_size=len(iso_bytes)
                )
                second = prepare_iso.prepare_iso(
                    archive_path, expected_size=len(iso_bytes)
                )

            self.assertEqual(first, Path(temporary) / "game.iso")
            self.assertEqual(second, first)
            self.assertEqual(first.read_bytes(), iso_bytes)

    def test_zip_refuses_to_replace_a_conflicting_iso(self) -> None:
        iso_bytes = b"supported"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "game.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("disc.iso", iso_bytes)
            destination = root / "game.iso"
            destination.write_bytes(b"conflict!")

            with self.assertRaisesRegex(
                prepare_iso.IsoPreparationError, "does not match"
            ):
                prepare_iso.prepare_iso(
                    archive_path, expected_size=len(iso_bytes)
                )

            self.assertEqual(destination.read_bytes(), b"conflict!")

    def test_zip_requires_exactly_one_iso(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            archive_path = Path(temporary) / "game.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("disc-1.iso", b"iso")
                archive.writestr("disc-2.iso", b"iso")

            with self.assertRaisesRegex(
                prepare_iso.IsoPreparationError, "exactly one ISO"
            ):
                prepare_iso.prepare_iso(archive_path, expected_size=3)

    def test_cli_rejects_an_iso_with_the_wrong_archived_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "game.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("disc.iso", b"wrong")
            config = root / "config.toml"
            config.write_text("[disc]\niso_size = 3\n", encoding="ascii")
            result_path = root / "result.txt"

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()) as stderr:
                result = prepare_iso.main(
                    [
                        "prepare_iso.py",
                        str(archive_path),
                        "--result",
                        str(result_path),
                        "--config",
                        str(config),
                    ]
                )

            self.assertEqual(result, 1)
            self.assertIn("archived ISO size", stderr.getvalue())
            self.assertFalse(result_path.exists())
            self.assertFalse((root / "game.iso").exists())


if __name__ == "__main__":
    unittest.main()
