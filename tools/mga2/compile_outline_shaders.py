#!/usr/bin/env python3
"""Rebuild or check the title's shader assets against the patched runtime."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import runpy
import sys
import tomllib

from prepare_runtime import verify
from toolkit_identity import identify_toolkit


ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "tools" / "mga2" / "runtime"


def decode_include(path: Path, word_size: int) -> bytes:
    text = path.read_text(encoding="ascii")
    start = text.index("{")
    end = text.index("}", start)
    body = text[start + 1 : end]
    tokens = re.findall(r"0x[0-9a-fA-F]+", body)
    if not tokens or re.sub(r"0x[0-9a-fA-F]+|[\s,]", "", body):
        raise ValueError(f"{path}: invalid shader initializer")
    try:
        return b"".join(int(token, 16).to_bytes(word_size, "little") for token in tokens)
    except OverflowError as error:
        raise ValueError(f"{path}: shader initializer value is out of range") from error


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolkit", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--dxc", help="path to dxc")
    parser.add_argument("--glslang", help="path to glslangValidator")
    parser.add_argument(
        "--write", action="store_true",
        help="replace generated assets instead of checking them",
    )
    args = parser.parse_args(argv)
    try:
        with (ROOT / "config" / "mga2.toml").open("rb") as stream:
            config = tomllib.load(stream)
        identify_toolkit(args.toolkit, config["runtime"]["commit"])
        verify(args.overlay, ASSETS / "outline.patch", ASSETS)
        d3d = runpy.run_path(str(args.toolkit / "tools" / "compile_d3d12_shaders.py"))
        vulkan = runpy.run_path(str(args.toolkit / "tools" / "compile_vulkan_shaders.py"))
        dxc = d3d["find_dxc"](args.dxc)
        glslang = vulkan["find_glslang"](args.glslang)
        d3d_source = args.overlay / "src" / "rt" / "gpu_d3d12" / "shaders" / "psp_ps.hlsl"
        vk_source = args.overlay / "src" / "rt" / "gpu_sdl3vk" / "shaders" / "psp.frag"
        generated = []
        for entry, name in (("main", "psp_ps.inc"), ("main_direct", "psp_ps_direct.inc")):
            data = d3d["compile_shader"](dxc, d3d_source, "ps_6_0", entry)
            generated.append((
                ASSETS / name, 1, data,
                d3d["render_include"](d3d_source, "ps_6_0", entry, data),
            ))
        data = vulkan["compile_shader"](glslang, vk_source, "frag")
        generated.append((
            ASSETS / "psp_frag.inc", 4, data,
            vulkan["render_include"](vk_source, "frag", data),
        ))
        for path, word_size, data, text in generated:
            if args.write:
                path.write_text(text, encoding="ascii", newline="\n")
                print(f"wrote {path}")
            elif decode_include(path, word_size) != data:
                raise ValueError(f"stale generated shader: {path}")
            else:
                print(f"verified {path}")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
