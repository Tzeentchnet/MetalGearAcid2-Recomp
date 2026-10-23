#!/usr/bin/env python3
"""Analyze and generate cached native C for Metal Gear Acid 2's main PRX."""

import argparse
import os
from pathlib import Path
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLKIT = Path(r"D:\Github\psp-recomp")


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--toolkit",
        type=Path,
        default=Path(os.environ.get("PSP_RECOMP_DIR", DEFAULT_TOOLKIT)),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "build" / "mga2" / "gen",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="emit one large C file instead of split translation units",
    )
    return parser.parse_args(argv[1:])


def run(command, *, env, stderr=None):
    command_text = [os.fspath(part) for part in command]
    print(f"> {subprocess.list2cmdline(command_text)}")
    return subprocess.run(
        command_text,
        check=False,
        env=env,
        stderr=stderr,
    )


def default_private_path(name, leaf):
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "psp-recomp" / name / leaf


def prepare_environment():
    env = dict(os.environ)
    if not env.get("PSP_RECOMP_CODEGEN_CACHE"):
        path = default_private_path("codegen-cache", "")
        if path is not None:
            env["PSP_RECOMP_CODEGEN_CACHE"] = os.fspath(path)
    if not env.get("PSP_RECOMP_FUNCTION_CATALOG"):
        path = default_private_path("function-catalog", "catalog.toml")
        if path is not None:
            env["PSP_RECOMP_FUNCTION_CATALOG"] = os.fspath(path)
    return env


def generate_prx(
    *,
    tools,
    codegen,
    prx,
    module,
    out_dir,
    stem,
    env,
    single,
    image_name=None,
):
    if not prx.is_file():
        print(
            f"ERROR: missing {prx}; run tools\\mga2\\extract.py first",
            file=sys.stderr,
        )
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    symbol_prefix = module.get("symbol_prefix")
    if symbol_prefix:
        matches_name = f"{stem}_function_matches.toml"
        symbols_name = f"{stem}_function_symbols.csv"
        imports_name = f"{stem}_imports.toml"
        functions_name = f"{stem}_functions.toml"
        log_name = f"{stem}_codegen.log"
    else:
        matches_name = "function_matches.toml"
        symbols_name = "function_symbols.csv"
        imports_name = "mga2_imports.toml"
        functions_name = "mga2_functions.toml"
        log_name = "codegen.log"

    stubs = out_dir / "stubs.txt"
    stubs.unlink(missing_ok=True)
    log_path = out_dir / log_name

    commands = [
        [
            sys.executable,
            tools / "function_catalog.py",
            "match",
            prx,
            "--base",
            f"{module['base']:#x}",
            "--output",
            out_dir / matches_name,
            "--symbols",
            out_dir / symbols_name,
        ],
        [
            sys.executable,
            tools / "imports.py",
            prx,
            f"{module['base']:#x}",
            f"--toml={out_dir / imports_name}",
        ],
        [
            sys.executable,
            tools / "analyze.py",
            prx,
            f"--base={module['base']:#x}",
            f"--toml={out_dir / functions_name}",
            "--quiet",
        ],
    ]
    if image_name:
        commands.insert(
            1,
            [
                sys.executable,
                tools / "prxload.py",
                prx,
                f"{module['base']:#x}",
                f"--out={out_dir / image_name}",
            ],
        )
    for command in commands:
        result = run(command, env=env)
        if result.returncode:
            return result.returncode

    codegen_command = [
        sys.executable,
        codegen,
        prx,
        out_dir / f"{stem}_recomp.c",
        f"--base={module['base']:#x}",
    ]
    codegen_command.extend(
        f"--function-entry={address:#x}"
        for address in module.get("function_entries", [])
    )
    if symbol_prefix:
        codegen_command.extend(
            [
                f"--symbol-prefix={symbol_prefix}",
                "--runtime-jal",
                "--verify-runtime-code",
            ]
        )
    if not single:
        codegen_command.append("--split")
    with log_path.open("w", encoding="utf-8") as log:
        result = run(codegen_command, env=env, stderr=log)
    print(log_path.read_text(encoding="utf-8"), end="")
    if result.returncode:
        return result.returncode
    if stubs.exists():
        print(
            f"ERROR: trapping stubs were emitted; see {stubs}",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv):
    args = parse_args(argv)
    config_path = ROOT / "config" / "mga2.toml"
    with config_path.open("rb") as stream:
        config = tomllib.load(stream)

    tools = args.toolkit / "tools"
    codegen = tools / "codegen.py"
    if not codegen.is_file():
        print(
            f"ERROR: psp-recomp tools were not found under {args.toolkit}",
            file=sys.stderr,
        )
        return 1

    env = prepare_environment()
    disc_dir = ROOT / "build" / "mga2" / "disc"
    main_module = config["module"]
    result = generate_prx(
        tools=tools,
        codegen=codegen,
        prx=disc_dir / Path(main_module["file"]),
        module=main_module,
        out_dir=args.out,
        stem="mga2",
        env=env,
        single=args.single,
        image_name="mga2_image.bin",
    )
    if result:
        return result

    for module in config.get("native_module", []):
        symbol_prefix = module["symbol_prefix"]
        print(f"generating native module {symbol_prefix} ({module['file']})")
        result = generate_prx(
            tools=tools,
            codegen=codegen,
            prx=disc_dir / Path(module["file"]),
            module=module,
            out_dir=args.out / "modules" / symbol_prefix,
            stem=symbol_prefix,
            env=env,
            single=args.single,
        )
        if result:
            return result
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
