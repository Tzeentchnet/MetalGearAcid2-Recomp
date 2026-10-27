from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import export_cards


def append_aligned(data: bytearray, alignment: int) -> None:
    data.extend(bytes((-len(data)) % alignment))


def fake_pack(texture_format: int = 5) -> bytes:
    count = 2
    descriptors = 32
    metadata = descriptors + count * 16
    data = bytearray(metadata + count * 48)
    struct.pack_into("<8I", data, 0, 0, 12, count, descriptors, count, metadata, 0, 0)
    storage_width = 16 if texture_format == 5 else 32
    storage_height = 8
    raw = bytes(range(128))
    palette = b"".join(
        bytes((i, 255 - i, i // 2, (i * 3) & 255))
        for i in range(256 if texture_format == 5 else 16)
    )
    for index in range(count):
        append_aligned(data, 16)
        source = len(data)
        compressed = zlib.compress(raw)
        data.extend(struct.pack("<I", len(compressed)) + compressed)
        append_aligned(data, 16)
        palette_offset = len(data)
        data.extend(palette)
        struct.pack_into(
            "<4BHHII", data, descriptors + index * 16,
            storage_width, 16, storage_height, 8, texture_format, 2,
            source, palette_offset,
        )
        struct.pack_into("<I", data, metadata + index * 48 + 4, 0x123400 + index)
        struct.pack_into("<I", data, metadata + index * 48 + 12, 3 | (2 << 16))
    return bytes(data)


def fake_qar(entries: dict[str, bytes]) -> bytes:
    data = bytearray()
    for payload in entries.values():
        data.extend(payload)
        append_aligned(data, 128)
    table = len(data)
    data.extend(struct.pack("<I", len(entries)))
    for payload in entries.values():
        data.extend(struct.pack("<II", 0, len(payload)))
    for name in entries:
        data.extend(name.encode("ascii") + b"\0")
    data.extend(struct.pack("<I", table))
    return bytes(data)


def fake_resource(entries: dict[str, bytes]) -> bytes:
    data = bytearray(struct.pack("<I", len(entries)))
    for name, payload in entries.items():
        data.extend(name.encode("ascii") + b"\0")
        append_aligned(data, 4)
        data.extend(struct.pack("<I", len(payload)))
        append_aligned(data, 16)
        data.extend(payload)
        data.extend(b"\0")
    return struct.pack("<I", len(data)) + zlib.compress(data)


def png_pixels(png: bytes) -> tuple[int, int, bytes]:
    if not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid signature")
    offset = 8
    payloads = []
    width = height = 0
    while offset < len(png):
        size = struct.unpack_from(">I", png, offset)[0]
        kind = png[offset + 4 : offset + 8]
        payload = png[offset + 8 : offset + 8 + size]
        crc = struct.unpack_from(">I", png, offset + 8 + size)[0]
        if zlib.crc32(kind + payload) & 0xFFFFFFFF != crc:
            raise ValueError("invalid PNG CRC")
        if kind == b"IHDR":
            width, height, depth, fmt, _, _, _ = struct.unpack(">IIBBBBB", payload)
            if (depth, fmt) != (8, 6):
                raise ValueError("unexpected PNG format")
        elif kind == b"IDAT":
            payloads.append(payload)
        elif kind == b"IEND":
            break
        offset += size + 12
    rows = zlib.decompress(b"".join(payloads))
    stride = width * 4
    pixels = bytearray()
    for y in range(height):
        row = rows[y * (stride + 1) : (y + 1) * (stride + 1)]
        if row[0] != 0:
            raise ValueError("unexpected PNG filter")
        pixels.extend(row[1:])
    return width, height, bytes(pixels)


class CardArchiveTests(unittest.TestCase):
    def test_decodes_swizzle_palette_and_alpha(self) -> None:
        records = export_cards.parse_pack(fake_pack(), "it")
        self.assertEqual(len(records), 2)
        self.assertEqual((records[0].width, records[0].height), (3, 2))
        self.assertEqual(
            records[0].rgba,
            b"".join(
                bytes((i, 255 - i, i // 2, (i * 3) & 255))
                for i in (0, 1, 2, 16, 17, 18)
            ),
        )
        self.assertEqual(records[0].rgba, records[1].rgba)
        self.assertEqual(records[0].indices_hash, records[1].indices_hash)
        self.assertEqual(records[0].palette_hash, records[1].palette_hash)
        self.assertNotEqual(records[0].identifier, records[1].identifier)
        self.assertNotEqual(records[0].palette_offset, records[1].palette_offset)
        self.assertNotEqual(records[0].filename, records[1].filename)

    def test_decodes_four_bit_indices_low_nibble_first(self) -> None:
        records = export_cards.parse_pack(fake_pack(4), "sp")
        colors = records[0].rgba
        self.assertEqual(colors[:4], bytes((0, 255, 0, 0)))
        self.assertEqual(colors[4:8], bytes((0, 255, 0, 0)))
        self.assertEqual(colors[8:12], bytes((1, 254, 0, 3)))

    def test_reads_all_five_packs_from_bounded_resource(self) -> None:
        archive = fake_qar({name: fake_pack() for name in export_cards.PACKS})
        resource = fake_resource({"data.cnf": b"config", "resident.qar": archive})
        records = export_cards.load_artwork(resource)
        self.assertEqual(len(records), 10)
        self.assertEqual({record.pack for record in records}, set(export_cards.PACKS.values()))

    def test_rejects_bad_sizes_streams_and_archive_indexes(self) -> None:
        resource = fake_resource({"resident.qar": fake_qar({"item": fake_pack()})})
        for bad in (resource[:-1], struct.pack("<I", 1) + resource[4:]):
            with self.subTest(bad=bad[:8]):
                with self.assertRaises(ValueError):
                    export_cards.resident_archive(bad)
        archive = bytearray(fake_qar({"item": fake_pack()}))
        struct.pack_into("<I", archive, len(archive) - 4, len(archive) + 1)
        with self.assertRaises(ValueError):
            export_cards.qar_entries(bytes(archive))
        pack = bytearray(fake_pack())
        struct.pack_into("<I", pack, 32 + 12, len(pack) - 1)
        with self.assertRaises(ValueError):
            export_cards.parse_pack(bytes(pack), "it")

    def test_rejects_missing_packs(self) -> None:
        resource = fake_resource({"resident.qar": fake_qar({"item": fake_pack()})})
        with self.assertRaisesRegex(ValueError, "missing"):
            export_cards.load_artwork(resource)


class CardExportTests(unittest.TestCase):
    def test_png_is_rgba_and_preserves_every_channel(self) -> None:
        rgba = bytes((255, 0, 3, 0, 10, 20, 30, 128, 40, 50, 60, 255, 1, 2, 3, 4))
        self.assertEqual(png_pixels(export_cards.png_rgba(2, 2, rgba)), (2, 2, rgba))

    def test_export_is_new_and_never_overwrites_existing_cards(self) -> None:
        records = export_cards.parse_pack(fake_pack(), "it")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "mods" / "cards"
            export_cards.export(records, output)
            first = output / "templates" / records[0].filename
            self.assertEqual(png_pixels(first.read_bytes()), (3, 2, records[0].rgba))
            self.assertEqual(
                (output / "catalog.txt").read_text(encoding="ascii").splitlines(),
                [export_cards.CATALOG_HEADER] + [record.catalog_line() for record in records],
            )
            edited = output / records[0].filename
            edited.write_bytes(b"my replacement")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                export_cards.export(records, output)
            self.assertEqual(edited.read_bytes(), b"my replacement")

    def test_verifies_the_iso_before_publishing(self) -> None:
        archive = fake_qar({name: fake_pack() for name in export_cards.PACKS})
        resource = fake_resource({"resident.qar": archive})

        class FakeIso:
            def __init__(self, path):
                self.path = path

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return None

            def read(self, path):
                self.path_read = path
                return resource

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = root / "disc.iso"
            iso.write_bytes(b"synthetic disc")
            config = root / "config.toml"
            config.write_text(
                f"[disc]\niso_size = {iso.stat().st_size}\n"
                'iso_sha1 = "0000000000000000000000000000000000000000"\n',
                encoding="ascii",
            )
            output = root / "cards"
            args = [str(iso), "--config", str(config), "--out", str(output)]
            with mock.patch.object(export_cards, "Iso", FakeIso):
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    self.assertEqual(export_cards.main(args), 1)
                self.assertFalse(output.exists())
                config.write_text(
                    f"[disc]\niso_size = {iso.stat().st_size}\n"
                    f'iso_sha1 = "{hashlib.sha1(iso.read_bytes()).hexdigest()}"\n',
                    encoding="ascii",
                )
                with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                    self.assertEqual(export_cards.main(args), 0)
            self.assertEqual(len(list((output / "templates").glob("*.png"))), 10)


if __name__ == "__main__":
    unittest.main()
