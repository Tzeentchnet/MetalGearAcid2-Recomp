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

An optional local 37-function catalog reports zero exact matches and four
normalized soft-float candidates: `__extendsfdf2`, `__adddf3`, `__subdf3`,
and `__negdf2`. They remain review evidence and do not drive generated-code
reuse. Public generation does not require a catalog.

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

## MGA2-F-010 - Exercised plaintext PRXs use exact guarded dispatch

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
eight observed stage paths. Exact instruction guards remain active after
dispatch-table activation. Tutorial runs with `SR_DISABLE_NATIVE_MODULES=*`
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
table differential preserves the pre-Arena execution state.

The Arena overlay later rewrites three instructions in the function at
`0x09a0f7d0`. Its exact guard therefore sends that function to the interpreter
while the remainder of the activated table stays native. A diagnostic
live-instruction native variant reduced interpreted instructions from
13,019,660 to 990,705 but did not improve measured throughput, so the exact
guard and interpreter fallback were retained. The differential above validates
the guarded dispatch policy; it does not imply that runtime-modified functions
continue executing stale native code. No unhandled code mismatch, loader
failure, HLE trap, interpreter fault, memory fault, or host crash occurs.

## MGA2-F-011 - Authentic secure saves expand runtime coverage

**Status:** Confirmed

Three public North American save archives were kept as ignored validation
inputs. The fixtures are not distributed with this project.

| Game | GameFAQs ID | Description | PSP directory | Archive SHA-256 |
|---|---:|---|---|---|
| Acid 1 | `10243` | 100% completion | `ULUS10006001` | `7c451329205896f1fa125a7152683845fa4a165b0106ec743a147bd48b748bc8` |
| Acid 2 | `11430` | After the tutorial, complete card library | `ULUS10077003` | `80a2e5967c62b3915dceea3daeb6df730d20fab3c46f2df550dfcd4c42120f54` |
| Acid 2 | `11261` | Before the new Metal Gear fight | `ULUS10077003` | `3ba054bbf48bf2feef1a0c6c10f540315993be1b1a2fc630fc2cd412d5727b44` |

