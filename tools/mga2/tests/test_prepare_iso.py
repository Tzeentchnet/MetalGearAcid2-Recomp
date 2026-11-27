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

            self.assertEqual(first, (Path(temporary) / "game.iso").resolve())
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



class CompressedImageTests(unittest.TestCase):
    def test_cso_is_converted_once_and_reused_until_it_changes(self) -> None:
        from test_discimage import sample_image, write_cso

        data = sample_image()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "game.cso"
            write_cso(source, data)
            destination = Path(temporary) / "build" / "game.iso"
            self.assertTrue(prepare_iso.is_compressed(source))

            with redirect_stdout(StringIO()):
                first = prepare_iso.prepare_compressed(
                    source, len(data), destination)
            self.assertEqual(first.read_bytes(), data)
            self.assertEqual(
                prepare_iso.converted_iso(source, len(data), destination),
                destination)

            output = StringIO()
            with redirect_stdout(output):
                prepare_iso.prepare_compressed(source, len(data), destination)
            self.assertIn("Reusing", output.getvalue())

            write_cso(source, data, block_size=4096)
            self.assertIsNone(
                prepare_iso.converted_iso(source, len(data), destination))

    def test_wrong_size_conversion_is_refused_and_removed(self) -> None:
        from test_discimage import sample_image, write_cso

        data = sample_image()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "game.cso"
            write_cso(source, data)
            destination = Path(temporary) / "game.iso"
            with redirect_stdout(StringIO()), self.assertRaises(
                    prepare_iso.IsoPreparationError):
                prepare_iso.prepare_compressed(
                    source, len(data) + 1, destination)
            self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
