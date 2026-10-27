# PSP Recomp Upstream Opportunities

This document distills general-purpose improvements discovered while bringing
Metal Gear Acid 2 (`ULUS10077`) through strict native execution, dynamic PRX
translation, secure savedata, and hardware-renderer validation. Detailed
title evidence remains in [FINDINGS.md](./FINDINGS.md).

The recommendations below target the shared PSP recompilation tool, generated
runtime, and renderer. Title hashes, memory addresses, startup register values,
and replay presentation numbers are evidence, not proposed shared defaults.

## Status vocabulary

- **Validated implementation:** implemented in the shared-runtime working tree
  used by this title and covered by focused or title-level tests.
- **Validated policy:** behavior demonstrated by this title that the shared
  tool should preserve, even if no new shared code is required.
- **Open improvement:** a reproducible limitation or tooling gap that remains.

These labels do not assert that a change has been merged into the upstream
repository.

## Priority summary

| Priority | Area | Discovery | Recommended upstream action | Status |
|---|---|---|---|---|
| P0 | CPU fallback | An interpreter slice can end after a branch but before its delay slot | Yield only at a complete architectural boundary | Validated implementation |
| P0 | GPU/VRAM coherence | A fallback texture can hash and decode a stale guest mirror while the framebuffer is GPU-newer | Materialize overlapping GPU data before hashing or decoding | Validated implementation |
| P0 | Texture decode | Per-texel watched VRAM reads can repeatedly scan the framebuffer cache | Prepare each complete level once, then decode a bounded host span | Validated implementation |
| P1 | Dynamic PRXs | Multiple overlays reuse one base and may modify code after activation | Generate identity-qualified dispatch tables with per-function byte guards and interpreter fallback | Validated implementation |
| P1 | D3D12 feedback | 16-bit render targets can be sampled as CLUT16 index surfaces | Add strict GPU-resident framebuffer feedback for compatible layouts | Validated implementation |
| P1 | D3D12 stencil | Some destination-independent PSP stencil operations need fixed-function depth ownership | Admit provably safe states to the direct path | Validated implementation |
| P1 | Vulkan fragments | Route completion can hide black 3D scenes when destination-alpha stencil, blend, logic, and native masks are approximated | Split provably compatible direct state from an ordered destination color/depth snapshot shader path | Validated implementation |
| P1 | Loader/HLE | Encrypted firmware modules can use either `~PSP` or `~SCE`, including raw-LBN paths | Route both signatures through the same exact identity policy | Validated implementation |
| P1 | UMD I/O | The title depends on real asynchronous UMD ioctl seek behavior | Execute supported ioctls through the async worker; never return synthetic success | Validated implementation |
| P2 | GE capture | Fixed vertex ceilings reject valid dense frames | Grow capture storage within explicit safety limits and spill through fenced upload slabs | Validated implementation |
| P2 | Feedback quality | Native-texel feedback can leave blocky outlines at high resolution despite SMAA | Generalize the title's opt-in physical-texel enhancement without changing native semantics | Title-specific implementation |
| P2 | Savedata | Secure savedata mode 4 is required by real North American saves | Keep decryption support and add synthetic create/reload coverage | Partially validated |
| P2 | Profiling | Backend stage timers can remain small while guest/GE frontend work misses the frame budget | Split frontend samples into scheduler, native guest, GE list, vertex, and HLE phases | Open improvement |
| P2 | Diagnostics | Queued GPU captures do not flush the final request on bounded exit | Drain or explicitly fail pending captures and report actual capture timing | Open improvement |
| P3 | Vulkan | A high-resolution swapchain still rendered the offscreen GE target at 512x272 | Scale Vulkan color/depth targets, feedback, copies, and presentation consistently | Validated implementation |

## 1. CPU execution and native dispatch

### 1.1 Interpreter slices must include branch delay slots