The source pages are
[Metal Gear Acid saves](https://gamefaqs.gamespot.com/psp/920776-metal-gear-acid/saves)
and
[Metal Gear Acid 2 saves](https://gamefaqs.gamespot.com/psp/928434-metal-gear-acid-2/saves).

Each test uses an isolated memory-stick root containing the listed directory
beneath `PSP\SAVEDATA`:

| Script | Required save directory | Validated path |
|---|---|---|
| `tools\mga2\import_mga1_runtime.pad` | `ULUS10006001` | Import SOCOM and reach the 54-point award |
| `tools\mga2\load_save_runtime.pad` | `ULUS10077003` | Load Acid 2 slot `003` into intermission |
| `tools\mga2\stage01_runtime.pad` | `ULUS10077003` | Enter Harbor Area and advance the aircraft briefing |
| `tools\mga2\arena_runtime.pad` | `ULUS10077003` | Enter Arena Easy and reach the playable card interface |

Keep the two Acid 2 fixtures in separate memory-stick roots because both use
`ULUS10077003`.

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

## MGA2-F-013 - Hardware renderers and xBRZ reach Arena gameplay

**Status:** Confirmed

The default clang-cl preset now compiles D3D12, Vulkan, and software into one
executable. Its launcher exposes and persists all four renderer choices
(including Automatic), 1x-8x internal resolution, 1x-5x texture scaling, and
balanced versus full-resolution D3D12 shading. A software-only preset retains
the deterministic GDI baseline and hides unavailable hardware choices.

SDL3 3.2.20 is fetched from the official release archive with pinned SHA-256
`33968846724f8b68d58ad0b42274e00e845fb4b35c0ac88cedbe023a755116d4`
when no local CMake package is available. The Vulkan SDK is discovered from
its standard Windows install root. The hardware build copies the matching
SDL3 3.2.20 DLL beside `mga2.exe`.

Decoded game textures can be scaled from 2x through 5x with the xBRZ
implementation used by PPSSPP v1.20.4. D3D12 and Vulkan share one C ABI around
the scaler. Framebuffer and render-target textures are deliberately excluded;
they retain each backend's normal ownership and resolution. Scaling is opt-in
because texture-cache resources and temporary buffers grow quadratically.

The following strict runtime checks completed without an HLE trap, renderer
fault, device loss, or host crash:

| Build / renderer | Settings | Route | Result |
|---|---|---|---|
| Combined / D3D12 | 8x internal (3840x2176), 2x xBRZ, full-rate 1x1 shading | Authentic late-game save to Arena Easy | Clean exit at presentation 45000 |
| Combined / Vulkan | Native GE target, 2x xBRZ | Same save and Arena input script | Clean exit at presentation 45000 |
| Combined / Vulkan | 4x internal, 2x xBRZ | Dead Cell and Arena visual checkpoints | Clean exit at presentation 38001 with Khronos validation |
| Combined / Vulkan | 8x internal, 2x xBRZ | Boot/front-end smoke | Clean exit at presentation 120 with Khronos validation |
| Combined / D3D12 | 2x internal, 5x xBRZ | Boot/front-end smoke | Clean exit at presentation 120 |
| Combined / Vulkan | Native GE target, 5x xBRZ | Boot/front-end smoke | Clean exit at presentation 120 |
| Software-only / GDI | Native PSP resolution | Boot/front-end smoke | Clean exit at presentation 120 |

The first D3D12 Arena attempt exposed a pre-existing fixed capture ceiling:
one dense frame requested 240,003 decoded vertices against a 240,000-vertex
limit. The renderer correctly refused a partial upload. Capture storage now
grows within explicit 1,048,576-vertex and 262,144-batch safety bounds and can
spill into the existing fenced upload slabs. A regression test captures the
exact 240,003-vertex case, and the identical 8x Arena rerun reaches
presentation 45000.

F11 was also exercised on both SDL3 backends. Each window expanded from
960x544 to the 3440x1440 desktop swapchain, continued rendering, restored to
960x544, and exited cleanly.

D3D12 is the high-resolution GE path: scaled color/depth targets, feedback,
copies, and presentation all follow the 1x-8x setting. Vulkan currently
presents to an arbitrary high-resolution swapchain and supports xBRZ texture
uploads, but its offscreen GE color/depth target remains native 512x272.

## MGA2-F-014 - D3D12 fallback textures synchronize GPU-newer framebuffers

**Status:** Confirmed

The tutorial scene alternates two 512-stride 5551 framebuffers at
`0x04000000` and `0x04044000`. Each rendered frame includes 240 sprite draws
that reinterpret the active 16-bit framebuffer as a 512x512 indexed texture.
That format mismatch correctly rejects the direct framebuffer alias, but the
D3D12 fallback texture path previously hashed and decoded the guest-VRAM mirror
without first materializing the newer GPU target. One stale mirror retained a
uniform dark character silhouette, so the artifact appeared and disappeared
as the displayed framebuffer changed.

A deterministic adjacent capture isolated the switch between presentations
28002 and 28003. Forced framebuffer-safe readback removed the silhouette. The
shared runtime now performs the normal watched VRAM read before hashing or
decoding a fallback texture, preserving direct aliases while synchronizing only
overlapping GPU-newer targets.

Without diagnostic safe mode, all 11 fixed captures from presentations
27996-28006 are byte-for-byte identical to the safe-readback control. The
targeted path required 2,245 readbacks over the replay instead of the control's
55,997. Graphics configuration, texture-scaler, and D3D12 vertex regression
tests also pass. The fixed D3D12 build also reaches presentation 45000 through
the authentic late-game Arena route without a renderer fault or host error.
The GPU-resident 16-bit feedback path in MGA2-F-016 now handles this scene
without entering the synchronized fallback; the fallback remains the explicit
correctness route for incompatible layouts.

## MGA2-F-015 - D3D12 direct stencil writes preserve character depth

**Status:** Confirmed

Arena cutscene character models showed moving triangular dark patches under
D3D12 while the software renderer produced the correct surfaces from the same
GE stream. At native pixel `(234,104)`, draw 12680 writes the visible front
surface at depth approximately 9202. Draw 12694 later submits a dark interior
surface at depth approximately 8192, which correctly fails the PSP `>=` depth
test in software but appeared in the D3D12 result.

The affected 5551 batches enabled stencil with an always-pass test, KEEP on
stencil and depth failure, and INCREMENT on depth pass. That state forced the
destination-snapshot shader path, whose fixed-function PSO used depth ALWAYS;
the path did not preserve the expected cross-draw depth ownership for these
surfaces. In one-bit 5551 alpha, the successful increment is
destination-independent and always writes 255.

The D3D12 runtime now admits safe destination-independent stencil states to its
direct path. Fixed-function D16 performs the PSP depth test and write, while the
direct pixel shader emits the known stencil value through alpha. Compatibility
requires an always-pass stencil test, a no-op depth-fail operation, an
depth-pass operation that is either a no-op or an unmasked,
destination-independent write, and blend state that does not consume the
replaced source alpha. Masked,
destination-dependent, and otherwise unsupported states remain on the exact
snapshot path.

Normal 4x D3D12 captures at presentations 27960, 27980, 28000, 28020, and
28040 keep the animated model surfaces intact without diagnostic overrides.
The final presentation-28000 capture has SHA-256
`d4f4a1b46dfd80b2d8bc1f33a605635e628e789b7dde238b741953a8c5463317`.
Its full-frame Lanczos-downsampled mean absolute error against the native
software reference is 2.6196, down from 4.4944 for the corrupted D3D12 frame.
Focused D3D12 pipeline tests cover the accepted 5551 increment state plus
depth-fail mutations, masked writes, destination-dependent operations, and
source-alpha blending that must remain manual.

On the same 60-flip late-Arena sample used during diagnosis, throughput is
31.85 FPS versus 31.53 FPS before the fix, while average GPU time falls from
11.19 ms to 7.87 ms. This is a correctness fix with a modest workload
reduction, not a remedy for the remaining guest GE CPU bottleneck.

## MGA2-F-016 - GPU-resident CLUT16 feedback restores tutorial speed

**Status:** Confirmed

The presentation-31,000 tutorial dialog stress case ran at 15.33 displayed FPS
on a Ryzen 7 9800X3D and GeForce RTX 5070 with the required D3D12 4x internal,
2x xBRZ, full-rate windowed profile. Slow frames spent approximately 109-122 ms
in frontend work, while backend CPU time averaged 2.25 ms and GPU work remained
within budget. Disabling xBRZ or reducing internal resolution to 1x did not
remove the stall.

The scene reinterprets alternating 512-stride 5551 render targets as 512x512
CLUT16 textures. D3D12 previously supported GPU feedback only for
8888-to-CLUT32, so these views repeatedly forced synchronous GPU readback,
content hashing, CPU palette decode, texture-cache allocation, upload, and
accidental xBRZ treatment. The fallback decoder had already synchronized the
whole texture range, but then issued a watched VRAM read for every CLUT16
texel. If the other framebuffer remained GPU-newer, each of those reads scanned
the framebuffer cache.

The shared renderer now:

- synchronizes each fallback texture level once and decodes from its bounded
  host span;
- accepts compatible unswizzled 565, 5551, and 4444 render targets as CLUT16
  feedback sources;
- carries the native source format in canonical texture/shader state;
- center-samples the scaled target, repacks the sampled color to the native
  16-bit PSP value, and performs the existing CLUT shift/mask/start lookup; and
- keeps framebuffer-derived textures out of the ordinary xBRZ texture cache.

Incompatible stride, bounds, format, swizzle, and active-mipmap layouts retain
the synchronized CPU fallback. `SR_D3D12_DISABLE_FEEDBACK_ALIASES=1` exposes
that route for differential validation.

The same 120-flip window now records:

| Metric | Before | After |
|---|---:|---:|
| Displayed FPS | 15.33 | 60.44 |
| Average frame interval | 65.24 ms | 16.54 ms |
| p95 / p99 | 116.74 / 122.31 ms | 16.76 / 17.09 ms |
| Maximum frame interval | 123.90 ms | 17.42 ms |
| Average frontend time | 63.03 ms | 15.49 ms |
| Average backend CPU time | 2.25 ms | 1.05 ms |
| Maximum GPU time | 8.57 ms | 12.28 ms |

The complete replay's framebuffer statistics changed from 2,689 readbacks,
zero aliases, and zero feedback snapshots to 2 readbacks, 654,720 aliases, and
493,587 ordered feedback snapshots. A repeated 1x-xBRZ fallback capture was
byte-identical across 49 emitted displayed frames. The GPU-feedback comparison
differed at 2,607 of 6,397,440 logical pixels (0.04075%, mean absolute channel
error 0.0583), confined to sparse character-edge samples; the dialog, model
fill, and silhouette remain visually aligned. The optimized route preserves
native game cadence and does not lower any requested quality setting.

### Renderer reference

This workload is unusually sensitive because the title does not treat the
render targets as ordinary sampled color textures. It alternates the
512-stride 5551 buffers at `0x04000000` and `0x04044000`, then submits 240
sprite draws per rendered frame that view the active buffer as a 512x512
CLUT16 index surface. Applying xBRZ to that view is both unnecessary and
incorrect: its source is already a scaled GPU render target, not a decoded
guest texture.

The D3D12 feedback compatibility matrix is intentionally narrow:

| Native render-target format | Indexed texture view | GPU feedback |
|---|---|---|
| 565, 5551, or 4444 | CLUT16 | Accepted |
| 8888 | CLUT32 | Accepted |
| Any other pairing | Any | Synchronized CPU fallback |

Admission also requires a matching byte stride, compatible base alignment and
bounds, an unswizzled view, and a compatible active mip level. These checks
must remain in place: interpreting only the format pair as sufficient can
alias a different guest-memory layout. Direct same-format framebuffer textures
are a separate path from the indexed feedback cases above.

The native source format is carried without enlarging the texture binding or
shader constant structures. Texture-binding bit 0 marks framebuffer CLUT
feedback, bit 1 retains the ordinary upscaled-texture flag, and bits 2-3 encode
the source PSP pixel format. The shader CLUT word mirrors the format in bits
28-29 while preserving the existing clamp flags in bits 30-31. The pixel
shader center-samples the internal-resolution texel, repacks it to the original
PSP 16-bit value, and only then applies the existing CLUT shift, mask, start,
and palette-format rules. Ordered snapshots are required when a render target
is sampled and subsequently modified in the same GE stream; using the live
target for every draw would let later writes change earlier feedback reads.

The correctness fallback still begins with one watched `sr_prepare_read()` for
the complete texture level. Decoding then uses a bounded host pointer for
direct-color, CLUT, swizzled, mipmapped, and DXT data. It does not globally
disable VRAM read watching. Reintroducing `MEM_R8`, `MEM_R16`, or `MEM_R32`
inside the per-texel loop would restore the pathological behavior: each of the
262,144 CLUT16 texels could rescan the framebuffer cache while another target
was GPU-newer.

### Profiling and validation notes

For this title, a large frontend frame time that is insensitive to internal
resolution and xBRZ is a strong indicator of guest-memory synchronization or
CPU texture decode rather than shader load. The optimized run deliberately
moves work back to the GPU, so its maximum GPU time rising from 8.57 ms to
12.28 ms is expected and remains within one 59.94 Hz period. Alias, feedback
snapshot, and readback counters are cumulative over the complete replay, not
only the measured window. The high alias and snapshot totals are expected from
the repeated 240-draw feedback workload and do not indicate a resource leak.

The reproducible gate is:

```powershell
python tools\mga2\benchmark_tutorial.py
```

It validates the executable's D3D12 4x/2x/full-rate profile, fast-forwards
`new_game_runtime.pad` to presentation 30,900, includes the CIRCLE pulse at
31,000, exits at 31,400, and summarizes 120 samples. Default acceptance is at
least 59 displayed FPS, p95 no greater than 18 ms, no frame above 33.4 ms,
maximum GPU time no greater than 16.68 ms, no more than four cumulative
readbacks, and nonzero alias and ordered-snapshot counts. Displayed FPS
measures host presentations, not unique game-state updates; the correct target
is full-speed 59.94 Hz emulation while leaving the title's native update
cadence unchanged.

GPU captures are queued and consumed on a later host presentation. In the
bounded differential runs, a 50-request manifest emitted 49 files because the
last queued request was not flushed before clean exit. Consecutive requested
PSP presentation numbers can also select guest-VRAM snapshots while a GPU
capture remains pending. Future byte comparisons should therefore use requests
spaced by observed host-present cadence and compare aligned emitted sequences,
not assume that every requested identifier names an immediately captured GPU
frame.

The small feedback-versus-fallback edge delta remained unchanged when using
legacy/conservative snapshots, matching the CPU CLUT expansion formula, and
running at native internal resolution. The expansion experiment was reverted.
No sampling, palette, or snapshot defect was isolated; asynchronous displayed
frame ordering in the capture path remains a possible explanation. Treat
silhouette attachment, stable sequence behavior, and the quantitative sparse
delta as the validation criteria rather than requiring byte identity between
the fast and queue-stalling paths.

## MGA2-F-017 - Save-based visuals pass while Arena remains below 60 FPS

**Status:** Confirmed

The two isolated Acid 2 slot `003` memory-stick fixtures were retested with the
current D3D12 4x internal-resolution, 2x xBRZ, full-rate profile on the same
Ryzen 7 9800X3D and GeForce RTX 5070. The completed-game fixture drives the
Arena replay through the Vamp/Dead Cell introduction and into card gameplay.
The post-tutorial fixture drives the Stage 01 aircraft briefing.

Each performance sample contains 120 actual host display flips and includes a
known replay presentation:

| Route | Sample includes | Displayed FPS | Average | p95 | Maximum | Frontend average | Backend average | GPU average / maximum |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Vamp/Dead Cell introduction | 28,000 | 48.45 | 20.64 ms | 38.19 ms | 63.83 ms | 19.76 ms | 0.89 ms | 5.57 / 11.62 ms |
| Arena card gameplay | 38,000 | 53.48 | 18.70 ms | 32.54 ms | 65.48 ms | 17.08 ms | 1.63 ms | 11.97 / 26.46 ms |
| Stage 01 aircraft briefing | 80,000 | 59.79 | 16.73 ms | 17.07 ms | 52.52 ms | 16.35 ms | 0.37 ms | 0.40 / 0.82 ms |

Stage 01 has one 52.52 ms frontend spike at presentation 79,905 immediately
after the fast-forward transition; the other 119 samples are at or below
17.47 ms. Its sustained cadence therefore passes, although the isolated spike
still fails the strict 33.4 ms maximum-frame gate.

The Arena results are not a recurrence of the framebuffer-readback defect.
Both Arena runs perform only two cumulative readbacks. The Dead Cell replay
uses 172,800 framebuffer aliases and 130,320 ordered feedback snapshots; the
longer Arena gameplay replay uses 474,000 aliases and 357,475 snapshots. The
feedback route is active and no texture fallback occurs.

Frame timing alternates between expensive new game frames and short repeated
presentations. In the Dead Cell window, 61 of 120 samples exceed 33.4 ms and
the expensive frames are frontend-bound while GPU work remains below budget.
Disabling vblank pacing raises throughput only to 50.57 FPS, with an 18.94 ms
frontend average and 11.75 ms maximum GPU time. This isolates a remaining
guest/GE frontend throughput limit rather than presentation pacing, xBRZ,
framebuffer readback, or GPU saturation.

Arena gameplay has a different mix. Its paced window includes 58 GPU samples
above 16.68 ms, while the unpaced run averages 73.55 FPS but retains 37.70 ms
p95 and 26.32 ms maximum GPU work. The route has average throughput headroom
but still contains both CPU and 4x full-rate GPU spikes. The fixed-quality
60-FPS target is therefore not yet met for either Arena phase.

Visual validation passes. A 50-frame GPU-backed Arena manifest spans
presentations 27,920-45,100, including 16 closely spaced Vamp animation frames
from 27,920 through 28,040. The model remains intact throughout: depth
ownership is stable, the former moving triangular dark surfaces do not return,
and the cartoon silhouette stays attached. The current presentation-28,000
capture has a mean absolute channel error of 1.5426 against the deterministic
480x272 software reference. A separate internal-resolution capture at
1920x1088 confirms the same surface and silhouette behavior before
downsampling.

The Stage 01 manifest emits 49 of 50 requested frames because the final
sentinel remains queued at bounded exit, matching the capture-harness behavior
documented in MGA2-F-016. All substantive requests are present. The cabin,
character models, portraits, text, and halftone dialogue panels remain stable
through the briefing. Presentations 80,000, 100,000, and 120,000 have mean
absolute channel errors of 3.2734, 3.4929, and 3.5264 against the software
reference. At 130,000 the current replay has advanced to the next dialogue
state, so that frame is not a valid pixel differential; it shows no rendering
fault.

This save-based pass expands the visual confidence of the CLUT16 and stencil
changes but also narrows the remaining performance work. The tutorial
feedback/readback bottleneck is fixed; the Dead Cell cutscene now needs
guest/GE frontend profiling, and Arena gameplay additionally needs 4x
full-rate GPU spike analysis.

## MGA2-F-018 - Arena bottlenecks cross the guest, GE, and D3D12 boundaries

**Status:** Confirmed, optimization in progress

The dedicated Arena benchmark samples 120 actual host flips around
presentations 28,000 and 38,000 after a 120-guest-presentation warm-up. Its
exclusive, fiber-aware profiler separates generated native guest execution,
interpreter fallback, HLE, scheduler, GE command processing, vertex work,
framebuffer synchronization, backend stages, and delayed D3D12 GPU queries.
This ruled out interpreter fallback as the primary cause and exposed different
limits in the two Arena phases.

The initial Dead Cell profile reached 50.86 FPS with 35.17 ms p95 and a
59.60 ms maximum. Expensive frames issued about 590 spline draws, and spline
tessellation alone reached 31.6 ms. The evaluator redundantly recomputed each
vertical patch-column intermediate for every generated vertex. Reusing that
separable intermediate per V row and U segment, retaining scratch storage, and
generating normals only when lighting or texture state consumes them reduced
the profiled window to 17.67 ms p95 at 59.51 FPS. Vertex work then averaged
5.75 ms and peaked at 12.48 ms; patch evaluation and draw work peaked at
6.03 ms and 3.06 ms. D3D12 vertex hashes remained identical, including
`cb55d899048a60c2` at backend presentation 12,480. That diagnostic enabled
`SR_GEDUMP=1` and therefore performed 118 readbacks, so a clean run is still
required before the strict acceptance gate can be marked passed.

Arena gameplay contains no patch workload. An expensive frame submits 39,972
transformed indices across 801 draws. An index-generation cache reduces those
to 23,132 unique transforms, while batched triangle capture removes repeated
backend reserve/capture calls. The current profile still reaches approximately
5.2 ms in decode/transform, 13.0 ms in primitive assembly, 14.2 ms in generated
native execution, and 4.0 ms in framebuffer synchronization. These maxima can
overlap differently across paced frames, but together explain why the CPU side
still misses one 59.94 Hz period.

Ordered framebuffer feedback was a separate GPU cost. The previous path copied
the entire 2048x2048 physical snapshot for every refresh even when a draw
sampled only a small PSP-space rectangle. The current path takes one full copy
when the target changes, tracks subsequent dirty draw regions, and refreshes
the bounding union of the requested source and accumulated dirt. On the
expensive gameplay frame it preserves the original 181 refreshes and 59 safe
reuses while reducing copied physical pixels from 759,169,024 to 16,030,000,
a 97.9% reduction. Maximum GPU time improved from 24.47 ms to 21.22 ms in the
paired `/O1` profile, but remains above the 16.68 ms gate.

A release `/O2` generated-code experiment required one full rebuild of all 361
generated translation units. The first paced gameplay run improved aggregate
throughput from 34.99 to 46.83 displayed FPS, but its 34.16 ms p95, 34.76 ms
maximum, and 22.90 ms maximum GPU time still failed. The changed host/guest
frame mix makes aggregate FPS insufficient by itself; matched workload
counters, percentiles, and aligned GPU queries remain the optimization
criteria. Runtime-only changes continue to use incremental targeted builds so
the generated corpus is not rebuilt unnecessarily.

## MGA2-F-019 - Vulkan required ordered destination fragment semantics

**Status:** Fixed and visually validated

The Vulkan route previously reached Arena presentation 45,000 without a
device loss, but route completion was a false correctness signal. At
presentation 28,000 the Dead Cell cinematic contained only the dark clear
color, while presentation 38,000 retained card UI but omitted the player,
stage, and map-preview rendering. The presentation-28,000 capture had a
whole-frame mean absolute channel error of 21.2253 against software even
though approximately 3.76 million triangles had reached the backend.

Culling, depth testing, the min/max depth range, and alpha testing were
independently disabled during the bisect without changing the black frame.
The divergence was instead in fragment ownership: the backend approximated or
ignored destination-alpha stencil, destination-dependent blend factors,
logic operations, native bit write masks, dithering, and framebuffer
feedback. Forcing whole-channel color writes changed the failure but could not
preserve the PSP ordering, confirming that this was not missing geometry.

The fixed Vulkan path now classifies each state before pipeline selection.
Provably representable states retain fixed-function blending and depth.
Everything else snapshots RGBA8 color and D16 depth, then evaluates the PSP
fragment order in GLSL: texture combine, alpha/color tests, stencil
fail/depth-fail/pass, depth testing, blending, dithering, logic operations,
native framebuffer packing, bit masks, and depth preservation. A packed
112-byte push-constant ABI stays within Vulkan's portable 128-byte guarantee.
Destination-dependent batches merge only within one GE draw identity.

Framebuffer color resources now retain a 512x512 sampling envelope while the
writable and presented region remains 512x272. Depth address and stride are
part of attachment ownership, overlapping GPU-newer aliases are materialized
before decode, and compatible sibling/self feedback remains GPU-resident.

The deterministic visual lane in `tools/mga2/validate_vulkan.py` captures
presentations 28,000 and 38,000 and checks whole frames plus character,
stage/player, map-preview, and card-UI regions. Against the software oracle:

| Renderer/profile | Presentation 28000 MAE | Presentation 38000 MAE |
|---|---:|---:|
| Vulkan, 1x textures | 0.0379 | 0.1068 |
| Vulkan, 2x xBRZ | 1.0100 | 1.3075 |
| D3D12, native internal resolution / 2x xBRZ | 1.2704 | 2.6574 |

At 2x the Vulkan map-preview region is byte-identical to software. The
visible main menu at presentation 8,000 also remains intact: its menu-panel
region measures MAE 0.9269 and RMSE 5.2073 against software with validation
enabled.

The initial Vulkan fix still ignored the shared `internal_resolution` setting,
so a nominal 4x Vulkan profile rasterized its GE targets at native 512x272
while D3D12 rasterized at 2048x1088. That produced visibly aliased model and
geometry edges despite matching launcher settings. Vulkan now scales color,
depth, destination and feedback snapshots, framebuffer-texture coordinates,
scissors, block transfers, guest uploads/readbacks, and the visible
presentation region together. A 4x route reaches both visual checkpoints and
an 8x smoke reaches presentation 120 with validation enabled and no
diagnostics. The native pixel gate explicitly sets `SR_VK_SCALE=1`.

The
Khronos validation pass also exposed a render-finished semaphore reused while
presentation still owned it and thousands of intentionally leaked shutdown
objects. Per-swapchain-image semaphores and complete backend teardown removed
both errors. Final 1x and 2x scene runs use the same pixel gates with
`SR_VK_VALIDATION=1`; successful execution without validation diagnostics is
part of the acceptance result.

## MGA2-F-020 - Character outline pixelation

**Status:** Opt-in launcher options implemented; sampled-scene validation

On D3D12, SMAA is an existing launcher option and operates on the final
internal-resolution image. A comparison at 4x internal resolution, native
textures, and full-rate shading confirmed that SMAA runs, but it does not
remove the large steps in the character outline. Texture scaling does not
apply to framebuffer feedback.

The Arena gameplay capture at presentation 38,000 exposes the effect in the
GE stream. The game draws 240 sprites using the active 512-stride 5551
framebuffer as a 512x512 CLUT16 texture, with source and destination shifted
by one PSP pixel in each diagonal direction. The repeated draws use an alpha
test and a dark vertex color. This is the same indexed-framebuffer feedback
class described in MGA2-F-016, not an ordinary texture.

The default **Original** mode retains the previous native-texel feedback.
**Sharper** samples detected outline feedback at physical render-target
resolution on D3D12 and Vulkan; at 1x it preserves the original sampling.
**Off** skips detected sprites on all three renderers. The title-specific
detector requires the observed same-target CLUT16/5551 layout, alpha and
stencil tests, modulate state, a dark vertex color, and a one-pixel diagonal
offset. It rejects active mip filtering, blending, logic operations, and
native RGB masks. Its cached feedback is limited to a CLUT index derived
solely from the 5551 alpha bit with KEEP stencil operations. Other states use
the normal renderer, rather than broadly suppressing indexed feedback.

At 4x, the opening tutorial's purple outline and Arena's dark outline both
responded to Sharper and Off. In one tutorial capture, Sharper changed 3,686
pixels and Off changed 18,221 relative to Original; partially filled 4x4
blocks in the character region increased from 888 to 1,704 with Sharper.
D3D12 and Vulkan produced identical tutorial captures for both modes.
Sampled Arena captures closely matched across backends, and native-resolution
Original and Sharper captures were identical. Vulkan validation reported no
warnings or errors on the tested paths. A software-renderer Arena capture also
confirmed that Off changes the outline.

In the sampled tutorial, Vulkan's Original mode already differed visibly from
D3D12's Original mode. A native capture from the previous installed executable
matched the new Vulkan Original capture byte-for-byte; this existing backend
difference is not changed by the outline options.

Vulkan's recognized, depth-disabled outline state reuses the alpha-only
feedback snapshot for its stencil check and writes RGB directly. This avoids
copying the full scaled destination for every outline sprite. Other states
retain the destination-aware path. In a short paced Arena cutscene at 4x,
Vulkan Sharper held about 60 host flips/s; the 95th-percentile frame time
improved from 29.0 ms before this optimization to 17.8 ms afterward. A short
8x sample measured 59.9 host flips/s and a 20.4 ms 95th percentile. Both
samples reported zero audio underruns, although the 8x sample recorded one
padding transition and audio resynchronization during the run. These are
short measurements on one machine, not a full-game performance or audio
guarantee; high resolution can still cause slowdown.

These options change rendering semantics above 1x and are deliberately
limited to observed outline states, not all framebuffer feedback. The
tutorial and Arena captures do not establish coverage of every scene or
effect. The opt-in tests in `tools/mga2/tests/test_outline_rendering.py`
exercise recorded scenes when an isolated Arena save is supplied, and
`test_outline_ui.py` can check the launcher on an interactive Windows desktop.

## MGA2-F-021 - Card-illustration replacement feasibility

**Status:** Implemented and validated in selected Arena card draws

The supported USA disc stores card illustrations in the compressed
`stage/init/_zar` resource, inside `resident.qar`. The following texture
packs contain 344 entries in total:

| Pack | Entries |
|---|---:|
| `cd_illustac.txp` | 27 |
| `cd_illustch.txp` | 122 |
| `cd_illustit.txp` | 44 |
| `cd_illustsp.txp` | 74 |
| `cd_illustwp.txp` | 77 |

These are not PNG files. The sampled packs contain compressed, swizzled,
paletted images; most illustration entries are 112x72 pixels. The count also
includes masks and other entries, so it is not a card count. Decoding the
entries produced 325 distinct RGBA images: 16 groups contain duplicate
images. Some entries have identical indexed pixels and palettes despite
distinct resource metadata, so a replacement keyed only by texture contents
cannot distinguish every resource.

In an isolated software-renderer Arena replay using
`tools\mga2\arena_runtime.pad`, a temporary texture diagnostic captured the
Survival Kit illustration. Its 112x72 RGB pixels matched entry 24 of
`cd_illustit.txp` byte-for-byte; the entry's texture metadata identifier is
`0x00692a43`. The live draw used a 128x128 logical texture with a 112-pixel
buffer width, swizzled 8-bit indices, and a palette. The presentation-38000
frame matched the uninstrumented replay byte-for-byte, with SHA-256
`8a43f66be7f0896b27114ba9545d10b000aa1c63cfdce490cf668e7e2a230b85`.
The live palette pointer led back to the relocated TXP and its metadata. The
loader uses that identity together with the original indexed pixels, palette,
and texture geometry, allowing differently identified duplicate images to be
replaced independently.

The exporter now verifies the user's ISO and creates a catalog and PNG
templates under `mods\cards`. A PNG copied from `templates` into that folder
replaces the corresponding illustration after a restart. Integer scales from
1x to 8x are accepted. Software uses a native-resolution downsample; D3D12
and Vulkan upload the higher-resolution artwork while retaining the PSP
logical dimensions, UVs, and original texture padding. See the
[card mod instructions](../README.md#card-illustration-mods).

An unmodded software replay using the new driver reproduced the
presentation-38000 SHA-256 above. With a synthetic 4x Survival Kit replacement,
9,751 pixels changed, all within the original large 112x72 and small 56x36
artwork regions. In a separate accelerated Arena replay, a synthetic 4x
Bandage replacement (`cd_illustit.txp` entry 11, ID `0x00922a43`) was applied
on both D3D12 and Vulkan. At 4x internal resolution, the changed pixels were
confined to the corresponding 448x288 and 224x144 artwork regions; each
renderer retained alternating two-pixel stripes, demonstrating detail finer
than a four-pixel PSP texel. The D3D12 run enabled background-decode
verification, and Vulkan validation reported no errors or warnings.

Focused exporter and native-loader tests cover malformed input, resource
identity, 4-bit and 8-bit textures, transparency, scaling, and non-square
mips. The opt-in recorded regression in
[`test_card_rendering.py`](../tools/mga2/tests/test_card_rendering.py)
compares unmodded and modded hardware captures when
`MGA2_CARD_RENDER_MEMSTICK` points to an Arena save; optional executable, ISO,
renderer, and Vulkan-validation overrides are defined in the test.

These observations do not establish coverage of every card, scene, or
resource-loading path. The exported entries include masks and other
non-illustration resources, and filenames are resource identifiers rather
than friendly card names. Portraits, other UI artwork, and vector replacements
remain separate follow-up work. No ISO-derived artwork is distributed.
