# Metal Gear Acid 2 Recomp

Source-only Windows static recompilation work for **Metal Gear Acid 2
(ULUS-10077 v1.00)** using the local `psp-recomp` toolkit.

No game executable, generated game C, disc data, trace, save, or capture should
be committed. Supply your own supported USA ISO.

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

## Current status

- The disc and main executable are pinned and verified.
- All 18,401 discovered main-module functions and 5,166 functions across ten
  exact dynamic-module dispatch tables generate successfully.
- All 23,260 cacheable functions produce an unchanged all-hit rerun.
- Code generation emits zero trapping stubs.
- A PPSSPP interpreter trace pins the standalone boot contract.
- Exact native policy covers KJFS, ZLIB, SOUND, and seven unique stage-overlay
  images. Other plaintext PRXs retain bounded interpreter fallback. Seven
  exact encrypted firmware-module identities use named HLE policy.
- Strict native boot reaches multiple stage overlays, async/callback threads,
  and the `sceFont` HLE after loading raw-LBN `libfont.prx`.
- A deterministic native input sequence reaches the opening movement tutorial.
- An independent PSP gameplay capture confirms that the tutorial's abstract
  yellow, white, and purple floor texture is the original presentation.
- Authentic Acid 1 and Acid 2 secure savedata loads successfully. The Acid 1
  import transfers SOCOM and awards 54 points; Acid 2 saves reach the
  intermission map, Stage 01 aircraft briefing, and Arena Easy gameplay.
- Native differentials produce byte-identical software-framebuffer checkpoints
  in the tutorial, Stage 01 briefing, and Arena gameplay.
- Full front-end and gameplay validation are not yet complete.

## Requirements

- Windows 10/11 x64
- Python 3.11 or newer
- CMake 3.25 or newer and Ninja
- Visual Studio 2022 Build Tools with clang-cl and a Windows SDK
- `psp-recomp` at `D:\Github\psp-recomp`, or pass another
  `PSP_RECOMP_DIR` to CMake and `--toolkit` to the generator

The generator honors `PSP_RECOMP_CODEGEN_CACHE` and
`PSP_RECOMP_FUNCTION_CATALOG`. When they are unset, it discovers the private
stores below `%LOCALAPPDATA%\psp-recomp`.

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

## Run

```powershell
$env:PSP_ISO = "$PWD\Metal Gear Acid 2 (USA).iso"
$env:SR_MEMSTICK = "$PWD\memstick"
$env:SR_MODULE_LOG = "1"
out\build\clang-cl\mga2.exe --boot `
  build\mga2\gen\mga2_image.bin 08804000 08804128 none
```

The initial build uses the software renderer and Win32 presenter. Keep strict
dispatch enabled; diagnostic permissive modes are not acceptance evidence.
Configured dynamic modules use native dispatch by default. For differential
testing only, `SR_DISABLE_NATIVE_MODULES=*` disables every dynamic table; a
comma-separated list of table names disables selected tables.

For the current deterministic native checkpoint, set
`SR_PADSCRIPT=tools\mga2\new_game_runtime.pad`,
`SR_FAST_FORWARD_PRESENT=82000`, and `SR_EXIT_AFTER_PRESENT=82000`.
The script enters **NEW GAME**, selects **EASY**, skips MGA1 save transfer, and
advances through the opening movement instructions. Its runtime presentation
timings are verified; the PPSSPP timing columns remain provisional until the
same input sequence is captured against the oracle.

Software-framebuffer captures at presentations 30000 and 82000 have SHA-256
`eb4abcd6e454a3c13c3724b07027ac9cac45c98e2e42d8ecda2780ee5c870d9f`
and `d679ddbd2b54a666fec067ad9f47658a7795cefe2902be724199307fdb5d30d2`.
Both hashes reproduce with all dynamic native tables disabled.

## Optional save-based validation

The save fixtures are not distributed with this project. Each test uses an
isolated memory-stick root containing the listed directory beneath
`PSP\SAVEDATA`:

| Script | Required save directory | Validated path |
|---|---|---|
| `tools\mga2\import_mga1_runtime.pad` | `ULUS10006001` | Import SOCOM and reach the 54-point award |
| `tools\mga2\load_save_runtime.pad` | `ULUS10077003` | Load Acid 2 slot `003` into intermission |
| `tools\mga2\stage01_runtime.pad` | `ULUS10077003` | Enter Harbor Area and advance the aircraft briefing |
| `tools\mga2\arena_runtime.pad` | `ULUS10077003` | Enter Arena Easy and reach the playable card interface |

Validation used these publicly posted North American saves:

| GameFAQs save | Description | Archive SHA-256 |
|---:|---|---|
| Acid 1 `10243` | 100% completion | `7c451329205896f1fa125a7152683845fa4a165b0106ec743a147bd48b748bc8` |
| Acid 2 `11430` | After the tutorial, complete card library | `80a2e5967c62b3915dceea3daeb6df730d20fab3c46f2df550dfcd4c42120f54` |
| Acid 2 `11261` | Before the new Metal Gear fight | `3ba054bbf48bf2feef1a0c6c10f540315993be1b1a2fc630fc2cd412d5727b44` |

The source pages are
[Metal Gear Acid saves](https://gamefaqs.gamespot.com/psp/920776-metal-gear-acid/saves)
and
[Metal Gear Acid 2 saves](https://gamefaqs.gamespot.com/psp/928434-metal-gear-acid-2/saves).
Keep the two Acid 2 fixtures in separate memory-stick roots because both use
`ULUS10077003`.

See [evidence-backed findings](docs/FINDINGS.md) and
[validation status](docs/STATUS.md).
