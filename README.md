# Metal Gear Acid 2 Recomp

Source-only Windows static recompilation work for **Metal Gear Acid 2
(ULUS-10077 v1.00)** using the public
[`psp-recomp`](https://github.com/Tzeentchnet/psp-recomp) toolkit.

No game executable, generated game C, disc data, trace, save, or capture should
be committed. Supply your own supported USA ISO.

> [!WARNING]
> **v0.1.0 is a prerelease, not a full-game compatibility claim.** The opening
> tutorial and selected save-based scenes are validated, but secure save
> creation/reload, media behavior, full playthroughs, and soak testing remain
> incomplete. Review [`docs/STATUS.md`](docs/STATUS.md) before building.

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

For the highest-quality 4K path:

1. Select **D3D12 hardware** or **Vulkan**.
2. Select **8x (3840x2176)** internal resolution.
3. Select **2x xBRZ** or **3x xBRZ** texture upscaling.
4. When using D3D12, select **Full resolution (best quality)** shading.
5. Optionally select **SMAA 1x High** for additional edge smoothing on D3D12.
6. Press **F11** in the game window for borderless desktop fullscreen.

The PSP display is 480:272, so 8x is 3840x2176 rather than exactly 3840x2160.
Presentation preserves that aspect ratio and adds a few black pixels on a UHD
display instead of stretching the image.

| Renderer | Internal GE resolution | Texture scaling | Post-process AA | Role |
|---|---|---|---|---|
| D3D12 | 1x-8x | 1x-5x xBRZ | Off / SMAA 1x High | Recommended high-resolution renderer |
| Vulkan | 1x-8x | 1x-5x xBRZ | None | Validated high-resolution hardware renderer |
| Software | Native PSP resolution | None | None | Pixel-exact reference baseline |

> [!NOTE]
> Vulkan currently trails D3D12 in performance. For smoother gameplay, use a
> lower internal resolution and texture-scaling factor than the 4K settings
> above, then increase them only when your system has enough performance
> headroom.

xBRZ scales decoded game textures before hardware upload. It does not scale
framebuffer/render-target textures; the separate internal-resolution setting
scales those resources in both hardware renderers. Higher factors can use
substantially more GPU memory. The D3D12 **Balanced** shading option uses
variable-rate shading on supported GPUs; **Full resolution** shades every
internal-resolution fragment and is the appropriate D3D12 setting for 4K
screenshots.

## Startup shortcut

Enable **Skip startup sequence (go directly to main menu)** in the launcher
to execute the normal memory-stick checks and title initialization at turbo
speed, then transition directly to the menu without playing the opening logos.
The option is disabled by default and does not bypass save initialization.

Settings are persisted in `graphics.ini` beside the executable. The equivalent
keys are `renderer`, `internal_resolution`, `texture_scale`, and
`d3d12_full_rate`; `anti_aliasing` accepts `off` or `smaa`, and
`skip_startup` accepts `off` or `on`.

## Requirements

- Windows 10/11 x64
- Python 3.11 or newer
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools with clang-cl and a Windows SDK
- Vulkan SDK when building the default Vulkan backend. A standard
  `C:\VulkanSDK\<version>` install is detected automatically.
- `psp-recomp` commit
  `b56ff30ef5997b9f168209df8c33156e82402e7b`, pinned in
  [`config/mga2.toml`](config/mga2.toml). A sibling checkout at
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

## Extract and generate

```powershell
python tools\mga2\extract.py ".\Metal Gear Acid 2 (USA).iso"
python tools\mga2\gen.py
```

When a function catalog is available, the generator records matches as
identity evidence. It always relocates each image, maps imports, records the
function inventories, and emits split C; the optional exact cache accelerates
unchanged reruns. The main module is written beneath
`build\mga2\gen`; configured native PRXs use unique symbol prefixes beneath
`build\mga2\gen\modules`. Dynamic tables use runtime JAL resolution and verify
guest function bytes before native dispatch. Normalized catalog matches do not
authorize code reuse.

## Build

From a Visual Studio x64 developer shell:

```powershell
cmake --preset clang-cl
cmake --build --preset clang-cl --target mga2_driver
```

This builds D3D12, Vulkan, and software into one executable. The deterministic
software-only baseline remains available as a separate preset:

```powershell
cmake --preset clang-cl-software
cmake --build --preset clang-cl-software --target mga2_driver
```

Ninja builds are incremental. After changing a runtime source file, rerun the
same targeted `cmake --build` command; do not regenerate game code or delete the
build tree. Changes to generated-code compiler options necessarily rebuild all
361 generated translation units, so batch those changes and measure the
resulting executable before changing the build profile again.

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