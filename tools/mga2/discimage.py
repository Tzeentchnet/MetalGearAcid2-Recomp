#!/usr/bin/env python3
"""Read PSP disc images stored as ISO, CSO (CISO) or CHD, and convert them to ISO.

Only the pieces a PSP UMD image uses are handled:

* CSO: CISO v1 and v2 with deflate blocks. ZSO (LZ4) and DAX are refused.
* CHD: version 5 DVD-style images (2048-byte units, as made by
  ``chdman createdvd``) with the zlib, lzma, huff, flac and zstd hunk codecs.
  zstd needs Python 3.14's ``compression.zstd`` or the ``zstandard`` package.
  CD-style CHDs (``chdman createcd``) and CHDs with a parent are refused.

Every CHD hunk is checked against the CRC-16 in the map, and the converted
image against the SHA-1 the CHD records for its data.
"""

import argparse
import hashlib
import lzma
import os
from pathlib import Path
import struct
import sys
import zlib

SECTOR = 2048
COMPRESSED_SUFFIXES = (".cso", ".chd")


class DiscImageError(ValueError):
    """The image is damaged or uses a feature this reader does not handle."""


def image_kind(path):
    with open(path, "rb") as stream:
        magic = stream.read(8)
    if magic[:4] == b"CISO":
        return "cso"
    if magic[:4] in (b"ZISO", b"DAX\x00"):
        return "unsupported-cso"
    if magic == b"MComprHD":
        return "chd"
    return "iso"


def is_compressed(path):
    return image_kind(path) != "iso"


# --------------------------------------------------------------------------
# CSO


class CsoImage:
    def __init__(self, path):
        self.stream = open(path, "rb")
        header = self.stream.read(24)
        if len(header) < 24 or header[:4] != b"CISO":
            raise DiscImageError(f"{path}: not a CSO image")
        (
            _header_size,
            self.size,
            self.block_size,
            version,
            self.align,
        ) = struct.unpack_from("<IQIBB", header, 4)
        if version not in (0, 1, 2):
            raise DiscImageError(f"{path}: CSO version {version} is not supported")
        if self.block_size == 0 or self.block_size % SECTOR:
            raise DiscImageError(
                f"{path}: CSO block size {self.block_size} is not supported"
            )
        self.version = version
        self.blocks = (self.size + self.block_size - 1) // self.block_size
        index = self.stream.read(4 * (self.blocks + 1))
        if len(index) != 4 * (self.blocks + 1):
            raise DiscImageError(f"{path}: CSO index is truncated")
        self.index = struct.unpack(f"<{self.blocks + 1}I", index)

    def block(self, number):
        raw_start = self.index[number]
        raw_end = self.index[number + 1]
        start = (raw_start & 0x7FFFFFFF) << self.align
        end = (raw_end & 0x7FFFFFFF) << self.align
        plain = bool(raw_start & 0x80000000)
        self.stream.seek(start)
        data = self.stream.read(end - start)
        expected = min(self.block_size, self.size - number * self.block_size)
        if self.version == 2:
            # v2 marks raw blocks by size; the flag selects LZ4 instead.
            if len(data) >= self.block_size:
                return data[:expected]
            if plain:
                raise DiscImageError("LZ4 blocks in CSO v2 are not supported")
        elif plain:
            return data[:expected]
        try:
            decompressor = zlib.decompressobj(-15)
            output = decompressor.decompress(data, expected)
        except zlib.error as error:
            raise DiscImageError(f"CSO block {number} is damaged: {error}") from error
        if len(output) != expected:
            raise DiscImageError(f"CSO block {number} is truncated")
        return output

    def iter_blocks(self):
        for number in range(self.blocks):
            yield self.block(number)

    def close(self):
        self.stream.close()


# --------------------------------------------------------------------------
# CHD bit reader and Huffman decoder (after MAME's bitstream.h/huffman.cpp)


class BitReader:
    __slots__ = ("data", "length", "position")

    def __init__(self, data):
        self.data = data
        self.length = len(data)
        self.position = 0

    def peek(self, count):
        if count == 0:
            return 0
        byte = self.position >> 3
        window = self.data[byte : byte + 5]
        if len(window) < 5:
            window = window + bytes(5 - len(window))
        value = int.from_bytes(window, "big")
        return (value >> (40 - (self.position & 7) - count)) & ((1 << count) - 1)

    def read(self, count):
        if count > 32:
            high = self.read(count - 32)
            return (high << 32) | self.read(32)
        value = self.peek(count)
        self.position += count
        return value

    def skip(self, count):
        self.position += count

    def overflow(self):
        return self.position > self.length * 8

    def byte_offset(self):
        return (self.position + 7) >> 3


