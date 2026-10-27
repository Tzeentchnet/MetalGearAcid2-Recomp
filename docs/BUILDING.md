# Building and testing

This guide covers manual extraction, generation, builds, and tests. Run the
commands from the repository root. See the [requirements](../README.md#requirements)
and [source setup](../README.md#get-the-source) before building, or use the
[quick installer](../README.md#quick-install).

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

Extraction checks all configured file hashes before publishing outputs, and
generation rechecks every main and native-module input. Generation stages a
complete split-source tree and publishes a source manifest only on success;
allow enough disk space for a second generated tree during regeneration.
Single-file generation is not supported by this project's CMake build.

For manual development against an unsupported toolkit, pass
`--allow-unsupported-toolkit` to `gen.py` and configure CMake with
`-DMGA2_ALLOW_UNSUPPORTED_TOOLKIT=ON`. Use the same toolkit at both stages.

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

## Tests

Source-only checks require neither an ISO nor the toolkit:

```powershell
python -m unittest discover -s tools\mga2\tests -p "test_*.py"
python -m compileall -q tools\mga2
python tools\mga2\check_release_contents.py
```

The content check examines known protected paths in tracked files and reachable
Git history; it is not a substitute for reviewing the release and its history.
CI runs these checks on Linux and Windows with Python 3.11 and 3.12.

The native test executables are excluded from the default build. After
generating inputs and configuring the combined preset, build them explicitly
in the same developer shell before running CTest:

```powershell
cmake --build --preset clang-cl --target mga2_display_state_tests mga2_perf_stats_tests mga2_ge_patch_math_tests mga2_graphics_config_tests mga2_texture_scaler_tests mga2_d3d12_vertex_tests mga2_vulkan_shader_state_tests
ctest --test-dir out\build\clang-cl --output-on-failure -R "^mga2_"
```

The software-only preset omits the texture-scaler, D3D12, and Vulkan targets.
Neither source-only tests nor these native unit tests establish gameplay or
renderer compatibility.
