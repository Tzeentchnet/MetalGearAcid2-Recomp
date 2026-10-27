from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_cards
from test_export_cards import fake_pack


@unittest.skipUnless(os.environ.get("MGA2_CARD_TEST_EXE"), "native card test host not configured")
class CardModNativeTests(unittest.TestCase):
    def run_host(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [os.environ["MGA2_CARD_TEST_EXE"], *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def test_matching_sampling_dimensions_alpha_and_errors(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mga2-card-native-") as temporary:
            root = Path(temporary)
            cards = root / "mods" / "cards"
            cards.mkdir(parents=True)
            pack = fake_pack()
            pack_path = root / "pack.bin"
            pack_path.write_bytes(pack)
            special_pack = fake_pack(4)
            special_pack_path = root / "special-pack.bin"
            special_pack_path.write_bytes(special_pack)
            items = export_cards.parse_pack(pack, "it")
            specials = export_cards.parse_pack(special_pack, "sp")
            characters = export_cards.parse_pack(pack, "ch")
            records = items + specials + characters[:1]
            (cards / "catalog.txt").write_text(
                export_cards.CATALOG_HEADER + "\n"
                + "".join(record.catalog_line() + "\n" for record in records),
                encoding="ascii", newline="\n",
            )
            pixels = bytes(
                channel
                for y in range(4)
                for x in range(6)
                for channel in (
                    x * 37, y * 70, (x + y) * 25,
                    255 if (x + y) % 2 == 0 else 64,
                )
            )
            (cards / items[0].filename).write_bytes(export_cards.png_rgba(6, 4, pixels))
            (cards / items[1].filename).write_bytes(
                export_cards.png_rgba(3, 2, bytes((0, 0, 255, 128)) * 6)
            )
            (cards / specials[0].filename).write_bytes(
                export_cards.png_rgba(3, 2, bytes((0, 255, 0, 64)) * 6)
            )
            (cards / specials[1].filename).write_bytes(b"not a PNG")
            (cards / characters[0].filename).write_bytes(
                export_cards.png_rgba(1, 1, bytes((1, 2, 3, 4)))
            )
            (cards / "unexpected.png").write_bytes(b"unexpected")
            result = self.run_host(
                "valid", str(root), str(pack_path), str(special_pack_path)
            )
            self.assertIn("card mod native tests passed", result.stdout)
            self.assertIn("cannot decode PNG", result.stderr)
            self.assertIn("expected 3x2 multiplied", result.stderr)
            self.assertIn("unknown replacement PNG", result.stderr)
            self.assertIn(f"applying {items[0].filename}", result.stderr)
            self.assertIn(f"applying {items[1].filename}", result.stderr)
            self.assertIn(f"applying {specials[0].filename}", result.stderr)

    def test_scale_boundaries_and_nonuniform_dimensions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mga2-card-native-") as temporary:
            root = Path(temporary)
            cards = root / "mods" / "cards"
            cards.mkdir(parents=True)
            pack = fake_pack()
            actions = export_cards.parse_pack(pack, "ac")
            characters = export_cards.parse_pack(pack, "ch")
            records = actions + characters[:1]
            (cards / "catalog.txt").write_text(
                export_cards.CATALOG_HEADER + "\n"
                + "".join(record.catalog_line() + "\n" for record in records),
                encoding="ascii", newline="\n",
            )
            (cards / actions[0].filename).write_bytes(
                export_cards.png_rgba(24, 16, bytes((1, 2, 3, 4)) * 384)
            )
            (cards / actions[1].filename).write_bytes(
                export_cards.png_rgba(27, 18, bytes((1, 2, 3, 4)) * 486)
            )
            (cards / characters[0].filename).write_bytes(
                export_cards.png_rgba(6, 2, bytes((1, 2, 3, 4)) * 12)
            )
            stderr = self.run_host("limits", str(root)).stderr
            self.assertIn(f"loaded {actions[0].filename} (8x)", stderr)
            self.assertIn("27x18; expected 3x2 multiplied", stderr)
            self.assertIn("6x2; expected 3x2 multiplied", stderr)

    def test_missing_and_invalid_catalogs_are_not_silent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="mga2-card-native-") as temporary:
            root = Path(temporary)
            self.assertNotIn("card mods:", self.run_host("empty", str(root)).stderr)
            cards = root / "mods" / "cards"
            cards.mkdir(parents=True)
            self.assertIn("cannot open catalog", self.run_host("empty", str(root)).stderr)
            (cards / "catalog.txt").write_text(
                export_cards.CATALOG_HEADER + "\ninvalid entry\n",
                encoding="ascii", newline="\n",
            )
            stderr = self.run_host("empty", str(root)).stderr
            self.assertIn("invalid catalog entry", stderr)
            self.assertIn("disabling replacements", stderr)


if __name__ == "__main__":
    unittest.main()