class Huffman:
    def __init__(self, num_codes, max_bits):
        self.num_codes = num_codes
        self.max_bits = max_bits
        self.lengths = [0] * num_codes
        self.lookup = None

    def _build(self):
        histogram = [0] * 33
        for length in self.lengths:
            if length > self.max_bits:
                raise DiscImageError("CHD Huffman code is too long")
            histogram[length] += 1
        start = 0
        for length in range(32, 0, -1):
            next_start = (start + histogram[length]) >> 1
            if length != 1 and next_start * 2 != start + histogram[length]:
                raise DiscImageError("CHD Huffman tree is inconsistent")
            histogram[length] = start
            start = next_start
        lookup = [0] * (1 << self.max_bits)
        for symbol, length in enumerate(self.lengths):
            if length == 0:
                continue
            code = histogram[length]
            histogram[length] += 1
            shift = self.max_bits - length
            first = code << shift
            entry = (symbol << 5) | length
            lookup[first : first + (1 << shift)] = [entry] * (1 << shift)
        self.lookup = lookup

    def import_rle(self, bits):
        width = 5 if self.max_bits >= 16 else 4 if self.max_bits >= 8 else 3
        current = 0
        while current < self.num_codes:
            length = bits.read(width)
            if length != 1:
                self.lengths[current] = length
                current += 1
                continue
            length = bits.read(width)
            if length == 1:
                self.lengths[current] = 1
                current += 1
                continue
            repeat = bits.read(width) + 3
            if current + repeat > self.num_codes:
                raise DiscImageError("CHD Huffman tree overruns")
            for _ in range(repeat):
                self.lengths[current] = length
                current += 1
        self._build()
        if bits.overflow():
            raise DiscImageError("CHD Huffman tree is truncated")

    def import_huffman(self, bits):
        small = Huffman(24, 6)
        small.lengths[0] = bits.read(3)
        start = bits.read(3) + 1
        count = 0
        for index in range(1, 24):
            if index < start or count == 7:
                small.lengths[index] = 0
            else:
                count = bits.read(3)
                small.lengths[index] = 0 if count == 7 else count
        small._build()

        temp = self.num_codes - 9
        rle_bits = 0
        while temp:
            temp >>= 1
            rle_bits += 1

        last = 0
        current = 0
        while current < self.num_codes:
            value = small.decode(bits)
            if value:
                last = value - 1
                self.lengths[current] = last
                current += 1
                continue
            count = bits.read(3) + 2
            if count == 9:
                count += bits.read(rle_bits)
            while count and current < self.num_codes:
                self.lengths[current] = last
                current += 1
                count -= 1
        if current != self.num_codes:
            raise DiscImageError("CHD Huffman tree has the wrong size")
        self._build()
        if bits.overflow():
            raise DiscImageError("CHD Huffman tree is truncated")

    def decode(self, bits):
        entry = self.lookup[bits.peek(self.max_bits)]
        bits.skip(entry & 31)
        return entry >> 5


# --------------------------------------------------------------------------
# CHD FLAC codec (16-bit stereo frames without a stream header)


def _signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class FlacBits(BitReader):
    def unary(self):
        count = 0
        while True:
            window = self.peek(32)
            if window:
                zeros = 32 - window.bit_length()
                self.position += zeros + 1
                return count + zeros
            count += 32
            self.position += 32
            if self.position > self.length * 8:
                raise DiscImageError("CHD FLAC data is truncated")

    def utf8(self):
        first = self.read(8)
        if first < 0x80:
            return first
        extra = 0
        mask = 0x40
        while first & mask:
            extra += 1
            mask >>= 1
        value = first & (mask - 1)
        for _ in range(extra):
            value = (value << 6) | (self.read(8) & 0x3F)
        return value


