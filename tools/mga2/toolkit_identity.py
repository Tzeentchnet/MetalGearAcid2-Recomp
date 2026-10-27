#!/usr/bin/env python3
"""Verify that generation and builds use the intended psp-recomp toolkit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib

from local_files import is_link_or_reparse_point


ROOT = Path(__file__).resolve().parents[2]
IDENTITY_FILE = "mga2_toolkit_identity.json"
IDENTITY_ROOTS = ("src", "tools", "third_party", "assets", "font")
IGNORED_DIRECTORIES = {".git", "__pycache__", ".pytest_cache"}


def source_tree_sha256(toolkit: Path) -> str:
    digest = hashlib.sha256()
    entries = []

    def raise_walk_error(error: OSError) -> None:
        raise error

    for name in IDENTITY_ROOTS:
        root = toolkit / name
        if is_link_or_reparse_point(root):
            raise ValueError(f"unsupported toolkit source link: {root}")
        if not root.exists():
            continue
        if not root.is_dir():
            raise ValueError(f"toolkit source root is not a directory: {root}")
        entries.append((root, True))
        for parent, directories, filenames in os.walk(
            root, followlinks=False, onerror=raise_walk_error
        ):
            directories[:] = sorted(
                name for name in directories if name not in IGNORED_DIRECTORIES
            )
            for entry in directories + filenames:
                path = Path(parent) / entry
                if is_link_or_reparse_point(path):
                    raise ValueError(f"unsupported toolkit source link: {path}")
            entries.extend((Path(parent) / name, True) for name in directories)
            for name in filenames:
                path = Path(parent) / name
                if not path.is_file():
                    raise ValueError(f"unsupported toolkit source entry: {path}")
                entries.append((path, False))
    for path, is_directory in sorted(entries):
        relative = path.relative_to(toolkit).as_posix().encode("utf-8")
        digest.update(b"D" if is_directory else b"F")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if not is_directory:
            digest.update(path.stat().st_size.to_bytes(8, "big"))
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    return digest.hexdigest()


def git_output(toolkit: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(toolkit), *arguments],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def identify_toolkit(
    toolkit: Path,
    expected_commit: str,
    *,
    allow_unsupported: bool = False,
) -> dict[str, object]:
    toolkit = toolkit.resolve()
    if not (toolkit / "tools" / "codegen.py").is_file():
        raise ValueError(f"psp-recomp tools were not found under {toolkit}")
    try:
        root = git_output(toolkit, "rev-parse", "--show-toplevel")
    except FileNotFoundError as error:
        if not allow_unsupported:
            raise ValueError(
                "Git is required to verify the toolkit revision; "
                "use --allow-unsupported-toolkit only for development"
            ) from error
        root = None

    is_checkout = (
        root is not None
        and root.returncode == 0
        and Path(root.stdout.strip()).resolve() == toolkit
    )
    revision = None
    dirty = None
    if is_checkout:
        commit = git_output(toolkit, "rev-parse", "--verify", "HEAD")
        status = git_output(
            toolkit, "status", "--porcelain=v1",
            "--untracked-files=normal", "--ignore-submodules=none",
        )
        if commit.returncode or status.returncode:
            raise ValueError(
                "could not determine toolkit revision and working-tree status: "
                + (commit.stderr or status.stderr).strip()
            )
        revision = commit.stdout.strip()
        dirty = bool(status.stdout.strip())

    supported = revision == expected_commit and dirty is False
    if not supported and not allow_unsupported:
        if not is_checkout:
            detail = "not a verifiable Git checkout"
        elif dirty:
            detail = f"checkout {revision} has uncommitted changes"
        else:
            detail = f"checkout is at {revision}, expected {expected_commit}"
        raise ValueError(
            f"unsupported psp-recomp toolkit: {detail}; "
            "use --allow-unsupported-toolkit only for development"
        )

    return {
        "schema": 1,
        "expected_commit": expected_commit,
        "revision": revision,
        "dirty": dirty,
        "source_sha256": None if supported else source_tree_sha256(toolkit),
    }


def check_manifest(path: Path, identity: dict[str, object]) -> None:
    with path.open("r", encoding="utf-8") as stream:
        recorded = json.load(stream)
    if recorded != identity:
        raise ValueError(
            f"toolkit identity differs from {path}; regenerate with this "
            "toolkit before building"
        )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "mga2.toml")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--allow-unsupported-toolkit", action="store_true")
    args = parser.parse_args(argv)
    try:
        with args.config.open("rb") as stream:
            config = tomllib.load(stream)
        identity = identify_toolkit(
            args.toolkit,
            config["runtime"]["commit"],
            allow_unsupported=args.allow_unsupported_toolkit,
        )
        if args.manifest is not None:
            check_manifest(args.manifest, identity)
        if identity["source_sha256"] is not None:
            print(
                "WARNING: using an unsupported or modified psp-recomp toolkit; "
                "this is a development build, not the validated release.",
                file=sys.stderr,
            )
        return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
