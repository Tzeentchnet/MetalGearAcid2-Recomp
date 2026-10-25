# Metal Gear Acid 2 Recomp

Source-only Windows static recompilation work for **Metal Gear Acid 2
(ULUS-10077 v1.00)** using the local `psp-recomp` toolkit.

No game executable, generated game C, disc data, trace, save, or capture should
be committed. Supply your own supported USA ISO.

> [!NOTE]
> **Why isn't there just an .exe to download?** Two reasons. First, safety:
> please don't download random .exe files from the internet, even from
> GitHub releases, including this one if it ever shows up! It's just good
> practice to be careful about what you run on your computer. Second, it's
> the law: this project doesn't own Metal Gear Acid 2, so it's not
> allowed to hand out a ready-to-play build of the game. Instead, you build
> the program yourself from this source code and combine it with a copy of
> the game disc that you already legally own. That way nobody's copyrighted
> game data ever leaves your own computer.

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

1. Select **D3D12 hardware**.
2. Select **8x (3840x2176)** internal resolution.
3. Select **2x xBRZ** or **3x xBRZ** texture upscaling.
4. Select **Full resolution (best quality)** D3D12 shading.
5. Press **F11** in the game window for borderless desktop fullscreen.

The PSP display is 480:272, so 8x is 3840x2176 rather than exactly 3840x2160.
Presentation preserves that aspect ratio and adds a few black pixels on a UHD
display instead of stretching the image.

| Renderer | Internal GE resolution | Texture scaling | Role |
|---|---|---|---|
| D3D12 | 1x-8x | 1x-5x xBRZ | Recommended high-resolution renderer |
| Vulkan | Native 512x272 target | 1x-5x xBRZ | Alternate hardware renderer |
| Software | Native PSP resolution | None | Pixel-exact reference baseline |

xBRZ scales decoded game textures before hardware upload. It does not scale
framebuffer/render-target textures, and higher factors can use substantially
more GPU memory. The D3D12 **Balanced** shading option uses variable-rate
shading on supported GPUs; **Full resolution** shades every internal-resolution
fragment and is the appropriate quality setting for 4K screenshots.

Settings are persisted in `graphics.ini` beside the executable. The equivalent
keys are `renderer`, `internal_resolution`, `texture_scale`, and
`d3d12_full_rate`.

## Requirements

- Windows 10/11 x64
- Python 3.11 or newer
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools with clang-cl and a Windows SDK
- Vulkan SDK when building the default Vulkan backend. A standard
  `C:\VulkanSDK\<version>` install is detected automatically.
- `psp-recomp` commit `b84b880` or newer at `D:\Github\psp-recomp`, or pass
  another `PSP_RECOMP_DIR` to CMake and `--toolkit` to the generator

The default preset downloads the pinned SDL3 3.2.20 VC development package
when SDL3 is not already discoverable by CMake. Set `MGA2_FETCH_SDL3=OFF` and
provide `SDL3_DIR` to require a local package instead.

The generator honors `PSP_RECOMP_CODEGEN_CACHE` and
`PSP_RECOMP_FUNCTION_CATALOG`. When they are unset, it discovers the private
stores below `%LOCALAPPDATA%\psp-recomp`.

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

The startup script uses the installed hardware launcher when available, then
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
`PSP_RECOMP_FUNCTION_CATALOG` values are preserved; otherwise the documented
defaults are used. Run `install.bat --help` for the complete option summary.

## Extract and generate

```powershell
python tools\mga2\extract.py ".\Metal Gear Acid 2 (USA).iso"
python tools\mga2\gen.py
```

The generator runs catalog matching for identity evidence, relocates each
image, maps imports, records the function inventories, and emits split C
through the exact codegen cache. The main module is written beneath
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

The equivalent manual command for an unstaged developer build is:

```powershell
$env:PSP_ISO = "$PWD\Metal Gear Acid 2 (USA).iso"
$env:SR_MEMSTICK = "$PWD\memstick"
$env:SR_MODULE_LOG = "1"
out\build\clang-cl\mga2.exe --boot `
  build\mga2\gen\mga2_image.bin 08804000 08804128 none --gui
```

The first windowed run opens graphics and controller setup. Save the graphics
settings, then select **Play Game** in the controller window to save the
bindings and start Metal Gear Acid 2. Reopen both dialogs later with:

```powershell
out\build\clang-cl\mga2.exe --configure
```

The configuration launcher starts the game after **Play Game** is selected;
the title-bar close button exits without launching.