The dynamic-module interpreter previously stopped exactly at its instruction
budget, including when the last instruction was a branch. The runtime CPU
state did not retain a pending branch target, so the following slice executed
the delay-slot instruction as ordinary fall-through. The eventual symptom was
unrelated-looking ZLIB corruption of the sound thread's stack.

The validated behavior is:

1. Taken and not-taken branches both establish a delay slot.
2. A slice may exceed its nominal instruction budget by one instruction to
   finish that slot.
3. Control returns to native dispatch only after the delay slot has completed.

Upstream tests should use a one-instruction budget and independently cover
taken and not-taken branches. The broader rule is that scheduling budgets are
soft limits when stopping at the limit would split an architectural operation.
This should be audited for every interpreted branch or jump form, not only the
forms exercised by this title.

### 1.2 Dynamic overlays need identity-qualified, guarded dispatch

Metal Gear Acid 2 repeatedly loads plaintext PRXs and stage overlays. Different
images reuse the same runtime base, two paths can contain byte-identical images,
and one late-game overlay rewrites three instructions in a translated function
after native activation.

A robust generated policy needs:

- observed load path;
- module name;
- complete image hash;
- runtime base;
- activation and deactivation tied to module lifetime;
- runtime JAL resolution for calls into the active image; and
- a guest-byte guard before entering each translated function.

When a guard fails, only that function should use the interpreter. The rest of
the matching module can remain native. In the observed self-modifying overlay,
this preserved correctness while avoiding stale native code. A diagnostic
variant that ran live modified instructions natively greatly reduced the
interpreted instruction count but did not improve measured throughput, so
weakening exact guards would have traded correctness for no demonstrated
benefit.

Recommended upstream tooling:

1. Generate a declarative dynamic-module manifest from observed loader events.
2. Deduplicate tables for byte-identical images while preserving path policy.
3. Emit exact guard coverage and fallback counters per module and function.
4. Report activation conflicts when two identities claim the same base.
5. Support isolated module disablement for native/interpreter differential
   tests.

Disabling all earlier native modules is not a reliable A/B method: timing or
random-state changes can alter later game state. Differential testing should
disable only the target module while preserving the execution history that
precedes it.

### 1.3 Catalog matches are evidence, not permission to reuse code

Normalized catalog matching found plausible soft-float routines that were not
exact byte matches. These are useful labels for review but are insufficient to
select generated code. Shared tooling should keep exact identity and semantic
classification separate:

- exact matches may support code reuse under the normal relocation policy;
- normalized matches should remain diagnostics until independently verified;
  and
- a human-readable symbol guess must never bypass byte guards.

### 1.4 Bootstrap state should be generated per title

The standalone entry contract includes argument memory, `k0`, stack and return
addresses, thread attributes, UID sequencing, and initial GE list state. The
values observed for this title are not safe global defaults.

An upstream bootstrap-capture utility should be able to record the oracle
state and emit title configuration. It should distinguish:

- executable/module metadata;
- process-wide startup state;
- initial thread state;
- synthetic return trampoline state; and
- initial kernel object and GE identifiers.

This reduces hand transcription while keeping title bootstrap data out of the
shared runtime.

## 2. Loader, HLE, I/O, and savedata

### 2.1 Treat `~PSP` and `~SCE` as encrypted containers

Required firmware modules used `~SCE` as well as the more commonly recognized
`~PSP` signature. Both signatures should enter the same encrypted-module
classification path. Acceptance must still depend on the existing exact
path/hash/module HLE policy; recognizing another container signature must not
become permissive module loading.

Synthetic loader tests should cover:

- both signatures;
- a recognized signature with an unknown hash;
- a known hash at an unexpected path; and
- truncated headers.

### 2.2 Raw-LBN paths require byte identity, not pathname assumptions

The title loads an encrypted `libfont.prx` through a
`disc0:/sce_lbn..._size...` path. The runtime must resolve the sector range,
hash the exact bytes, identify the module, and apply the same HLE-only policy
used for a canonical filesystem path.

