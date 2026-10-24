# Validation Status

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
- Authentic Acid 1 and Acid 2 secure savedata loads successfully. The Acid 1
  import transfers SOCOM and awards 54 points.
- The default build exposes D3D12, Vulkan, and software renderers. D3D12
  supports 1x-8x internal rendering, both hardware backends support optional
  2x-5x xBRZ texture scaling, and F11 toggles desktop fullscreen.

## Validation matrix

| Level | Status | Evidence |
|---|---|---|
| Exact input | Pass | ISO size and SHA-1 verified |
| Extraction inventory | Pass | 80 plaintext and 27 encrypted PRXs |
| Catalog match | Pass | 0 exact, 4 normalized review candidates |
| Main code generation | Pass | 18,401 functions, 0 trapping stubs |
| Dynamic code generation | Pass | 5,166 functions across 10 exact dispatch tables, 0 trapping stubs |
| Exact cache rerun | Pass | 23,260 hits, 0 misses/writes |
| Shared opcode regression | Pass | Generated VFPU suite and C compile |
| PPSSPP boot oracle | Pass | One-instruction entry trace |
| Interpreter fallback | Pass | Unaligned accesses and taken/not-taken branch-budget boundaries |
| Native full build | Pass | clang-cl Release build compiles 361 generated translation units |
| Combined graphics build | Pass | One executable contains D3D12, Vulkan, and software; pinned SDL3 DLL is deployed |
| Graphics launcher | Pass | Renderer, 1x-8x internal resolution, 1x-5x xBRZ, and D3D12 shading settings persist |
| D3D12 high resolution | Pass | 8x (3840x2176), 2x xBRZ, full-rate shading reaches Arena presentation 45000 |
| Vulkan hardware backend | Pass | 2x xBRZ reaches Arena presentation 45000 on the native-resolution GE target |
| Software graphics baseline | Pass | Software-only preset and GDI presenter reach presentation 120 |
| Fullscreen toggle | Pass | F11 expands and restores both SDL3 hardware windows without device loss |
| Native boot trace | Pass | Strict boot reaches multiple stage overlays and async/callback threads |
| Native module policy | Pass | 3 core PRXs and 8 observed stage paths activate 10 exact native tables |
| Native/interpreted differential | Pass | Byte-identical tutorial, Stage 01 briefing, and isolated Arena captures |
| Exact font policy | Pass | Raw-LBN `libfont.prx` reaches `sceFontNewLib` and `sceFontFindOptimumFont` |
| Front end | Pass | Deterministic captures reach the main menu |
| Scripted input | Pass | START/CIRCLE/CROSS sequence reaches New Game on Easy |
| Initial gameplay | Pass | Strict software-renderer run advances through the opening movement tutorial |
| Tutorial visual oracle | Pass | Independent PSP gameplay footage shows the same abstract floor atlas and geometry |
| Secure savedata load/import | Pass | Acid 1 SOCOM transfer plus two Acid 2 slot `003` loads |
| Later-stage coverage | Pass | Intermission and Stage 01 aircraft briefing |
| Arena gameplay | Pass | Arena Easy reaches the playable card interface |
| Secure save write/reload | Pending | Not validated |
| Media, full gameplay, soak | Pending | Not validated |

The current milestone is deterministic, input-driven native execution through
the opening movement tutorial plus authentic-save coverage of Acid 1 import,
intermission, the Stage 01 briefing, and Arena gameplay. Software remains the
pixel-exact oracle; D3D12 now provides the validated high-resolution path and
Vulkan provides an alternate native-resolution hardware path. The main module
and ten exercised dynamic-module images are recompiled. Unconfigured plaintext
PRXs retain strict interpreter fallback. Presentation-index differentials are
exact in all three exercised gameplay lanes. Secure save creation/reload,
longer gameplay, media behavior, automated PPSSPP hardware-frame comparison,
and soak testing are still required; this is not yet full-game compatibility.
