# Metal Gear Acid 2 Findings

## MGA2-F-001 - Supported disc identity

**Status:** Confirmed

**Inputs**

- Metal Gear Acid 2 USA v1.00 (`ULUS10077`)
- ISO size `917,307,392`
- ISO SHA-1 `87cebe80a93c4231bdbab26ad630c6d8e2fddab5`

**Observation**

The disc contains 476 files. `EBOOT.BIN` is encrypted, while `BOOT.BIN` is a
plaintext relocatable ELF for module `mgp_main`. The module and stage roots
contain 80 additional plaintext PRXs and 27 encrypted firmware PRXs.

**Impact**

Title configuration. No main-executable decryption step is required.

## MGA2-F-002 - Main module is statically translatable

**Status:** Confirmed

**Inputs**

- `BOOT.BIN` SHA-1 `c1fea0e177c98372eba78bb8cc4fd279f43c383b`
- `psp-recomp` commit `66c18a57bef4a470751a5d56ab53acd9420f3fb0`

**Observation**

| Property | Value |
|---|---|
| Base | `0x08804000` |
| Entry | `0x08804128` |
| GP | `0x089fa9a0` |
| Text size | `0x1cc834` |
| Image size | `0x2b3ac0` |
| Relocations | `73,393` |
| Functions | `18,401` |
| Imports | 164 stubs across 24 libraries |

Code generation emits zero trapping stubs. The exact cache reports 18,237
hits, zero misses, and zero writes on an unchanged rerun, with no generated
file timestamp changes.

**Impact**

Title configuration plus one shared `vmmov` implementation in native codegen
and interpreter fallback.

## MGA2-F-003 - Catalog matches are identity evidence only

**Status:** Confirmed

The private 37-function catalog reports zero exact matches and four normalized
soft-float candidates: `__extendsfdf2`, `__adddf3`, `__subdf3`, and
`__negdf2`. They remain review evidence and do not drive generated-code reuse.

## MGA2-F-004 - Standalone boot contract

**Status:** Confirmed

**Inputs**

- PPSSPP commit `fa50bb1976065c4f8b1b47af227d367fe9771555`
- Interpreter and software renderer
- One-instruction trace at `0x08804128`

**Observation**

| State | Oracle value |
|---|---|
| Argument length | `0x21` |
| Argument pointer | `0x09fffed0` |
| Argument | `disc0:/PSP_GAME/SYSDIR/EBOOT.BIN\0` |
| `k0` | `0x09ffff00` |
| `sp` | `0x09fffe90` |
| `ra` | `0x08000030` |
| Module-start UID | `0x113` |
| Kernel next UID | `0x114` |
| Initial GE list ID | `0` |
| Priority | `0x20` |
| Stack size | `0x40000` |

The module entry creates `user_main` at `0x088041e4` (UID `0x114`) and
`Main` at `0x08804564` (UID `0x115`).

**Impact**

Title configuration. These values must not become shared defaults.

## MGA2-F-005 - Encrypted firmware modules use the `~SCE` signature

**Status:** Confirmed

Six modules needed during initial boot use `~SCE` rather than `~PSP`:
`videocodec`, `audiocodec`, `sc_sascore`, `libatrac3plus`, `mpegbase`, and
`mpeg`.

**Impact**

Shared runtime mechanism. The loader accepts either encrypted signature only
through the same exact path/hash HLE policy, with synthetic coverage for both
container types.

## MGA2-F-006 - Interpreter fallback boundaries include branch delay slots

**Status:** Confirmed

The dynamic-module interpreter originally returned at its instruction budget
after a branch but before the branch delay slot. The runtime CPU state does not
retain the reference interpreter's pending branch target, so the next fallback
segment resumed the delay-slot instruction as ordinary fall-through. This
eventually sent ZLIB down an invalid copy path that overwrote the SOUND thread
stack.

Normal taken and not-taken branches now both establish a delay slot, and an
interpreter segment may exceed its nominal budget by one instruction to finish
that slot. Exact regressions cover both outcomes at a one-instruction boundary.
The default one-million-instruction budget now advances past the former
ZLIB/SOUND corruption.

## MGA2-F-007 - UMD ioctl seek is required during native boot

**Status:** Confirmed

PPSSPP observes
`sceIoIoctlAsync(3, 0x01010005, 0x09f9faa0, 4, 0, 0)` as a UMD-file seek.
The runtime now executes synchronous and asynchronous ioctl operations through
the existing async-I/O worker, including the UMD query, seek, and read commands
used by the title. The asynchronous request completes through `SceIoAsync`
rather than returning synthetic success.

