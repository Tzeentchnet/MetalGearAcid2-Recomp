#!/usr/bin/env python3
"""Verify the supported Metal Gear Acid 2 ISO and extract local build inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import tomllib

from iso9660 import Iso, sha1_file

ROOT = Path(__file__).resolve().parents[2]


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("iso", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "build" / "mga2" / "disc",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "config" / "mga2.toml",
    )
    return parser.parse_args(argv[1:])


def write_entry(entry, data, output_root):
    iso_path = entry.path.lstrip("/")
    destination = output_root.joinpath(*iso_path.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return destination


def module_kind(data):
    if data.startswith(b"\x7fELF"):
        return "elf"
    if data.startswith((b"~PSP", b"~SCE")):
        return "encrypted"
    return "data"


def extract_iso(argv):
    args = parse_args(argv)
    try:
        with args.config.open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        print(f"ERROR: could not read {args.config}: {error}", file=sys.stderr)
        return 1

    actual_size = args.iso.stat().st_size
    expected_size = config["disc"]["iso_size"]
    if actual_size != expected_size:
        print(
            f"ERROR: ISO size {actual_size} != expected {expected_size}",
            file=sys.stderr,
        )
        return 1
    print(f"hashing {args.iso} ({actual_size:,} bytes)...")
    actual_sha1 = sha1_file(args.iso)
    expected_sha1 = config["disc"]["iso_sha1"]
    if actual_sha1 != expected_sha1:
        print(
            f"ERROR: ISO SHA-1 {actual_sha1} != expected {expected_sha1}",
            file=sys.stderr,
        )
        return 1
    print(f"ISO SHA-1 ok ({actual_sha1})")

    expected_files = config["disc"]["files"]
    module_hashes = {
        module["file"].upper(): module["sha1"]
        for module in config.get("hle_module", [])
    }
    module_hashes.update(
        {
            module["file"].upper(): module["sha1"]
            for module in config.get("native_module", [])
        }
    )
    roots = tuple(
        root.upper().rstrip("/") + "/"
        for root in config["disc"]["plaintext_module_roots"]
    )
    records = []
    failures = []
    extracted = set()
    seen_modules = set()
    pending = []
    with Iso(args.iso) as iso:
        for iso_path, expected_hash in expected_files.items():
            entry = iso.lookup(iso_path)
            data = iso.read(entry)
            actual_hash = hashlib.sha1(data).hexdigest()
            if actual_hash != expected_hash:
                failures.append(
                    f"{iso_path}: {actual_hash} != {expected_hash}"
                )
            extracted.add(iso_path.upper())
            pending.append((entry, data))
            print(
                f"  {iso_path:<52} {len(data):>10,} "
                f"{actual_hash}"
            )

        for entry in sorted(iso.files(), key=lambda value: value.path.upper()):
            iso_path = entry.path.lstrip("/")
            upper = iso_path.upper()
            if (
                not upper.endswith(".PRX")
                or not upper.startswith(roots)
            ):
                continue
            data = iso.read(entry)
            kind = module_kind(data)
            actual_hash = hashlib.sha1(data).hexdigest()
            records.append(
                {
                    "path": iso_path,
                    "size": len(data),
                    "lba": entry.lba,
                    "sha1": actual_hash,
                    "kind": kind,
                }
            )
            if upper in module_hashes:
                seen_modules.add(upper)
            if upper in module_hashes and actual_hash != module_hashes[upper]:
                failures.append(
                    f"{iso_path}: {actual_hash} != {module_hashes[upper]}"
                )
            if upper not in extracted:
                pending.append((entry, data))
                print(
                    f"  {iso_path:<52} {len(data):>10,} "
                    f"{actual_hash} {kind}"
                )

    for missing in sorted(module_hashes.keys() - seen_modules):
        failures.append(f"configured module was not found: {missing}")
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for entry, data in pending:
        write_entry(entry, data, args.out)
    inventory_path = args.out.parent / "disc_inventory.json"
    inventory_path.write_text(
        json.dumps(
            {
                "iso_size": actual_size,
                "iso_sha1": actual_sha1,
                "files": records,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {args.out}: "
        f"{sum(item['kind'] == 'elf' for item in records)} plaintext and "
        f"{sum(item['kind'] == 'encrypted' for item in records)} encrypted PRXs"
    )
    print(f"wrote {inventory_path}")
    return 0


def main(argv):
    try:
        return extract_iso(argv)
    except (OSError, ValueError, KeyError) as error:
        print(f"ERROR: extraction failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