def _flac_residual(bits, block_size, order, out):
    method = bits.read(2)
    if method > 1:
        raise DiscImageError("CHD FLAC residual coding is not supported")
    parameter_bits = 4 if method == 0 else 5
    escape = (1 << parameter_bits) - 1
    partition_order = bits.read(4)
    partitions = 1 << partition_order
    per_partition = block_size >> partition_order
    for partition in range(partitions):
        count = per_partition - (order if partition == 0 else 0)
        parameter = bits.read(parameter_bits)
        if parameter == escape:
            width = bits.read(5)
            for _ in range(count):
                out.append(_signed(bits.read(width), width) if width else 0)
            continue
        for _ in range(count):
            value = (bits.unary() << parameter) | bits.read(parameter)
            out.append((value >> 1) ^ -(value & 1))


FIXED_COEFFICIENTS = ((), (1,), (2, -1), (3, -3, 1), (4, -6, 4, -1))


def _flac_subframe(bits, block_size, sample_bits):
    if bits.read(1):
        raise DiscImageError("CHD FLAC subframe is damaged")
    kind = bits.read(6)
    wasted = 0
    if bits.read(1):
        wasted = bits.unary() + 1
        sample_bits -= wasted
    if kind == 0:
        samples = [_signed(bits.read(sample_bits), sample_bits)] * block_size
    elif kind == 1:
        samples = [
            _signed(bits.read(sample_bits), sample_bits)
            for _ in range(block_size)
        ]
    elif 8 <= kind <= 12:
        order = kind & 7
        samples = [
            _signed(bits.read(sample_bits), sample_bits) for _ in range(order)
        ]
        residual = []
        _flac_residual(bits, block_size, order, residual)
        coefficients = FIXED_COEFFICIENTS[order]
        for value in residual:
            prediction = 0
            for index, coefficient in enumerate(coefficients):
                prediction += coefficient * samples[-1 - index]
            samples.append(prediction + value)
    elif kind >= 32:
        order = (kind & 31) + 1
        samples = [
            _signed(bits.read(sample_bits), sample_bits) for _ in range(order)
        ]
        precision = bits.read(4) + 1
        if precision == 16:
            raise DiscImageError("CHD FLAC LPC precision is invalid")
        shift = _signed(bits.read(5), 5)
        if shift < 0:
            raise DiscImageError("CHD FLAC LPC shift is negative")
        coefficients = [
            _signed(bits.read(precision), precision) for _ in range(order)
        ]
        residual = []
        _flac_residual(bits, block_size, order, residual)
        for value in residual:
            prediction = 0
            for index, coefficient in enumerate(coefficients):
                prediction += coefficient * samples[-1 - index]
            samples.append((prediction >> shift) + value)
    else:
        raise DiscImageError(f"CHD FLAC subframe type {kind} is reserved")
    if wasted:
        samples = [sample << wasted for sample in samples]
    return samples


FLAC_BLOCK_SIZES = {
    1: 192, 2: 576, 3: 1152, 4: 2304, 5: 4608,
    8: 256, 9: 512, 10: 1024, 11: 2048, 12: 4096,
    13: 8192, 14: 16384, 15: 32768,
}