## MGA2-F-008 - Raw-LBN `libfont.prx` is an exact HLE module

**Status:** Confirmed

The title loads `PSP_GAME/USRDIR/modules/libfont.prx` through raw path
`disc0:/sce_lbn0xb760_size0x5bc0`. The module is encrypted, has SHA-1
`1b107660cd2b2c9ac946243822e67d0d421b9a91`, and PPSSPP identifies it as
`sceFont_Library`.

The exact path/hash policy accepts this module as HLE-only. A strict 55-second
native smoke run, with permissive dispatch and module loading disabled,
reached `sceFontNewLib` and `sceFontFindOptimumFont`, continued in the stage
overlay, and produced no HLE trap, interpreter fault, memory fault, or host
crash.

## MGA2-F-009 - Strict native execution reaches the 3D tutorial

**Status:** Confirmed

A clean-memstick software-renderer run captured deterministic native frames
without permissive dispatch or module loading. Presentation 120 reproduced
byte-for-byte across two independent runs with SHA-256
`e66ccf4337edff83eaebd345216d8c7fb289ead04e48ac356f7842a8832ca70c`
and displays the memory-stick check. Later checkpoints render the safety
notice, KONAMI and Kojima logos, title art, and the complete main menu.

The presentation-timed input sequence in
`tools/mga2/new_game_runtime.pad` enters **NEW GAME**, selects **EASY**,
declines MGA1 save transfer, and loads two further `mgp_stage` overlays:

| Raw path | UID | Image size |
|---|---:|---:|
| `disc0:/sce_lbn0x649f0_size0xe67` | `0x1b5` | `0x800` |
| `disc0:/sce_lbn0x66200_size0x1bf0f` | `0x1bc` | `0x16a00` |

By presentation 30000 the strict runtime renders the opening 3D tutorial,
including the player character and dialogue. The captured frame has SHA-256
`eb4abcd6e454a3c13c3724b07027ac9cac45c98e2e42d8ecda2780ee5c870d9f`.
Further scripted CIRCLE pulses advance through the opening movement
instructions. Presentation 82000 has SHA-256
`d679ddbd2b54a666fec067ad9f47658a7795cefe2902be724199307fdb5d30d2`.
No HLE trap, interpreter fault, memory fault, or host crash occurs before
either bounded clean exit.

## MGA2-F-010 - Exercised plaintext PRXs have exact native dispatch

**Status:** Confirmed

Ten unique dispatch tables cover the repeatedly exercised core PRXs and
stage overlays:

| Dispatch table | Module | Base | Functions | Cacheable |
|---|---|---:|---:|---:|
| `mga2_kjfs` | `KCEJ_FS` | `0x099c7b00` | 563 | 512 |
| `mga2_zlib` | `ZLIB` | `0x099d7f00` | 118 | 118 |
| `mga2_sound` | `KCEJ_SOUND` | `0x099dc000` | 919 | 831 |
| `mga2_stage_init` | `mgp_stage` | `0x09a0b500` | 215 | 215 |
| `mga2_stage_resource` | `mgp_stage` | `0x09a0b500` | 26 | 26 |
| `mga2_stage_title` | `mgp_stage` | `0x09a0b500` | 675 | 671 |
| `mga2_stage_tu0000` | `mgp_stage` | `0x09a0b500` | 843 | 843 |
| `mga2_stage_intermission` | `mgp_stage` | `0x09a0b500` | 960 | 960 |
| `mga2_stage_st0000` | `mgp_stage` | `0x09a0b500` | 187 | 187 |
| `mga2_stage_a0001` | `mgp_stage` | `0x09a0b500` | 660 | 660 |

Each policy entry requires the observed path, module name, SHA-1, and runtime
base. Code generation uses runtime JAL resolution and guest-byte verification.
The two byte-identical resource overlays share one table, while activation and
deactivation select the correct table as stage images reuse `0x09a0b500`.

All 5,166 dynamic-module functions generate without a trapping stub. Together
with the main image, an exact-cache rerun reports 23,260 hits, zero misses, and
zero writes. The clang-cl Release build compiles 361 generated translation
units.

A strict scripted run logs native activation for the three core PRXs and all
eight observed stage paths. Tutorial runs with `SR_DISABLE_NATIVE_MODULES=*`
produce byte-identical framebuffers at presentations 30000 and 82000.
Save-based Stage 01 runs match at presentations 80000, 100000, 120000, and
130000.

