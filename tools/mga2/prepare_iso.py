#!/usr/bin/env python3
"""Resolve an ISO input, extracting a ZIP beside its archive when needed."""

from __future__ import annotations

import argparse
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
import tomllib
import zipfile
import zlib


ROOT = Path(__file__).resolve().parents[2]


class IsoPreparationError(ValueError):
    pass


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "mga2.toml",
    )
    return parser.parse_args(argv[1:])


def archive_iso_path(source: Path) -> Path:
    if source.stem.lower().endswith(".iso"):
        return source.with_suffix("")
    return source.with_suffix(".iso")


def crc32_file(path: Path) -> int:
    checksum = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            checksum = zlib.crc32(chunk, checksum)
    return checksum & 0xFFFFFFFF


def prepare_zip(source: Path, expected_size: int) -> Path:
    destination = archive_iso_path(source)
    if not str(destination).isascii():
        raise IsoPreparationError(
            "the extracted ISO path must use ASCII characters; "
            "move the ZIP to an ASCII-only path"
        )

    with zipfile.ZipFile(source) as archive:
        iso_entries = [
            entry
            for entry in archive.infolist()
            if not entry.is_dir()
            and PurePosixPath(entry.filename.replace("\\", "/")).suffix.lower()
            == ".iso"
        ]
        if len(iso_entries) != 1:
            raise IsoPreparationError(
                f"ZIP must contain exactly one ISO file; found {len(iso_entries)}"
            )
        entry = iso_entries[0]
        if entry.flag_bits & 0x1:
            raise IsoPreparationError("password-protected ZIP files are not supported")
        if entry.file_size != expected_size:
            raise IsoPreparationError(
                f"archived ISO size {entry.file_size} != expected {expected_size}"
            )

        if destination.exists():
            if not destination.is_file():
                raise IsoPreparationError(
                    f'extraction destination is not a file: "{destination}"'
                )
            if (
                destination.stat().st_size != entry.file_size
                or crc32_file(destination) != entry.CRC
            ):
                raise IsoPreparationError(
                    f'existing ISO does not match the ZIP: "{destination}"; '
                    "move or delete it before retrying"
                )
            print(f'Reusing extracted ISO: "{destination}"')
            return destination.resolve()

        print(f'Extracting "{entry.filename}" to "{destination}"...')
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".mga2-",
                suffix=".partial",
                dir=destination.parent,
                delete=False,
            ) as output:
                temporary_path = Path(output.name)
                with archive.open(entry) as archived_iso:
                    shutil.copyfileobj(archived_iso, output, length=1024 * 1024)
            if temporary_path.stat().st_size != expected_size:
                raise IsoPreparationError(
                    "extracted ISO size changed during extraction"
                )
            temporary_path.replace(destination)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()
    return destination.resolve()


def prepare_iso(source: Path, expected_size: int) -> Path:
    source = source.resolve(strict=True)
    if not source.is_file():
        raise IsoPreparationError(f'ISO input is not a file: "{source}"')
    if source.suffix.lower() == ".zip":
        return prepare_zip(source, expected_size)
    if not str(source).isascii():
        raise IsoPreparationError(
            "the ISO path must use ASCII characters; "
            "move the ISO to an ASCII-only path"
        )
    return source


def run(argv: list[str]) -> int:
    args = parse_args(argv)
    with args.config.open("rb") as stream:
        config = tomllib.load(stream)
    expected_size = config["disc"]["iso_size"]
    if not isinstance(expected_size, int):
        raise IsoPreparationError("disc.iso_size must be an integer")

    iso_path = prepare_iso(args.source, expected_size)
    args.result.write_text(str(iso_path) + "\n", encoding="ascii")
    print(f'Using ISO: "{iso_path}"')
    return 0


def main(argv: list[str]) -> int:
    try:
        return run(argv)
    except (
        IsoPreparationError,
        KeyError,
        NotImplementedError,
        OSError,
        RuntimeError,
        tomllib.TOMLDecodeError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as error:
        print(f"ERROR: could not prepare ISO input: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
