# Metal Gear Acid 2 Recomp

Source-only Windows static recompilation work for **Metal Gear Acid 2
(ULUS-10077 v1.00)** using the public
[`psp-recomp`](https://github.com/Tzeentchnet/psp-recomp) toolkit.

No game executable, generated game C, disc data, trace, save, or capture should
be committed. Supply your own supported USA ISO.

> [!WARNING]
> **This is a testing and evaluation release, and I do not make a full-game compatibility claim.** 

> [!NOTE]
> **Why isn't there just an .exe to download?** Two reasons. First, safety:
> please don't download random .exe files from the internet, even from
> GitHub releases, including this one if it ever shows up! It's just good
> practice to be careful about what you run on your computer. Second, this
> project does not distribute copyrighted Metal Gear Acid 2 content. Instead,
> you build the program from source and use your own legally obtained disc
> image, so game data remains on your computer.

## Supported input

| Property | Value |
|---|---|
| Disc ID | `ULUS10077` |
| Version | USA v1.00 |
| ISO size | `917,307,392` bytes |
| ISO SHA-1 | `87cebe80a93c4231bdbab26ad630c6d8e2fddab5` |
| Main module | `PSP_GAME/SYSDIR/BOOT.BIN` |
| Main entry | `0x08804128` |

`EBOOT.BIN` is encrypted, but the same disc includes the plaintext main ELF as
`BOOT.BIN`. The project verifies both files and uses only the plaintext copy
for static translation.


## Graphics quality

The combined launcher offers **Automatic**, **D3D12 hardware**,
**Software reference**, and **Vulkan**. Automatic selects D3D12 when it is
compiled in.

Start at a moderate internal resolution such as 3x or 4x and lower it if
gameplay or audio slows down. For a higher-quality 4K path, if your GPU has
enough headroom:

1. Select **D3D12 hardware** or **Vulkan**.
2. Select **8x (3840x2176)** internal resolution.
3. Select **2x xBRZ** or **3x xBRZ** texture upscaling.
4. When using D3D12, select **Full resolution (best quality)** shading.
5. Optionally select **SMAA 1x High** for additional edge smoothing on D3D12.
6. Choose a **Character outlines** mode as described below.
7. Press **F11** in the game window for borderless desktop fullscreen.

The PSP display is 480:272, so 8x is 3840x2176 rather than exactly 3840x2160.
Presentation preserves that aspect ratio and adds a few black pixels on a UHD
display instead of stretching the image.

| Renderer | Internal GE resolution | Texture scaling | Post-process AA | Role |
|---|---|---|---|---|
| D3D12 | 1x-8x | 1x-5x xBRZ | Off / SMAA 1x High | Recommended high-resolution renderer |
| Vulkan | 1x-8x | 1x-5x xBRZ | None | Validated high-resolution hardware renderer |
| Software | Native PSP resolution | None | None | Pixel-exact reference baseline |

> [!NOTE]
> For smoother gameplay, use a lower internal resolution and texture-scaling
> factor than the 4K settings above, then increase them only when your system
> has enough performance headroom. Higher internal resolution sharpens geometry
> and can show more detail from your high-resolution card replacements. It
> cannot restore detail missing from the original low-resolution textures.

xBRZ scales decoded game textures before hardware upload. It does not scale
framebuffer/render-target textures; the separate internal-resolution setting
scales those resources in both hardware renderers. Higher factors can use
substantially more GPU memory. The D3D12 **Balanced** shading option uses
variable-rate shading on supported GPUs; **Full resolution** shades every
internal-resolution fragment and is the appropriate D3D12 setting for 4K
screenshots.

SMAA smooths the final image, but some character outlines can still look
blocky at high resolutions because the game generates them from framebuffer
feedback. xBRZ does not affect those framebuffer textures. The launcher
offers three **Character outlines** modes:

- **Original** (default) retains the existing rendering.
- **Sharper** keeps detected outlines and samples their feedback at the
  internal resolution. It requires D3D12 or Vulkan and has no visual effect
  at native 1x resolution.
- **Off** hides detected character outlines and also works with the software
  renderer.

These are targeted enhancements, not a guarantee that every outline in every
scene is detected. They have been tested in selected tutorial and Arena
scenes; see the
[outline investigation](docs/FINDINGS.md#mga2-f-020---character-outline-pixelation).

## Card illustration mods

You can replace card illustrations with PNG files without modifying the ISO.
Generate templates from your own supported USA disc, specifying a **new**
`mods\cards` directory beside the installed `mga2.exe`:

```powershell
python tools\mga2\export_cards.py "C:\Games\Metal Gear Acid 2 (USA).iso" --out "C:\Games\MGA2\mods\cards"
```

The exporter verifies the ISO and creates `catalog.txt` and a `templates`
folder. It refuses to overwrite an existing card folder. To replace an
illustration:

1. Browse the PNGs in `mods\cards\templates` to find the image.
2. Copy it into `mods\cards`, keeping its filename, and edit that copy.
3. Restart the game. Remove the copy to restore the original illustration.

The PNG must have the template's dimensions or the same whole-number
multiple on both axes, up to 8x. For example, a 112x72 template accepts a
448x288 replacement. Transparent PNGs are supported, subject to the game's
normal transparency and color effects. The game keeps the original card
geometry and on-screen size. D3D12 and Vulkan retain the additional image
detail; use a higher internal resolution to see it. The software renderer
uses a native-resolution version. Decoded replacements are limited to
512 MiB in total; images that exceed the limit are reported and not loaded.

The exported entries include masks and other resources, not just unique
cards. Filenames identify resource entries rather than friendly card names.
This first version is limited to the card-illustration packs and tested scenes;
other UI artwork, portraits, and vector images are not replaced. Invalid PNGs,
unexpected filenames, and catalog errors are reported in the launch console.

## Startup shortcut

Enable **Skip startup sequence (go directly to main menu)** in the launcher
to run the normal startup sequence at turbo speed and automatically press
START to reach the main menu. Opening logos may appear briefly. The option is
disabled by default and does not bypass memory-stick or title initialization.

## Settings

Settings are persisted in `graphics.ini` beside the executable. The equivalent
keys are `renderer`, `internal_resolution`, `texture_scale`, and
`d3d12_full_rate`; `anti_aliasing` accepts `off` or `smaa`, and
`skip_startup` accepts `off` or `on`. `outlines` accepts `original`, `sharper`,
or `off`.

## Requirements

- Windows 10/11 x64
- Python 3.11 or newer
- Git, to verify the toolkit checkout and its working-tree state
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools with clang-cl and a Windows SDK
- Vulkan SDK when building the default Vulkan backend. A standard
  `C:\VulkanSDK\<version>` install is detected automatically.
- `psp-recomp` commit
  `b56ff30ef5997b9f168209df8c33156e82402e7b`, pinned in
  [`config/mga2.toml`](config/mga2.toml), with no tracked changes or
  non-ignored untracked files. A sibling checkout at
  `..\psp-recomp` is used by default; `PSP_RECOMP_DIR`, CMake's
  `PSP_RECOMP_DIR`, and generator/installer `--toolkit` options can override
  it.

The default preset downloads the pinned SDL3 3.2.20 VC development package
when SDL3 is not already discoverable by CMake. Set `MGA2_FETCH_SDL3=OFF` and
provide `SDL3_DIR` to require a local package instead.

The generator can use `PSP_RECOMP_CODEGEN_CACHE` to accelerate repeat runs;
the default cache below `%LOCALAPPDATA%\psp-recomp` is created on demand.
`PSP_RECOMP_FUNCTION_CATALOG` is optional identity evidence and is never
required for code generation. Set it to `0` to skip matching; any other
explicitly configured catalog path must exist.

## Get the source

Clone this project and the public toolkit beside each other:

```bat
git clone https://github.com/Tzeentchnet/MetalGearAcid2-Recomp.git
git clone https://github.com/Tzeentchnet/psp-recomp.git
cd MetalGearAcid2-Recomp
git -C ..\psp-recomp checkout b56ff30ef5997b9f168209df8c33156e82402e7b
```

The pin is deliberate: generated code, runtime behavior, and project
integration are validated together.

## Quick install

`install.bat` verifies the source requirements, initializes the Visual Studio
x64 environment, verifies and extracts the user-owned ISO, generates the
native code, builds the project, and stages a runnable installation. It checks
prerequisites but does not install system software or copy the ISO.

Place the supported ISO beside the script under its default name, then run
from Command Prompt or double-click:

```bat
install.bat
```

The default hardware build is staged in `out\install\clang-cl`. After
installation, start the game from the project root with:

```bat
play.bat
```

The startup script uses the installed hardware build when available, then
falls back to the software-only installation or an existing developer build.
The installed launcher records the verified ISO's original location and uses
an isolated `memstick` directory inside the installation.

Paths and the renderer set can be overridden:

```bat
install.bat --iso "E:\Games\Metal Gear Acid 2 (USA).iso"
install.bat --toolkit "E:\Source\psp-recomp"
install.bat --install-dir "%LOCALAPPDATA%\Programs\Metal Gear Acid 2"
install.bat --software-only
```

`--software-only` uses the `clang-cl-software` preset and does not require the
Vulkan SDK. Existing `PSP_RECOMP_DIR`, `PSP_RECOMP_CODEGEN_CACHE`, and
`PSP_RECOMP_FUNCTION_CATALOG` values are preserved. The code-generation cache
and function catalog are optional. Run `install.bat --help` for the complete
option summary.

> [!IMPORTANT]
> The installer currently requires an **ASCII-only absolute ISO path**.
> Non-ASCII paths cannot be handled reliably by the Windows launcher and the
> runtime's narrow-character file APIs; the installer rejects them before
> extraction. Move the ISO to a path such as `C:\Games\MGA2.iso`. Full Unicode
> support for project, toolkit, installation, and memory-stick paths has not
> been validated either.

The toolkit revision and clean working tree are checked before generation and
again when configuring and building. For deliberate development with a
modified, unpinned, or non-Git toolkit, pass `--allow-unsupported-toolkit` to
`install.bat` to enable an explicitly unsupported build. Its toolkit source
identity is recorded, and changing its source, tool, or asset trees requires
regeneration. This override is not a validated release configuration.

## Manual development

See the [build and test guide](docs/BUILDING.md) for manual extraction and
generation, building, and testing.

## Run

For normal startup after installation, double-click `play.bat` or run it from
Command Prompt:

```bat
play.bat
```

Pass the supported ISO as the first argument if it has moved since
installation:

```bat
play.bat "E:\Games\Metal Gear Acid 2 (USA).iso"
```

Normal startup opens the graphics and controller launcher before entering the
game. The equivalent manual command for an unstaged developer build is:

```powershell
$env:PSP_ISO = "$PWD\Metal Gear Acid 2 (USA).iso"
$env:SR_MEMSTICK = "$PWD\memstick"
$env:SR_MODULE_LOG = "1"
out\build\clang-cl\mga2.exe --configure
```

The first windowed run opens graphics and controller setup. Save the graphics
settings, then select **Play Game** in the controller window to save the
bindings and start Metal Gear Acid 2. Reopen both dialogs later with:

```powershell
out\build\clang-cl\mga2.exe --configure
```

The configuration launcher starts the game after **Play Game** is selected;
the title-bar close button exits without launching.

Performance benchmarks and Vulkan visual validation are documented in
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

## Release and license

- [`docs/RELEASE_NOTES_v0.1.0.md`](docs/RELEASE_NOTES_v0.1.0.md) summarizes
  the prerelease scope and known limitations.
- [`CHANGELOG.md`](CHANGELOG.md) records user-visible changes.
- This project is licensed under
  [GPL-2.0-or-later](LICENSE), matching the combined `psp-recomp`/PPSSPP
  runtime obligations. Metal Gear Acid 2 and its assets are not included and
  remain the property of their respective rights holders.