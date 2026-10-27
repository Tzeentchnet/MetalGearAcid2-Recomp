#!/usr/bin/env python3
"""Reject common game-derived, binary, and generated files from Git history."""

from __future__ import annotations

from pathlib import PurePosixPath
import re
import subprocess
import sys


PROTECTED_SUFFIXES = {
    ".iso", ".cso", ".chd", ".img", ".cue", ".pbp", ".prx", ".elf",
    ".bin", ".sfo", ".sav", ".trace", ".ppm", ".exe", ".dll", ".zip",
    ".7z", ".rar", ".log",
}
GENERATED_SOURCE = re.compile(
    r".+_recomp(?:_[0-9]{3}|_register)?\.(?:c|h)$", re.IGNORECASE
)


def protected_path(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    lowered = tuple(part.lower() for part in parts)
    if any(part in {"build", "out", "memstick"} for part in lowered):
        return True
    if any(
        lowered[index : index + 2] == ("psp", "savedata")
        for index in range(len(lowered) - 1)
    ):
        return True
    if not lowered:
        return False
    name = lowered[-1]
    return (
        PurePosixPath(name).suffix in PROTECTED_SUFFIXES
        or name.startswith(("capture_present_", "snap_", "fb_"))
        or GENERATED_SOURCE.fullmatch(name) is not None
    )


def git_paths(*arguments: str) -> set[str]:
    result = subprocess.run(
        ["git", *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return {
        part.decode("utf-8", errors="surrogateescape")
        for part in result.stdout.split(b"\0")
        if part
    }


def main() -> int:
    try:
        tracked = git_paths("ls-files", "-z")
        history = git_paths(
            "log", "--all", "--root", "-m", "--pretty=format:",
            "--name-only", "-z",
        )
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"ERROR: could not inspect Git release contents: {error}", file=sys.stderr)
        return 2
    rejected = sorted(path for path in tracked | history if protected_path(path))
    if rejected:
        print("ERROR: protected or generated files appear in Git:", file=sys.stderr)
        for path in rejected:
            print(f"  {path}", file=sys.stderr)
        return 1
    print("Tracked files and reachable history contain no known protected paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
