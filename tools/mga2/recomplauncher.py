#!/usr/bin/env python3
"""Set up or start Metal Gear Acid 2 without windows, for game launchers.

play.bat --prepare --game IMAGE [--data DIR]
    Convert a CSO or CHD image to an ISO once, fetch the pinned psp-recomp
    toolkit, then build and install the game with install.bat, printing
    "progress <0..1> <text>" lines as it goes.
play.bat --play --game IMAGE --data DIR [--show-setup] [--fullscreen|--windowed]
    Start the installed game with its settings, memory stick and logs in DIR.
    The window starts full screen in RecompLauncher's Big Picture mode unless
    --fullscreen or --windowed says otherwise.

Without --prepare or --play, play.bat behaves exactly as before.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

import prepare_iso


ROOT = Path(__file__).resolve().parents[2]
PRESETS = ("clang-cl", "clang-cl-software")
STAMP_NAME = "recomplauncher-build.json"
STAMP_VERSION = 1
LOG_NAME = "mga2.log"
KEPT_LOGS = 4

# Exit codes of --play when the game cannot start; recomplauncher.json
# explains them to the player.
PLAY_NOT_BUILT = 120
PLAY_ISO_UNUSABLE = 121
PLAY_PATH_UNSUPPORTED = 122

REQUIREMENTS = (
    "Setting up needs Python 3.11+, Git, CMake 3.25+, Ninja, Visual Studio "
    "2022 Build Tools with clang-cl and a Windows SDK, and the Vulkan SDK: "
    "https://github.com/Tzeentchnet/MetalGearAcid2-Recomp#requirements"
)

# install.bat's own step lines, and where each one starts on the setup bar.
INSTALL_STEPS = (
    ("Checking installation prerequisites", 0.04, "Checking the build tools"),
    ("[1/6] Verifying", 0.06, "Checking and unpacking your disc"),
    ("[2/6] Generating", 0.12, "Generating the game's code"),
    ("[3/6] Configuring", 0.30, "Configuring the build"),
    ("[4/6] Building", 0.35, "Compiling the game"),
    ("[5/6] Staging", 0.93, "Installing the game"),
    ("[6/6] Installation complete", 0.98, "Finishing"),
)
COMPILE_START = 0.35
COMPILE_END = 0.92
NINJA_STATUS = re.compile(r"^\[(\d+)/(\d+)\] ")

# Everything the build reads from this project; a change to any of them
# means the installed game must be built again.
BUILD_INPUT_FILES = ("install.bat", "CMakeLists.txt", "CMakePresets.json")
BUILD_INPUT_DIRECTORIES = ("cmake", "config", Path("tools", "mga2"))
IGNORED_DIRECTORIES = {"tests", "__pycache__"}


class LauncherError(Exception):
    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code


def progress(fraction: float, text: str) -> None:
    print(f"progress {fraction:.2f} {text}", flush=True)


def load_config(root: Path = ROOT) -> dict:
    with (root / "config" / "mga2.toml").open("rb") as stream:
        return tomllib.load(stream)


def require_ascii(path: Path, what: str, code: int) -> None:
    if not str(path).isascii():
        raise LauncherError(
            f"{what} must use only ASCII characters: {path}\n"
            "Move it to a path such as C:\\Games and try again.",
            code,
        )


def check_iso(iso: Path, expected_size: int, code: int) -> Path:
    iso = iso.absolute()
    require_ascii(iso, "The disc image path", code)
    if not iso.is_file():
        raise LauncherError(f"The disc image was not found: {iso}", code)
    size = iso.stat().st_size
    if size != expected_size:
        raise LauncherError(
            f"This disc image is {size:,} bytes; the USA v1.00 release "
            f"(ULUS-10077) is {expected_size:,} bytes. Pick that one.",
            code,
        )
    return iso


def build_inputs_digest(root: Path = ROOT) -> str:
    paths = [root / name for name in BUILD_INPUT_FILES]
    for directory in BUILD_INPUT_DIRECTORIES:
        for parent, directories, filenames in os.walk(root / directory):
            directories[:] = sorted(
                name for name in directories if name not in IGNORED_DIRECTORIES
            )
            paths.extend(
                Path(parent) / name
                for name in filenames
                if not name.endswith(".pyc")
            )
    digest = hashlib.sha256()
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def expected_stamp(preset: str, root: Path = ROOT) -> dict:
    return {
        "version": STAMP_VERSION,
        "preset": preset,
        "inputs": build_inputs_digest(root),
    }


def install_directory(preset: str, root: Path = ROOT) -> Path:
    return root / "out" / "install" / preset


def is_installed(directory: Path) -> bool:
    return (directory / "mga2.exe").is_file() and (
        directory / "mga2_image.bin"
    ).is_file()


def is_current_build(preset: str, root: Path = ROOT) -> bool:
    directory = install_directory(preset, root)
    if not is_installed(directory):
        return False
    try:
        recorded = json.loads((directory / STAMP_NAME).read_text("utf-8"))
    except (OSError, ValueError):
        return False
    return recorded == expected_stamp(preset, root)


def git(repository: Path | None, *arguments: str, capture: bool = False) -> str:
    command = ["git"]
    if repository is not None:
        command += ["-C", str(repository)]
    command.extend(arguments)
    environment = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            command, check=True, text=True, env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as error:
        raise LauncherError(f"Git was not found on PATH. {REQUIREMENTS}") from error
    except subprocess.CalledProcessError as error:
        raise LauncherError(
            f"git {' '.join(arguments[:2])} failed with exit code "
            f"{error.returncode}. Check your internet connection and try again."
        ) from error
    return result.stdout.strip() if capture else ""


def ensure_toolkit(repository: str, commit: str, root: Path = ROOT) -> Path:
    """Check out the pinned toolkit in .deps, reusing an earlier checkout."""
    target = root / ".deps" / "psp-recomp"
    if target.exists():
        if not (target / ".git").exists():
            raise LauncherError(
                f"{target} is not a Git checkout. Delete it, then set up again."
            )
        if git(target, "rev-parse", "HEAD", capture=True) != commit:
            git(target, "fetch", "--quiet", "origin", commit)
            git(target, "checkout", "--quiet", "--detach", commit)
        return target
    partial = target.with_name("psp-recomp.partial")
    if partial.exists():
        shutil.rmtree(partial)
    partial.parent.mkdir(parents=True, exist_ok=True)
    git(None, "clone", "--quiet", "--no-checkout", repository, str(partial))
    git(partial, "checkout", "--quiet", "--detach", commit)
    os.replace(partial, target)
    return target


class InstallProgress:
    """Turn install.bat's step lines and Ninja's status into progress lines."""

    def __init__(self) -> None:
        self.compiling = False
        self.reported = -1

    def line(self, text: str) -> None:
        for prefix, fraction, label in INSTALL_STEPS:
            if text.startswith(prefix):
                self.compiling = prefix.startswith("[4/6]")
                progress(fraction, label)
                return
        if not self.compiling:
            return
        match = NINJA_STATUS.match(text)
        if not match:
            return
        done, total = int(match.group(1)), int(match.group(2))
        if not total:
            return
        percent = done * 100 // total
        if percent == self.reported:
            return
        self.reported = percent
        fraction = COMPILE_START + (COMPILE_END - COMPILE_START) * done / total
        progress(fraction, f"Compiling the game ({percent}%)")


def batch_command(script: Path, arguments: list[str]) -> str:
    # /s keeps cmd.exe from stripping quotes inside the command, so paths with
    # spaces or parentheses reach the script intact.
    inner = subprocess.list2cmdline([str(script), *arguments])
    return f'cmd.exe /d /s /c "{inner}"'


def run_install(
    iso: Path, toolkit: Path, environment: dict[str, str], root: Path = ROOT
) -> int:
    command = batch_command(
        root / "install.bat", ["--iso", str(iso), "--toolkit", str(toolkit)]
    )
    tracker = InstallProgress()
    process = subprocess.Popen(
        command, cwd=root, env=environment, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    assert process.stdout is not None
    for raw in process.stdout:
        text = raw.decode("mbcs" if os.name == "nt" else "utf-8", "replace")
        text = text.rstrip("\r\n")
        print(text, flush=True)
        tracker.line(text)
    return process.wait()


def prepare(args: argparse.Namespace) -> int:
    config = load_config()
    preset = PRESETS[0]
    progress(0.01, "Checking your disc image")
    require_ascii(ROOT, "The game's folder", 2)
    iso = unpack_image(args.game, int(config["disc"]["iso_size"]))

    if is_current_build(preset):
        progress(1, "Already built")
        return 0
    stamp = install_directory(preset) / STAMP_NAME
    stamp.unlink(missing_ok=True)

    progress(0.02, "Getting the psp-recomp toolkit")
    if args.toolkit is not None:
        toolkit = args.toolkit.absolute()
    else:
        toolkit = ensure_toolkit(
            config["runtime"]["repository"], config["runtime"]["commit"]
        )

    environment = os.environ.copy()
    data = data_directory(args)
    if data is not None:
        require_ascii(data, "The game's data folder", 2)
        environment["PSP_RECOMP_CODEGEN_CACHE"] = str(
            data / "cache" / "psp-recomp-codegen"
        )
    result = run_install(iso, toolkit, environment)
    if result != 0:
        print(f"Setup stopped: install.bat exited with code {result}.")
        print(REQUIREMENTS)
        return result

    stamp.write_text(
        json.dumps(expected_stamp(preset), indent=2) + "\n", encoding="utf-8"
    )
    progress(1, "Ready to play")
    return 0


def unpack_image(source: Path, expected_size: int) -> Path:
    """Return the ISO to build from, converting a CSO or CHD image once."""
    source = source.absolute()
    if not source.is_file():
        raise LauncherError(f"The disc image was not found: {source}", 2)
    if not prepare_iso.is_compressed(source):
        return check_iso(source, expected_size, 2)
    reported = [-1]

    def report(done: int, total: int) -> None:
        percent = done * 100 // max(total, 1)
        if percent != reported[0]:
            reported[0] = percent
            progress(0.01 + 0.01 * percent / 100,
                     f"Unpacking your disc image ({percent}%)")

    try:
        iso = prepare_iso.prepare_compressed(
            source, expected_size, prepare_iso.CONVERTED_ISO, report
        )
    except ValueError as error:
        raise LauncherError(f"Your disc image couldn't be unpacked: {error}", 2)
    return check_iso(iso, expected_size, 2)


def playable_iso(source: Path, expected_size: int) -> Path:
    """Return the ISO the game reads: the image itself, or its converted ISO."""
    source = source.absolute()
    if source.is_file() and prepare_iso.is_compressed(source):
        converted = prepare_iso.converted_iso(source, expected_size)
        if converted is None:
            raise LauncherError(
                "This CSO or CHD image hasn't been unpacked yet. Set the game "
                "up again.",
                PLAY_NOT_BUILT,
            )
        source = converted
    return check_iso(source, expected_size, PLAY_ISO_UNUSABLE)


def data_directory(args: argparse.Namespace) -> Path | None:
    if args.data is not None:
        return args.data.absolute()
    value = os.environ.get("RECOMPLAUNCHER_DATA")
    return Path(value) if value else None


def rotate_logs(logs: Path) -> Path:
    logs.mkdir(parents=True, exist_ok=True)
    current = logs / LOG_NAME
    stem, suffix = current.stem, current.suffix
    for index in range(KEPT_LOGS, 0, -1):
        older = logs / f"{stem}.{index}{suffix}"
        newer = current if index == 1 else logs / f"{stem}.{index - 1}{suffix}"
        if newer.exists():
            os.replace(newer, older)
    return current


def play(args: argparse.Namespace, extra: list[str]) -> int:
    config = load_config()
    installation = next(
        (
            install_directory(preset)
            for preset in PRESETS
            if is_installed(install_directory(preset))
        ),
        None,
    )
    if installation is None:
        raise LauncherError(
            "Metal Gear Acid 2 has not been built yet. Set it up first.",
            PLAY_NOT_BUILT,
        )
    require_ascii(installation, "The game's folder", PLAY_PATH_UNSUPPORTED)
    iso = playable_iso(args.game, int(config["disc"]["iso_size"]))
    data = data_directory(args)
    if data is None:
        raise LauncherError("Pass --data DIR for the game's settings and saves.", 2)
    require_ascii(data, "The game's data folder", PLAY_PATH_UNSUPPORTED)

    memstick = data / "memstick"
    memstick.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment["PSP_ISO"] = str(iso)
    environment["SR_MEMSTICK"] = str(memstick)
    environment["SR_SETTINGS_DIR"] = str(data)
    # SR_SETTINGS_DIR also moves where the runtime looks for its own files,
    # so point those back at the installation and keep caches in cache.
    environment["PSP_VFPU_TABLES"] = str(installation / "assets" / "vfpu")
    environment["SR_FONTDIR"] = str(installation / "font")
    environment["SR_D3D12_PSO_KEYS"] = str(data / "cache" / "pso_keys.bin")
    environment.setdefault("SR_MODULE_LOG", "1")
    if args.window is not None:
        environment["SR_FULLSCREEN"] = "1" if args.window == "fullscreen" else "0"

    mode = "--configure" if args.show_setup else "--play"
    log_path = rotate_logs(data / "logs")
    print(f"Game output: {log_path}", flush=True)
    with log_path.open("wb") as log:
        process = subprocess.Popen(
            [str(installation / "mga2.exe"), mode, *extra],
            cwd=installation, env=environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT,
        )
        return process.wait()


def parse_args(argv: list[str]) -> tuple[argparse.Namespace, list[str]]:
    parser = argparse.ArgumentParser(
        prog="play.bat",
        description="Set up or start Metal Gear Acid 2 without windows, "
        "for game launchers.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--prepare", action="store_true",
        help="build and install the game, printing progress lines",
    )
    mode.add_argument(
        "--play", action="store_true",
        help="start the installed game with its saved settings",
    )
    parser.add_argument(
        "--game", type=Path, required=True, metavar="ISO",
        help="the supported ULUS-10077 USA v1.00 disc image (ISO, CSO or CHD)",
    )
    parser.add_argument(
        "--data", type=Path, metavar="DIR",
        help="the folder for settings, saves, caches and logs "
        "(default: RECOMPLAUNCHER_DATA)",
    )
    parser.add_argument(
        "--toolkit", type=Path, metavar="PATH",
        help="with --prepare: an existing psp-recomp checkout to build with",
    )
    parser.add_argument(
        "--show-setup", action="store_true",
        help="with --play: open the game's graphics and controller windows first",
    )
    window = parser.add_mutually_exclusive_group()
    window.add_argument(
        "--fullscreen", dest="window", action="store_const", const="fullscreen",
        help="with --play: always start full screen",
    )
    window.add_argument(
        "--windowed", dest="window", action="store_const", const="windowed",
        help="with --play: always start in a window",
    )
    args, extra = parser.parse_known_args(argv)
    if args.prepare and (extra or args.show_setup or args.window):
        parser.error(
            "--show-setup, --fullscreen, --windowed and game options are only "
            "used with --play"
        )
    if args.play and args.toolkit is not None:
        parser.error("--toolkit is only used with --prepare")
    return args, extra


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    args, extra = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return prepare(args) if args.prepare else play(args, extra)
    except LauncherError as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return error.code
    except (KeyError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
