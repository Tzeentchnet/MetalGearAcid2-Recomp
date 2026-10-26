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

Settings are persisted in `graphics.ini` beside the executable. The equivalent
keys are `renderer`, `internal_resolution`, `texture_scale`, and
`d3d12_full_rate`; `anti_aliasing` accepts `off` or `smaa`.

## Requirements

- Windows 10/11 x64
- Python 3.11 or newer
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools with clang-cl and a Windows SDK
- Vulkan SDK when building the default Vulkan backend. A standard
  `C:\VulkanSDK\<version>` install is detected automatically.
- `psp-recomp` commit `dca4a7c` or newer at `D:\Github\psp-recomp`, or pass
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

## Tutorial performance benchmark

After building the combined renderer, run the deterministic opening-dialog
benchmark with:

```powershell
python tools\mga2\benchmark_tutorial.py
```

The benchmark requires the D3D12 4x internal-resolution, 2x xBRZ, full-rate
profile in the executable's `graphics.ini`. It fast-forwards the checked-in
input replay to presentation 30,900, includes the CIRCLE pulse at presentation
31,000, and validates a 120-flip steady-state window. The default gates require
at least 59 displayed FPS, p95 at or below 18 ms, no frame above 33.4 ms, GPU
time within one 59.94 Hz period, active framebuffer-feedback aliases, and no
more than four cumulative startup/shutdown framebuffer readbacks.

Logs, the performance CSV, and a machine-readable `summary.json` are written
under `out\benchmarks`. Use `--iso`, `--executable`, or `--output` to override
the default local paths.

## Arena performance benchmark

The completed-save Arena route is the primary renderer and runtime stress
test. Supply an isolated memory-stick root containing
`PSP\SAVEDATA\ULUS10077003`; its `00000000.000` file must be exactly 48,800
bytes. Then run:

```powershell
python tools\mga2\benchmark_arena.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick
```

The default run validates two 120-host-flip windows: the Dead Cell
introduction around presentation 28,000 and playable Arena card combat around
presentation 38,000. Fast-forwarding stops 120 guest presentations before
each measurement window so transition work is not mistaken for steady-state
rendering. The fixed acceptance profile and gates are identical to the
tutorial benchmark: D3D12 at 4x internal resolution, 2x xBRZ, full-rate
shading, at least 59 displayed FPS, p95 no greater than 18 ms, no frame above
33.4 ms, no GPU sample above 16.68 ms, at most four cumulative readbacks, and
active framebuffer aliases and ordered feedback snapshots.

Use `--case dead-cell` or `--case gameplay` while iterating. Add
`--include-unpaced` only for a non-gating throughput diagnostic. Each case
writes its command log, per-presentation `perf.csv`, and summary beneath a new
directory in `out\benchmarks`; the parent `summary.json` records both cases
and every failed gate.

The current experiment history, rejected approaches, remaining bottlenecks,
and ranked follow-up work are recorded in
[`docs/ARENA_PERFORMANCE.md`](docs/ARENA_PERFORMANCE.md).

## Vulkan visual validation

Vulkan correctness is gated by rendered pixels rather than successful route
completion. Run the completed-save visual lane with:

```powershell
python tools\mga2\validate_vulkan.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick `
  --include-d3d12
```

The command creates isolated software, Vulkan, and optional D3D12 memory-stick
copies. It captures presentation 28,000 (Dead Cell cinematic) and presentation
38,000 (Arena gameplay), then checks the whole frames and focused character,
stage/player, map-preview, and card-UI regions. The dependency-free PPM metric
gate uses the software renderer as its oracle and holds Vulkan to bounds
calibrated against the native-resolution D3D12 cross-check.

Use `--reference-dir`, `--vulkan-dir`, or `--d3d12-dir` to validate existing
capture directories without rerunning those renderers. Set
`SR_VK_VALIDATION=1` to require the Khronos validation layer and report Vulkan
synchronization, layout, descriptor, and lifetime errors.