def flac_decode(data, output_bytes):
    if not data or data[0] not in (ord("L"), ord("B")):
        raise DiscImageError("CHD FLAC hunk has no byte-order marker")
    order = "<" if data[0] == ord("L") else ">"
    bits = FlacBits(data[1:])
    frames_needed = output_bytes // 4
    pcm = bytearray()
    decoded = 0
    while decoded < frames_needed:
        bits.position = (bits.position + 7) & ~7
        if bits.read(15) != 0x7FFC:
            raise DiscImageError("CHD FLAC frame sync is missing")
        bits.read(1)
        block_code = bits.read(4)
        rate_code = bits.read(4)
        channels_code = bits.read(4)
        size_code = bits.read(3)
        bits.read(1)
        bits.utf8()
        if block_code == 6:
            block_size = bits.read(8) + 1
        elif block_code == 7:
            block_size = bits.read(16) + 1
        elif block_code in FLAC_BLOCK_SIZES:
            block_size = FLAC_BLOCK_SIZES[block_code]
        else:
            raise DiscImageError("CHD FLAC block size is invalid")
        if rate_code == 12:
            bits.read(8)
        elif rate_code in (13, 14):
            bits.read(16)
        if size_code not in (0, 4):
            raise DiscImageError("CHD FLAC sample size is not 16 bits")
        bits.read(8)  # frame header CRC-8
        if channels_code == 1:
            left = _flac_subframe(bits, block_size, 16)
            right = _flac_subframe(bits, block_size, 16)
        elif channels_code == 8:
            left = _flac_subframe(bits, block_size, 16)
            side = _flac_subframe(bits, block_size, 17)
            right = [a - b for a, b in zip(left, side)]
        elif channels_code == 9:
            side = _flac_subframe(bits, block_size, 17)
            right = _flac_subframe(bits, block_size, 16)
            left = [a + b for a, b in zip(side, right)]
        elif channels_code == 10:
            mid = _flac_subframe(bits, block_size, 16)
            side = _flac_subframe(bits, block_size, 17)
            left = []
            right = []
            for m, s in zip(mid, side):
                m = (m << 1) | (s & 1)
                left.append((m + s) >> 1)
                right.append((m - s) >> 1)
        else:
            raise DiscImageError("CHD FLAC data is not stereo")
        bits.position = (bits.position + 7) & ~7
        bits.read(16)  # frame CRC-16
        take = min(block_size, frames_needed - decoded)
        interleaved = [0] * (take * 2)
        interleaved[0::2] = left[:take]
        interleaved[1::2] = right[:take]
        pcm += struct.pack(f"{order}{take * 2}h", *interleaved)
        decoded += take
    return bytes(pcm)


# --------------------------------------------------------------------------
# CHD image


_CRC16_TABLE = []
for _byte in range(256):
    _value = _byte << 8
    for _ in range(8):
        _value = ((_value << 1) ^ 0x1021) if _value & 0x8000 else (_value << 1)
    _CRC16_TABLE.append(_value & 0xFFFF)


def _crc16(data):
    """CRC-16/CCITT-FALSE, as chd.cpp computes it."""
    crc = 0xFFFF
    table = _CRC16_TABLE
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ table[(crc >> 8) ^ byte]
    return crc


def _lzma_dictionary_size(hunk_bytes):
    # LzmaEncProps_Normalize at level 9, reduced to the hunk size.
    size = 1 << 26
    if size > hunk_bytes:
        for shift in range(11, 31):
            if hunk_bytes <= (2 << shift):
                return 2 << shift
            if hunk_bytes <= (3 << shift):
                return 3 << shift
    return size


def _zstd_decompress(data, size):
    try:
        from compression import zstd  # Python 3.14+

        return zstd.decompress(data)[:size]
    except ImportError:
        pass
    try:
        import zstandard
    except ImportError as error:
        raise DiscImageError(
            "This CHD uses zstd compression, which needs Python 3.14 or the "
            "'zstandard' package (py -m pip install zstandard)."
        ) from error
    return zstandard.ZstdDecompressor().decompress(data, max_output_size=size)


COMPRESSION_NONE = 4
COMPRESSION_SELF = 5
COMPRESSION_PARENT = 6
CODEC_NAMES = {
    b"zlib": "zlib",
    b"lzma": "lzma",
    b"huff": "huff",
    b"flac": "flac",
    b"zstd": "zstd",
}
CD_CODECS = {b"cdzl", b"cdlz", b"cdfl", b"cdzs"}


