#!/usr/bin/env python3
"""Materialize and verify this title's patch over the pinned runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from local_files import is_link_or_reparse_point


COPIED_DIRECTORIES = (
    Path("src", "rt"),
    Path("src", "ref"),
    Path("tools", "tests"),
    Path("third_party", "ppsspp_savedata"),
    Path("third_party", "smaa"),
    Path("third_party", "xbrz"),
)
SHADERS = {
    "psp_ps.inc": Path("src", "rt", "gpu_d3d12", "shaders", "psp_ps.inc"),
    "psp_ps_direct.inc": Path(
        "src", "rt", "gpu_d3d12", "shaders", "psp_ps_direct.inc"
    ),
    "psp_frag.inc": Path("src", "rt", "gpu_sdl3vk", "psp_frag.inc"),
}
MARKER = ".mga2-runtime-overlay.json"


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()

    def raise_walk_error(error: OSError) -> None:
        raise error

    entries: list[tuple[Path, bool]] = []
    for parent, directories, filenames in os.walk(
        root, followlinks=False, onerror=raise_walk_error
    ):
        directories.sort()
        filenames.sort()
        for name in directories + filenames:
            path = Path(parent) / name
            if is_link_or_reparse_point(path):
                raise ValueError(f"runtime overlay contains a link: {path}")
        entries.extend((Path(parent) / name, True) for name in directories)
        entries.extend(
            (Path(parent) / name, False)
            for name in filenames
            if name != MARKER or Path(parent) != root
        )
    for path, is_directory in sorted(entries):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(b"D" if is_directory else b"F")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        if not is_directory:
            if not path.is_file():
                raise ValueError(f"unsupported runtime overlay entry: {path}")
            digest.update(bytes.fromhex(file_hash(path)))
    return digest.hexdigest()


def expected_inputs(patches: list[Path], shaders: Path) -> dict[str, object]:
    return {
        "schema": 2,
        "patches": [
            {"name": patch.name, "sha256": file_hash(patch)}
            for patch in patches
        ],
        "shaders": {name: file_hash(shaders / name) for name in SHADERS},
    }


def verify(overlay: Path, patches: list[Path], shaders: Path) -> None:
    if is_link_or_reparse_point(overlay):
        raise ValueError(f"runtime overlay cannot be a link: {overlay}")
    with (overlay / MARKER).open("r", encoding="utf-8") as stream:
        recorded = json.load(stream)
    expected = expected_inputs(patches, shaders)
    expected["tree_sha256"] = tree_hash(overlay)
    if recorded != expected:
        raise ValueError(
            "runtime overlay differs from its recorded inputs; "
            "rerun CMake configuration"
        )


def prepare(toolkit: Path, overlay: Path, patches: list[Path], shaders: Path) -> None:
    toolkit = toolkit.resolve(strict=True)
    overlay = overlay.absolute()
    if overlay.name != "mga2-runtime-overlay":
        raise ValueError("runtime overlay must be named mga2-runtime-overlay")
    if is_link_or_reparse_point(overlay):
        raise ValueError(f"runtime overlay cannot be a link: {overlay}")
    resolved_overlay = overlay.resolve()
    if (resolved_overlay == toolkit or
            resolved_overlay in toolkit.parents or
            toolkit in resolved_overlay.parents):
        raise ValueError("runtime overlay must not overlap the toolkit")
    if overlay.exists() and not (overlay / MARKER).is_file():
        raise ValueError(f"refusing to replace unowned directory: {overlay}")

    overlay.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="mga2-runtime-stage-", dir=overlay.parent
    ) as temporary:
        stage = Path(temporary) / "overlay"
        for relative in COPIED_DIRECTORIES:
            source = toolkit / relative
            if is_link_or_reparse_point(source):
                raise ValueError(f"toolkit source cannot be a link: {source}")
            tree_hash(source)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination)

        environment = os.environ.copy()
        environment["GIT_CEILING_DIRECTORIES"] = str(stage.parent)
        for patch in patches:
            command = [
                "git", "-c", "core.autocrlf=false", "apply",
                "--ignore-space-change", "--whitespace=nowarn",
                str(patch.resolve()),
            ]
            for arguments in (command[:4] + ["--check"] + command[4:], command):
                result = subprocess.run(
                    arguments, cwd=stage, env=environment,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", check=False,
                )
                if result.returncode:
                    raise ValueError(
                        f"cannot apply pinned runtime patch {patch.name}: "
                        + (result.stderr or result.stdout).strip()
                    )
        for name, relative in SHADERS.items():
            shutil.copyfile(shaders / name, stage / relative)
        manifest = expected_inputs(patches, shaders)
        manifest["tree_sha256"] = tree_hash(stage)
        (stage / MARKER).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if overlay.exists():
            shutil.rmtree(overlay)
        os.replace(stage, overlay)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--patch", type=Path, action="append", required=True)
    parser.add_argument("--shaders", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify:
            verify(args.overlay, args.patch, args.shaders)
        else:
            prepare(args.toolkit, args.overlay, args.patch, args.shaders)
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
