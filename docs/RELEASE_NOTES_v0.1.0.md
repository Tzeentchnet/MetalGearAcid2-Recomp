# Metal Gear Acid 2 Recomp v0.1.0

`v0.1.0` is a source-only prerelease for the USA v1.00 release of Metal Gear
Acid 2 (`ULUS-10077`). It is intended for testing and development, not as a
full-game compatibility claim.

## Distribution policy

The release contains source code, configuration, documentation, and
reproducible build tooling only. It does not contain an executable, generated
guest C, extracted PRXs, disc data, saves, traces, or framebuffer captures.
Users must supply their own legally obtained disc image. The installer verifies
the exact supported ISO before extracting or generating anything locally.

## Highlights

- Combined D3D12, Vulkan, and software-reference launcher.
- 1x-8x internal rendering plus optional 2x-5x xBRZ texture scaling.
- Optional D3D12 SMAA 1x High post-process anti-aliasing.
- Optional **Skip startup sequence** setting that retains normal memory-stick
  and title initialization before entering the main menu.
- Controller configuration, XAudio2 output, fullscreen presentation, secure
  savedata loading/import, and deterministic validation tools.
- Public build defaults use a sibling `psp-recomp` checkout and no longer
  require a private function catalog or pre-populated code-generation cache.

## Validated scope

- Exact ULUS-10077 v1.00 input verification and extraction.
- Clean native generation with no trapping stubs.
- Main-menu and scripted New Game entry.
- Opening movement tutorial.
- Authentic Acid 1 import and selected Acid 2 save-based scenes.
- D3D12 and Vulkan high-resolution visual routes.
- Software renderer as the pixel-reference baseline.

Detailed evidence is in [STATUS.md](STATUS.md) and
[BENCHMARKS.md](BENCHMARKS.md).

## Known limitations

- Secure save creation and reload have not been validated.
- Full gameplay, all media paths, and long soak runs have not been completed.
- Arena and some later scenes remain below the fixed-quality 60 FPS target.
- Only the USA v1.00 ISO with the documented SHA-1 is supported.
- Windows 10/11 x64 and the exact runtime revision in
  [`config/mga2.toml`](../config/mga2.toml) are required.

## Building

Clone this repository and `Tzeentchnet/psp-recomp` beside each other, check out
the runtime commit pinned in [`config/mga2.toml`](../config/mga2.toml), and
follow the [README](../README.md). `install.bat` verifies the disc, generates
native code locally, builds the selected renderer set, and stages a runnable
local installation.

## License

Project source is licensed under
[GPL-2.0-or-later](../LICENSE). Metal Gear Acid 2, its executable code, media,
and assets are not included and remain the property of their respective rights
holders.