class ChdImage:
    def __init__(self, path):
        self.path = path
        self.stream = open(path, "rb")
        header = self.stream.read(124)
        if len(header) < 16 or header[:8] != b"MComprHD":
            raise DiscImageError(f"{path}: not a CHD image")
        length, version = struct.unpack_from(">II", header, 8)
        if version != 5 or length < 124 or len(header) < 124:
            raise DiscImageError(
                f"{path}: CHD version {version} is not supported; "
                "recreate it with a current chdman (createdvd)"
            )
        tags = [header[16 + 4 * i : 20 + 4 * i] for i in range(4)]
        (
            self.size,
            self.map_offset,
            _meta_offset,
            self.hunk_bytes,
            self.unit_bytes,
        ) = struct.unpack_from(">QQQII", header, 32)
        self.raw_sha1 = header[64:84]
        parent = header[104:124]
        if any(parent):
            raise DiscImageError(
                f"{path}: CHDs that depend on a parent CHD are not supported"
            )
        if any(tag in CD_CODECS for tag in tags):
            raise DiscImageError(
                f"{path} is a CD-style CHD. Recreate it from the ISO with "
                "'chdman createdvd -hs 2048'."
            )
        if self.unit_bytes != SECTOR or self.hunk_bytes % SECTOR:
            raise DiscImageError(
                f"{path}: CHD unit size {self.unit_bytes} is not a 2048-byte "
                "DVD layout; recreate it with 'chdman createdvd -hs 2048'"
            )
        self.codecs = []
        for tag in tags:
            if tag == b"\0\0\0\0":
                self.codecs.append(None)
            elif tag in CODEC_NAMES:
                self.codecs.append(CODEC_NAMES[tag])
            else:
                name = tag.decode("ascii", "replace")
                raise DiscImageError(f"{path}: CHD codec '{name}' is not supported")
        self.hunks = (self.size + self.hunk_bytes - 1) // self.hunk_bytes
        self.compressed = self.codecs[0] is not None
        self._read_map()
        self._cache_number = None
        self._cache = None

    def _read_map(self):
        stream = self.stream
        stream.seek(self.map_offset)
        if not self.compressed:
            raw = stream.read(4 * self.hunks)
            offsets = struct.unpack(f">{self.hunks}I", raw)
            self.map = [
                (COMPRESSION_NONE if offset else COMPRESSION_SELF, self.hunk_bytes,
                 offset * self.hunk_bytes, None)
                for offset in offsets
            ]
            return
        header = stream.read(16)
        map_bytes = struct.unpack_from(">I", header, 0)[0]
        first_offset = int.from_bytes(header[4:10], "big")
        map_crc = struct.unpack_from(">H", header, 10)[0]
        length_bits, self_bits, parent_bits = header[12], header[13], header[14]
        bits = BitReader(stream.read(map_bytes))

        decoder = Huffman(16, 8)
        decoder.import_rle(bits)
        kinds = []
        last = 0
        repeat = 0
        for _ in range(self.hunks):
            if repeat > 0:
                kinds.append(last)
                repeat -= 1
                continue
            value = decoder.decode(bits)
            if value == 7:  # RLE small
                kinds.append(last)
                repeat = 2 + decoder.decode(bits)
            elif value == 8:  # RLE large
                kinds.append(last)
                repeat = 2 + 16 + (decoder.decode(bits) << 4)
                repeat += decoder.decode(bits)
            else:
                last = value
                kinds.append(value)

        entries = []
        raw_map = bytearray()
        offset_cursor = first_offset
        last_self = 0
        last_parent = 0
        hunk_units = self.hunk_bytes // self.unit_bytes
        for number, kind in enumerate(kinds):
            offset = offset_cursor
            length = 0
            crc = 0
            if kind <= 3:
                length = bits.read(length_bits)
                offset_cursor += length
                crc = bits.read(16)
            elif kind == COMPRESSION_NONE:
                length = self.hunk_bytes
                offset_cursor += length
                crc = bits.read(16)
            elif kind == COMPRESSION_SELF:
                offset = last_self = bits.read(self_bits)
            elif kind == COMPRESSION_PARENT:
                offset = last_parent = bits.read(parent_bits)
            elif kind in (9, 10):  # SELF_0, SELF_1
                if kind == 10:
                    last_self += 1
                kind = COMPRESSION_SELF
                offset = last_self
            elif kind == 11:  # PARENT_SELF
                kind = COMPRESSION_PARENT
                offset = last_parent = number * hunk_units
            elif kind in (12, 13):  # PARENT_0, PARENT_1
                if kind == 13:
                    last_parent += hunk_units
                kind = COMPRESSION_PARENT
                offset = last_parent
            else:
                raise DiscImageError(f"CHD map entry {number} is invalid")
            raw_map.append(kind)
            raw_map += length.to_bytes(3, "big")
            raw_map += offset.to_bytes(6, "big")
            raw_map += crc.to_bytes(2, "big")
            entries.append((kind, length, offset, crc))
        if _crc16(raw_map) != map_crc:
            raise DiscImageError("CHD map is damaged (CRC mismatch)")
        self.map = entries

    def hunk(self, number, depth=0):
        if number == self._cache_number:
            return self._cache
        kind, length, offset, crc = self.map[number]
        if kind == COMPRESSION_SELF:
            if not self.compressed and offset == 0:
                data = bytes(self.hunk_bytes)
            else:
                if depth > 8 or offset == number:
                    raise DiscImageError(f"CHD hunk {number} refers to itself")
                data = self.hunk(offset, depth + 1)
            self._cache_number, self._cache = number, data
            return data
        if kind == COMPRESSION_PARENT:
            raise DiscImageError("CHD hunk needs a parent CHD")
        self.stream.seek(offset)
        payload = self.stream.read(length)
        if len(payload) != length:
            raise DiscImageError(f"CHD hunk {number} is truncated")
        if kind == COMPRESSION_NONE:
            data = payload
        else:
            codec = self.codecs[kind]
            if codec is None:
                raise DiscImageError(f"CHD hunk {number} uses an unset codec")
            data = self._decompress(codec, payload, number)
        if crc is not None and _crc16(data) != crc:
            raise DiscImageError(f"CHD hunk {number} is damaged (CRC mismatch)")
        self._cache_number, self._cache = number, data
        return data

    def _decompress(self, codec, payload, number):
        size = self.hunk_bytes
        try:
            if codec == "zlib":
                data = zlib.decompressobj(-15).decompress(payload, size)
            elif codec == "lzma":
                decompressor = lzma.LZMADecompressor(
                    format=lzma.FORMAT_RAW,
                    filters=[{
                        "id": lzma.FILTER_LZMA1,
                        "dict_size": _lzma_dictionary_size(size),
                        "lc": 3,
                        "lp": 0,
                        "pb": 2,
                    }],
                )
                data = decompressor.decompress(payload, size)
            elif codec == "huff":
                bits = BitReader(payload)
                decoder = Huffman(256, 16)
                decoder.import_huffman(bits)
                data = bytes(decoder.decode(bits) for _ in range(size))
            elif codec == "flac":
                data = flac_decode(payload, size)
            elif codec == "zstd":
                data = _zstd_decompress(payload, size)
            else:
                raise DiscImageError(f"CHD codec {codec} is not supported")
        except (zlib.error, lzma.LZMAError) as error:
            raise DiscImageError(
                f"CHD hunk {number} is damaged: {error}"
            ) from error
        if len(data) != size:
            raise DiscImageError(f"CHD hunk {number} decoded to the wrong size")
        return data

    def iter_blocks(self):
        remaining = self.size
        for number in range(self.hunks):
            data = self.hunk(number)
            yield data[: min(len(data), remaining)]
            remaining -= len(data)

    def close(self):
        self.stream.close()