Arena `a0001.prx` was isolated by disabling only
`mga2_stage_a0001`; native and interpreted captures match at presentations
28000, 32000, 38000, and 45000:

| Presentation | SHA-256 |
|---:|---|
| 28000 | `40a6fa8b5034ff4fbba5ab48f025d210e2753757003a83edd005f1facd8f0769` |
| 32000 | `ab188633aabc54d34d0dc0be9f7d8e8b720e6d332e2d827bfd71d9ec565785d5` |
| 38000 | `8a43f66be7f0896b27114ba9545d10b000aa1c63cfdce490cf668e7e2a230b85` |
| 45000 | `e8add670ff2f695c1462f40d0bbc84540817facd26b564e0debfd229a6783777` |

Disabling every earlier native module changes the Arena random-hand seed and
therefore is not a valid late-frame comparison for this path. The isolated
table differential preserves the pre-Arena execution state. No runtime-code
mismatch, loader failure, HLE trap, interpreter fault, memory fault, or host
crash occurs.

## MGA2-F-011 - Authentic secure saves expand runtime coverage

**Status:** Confirmed

Three public North American save archives were kept as ignored validation
inputs:

| Game | GameFAQs ID | PSP directory | Archive SHA-256 |
|---|---:|---|---|
| Acid 1 | `10243` | `ULUS10006001` | `7c451329205896f1fa125a7152683845fa4a165b0106ec743a147bd48b748bc8` |
| Acid 2 | `11430` | `ULUS10077003` | `80a2e5967c62b3915dceea3daeb6df730d20fab3c46f2df550dfcd4c42120f54` |
| Acid 2 | `11261` | `ULUS10077003` | `3ba054bbf48bf2feef1a0c6c10f540315993be1b1a2fc630fc2cd412d5727b44` |

The runtime handles savedata mode 4 and securely decrypts both formats. The
Acid 1 host file is 30,868 bytes and yields a 30,852-byte payload for game
`ULUS10006`, save `001`. Acid 2 host files are 48,800 bytes and yield
48,784-byte payloads for game `ULUS10077`, save `003`.

The Acid 1 import browser displays SOCOM, confirms the transfer, reports
`Card transfer complete.`, and awards 54 points. Both Acid 2 saves load into
intermission. The post-tutorial save enters the Harbor Area Stage 01 aircraft
briefing, while the late-game save enters Arena Easy and reaches its playable
card interface.

These paths exposed and validated exact native policy for:

| Canonical image | Raw path | SHA-1 |
|---|---|---|
| `stage/intermission/intermission.prx` | `disc0:/sce_lbn0x62240_size0x22a51` | `cc53bb130dd68d55ecbd6e179e8ab5120037ba41` |
| `stage/st0000/st0000.prx` | `disc0:/sce_lbn0x62d90_size0x5331` | `436c19f97a9dc3858fd9c2d30010ae466e5092ba` |
| `stage/a0001/a0001.prx` | `disc0:/sce_lbn0x680f0_size0x154b8` | `231bd5573c63874ea2bb23dd3f9f9955238b5c4f` |

No secure-save, loader, HLE, interpreter, memory, or host fault occurs. Secure
save creation and reload are not yet covered.

## MGA2-F-012 - The abstract tutorial floor is original game art

**Status:** Confirmed

The opening tutorial's bright yellow, white, and purple floor initially
appeared inconsistent with the otherwise industrial texture set. An
independent PSP gameplay capture at `2:30-2:40` shows the same abstract atlas,
black side geometry, purple outlines, camera angle, and character placement:

`https://www.youtube.com/watch?v=vt0S_DG7c9U`

A targeted runtime trace also rules out stale VRAM or a failed texture upload.
Immediately before the first tutorial draw, the game copies the complete
`0x40000`-byte indexed source at `0x092928e0` into texture address
`0x040cc000`; its CLUT follows at `0x092d28e0`. The first transformed draws
then intentionally select that 512x512 swizzled format-5 texture. The source
comes from the tutorial resource path
`disc0:/sce_lbn0x66240_size0xac191`, not a retained title framebuffer.

Two independently traced presentation-14000 runs produced the same
software-framebuffer SHA-256:
`32d2126ef5adab31c3eff7c853eccc97b88cad72f0cd1c918f9835eddf422b41`.
No renderer workaround or title-specific suppression is warranted.
