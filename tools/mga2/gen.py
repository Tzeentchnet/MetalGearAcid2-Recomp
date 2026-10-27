#!/usr/bin/env python3
"""Analyze and generate cached native C for Metal Gear Acid 2's main PRX."""

import argparse
import filecmp
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib

from iso9660 import sha1_file
from toolkit_identity import IDENTITY_FILE, identify_toolkit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TOOLKIT = ROOT.parent / "psp-recomp"
SOURCE_MANIFEST = "mga2_generated_sources.txt"


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
        "--allow-unsupported-toolkit",
        action="store_true",
        help="allow a modified, unpinned, or non-Git toolkit for development",
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


def default_local_path(name, leaf):
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        return None
    return Path(local_app_data) / "psp-recomp" / name / leaf


def prepare_environment():
    env = dict(os.environ)
    if not env.get("PSP_RECOMP_CODEGEN_CACHE"):
        path = default_local_path("codegen-cache", "")
        if path is not None:
            env["PSP_RECOMP_CODEGEN_CACHE"] = os.fspath(path)
    if not env.get("PSP_RECOMP_FUNCTION_CATALOG"):
        path = default_local_path("function-catalog", "catalog.toml")
        if path is not None and path.is_file():
            env["PSP_RECOMP_FUNCTION_CATALOG"] = os.fspath(path)
    return env


def resolve_function_catalog(tools, env):
    configured = env.get("PSP_RECOMP_FUNCTION_CATALOG")
    if configured == "0":
        return None, False
    if configured:
        return Path(os.path.expandvars(configured)).expanduser(), True

    default = tools.parent / "assets" / "functions" / "catalog.toml"
    return (default, False) if default.is_file() else (None, False)


def verify_prx(prx, expected_sha1):
    if not prx.is_file():
        raise ValueError(f"missing {prx}; run tools\\mga2\\extract.py first")
    actual_sha1 = sha1_file(prx)
    if actual_sha1 != expected_sha1:
        raise ValueError(
            f"SHA-1 mismatch for {prx}: {actual_sha1} != {expected_sha1}; "
            "rerun tools\\mga2\\extract.py"
        )


def generate_prx(
    *,
    tools,
    codegen,
    prx,
    module,
    out_dir,
    stem,
    env,
    expected_sha1,
    image_name=None,
):
    verify_prx(prx, expected_sha1)

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

    catalog_path, catalog_required = resolve_function_catalog(tools, env)
    if catalog_path is not None and not catalog_path.is_file():
        if catalog_required:
            print(
                "ERROR: PSP_RECOMP_FUNCTION_CATALOG does not exist: "
                f"{catalog_path}",
                file=sys.stderr,
            )
            return 1
        catalog_path = None

    commands = []
    if catalog_path is not None:
        commands.append([
            sys.executable,
            tools / "function_catalog.py",
            "match",
            prx,
            "--base",
            f"{module['base']:#x}",
            "--catalog",
            catalog_path,
            "--output",
            out_dir / matches_name,
            "--symbols",
            out_dir / symbols_name,
        ])
    else:
        (out_dir / matches_name).unlink(missing_ok=True)
        (out_dir / symbols_name).unlink(missing_ok=True)
        print(f"function catalog unavailable; skipping identity match for {stem}")

    if image_name:
        commands.append(
            [
                sys.executable,
                tools / "prxload.py",
                prx,
                f"{module['base']:#x}",
                f"--out={out_dir / image_name}",
            ]
        )
    commands.extend([
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
    ])
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
    overrides = module.get("overrides")
    if overrides:
        overrides_path = ROOT / overrides
        if not overrides_path.is_file():
            print(
                f"ERROR: missing codegen overrides {overrides_path}",
                file=sys.stderr,
            )
            return 1
        codegen_command.append(f"--overrides={overrides_path}")
    if symbol_prefix:
        codegen_command.extend(
            [
                f"--symbol-prefix={symbol_prefix}",
                "--runtime-jal",
                "--verify-runtime-code",
            ]
        )
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