The raw path is meaningful identity evidence and should be logged, but it is
not a stable human-readable module name. Upstream policy should retain both the
observed path and resolved byte identity.

### 2.3 Supported UMD ioctls must perform real asynchronous work

The title uses `sceIoIoctlAsync` command `0x01010005` as a UMD-file seek and
depends on query, seek, and read operations completing through `SceIoAsync`.
Returning success without changing the file position allows boot to continue
temporarily but corrupts later reads.

Supported synchronous and asynchronous commands should share one operation
implementation. The asynchronous API should enqueue that operation on the
existing I/O worker and publish its real result through the normal completion
mechanism. Unknown commands need an explicit error and diagnostic rather than
a success-shaped fallback.

Recommended tests should assert:

- resulting file position;
- bytes returned by the read following a seek;
- completion ordering;
- result propagation through the async wait/poll APIs; and
- behavior for invalid handles, buffers, and command payload sizes.

### 2.4 Secure savedata needs creation and reload coverage

Secure savedata mode 4 successfully decrypts authentic Acid 1 and Acid 2 save
formats. In both observed layouts, the decrypted game payload is 16 bytes
smaller than the host file. The real save archives cannot be distributed as
upstream fixtures.

The remaining upstream gap is a legally distributable synthetic test that:

1. creates a secure save;
2. closes and reopens the memory-stick root;
3. enumerates and loads the save through the normal APIs;
4. verifies the plaintext and metadata; and
5. exercises corruption, wrong-key, and truncated-file errors.

Decrypt-only coverage is useful but does not validate the complete lifecycle.

## 3. Graphics and memory coherence

### 3.1 A GPU-newer framebuffer must be materialized before CPU fallback

The D3D12 texture fallback originally hashed and decoded the guest-VRAM mirror
without synchronizing an overlapping GPU-newer framebuffer. Alternating
framebuffers therefore produced alternating correct and stale character data.

Before hashing or decoding any CPU fallback texture, the renderer should:

1. compute the complete source range for the active mip level;
2. perform the normal watched read/materialization for that range;
3. hash the synchronized bytes; and
4. decode from those same bytes.

The operation should synchronize only overlapping GPU-newer targets. Direct
aliases and compatible feedback aliases must remain GPU-resident. Tests need
two alternating targets so a single-target implementation cannot pass by
accident.

### 3.2 Prepare once, then decode bounded memory

After the complete texture level has been synchronized, calling watched
`MEM_R8`, `MEM_R16`, or `MEM_R32` for every texel is redundant and can be
catastrophic. The observed CLUT16 level contained 262,144 texels, and every
read could rescan the framebuffer cache while another target remained
GPU-newer.

The validated decoder performs one `sr_prepare_read()` for the complete level,
obtains a bounded host span, and decodes from it. This fast path must preserve:

- direct-color and CLUT4/8/16/32 formats;
- swizzled and linear layouts;
- mip levels;
- DXT block decoding;
- integer-overflow and guest-range checks; and
- global read watching outside the already prepared span.

This should be a shared memory-access pattern, not a renderer-specific escape
hatch that disables watch handling globally.

### 3.3 Add strict GPU feedback for indexed framebuffer views

The title renders to 16-bit targets and then reinterprets those pixels as
CLUT16 indices. Reading back, decoding, scaling, and re-uploading such a target
is both slow and semantically wrong for an already scaled render target.

The validated D3D12 compatibility matrix is:

| Native render-target format | Indexed texture format | Feedback route |
|---|---|---|
| 565, 5551, or 4444 | CLUT16 | GPU-resident |
| 8888 | CLUT32 | GPU-resident |
| Other pairings | Any | Synchronized CPU fallback |

Admission must also validate stride, byte alignment, range containment,
swizzle state, and active mip compatibility. Direct same-format framebuffer
textures remain a separate alias class.