def _open_closing(cls, path):
    image = cls.__new__(cls)
    try:
        image.__init__(path)
    except BaseException:
        stream = getattr(image, "stream", None)
        if stream is not None:
            stream.close()
        raise
    return image


def open_compressed(path):
    kind = image_kind(path)
    if kind == "cso":
        return _open_closing(CsoImage, path)
    if kind == "chd":
        return _open_closing(ChdImage, path)
    if kind == "unsupported-cso":
        raise DiscImageError(
            f"{path}: ZSO and DAX images are not supported; use ISO, CSO or CHD"
        )
    raise DiscImageError(f"{path} is not a compressed disc image")


def convert_to_iso(source, destination, progress=None):
    """Decompress source to destination and return the image's SHA-1."""
    source = Path(source)
    destination = Path(destination)
    image = open_compressed(source)
    digest = hashlib.sha1()
    temporary = destination.with_name(destination.name + ".partial")
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with open(temporary, "wb") as output:
            for block in image.iter_blocks():
                output.write(block)
                digest.update(block)
                written += len(block)
                if progress is not None:
                    progress(written, image.size)
        if written != image.size:
            raise DiscImageError(
                f"{source}: decoded {written} bytes, expected {image.size}"
            )
        if isinstance(image, ChdImage) and any(image.raw_sha1):
            if digest.digest() != image.raw_sha1:
                raise DiscImageError(
                    f"{source}: decoded data does not match the SHA-1 the CHD "
                    "records; the file is damaged"
                )
        os.replace(temporary, destination)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    finally:
        image.close()
    return digest.hexdigest()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help=".cso or .chd image")
    parser.add_argument("destination", type=Path, help="ISO to write")
    args = parser.parse_args(argv)
    try:
        sha1 = convert_to_iso(args.source, args.destination)
    except (OSError, DiscImageError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"wrote {args.destination} (SHA-1 {sha1})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