def collect_sources(staging, modules):
    sources = []
    for relative_dir, stem in modules:
        if not re.fullmatch(r"[A-Za-z0-9_]+", stem):
            raise ValueError(f"invalid generated module prefix: {stem}")
        directory = staging / relative_dir
        header = directory / f"{stem}_recomp.h"
        register = directory / f"{stem}_recomp_register.c"
        chunks = sorted(directory.glob(f"{stem}_recomp_[0-9][0-9][0-9].c"))
        if not header.is_file() or not register.is_file() or not chunks:
            raise ValueError(f"incomplete split generation for {stem} in {directory}")
        sources.extend(
            path.relative_to(staging).as_posix()
            for path in [*chunks, register]
        )
    if not (staging / "mga2_image.bin").is_file():
        raise ValueError("generation did not produce mga2_image.bin")
    return sources


def publish_generation(staging, output, sources):
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / SOURCE_MANIFEST
    manifest.unlink(missing_ok=True)
    for path in sorted(path for path in staging.rglob("*") if path.is_file()):
        destination = output / path.relative_to(staging)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_file() and filecmp.cmp(path, destination, shallow=False):
            continue
        os.replace(path, destination)
    temporary_manifest = output / f".{SOURCE_MANIFEST}.tmp"
    temporary_manifest.write_text("\n".join(sources) + "\n", encoding="utf-8")
    os.replace(temporary_manifest, manifest)


def generate(args):
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

    identity = identify_toolkit(
        args.toolkit,
        config["runtime"]["commit"],
        allow_unsupported=args.allow_unsupported_toolkit,
    )
    if identity["source_sha256"] is not None:
        print(
            "WARNING: using an unsupported or modified psp-recomp toolkit; "
            "this is a development build, not the validated release.",
            file=sys.stderr,
        )
    env = prepare_environment()
    disc_dir = ROOT / "build" / "mga2" / "disc"
    main_module = config["module"]
    main_hash = config["disc"]["files"][main_module["file"]]
    native_modules = config.get("native_module", [])
    verify_prx(disc_dir / Path(main_module["file"]), main_hash)
    prefixes = set()
    for module in native_modules:
        prefix = module["symbol_prefix"]
        if not re.fullmatch(r"[A-Za-z0-9_]+", prefix) or prefix in prefixes:
            raise ValueError(f"invalid or duplicate generated module prefix: {prefix}")
        prefixes.add(prefix)
        verify_prx(disc_dir / Path(module["file"]), module["sha1"])

    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".mga2-gen-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "gen"
        result = generate_prx(
            tools=tools,
            codegen=codegen,
            prx=disc_dir / Path(main_module["file"]),
            module=main_module,
            out_dir=staging,
            stem="mga2",
            env=env,
            expected_sha1=main_hash,
            image_name="mga2_image.bin",
        )
        if result:
            return result
        generated_modules = [(Path(), "mga2")]
        for module in native_modules:
            symbol_prefix = module["symbol_prefix"]
            print(f"generating native module {symbol_prefix} ({module['file']})")
            relative_dir = Path("modules") / symbol_prefix
            result = generate_prx(
                tools=tools,
                codegen=codegen,
                prx=disc_dir / Path(module["file"]),
                module=module,
                out_dir=staging / relative_dir,
                stem=symbol_prefix,
                env=env,
                expected_sha1=module["sha1"],
            )
            if result:
                return result
            generated_modules.append((relative_dir, symbol_prefix))
        sources = collect_sources(staging, generated_modules)
        if identify_toolkit(
            args.toolkit,
            config["runtime"]["commit"],
            allow_unsupported=args.allow_unsupported_toolkit,
        ) != identity:
            raise ValueError("toolkit changed during generation; retry")
        (staging / IDENTITY_FILE).write_text(
            json.dumps(identity, indent=2) + "\n", encoding="utf-8"
        )
        publish_generation(staging, output, sources)
        print(f"wrote {output / SOURCE_MANIFEST} ({len(sources)} sources)")
    return 0


def main(argv):
    args = parse_args(argv)
    try:
        return generate(args)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