A proven state encoding used existing storage:

- texture-binding bit 0: framebuffer CLUT feedback;
- texture-binding bit 1: ordinary upscaled texture;
- texture-binding bits 2-3: native framebuffer format;
- shader CLUT word bits 28-29: native framebuffer format; and
- shader CLUT word bits 30-31: existing clamp state.

The shader center-samples the logical source texel from the scaled render
target, repacks the color to its original PSP native format, then applies CLUT
shift, mask, start, and palette format. Ordered snapshots are required when a
target is sampled and later modified in the same GE stream; binding the live
target for all draws can make earlier reads observe later writes.

Framebuffer-derived views must bypass ordinary xBRZ processing. xBRZ belongs
to decoded guest textures, not render targets already owned and scaled by the
backend.

Recommended coverage:

- all three 16-bit source formats into CLUT16;
- 8888 into CLUT32;
- incompatible source/index pairs;
- bad stride, misalignment, out-of-bounds range, swizzle, and mip cases;
- CLUT shift/mask/start combinations;
- same-target ordering; and
- forced CPU fallback differential captures.

At high internal resolutions, native-texel sampling can also preserve blocky
silhouettes in framebuffer-based character outlines. This project now offers
opt-in physical-texel sampling on D3D12 and Vulkan and a separately guarded
outline suppression mode. The normal renderer remains the default. The Vulkan
outline path can reuse an alpha-only feedback snapshot for a KEEP-stencil,
RGB-only, depth-disabled state, avoiding repeated full-target destination
copies. Sampled tutorial and Arena captures, native-resolution equality, and
short paced performance checks are described in
[MGA2-F-020](./FINDINGS.md#mga2-f-020---character-outline-pixelation).
These title-specific checks do not prove a general feedback replacement:
scaled offsets, wrapping, clamping, filtering, other effects, and performance
still need broader coverage before upstream generalization.

### 3.4 Direct stencil paths need proof of destination independence

A PSP state using always-pass stencil, KEEP on failure, and INCREMENT on depth
pass was routed through a destination-snapshot shader whose fixed-function PSO
used depth ALWAYS. Dark interior surfaces then bypassed the expected cross-draw
depth ownership.

For one-bit 5551 alpha, a successful increment is destination-independent and
produces 255. The validated direct route lets fixed-function D16 perform the
PSP depth test and write while the pixel shader emits the known stencil value
through alpha.

An upstream eligibility helper should admit a state only when:

- the stencil test is always pass;
- the depth-fail operation is a no-op;
- the depth-pass operation is a no-op or an unmasked,
  destination-independent write; and
- blending does not consume the replaced source alpha.

Masked writes, destination-dependent operations, and source-alpha consumers
must remain on the exact snapshot path. Unit tests should mutate each
eligibility condition independently.

### 3.5 Capture storage should grow safely instead of truncating

A valid dense frame requested 240,003 decoded vertices against a fixed
240,000-vertex capture ceiling. Refusing the upload was safer than drawing a
partial frame, but the fixed limit was too low.

The validated approach grows storage within explicit limits of 1,048,576
vertices and 262,144 batches and can spill through existing fenced upload
slabs. Upstream behavior should remain all-or-error: never silently truncate a
GE frame. Keep a regression at exactly 240,003 vertices so a future fixed
allocation does not reintroduce the boundary.

### 3.6 Vulkan needs an exact destination-aware fragment path

The Vulkan backend accepted millions of Arena triangles while producing a
black in-engine cinematic. Disabling culling, depth testing, depth-range
discard, or alpha testing did not change the frame. The missing state was
ordered destination behavior: PSP stencil lives in destination alpha, several
blend modes consume destination values, and logic/native bit masks occur
after blending and dithering.

The validated design uses a conservative state classifier. Fixed-function
Vulkan is allowed only when the complete PSP state is representable.
Otherwise the backend snapshots RGBA8 color and D16 depth between GE draw
identities and evaluates fragment tests, stencil/depth transitions, blend,
dither, logic, native packing, write masks, and depth output in one shader.
The push-constant layout is 112 bytes, below Vulkan's guaranteed 128-byte
minimum.

Upstream tests should independently mutate every direct-path admission rule,
compile checked-in GLSL deterministically, and retain a title-level pixel
gate. A route reaching its exit presentation is not renderer correctness
evidence. The same validation pass should cover presentation semaphore
ownership and complete device-object teardown.

### 3.7 Vulkan internal-resolution parity requires complete ownership scaling

The validated Vulkan implementation now honors the shared 1x-8x internal
resolution. It scales color and depth attachments, destination and feedback
snapshots, framebuffer-texture coordinates, scissors, block transfers,
guest-memory upload/readback sampling, and the visible presentation region as
one ownership model. Scaling only presentation or texture uploads did not
reduce geometry aliasing and would have produced mismatched feedback
coordinates.

Native-resolution pixel regression runs use an explicit `SR_VK_SCALE=1`
override. Separate 4x scene and 8x boot runs complete with the Khronos
validation layer enabled.

## 4. Diagnostics and regression infrastructure

### 4.1 Deterministic input replays should be first-class tests

Presentation-timed pad scripts made boot, tutorial, save loading, Stage 01, and
late-game Arena paths reproducible. The optimization benchmark additionally
places an input pulse inside the measured window so a run cannot pass while
stalled before the problematic transition.

Shared benchmark support should record:

- executable and content identity;
- graphics profile;
- replay identity;
- requested start, pulse, and exit presentations;
- actual sampled presentation range;
- displayed FPS and frame percentiles;
- frontend, backend CPU, and GPU times; and
- renderer coherence counters.

The title implementation also showed that fast-forward should stop before the
measured range. A configurable guest-presentation warm-up prevents one-time
scheduler/audio transition work from being reported as steady scene cost.
Delayed GPU queries must carry their source host-flip identifier so reports can
realign them instead of assigning GPU work to the later row where the query
became readable.

Displayed FPS measures host presentations, not unique guest game-state
updates. Tooling and reports should name those separately so performance work
does not accidentally change a title's native update cadence.

### 4.2 Renderer coherence counters should be structured

Readbacks, direct aliases, feedback aliases, ordered feedback snapshots, and
fallback decodes were essential to distinguish a true fix from a quality
reduction. These should be exposed as structured benchmark output rather than
only parsed from an exit log.

Useful refinements include:

- totals and measurement-window deltas;
- per-format and per-rejection-reason counts;
- bytes transferred by readback;
- fallback decode time and texel count; and
- maximum live snapshot storage.

Arena feedback profiling adds one more useful quantity: physical pixels copied
into ordered snapshots. Snapshot count alone hid a 2048x2048 copy per refresh;
tracking copied area verified a reduction from 759,169,024 to 16,030,000
physical pixels on the expensive gameplay frame without losing its 59 safe
snapshot reuses.

High alias or snapshot counts are not inherently bad; for a feedback-heavy
title they show that the GPU-resident route is active. Readback counts need
context because startup and shutdown operations may be included in totals.

### 4.3 Split frontend time into actionable phases

Save-based Arena validation exposed two cases that the existing frontend versus
backend split cannot fully explain:

- the Dead Cell introduction remains at 50.57 FPS with vblank pacing disabled,
  an 18.94 ms frontend average, and GPU work below 11.75 ms; and
- Arena gameplay rises from 53.48 paced FPS to 73.55 unpaced FPS but retains
  26.32 ms GPU spikes.

The first is a true guest/GE frontend throughput limit. The second combines
pacing behavior with intermittent 4x GPU pressure. D3D12 stage averages alone
do not identify which part of the frontend owns the remaining time.

Structured performance samples should separately report:

- host scheduler sleep and vblank wait;
- generated native guest execution;
- interpreter fallback;
- GE list management and command decode;
- vertex decode, transform, clipping, and capture;
- texture or framebuffer synchronization outside the backend;
- HLE service time; and
- graphics-backend preparation, submission, and GPU queries.

The implemented split isolated two reusable optimization rules. First,
separable spline and Bezier evaluators should compute patch-column
intermediates once per axis segment rather than once per output vertex; exact
geometry hashes can verify that reuse. Second, indexed transformed vertices
should be cached within a draw before clipping and primitive assembly. In the
Arena gameplay workload this reduces 39,972 submitted indices to 23,132 unique
transforms, although primitive assembly and clipping remain separately
measurable costs.

The counters should align to each host display sample or include generation
ranges that can be joined to it. Paired paced and `SR_NOVBPACE=1` runs should
be a supported diagnostic mode: the difference distinguishes throughput
limits from cadence/coalescing behavior without changing the production
acceptance run.

Generated-code optimization level is another build/runtime tradeoff. Changing
it invalidates every generated translation unit, so benchmark one release
profile at a time and keep runtime iteration incremental. A title-side `/O2`
experiment improved aggregate paced throughput but did not clear p95 or GPU
gates, demonstrating why compiler-profile changes must be judged with matched
workload counters rather than FPS alone.

### 4.4 GPU capture requests need explicit completion semantics

GPU captures are queued and consumed on a later host presentation. In bounded
runs, a 50-request manifest emitted 49 files because the final queued capture
was not flushed before clean exit. Consecutive requested PSP presentation
numbers can also fall back to guest-VRAM snapshots while another GPU capture
is pending.

The upstream harness should do one of the following:

1. drain pending captures before a bounded clean exit; or
2. fail unconsumed requests explicitly and report why.

Each output should record the requested guest presentation, actual host
presentation, capture source, and queue latency. This would make byte
comparisons reliable without manually spacing requests.

### 4.5 Keep a deterministic software-renderer oracle

Software output was essential for separating original title art from hardware
renderer bugs and for identifying incorrect depth/stencil behavior. Upstream
visual tests should support:

- fixed software-framebuffer hashes;
- adjacent-frame captures around a transition;
- hardware-to-software downsampled error metrics;
- native-versus-interpreted module differentials; and
- texture provenance traces showing the source copy, texture address, format,
  and CLUT.

Reference video can help classify suspicious art, but guest-memory provenance
and deterministic software output should remain the technical oracle.

## 5. Suggested upstream patch grouping

To keep review and regression isolation manageable, the discoveries can be
upstreamed in these groups:

1. **CPU correctness:** branch-delay completion and exact dynamic-function
   guards.
2. **Loader and I/O:** `~SCE`, raw-LBN exact identity, and UMD ioctl execution.
3. **Framebuffer coherence:** synchronized fallback reads and prepared-span
   texture decoding.
4. **D3D12 rendering:** CLUT16 feedback, state packing, shader reconstruction,
   ordered snapshots, and direct stencil eligibility.
5. **Capacity and diagnostics:** dynamic GE capture storage, structured
   counters, benchmark output, and capture-queue completion.
6. **Remaining platform parity:** Vulkan scaled offscreen targets and secure
   savedata create/reload tests.

Each group should land with focused synthetic tests before relying on this
title's longer replay routes.

## 6. Data that must remain title-specific

Do not promote the following Metal Gear Acid 2 observations into shared
defaults:

- disc, executable, PRX, and savedata hashes;
- startup argument, register, stack, UID, and GE list values;
- module load paths, runtime bases, and dispatch table membership;
- framebuffer addresses and replay presentation numbers;
- renderer quality presets; and
- accepted visual hashes or benchmark thresholds.

The shared tool should provide schemas, generators, guards, and diagnostics for
these values. The title repository should continue to own their concrete
configuration and replay evidence.
