#!/usr/bin/env python3
"""Export card-illustration templates from the verified MGA2 USA ISO."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import os
import struct
import sys
import tempfile
import tomllib
import zlib

from iso9660 import Iso, sha1_file
from local_files import is_link_or_reparse_point


ROOT = Path(__file__).resolve().parents[2]
RESOURCE = "PSP_GAME/USRDIR/stage/init/_zar"
PACKS = {
    "cd_illustac.txp": "ac",
    "cd_illustch.txp": "ch",
    "cd_illustit.txp": "it",
    "cd_illustsp.txp": "sp",
    "cd_illustwp.txp": "wp",
}
CATALOG_HEADER = "MGA2_CARD_CATALOG 1"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 4096


@dataclass(frozen=True)
class CardArtwork:
    pack: str
    index: int
    identifier: int
    count: int
    descriptors: int
    metadata: int
    palette_offset: int
    storage_width: int
    storage_height: int
    format: int
    width: int
    height: int
    indices_hash: int
    palette_hash: int
    rgba: bytes

    @property
    def filename(self) -> str:
        return f"{self.pack}_{self.index:03d}_{self.identifier:08x}.png"

    def catalog_line(self) -> str:
        return (
            f"{self.pack} {self.index} {self.identifier:08x} {self.count} "
            f"{self.descriptors} {self.metadata} {self.palette_offset} "
            f"{self.storage_width} {self.storage_height} {self.format} "
            f"{self.width} {self.height} "
            f"{self.indices_hash:016x} {self.palette_hash:016x}"
        )


def align(value: int, boundary: int) -> int:
    return (value + boundary - 1) & -boundary


def checked_slice(data: bytes, offset: int, size: int, label: str) -> bytes:
    if offset < 0 or size < 0 or offset > len(data) or size > len(data) - offset:
        raise ValueError(f"{label} is outside its container")
    return data[offset : offset + size]


def read_u32(data: bytes, offset: int, label: str) -> int:
    return struct.unpack("<I", checked_slice(data, offset, 4, label))[0]


def read_name(data: bytes, offset: int, limit: int, label: str) -> tuple[str, int]:
    if offset < 0 or offset >= limit or limit > len(data):
        raise ValueError(f"{label} name is outside its container")
    end = data.find(b"\0", offset, limit)
    if end < 0:
        raise ValueError(f"{label} name is not terminated")
    try:
        name = data[offset:end].decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError(f"{label} name is not ASCII") from error
    if not name or "/" in name or "\\" in name:
        raise ValueError(f"invalid {label} name")
    return name, end + 1


def inflate_exact(data: bytes, expected: int, label: str) -> bytes:
    if expected <= 0 or expected > MAX_ARCHIVE_BYTES:
        raise ValueError(f"{label} has an invalid decompressed size")
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, expected + 1)
        if decoder.unconsumed_tail or len(result) > expected:
            raise ValueError(f"{label} exceeds its decompressed size")
        result += decoder.flush()
    except zlib.error as error:
        raise ValueError(f"{label} has invalid zlib data: {error}") from error
    if len(result) != expected or not decoder.eof or decoder.unused_data:
        raise ValueError(f"{label} has a truncated or mismatched zlib stream")
    return result


def resident_archive(compressed: bytes) -> bytes:
    expected = read_u32(compressed, 0, "resource size")
    archive = inflate_exact(compressed[4:], expected, "init resource")
    count = read_u32(archive, 0, "resource entry count")
    if not 0 < count <= MAX_ARCHIVE_ENTRIES:
        raise ValueError("invalid init resource entry count")
    offset = 4
    resident = None
    names = set()
    for _ in range(count):
        name, next_offset = read_name(archive, offset, len(archive), "resource")
        if name in names:
            raise ValueError(f"duplicate init resource entry: {name}")
        names.add(name)
        size_offset = align(next_offset, 4)
        size = read_u32(archive, size_offset, f"{name} size")
        payload_offset = align(size_offset + 4, 16)
        payload = checked_slice(archive, payload_offset, size, name)
        offset = payload_offset + size
        if checked_slice(archive, offset, 1, f"{name} separator") != b"\0":
            raise ValueError(f"{name} has no resource separator")
        offset += 1
        if name == "resident.qar":
            resident = payload
    if offset != len(archive):
        raise ValueError("init resource has trailing data")
    if resident is None:
        raise ValueError("resident.qar is missing from the init resource")
    return resident


def qar_entries(archive: bytes) -> dict[str, bytes]:
    table = read_u32(archive, len(archive) - 4, "QAR footer")
    count = read_u32(archive, table, "QAR entry count")
    if not 0 < count <= MAX_ARCHIVE_ENTRIES:
        raise ValueError("invalid QAR entry count")
    records_end = table + 4 + count * 8
    if records_end > len(archive) - 4:
        raise ValueError("QAR index is outside its container")
    name_offset = records_end
    payload_offset = 0
    entries = {}
    for index in range(count):
        size = read_u32(archive, table + 8 + index * 8, "QAR entry size")
        name, name_offset = read_name(
            archive, name_offset, len(archive) - 4, "QAR entry"
        )
        if name in entries:
            raise ValueError(f"duplicate QAR entry: {name}")
        if payload_offset > table or size > table - payload_offset:
            raise ValueError(f"QAR entry {name} overlaps its index")
        entries[name] = checked_slice(archive, payload_offset, size, name)
        payload_offset = align(payload_offset + size, 128)
    return entries


def fnv64(data: bytes) -> int:
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value


def decode_rgba(
    indices: bytes, palette: bytes, storage_width: int, storage_height: int,
    width: int, height: int, texture_format: int,
) -> bytes:
    if texture_format not in (4, 5):
        raise ValueError("unsupported card texture format")
    if not (0 < width <= storage_width <= 512 and
            0 < height <= storage_height <= 512):
        raise ValueError("invalid card texture dimensions")
    bits = 4 if texture_format == 4 else 8
    row_bytes = storage_width * bits // 8
    if (storage_width * bits) % 8 or row_bytes % 16 or storage_height % 8:
        raise ValueError("invalid swizzled card texture layout")
    if len(indices) != row_bytes * storage_height:
        raise ValueError("incorrect card texture index length")
    if len(palette) != (16 if bits == 4 else 256) * 4:
        raise ValueError("incorrect card texture palette length")
    rgba = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            column = x * bits // 8
            offset = (
                (y // 8) * row_bytes * 8 + (column // 16) * 128
                + (y % 8) * 16 + column % 16
            )
            value = indices[offset]
            if bits == 4:
                value = (value >> (4 * (x & 1))) & 15
            destination = (y * width + x) * 4
            rgba[destination : destination + 4] = palette[value * 4 : value * 4 + 4]
    return bytes(rgba)


def parse_pack(data: bytes, pack: str) -> list[CardArtwork]:
    header = struct.unpack("<8I", checked_slice(data, 0, 32, f"{pack} header"))
    zero, version, count, descriptors, metadata_count, metadata, _, _ = header
    if zero != 0 or version != 12 or not 0 < count <= MAX_ARCHIVE_ENTRIES:
        raise ValueError(f"invalid {pack} texture-pack header")
    if metadata_count != count:
        raise ValueError(f"{pack} texture and metadata counts differ")
    checked_slice(data, descriptors, count * 16, f"{pack} descriptors")
    checked_slice(data, metadata, count * 48, f"{pack} metadata")
    records = []
    for index in range(count):
        storage_width, _, storage_height, _, fmt, flags, source, palette = (
            struct.unpack_from("<4BHHII", data, descriptors + index * 16)
        )
        meta_offset = metadata + index * 48
        identifier = read_u32(data, meta_offset + 4, f"{pack} identifier")
        dimensions = read_u32(data, meta_offset + 12, f"{pack} dimensions")
        width, height = dimensions & 0xFFFF, dimensions >> 16
        if fmt not in (4, 5) or flags != 2:
            raise ValueError(f"{pack} entry {index} has an unsupported format")
        if not (0 < width <= storage_width <= 512 and
                0 < height <= storage_height <= 512):
            raise ValueError(f"{pack} entry {index} has invalid dimensions")
        raw_size = storage_width * storage_height * (4 if fmt == 4 else 8) // 8
        compressed_size = read_u32(data, source, f"{pack} image length")
        compressed = checked_slice(data, source + 4, compressed_size, f"{pack} image")
        indices = inflate_exact(compressed, raw_size, f"{pack} entry {index}")
        colors = checked_slice(data, palette, 64 if fmt == 4 else 1024, f"{pack} palette")
        rgba = decode_rgba(
            indices, colors, storage_width, storage_height, width, height, fmt
        )
        records.append(CardArtwork(
            pack, index, identifier, count, descriptors, metadata, palette,
            storage_width, storage_height, fmt, width, height,
            fnv64(indices), fnv64(colors), rgba,
        ))
    return records


def load_artwork(resource: bytes) -> list[CardArtwork]:
    archive = qar_entries(resident_archive(resource))
    missing = PACKS.keys() - archive.keys()
    if missing:
        raise ValueError("card texture packs are missing: " + ", ".join(sorted(missing)))
    records = []
    for name, pack in PACKS.items():
        records.extend(parse_pack(archive[name], pack))
    return records


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload)) + kind + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    if width <= 0 or height <= 0 or len(rgba) != width * height * 4:
        raise ValueError("invalid PNG image dimensions or pixel data")
    rows = b"".join(
        b"\0" + rgba[y * width * 4 : (y + 1) * width * 4]
        for y in range(height)
    )
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(rows, 9))
        + png_chunk(b"IEND", b"")
    )


def export(records: list[CardArtwork], output: Path) -> None:
    output = output.absolute()
    if output.exists() or is_link_or_reparse_point(output):
        raise ValueError(f"refusing to overwrite an existing card folder: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="mga2-card-export-", dir=output.parent
    ) as temporary:
        stage = Path(temporary) / "cards"
        templates = stage / "templates"
        templates.mkdir(parents=True)
        for record in records:
            (templates / record.filename).write_bytes(
                png_rgba(record.width, record.height, record.rgba)
            )
        (stage / "catalog.txt").write_text(
            CATALOG_HEADER + "\n"
            + "".join(record.catalog_line() + "\n" for record in records),
            encoding="ascii", newline="\n",
        )
        os.rename(stage, output)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path, help="supported MGA2 USA ISO")
    parser.add_argument(
        "--out", type=Path, required=True,
        help="new mods\\cards folder beside the game executable",
    )
    parser.add_argument(
        "--config", type=Path, default=ROOT / "config" / "mga2.toml"
    )
    args = parser.parse_args(argv)
    try:
        if args.out.exists() or is_link_or_reparse_point(args.out):
            raise ValueError(f"refusing to overwrite an existing card folder: {args.out}")
        with args.config.open("rb") as stream:
            disc = tomllib.load(stream)["disc"]
        actual_size = args.iso.stat().st_size
        if actual_size != disc["iso_size"]:
            raise ValueError(f"ISO size {actual_size} != expected {disc['iso_size']}")
        print(f"hashing {args.iso} ({actual_size:,} bytes)...", flush=True)
        actual_hash = sha1_file(args.iso)
        if actual_hash != disc["iso_sha1"]:
            raise ValueError(f"ISO SHA-1 {actual_hash} != expected {disc['iso_sha1']}")
        with Iso(args.iso) as iso:
            resource = iso.read(RESOURCE)
        records = load_artwork(resource)
        export(records, args.out)
        print(f"exported {len(records)} card texture templates to {args.out}")
        return 0
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as error:
        print(f"ERROR: card export failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
