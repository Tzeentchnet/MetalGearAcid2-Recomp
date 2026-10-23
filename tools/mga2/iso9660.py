"""Minimal read-only ISO9660 reader for PSP UMD images."""

import hashlib
import struct

SECTOR = 2048


class IsoFile:
    __slots__ = ("path", "lba", "size", "is_dir")

    def __init__(self, path, lba, size, is_dir):
        self.path = path
        self.lba = lba
        self.size = size
        self.is_dir = is_dir

    @property
    def offset(self):
        return self.lba * SECTOR


class Iso:
    def __init__(self, path):
        self.path = path
        self.stream = open(path, "rb")
        self.stream.seek(16 * SECTOR)
        descriptor = self.stream.read(SECTOR)
        if descriptor[1:6] != b"CD001":
            raise ValueError(f"{path}: no ISO9660 primary volume descriptor")
        self.volume_id = descriptor[40:72].decode("ascii", "replace").strip()
        root = descriptor[156:190]
        self.entries = {}
        self._walk(
            struct.unpack_from("<I", root, 2)[0],
            struct.unpack_from("<I", root, 10)[0],
            "",
        )

    def _walk(self, lba, size, prefix):
        self.stream.seek(lba * SECTOR)
        data = self.stream.read(size)
        offset = 0
        while offset < len(data):
            record_size = data[offset]
            if record_size == 0:
                offset = (offset // SECTOR + 1) * SECTOR
                continue
            record = data[offset : offset + record_size]
            offset += record_size
            name = record[33 : 33 + record[32]]
            if name in (b"\x00", b"\x01"):
                continue
            name = name.decode("ascii", "replace").split(";")[0]
            entry_lba = struct.unpack_from("<I", record, 2)[0]
            entry_size = struct.unpack_from("<I", record, 10)[0]
            is_dir = bool(record[25] & 2)
            full_path = f"{prefix}/{name}"
            entry = IsoFile(full_path, entry_lba, entry_size, is_dir)
            self.entries[full_path.upper()] = entry
            if is_dir:
                self._walk(entry_lba, entry_size, full_path)

    def files(self):
        return [entry for entry in self.entries.values() if not entry.is_dir]

    def lookup(self, path):
        entry = self.entries.get(("/" + path.strip("/")).upper())
        if entry is None:
            raise FileNotFoundError(f"{path} not found in {self.path}")
        return entry

    def read(self, path_or_entry, offset=0, size=None):
        entry = (
            path_or_entry
            if isinstance(path_or_entry, IsoFile)
            else self.lookup(path_or_entry)
        )
        if size is None:
            size = entry.size - offset
        size = max(0, min(size, entry.size - offset))
        self.stream.seek(entry.offset + offset)
        return self.stream.read(size)

    def close(self):
        self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def sha1_file(path, chunk_size=1 << 22):
    digest = hashlib.sha1()
    with open(path, "rb") as stream:
        while True:
            chunk = stream.read(chunk_size)
            if not chunk:
                return digest.hexdigest()
            digest.update(chunk)
