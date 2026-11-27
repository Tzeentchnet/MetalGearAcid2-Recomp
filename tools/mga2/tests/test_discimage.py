import hashlib
import lzma
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import discimage  # noqa: E402


def sample_image(sectors=40):
    blocks = []
    for index in range(sectors):
        if index % 7 == 3:
            blocks.append(bytes(discimage.SECTOR))
        else:
            seed = hashlib.sha256(str(index).encode()).digest()
            text = (b"METAL GEAR ACID " + seed) * 64
            blocks.append(text[: discimage.SECTOR])
    return b"".join(blocks)


def write_cso(path, data, block_size=2048, align=0):
    blocks = [data[i : i + block_size] for i in range(0, len(data), block_size)]
    header_size = 24
    index_size = 4 * (len(blocks) + 1)
    payloads = []
    for number, block in enumerate(blocks):
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        packed = compressor.compress(block) + compressor.flush()
        # Store every third block raw, as CSO writers do for poor ratios.
        payloads.append((block, True) if number % 3 == 2 else (packed, False))
    offset = header_size + index_size
    index = []
    body = bytearray()
    for payload, plain in payloads:
        index.append((offset >> align) | (0x80000000 if plain else 0))
        body += payload
        offset += len(payload)
    index.append(offset >> align)
    header = b"CISO" + struct.pack(
        "<IQIBB2x", header_size, len(data), block_size, 1, align
    )
    path.write_bytes(header + struct.pack(f"<{len(index)}I", *index) + body)


class BitWriter:
    def __init__(self):
        self.bits = []

    def write(self, value, count):
        for shift in range(count - 1, -1, -1):
            self.bits.append((value >> shift) & 1)

    def getvalue(self):
        padded = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(
            int("".join(map(str, padded[i : i + 8])), 2)
            for i in range(0, len(padded), 8)
        )


def write_chd(path, data, hunk_bytes=4096, self_hunk=None):
    """A CHD v5 using codec 0 = zlib, 1 = lzma, raw hunks and one self copy."""
    hunks = [data[i : i + hunk_bytes] for i in range(0, len(data), hunk_bytes)]
    hunks[-1] = hunks[-1] + bytes(hunk_bytes - len(hunks[-1]))
    header_size = 124
    entries = []
    payload = bytearray()
    first_offset = header_size
    for number, hunk in enumerate(hunks):
        crc = discimage._crc16(hunk)
        if self_hunk is not None and number == self_hunk:
            entries.append((5, 0, 0, crc))
            continue
        choice = number % 3
        if choice == 0:
            compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
            packed = compressor.compress(hunk) + compressor.flush()
            entries.append((0, len(packed), None, crc))
        elif choice == 1:
            packed = lzma.compress(
                hunk,
                format=lzma.FORMAT_RAW,
                filters=[{
                    "id": lzma.FILTER_LZMA1,
                    "dict_size": discimage._lzma_dictionary_size(hunk_bytes),
                    "lc": 3, "lp": 0, "pb": 2,
                }],
            )
            entries.append((1, len(packed), None, crc))
        else:
            packed = hunk
            entries.append((4, len(packed), None, crc))
        payload += packed

    length_bits = max(entry[1] for entry in entries).bit_length()
    bits = BitWriter()
    for _ in range(16):  # every code 4 bits long: symbol s has code s
        bits.write(4, 4)
    for kind, _, _, _ in entries:
        bits.write(kind, 4)
    raw_map = bytearray()
    offset = first_offset
    for kind, length, _, crc in entries:
        if kind <= 3:
            bits.write(length, length_bits)
            bits.write(crc, 16)
            entry_offset = offset
            offset += length
        elif kind == 4:
            bits.write(crc, 16)
            entry_offset = offset
            offset += length
        else:
            bits.write(0, 8)  # self_bits = 8: copy hunk 0
            entry_offset = 0
            length = 0
            crc = 0
        raw_map += bytes([kind]) + length.to_bytes(3, "big")
        raw_map += entry_offset.to_bytes(6, "big") + crc.to_bytes(2, "big")
    compressed_map = bits.getvalue()
    map_offset = first_offset + len(payload)
    map_header = (
        struct.pack(">I", len(compressed_map))
        + first_offset.to_bytes(6, "big")
        + struct.pack(">H", discimage._crc16(raw_map))
        + bytes([length_bits, 8, 0, 0])
    )
    header = bytearray(header_size)
    header[0:8] = b"MComprHD"
    struct.pack_into(">II", header, 8, header_size, 5)
    header[16:32] = b"zlib" + b"lzma" + bytes(8)
    struct.pack_into(
        ">QQQII", header, 32, len(data), map_offset, 0, hunk_bytes, 2048
    )
    header[64:84] = hashlib.sha1(data).digest()
    path.write_bytes(bytes(header) + payload + map_header + compressed_map)


class DiscImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_detects_kinds(self):
        iso = self.root / "a.iso"
        iso.write_bytes(bytes(4096))
        self.assertEqual(discimage.image_kind(iso), "iso")
        zso = self.root / "a.zso"
        zso.write_bytes(b"ZISO" + bytes(60))
        self.assertEqual(discimage.image_kind(zso), "unsupported-cso")
        with self.assertRaisesRegex(discimage.DiscImageError, "ZSO"):
            discimage.convert_to_iso(zso, self.root / "out.iso")

    def test_converts_cso(self):
        data = sample_image()
        source = self.root / "game.cso"
        write_cso(source, data)
        destination = self.root / "game.iso"

        sha1 = discimage.convert_to_iso(source, destination)

        self.assertEqual(destination.read_bytes(), data)
        self.assertEqual(sha1, hashlib.sha1(data).hexdigest())

    def test_converts_aligned_cso_with_partial_last_block(self):
        data = sample_image(9)[:-512]
        source = self.root / "game.cso"
        write_cso(source, data, block_size=4096, align=0)
        destination = self.root / "game.iso"

        discimage.convert_to_iso(source, destination)

        self.assertEqual(destination.read_bytes(), data)

    def test_converts_chd_with_zlib_lzma_raw_and_self_hunks(self):
        data = sample_image(40)
        # Make hunk 4 equal to hunk 0 so the self reference is honest.
        data = data[:4 * 4096] + data[:4096] + data[5 * 4096 :]
        source = self.root / "game.chd"
        write_chd(source, data, self_hunk=4)
        destination = self.root / "game.iso"

        sha1 = discimage.convert_to_iso(source, destination)

        self.assertEqual(destination.read_bytes(), data)
        self.assertEqual(sha1, hashlib.sha1(data).hexdigest())

    def test_rejects_damaged_chd_hunk(self):
        data = sample_image(16)
        source = self.root / "game.chd"
        write_chd(source, data)
        raw = bytearray(source.read_bytes())
        raw[124 + 40] ^= 0xFF  # inside the first (zlib) hunk
        source.write_bytes(bytes(raw))

        with self.assertRaises(discimage.DiscImageError):
            discimage.convert_to_iso(source, self.root / "out.iso")
        self.assertFalse((self.root / "out.iso").exists())
        self.assertFalse((self.root / "out.iso.partial").exists())

    def test_rejects_cd_chd(self):
        source = self.root / "cd.chd"
        header = bytearray(124)
        header[0:8] = b"MComprHD"
        struct.pack_into(">II", header, 8, 124, 5)
        header[16:20] = b"cdlz"
        struct.pack_into(">QQQII", header, 32, 2448, 124, 0, 19584, 2448)
        source.write_bytes(bytes(header))

        with self.assertRaisesRegex(discimage.DiscImageError, "createdvd"):
            discimage.convert_to_iso(source, self.root / "out.iso")

    def test_huffman_canonical_codes(self):
        decoder = discimage.Huffman(4, 3)
        decoder.lengths = [1, 2, 3, 3]
        decoder._build()
        # Longer codes take the low values: lengths 3 -> 000, 001; 2 -> 01;
        # 1 -> 1.
        bits = discimage.BitReader(bytes([0b10100000, 0b10000000]))
        self.assertEqual(
            [decoder.decode(bits) for _ in range(4)], [0, 1, 2, 3]
        )


if __name__ == "__main__":
    unittest.main()
