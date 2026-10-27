from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from compile_outline_shaders import decode_include


class OutlineShaderAssetTests(unittest.TestCase):
    def test_decodes_byte_and_little_endian_word_initializers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shader.inc"
            path.write_text("/* header */\n{0x01, 0x7f, 0xff}\n", encoding="ascii")
            self.assertEqual(decode_include(path, 1), b"\x01\x7f\xff")
            path.write_text("{0x07230203, 0x12345678}", encoding="ascii")
            self.assertEqual(
                decode_include(path, 4), b"\x03\x02\x23\x07\x78\x56\x34\x12"
            )

    def test_rejects_malformed_or_out_of_range_initializer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "shader.inc"
            path.write_text("{0x100}", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "out of range"):
                decode_include(path, 1)
            path.write_text("{0x01, invalid}", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "invalid"):
                decode_include(path, 1)


if __name__ == "__main__":
    unittest.main()
