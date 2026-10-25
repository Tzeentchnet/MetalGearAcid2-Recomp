# Arena Performance Optimization Ledger

This document is the investigation handoff for the fixed-quality Arena
performance work. It records what was measured, which changes remain in the
worktree, which experiments were rejected, and where the next investigation
should begin.

The work is not complete. The Dead Cell profile has reached the steady-state
FPS and p95 targets in a diagnostic run, but still needs a clean acceptance
run. Arena gameplay still fails both CPU and GPU budgets.

## Acceptance contract

The primary target is the completed-save Arena Easy replay:

```powershell
python tools\mga2\benchmark_arena.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick
```

The memory-stick fixture must contain
`PSP\SAVEDATA\ULUS10077003\00000000.000` with a size of exactly 48,800
bytes. Game-derived saves, logs, captures, and generated code remain ignored.

The two default cases are:

| Case | Measurement start | Required presentation | Exit bound | Warm-up |
|---|---:|---:|---:|---:|
| Dead Cell introduction | 27,900 | 28,000 | 28,800 | 120 guest presentations |
| Arena gameplay | 37,900 | 38,000 | 38,800 | 120 guest presentations |

Each case measures 120 actual host flips. Acceptance uses the production paced
path and the following fixed profile:

- D3D12 renderer;
- 4x internal resolution;
- 2x xBRZ texture scaling;
- full-rate 1x1 shading;
- at least 59 displayed FPS;
- p95 no greater than 18 ms;
- no frame above 33.4 ms;
- no GPU sample above 16.68 ms;
- at most four cumulative framebuffer readbacks; and
- nonzero framebuffer aliases and ordered feedback snapshots.

`SR_NOVBPACE=1`, `SR_GEDUMP=1`, legacy feedback snapshots, forced fallback,
and reduced-quality profiles are diagnostic only and cannot produce an
acceptance pass.

## Measurement infrastructure added

The title now has shared benchmark support in
[`benchmark_common.py`](../tools/mga2/benchmark_common.py), the two-window
Arena driver in [`benchmark_arena.py`](../tools/mga2/benchmark_arena.py), and
Python regression coverage in
[`test_benchmark_common.py`](../tools/mga2/tests/test_benchmark_common.py).

Runtime profiling is:

- exclusive rather than nested;
- preserved across Windows fiber switches;
- emitted once per actual host presentation;
- aligned to the source host flip for delayed D3D12 timestamp queries; and
- split into scheduler, generated native guest, interpreter, HLE, GE command,
  vertex decode/transform, primitive assembly, patch evaluation, patch draw,
  synchronization, backend stages, and GPU time.

Workload counters include GE lists, commands, draws, submitted and uniquely
transformed vertices, backend batches and vertices, framebuffer aliases,
ordered feedback refreshes, safe reuses, physical snapshot pixels, readbacks,
and interpreter instructions.

This profiling established that interpreter fallback is not the primary Arena
bottleneck. It also showed that a faster or slower host frame changes which
guest presentations appear in a fixed 120-host-flip sample. Aggregate FPS must
therefore be interpreted together with matched workload counters, frame
percentiles, and aligned GPU samples.

## Baselines

The first fixed-quality two-window baseline was:

| Case | FPS | p95 | Maximum | Maximum GPU |
|---|---:|---:|---:|---:|
| Dead Cell introduction | 50.86 | 35.17 ms | 59.60 ms | Below budget |
| Arena gameplay | 54.90 | 33.26 ms | 56.33 ms | 24.48 ms |

A later gameplay profile, before partial feedback copies, measured 56.30 FPS,
31.63 ms p95, a 33.70 ms maximum, and a 24.47 ms maximum GPU sample. Its
expensive frame contained approximately:

- 801 transformed draws;
- 39,972 submitted transformed indices;
- 23,132 unique transformed vertices after deduplication;
- 118,950 captured backend vertices;
- 1,427 backend batches;
- 181 ordered feedback refreshes; and
- 59 safe feedback-snapshot reuses.

The different aggregate FPS values are caused by paced host/guest frame
selection. The expensive-frame workload is the useful comparison point.

## Changes retained

### 1. Separable spline and Bezier evaluation

**Root cause:** Dead Cell issues about 590 spline draws on an expensive frame.
The vertical `PatchColumn` intermediate depends on the V coordinate and U
segment, but the old evaluator recomputed it for every generated vertex.
Spline work alone reached approximately 31.6 ms.

**Changes:**

- compute vertical patch-column intermediates once per V row and U segment;
- reuse patch control, generated-vertex, and axis-parameter scratch storage;
- reuse projected patch-grid vertices;
- generate normals only when lighting, environment mapping, or normal-sourced
  texture generation consumes them; and
- capture patch triangles in one backend list.

**Measured result:** a diagnostic Dead Cell run reached 59.51 FPS and
17.67 ms p95. Vertex work averaged 5.75 ms and peaked at 12.48 ms. Patch
evaluation and patch draw work peaked at 6.03 ms and 3.06 ms.

**Correctness evidence:** D3D12 vertex hashes remained identical across the
refactor, including `cb55d899048a60c2` at backend presentation 12,480.

**Remaining caveat:** that run used `SR_GEDUMP=1`, produced 118 readbacks, and
therefore intentionally failed the readback gate. A clean non-diagnostic run
is still required.

### 2. Indexed transform deduplication

An indexed transformed-vertex cache uses direct entries for source indices
below 65,536 and generation tags to avoid clearing the complete cache for each
draw. On the expensive gameplay frame it reduces 39,972 submitted indices to
23,132 actual decode/transform operations.

The current code also stores sequence references to those direct-cache
vertices instead of copying a complete clip-space vertex for every submitted
index. Matched expensive frames improve primitive assembly by approximately
0.2-0.3 ms. Backend presentation 16,320 retains the exact vertex hash
`9e2c275cc17a3847`.

This is a small CPU improvement, not a solution to the frame budget.

### 3. Batched triangle capture

GE triangle lists, strips, fans, and patch grids collect projected triangles
for one draw before calling the D3D12 capture layer. This removes repeated
reserve and capture calls while preserving:

- cull-order and strip-parity handling;
- flat-shading provoking-vertex colors;
- near-plane clipping;
- per-subtriangle rejection;
- software and per-triangle fallback when batching fails; and
- the Vulkan fallback, whose optional list hook remains null.

The D3D12 unit test has been extended for list capture. The focused
`mga2_d3d12_vertex` CTest builds and passes.

### 4. Ordered partial framebuffer-feedback copies

**Root cause:** each feedback refresh copied the complete 2048x2048 physical
snapshot even when the draw sampled a very small PSP-space source rectangle.

The retained algorithm:

1. copies the complete target when the feedback target changes;
2. tracks all framebuffer draw rectangles dirtied since that snapshot;
3. refreshes the bounding union of the requested source and accumulated dirt;
4. clears dirty tracking because that union makes the snapshot globally
   current again; and
5. retains `SR_D3D12_LEGACY_FEEDBACK_SNAPSHOTS=1` for a full-copy
   differential.

On the expensive gameplay frame this preserves the original 181 refreshes and
59 safe reuses while reducing copied physical pixels from 759,169,024 to
16,030,000, a 97.9% reduction. In the paired `/O1` profile, maximum GPU time
improved from 24.47 ms to 21.22 ms. This is material, but still above the
16.68 ms gate.

Exact visual comparison against the legacy full-copy mode is still pending.

### 5. Release `/O2` generated code

Changing the generated game library from size-oriented `/O1` to `/O2`
required one full rebuild of all 361 generated translation units. The first
paced gameplay run improved aggregate throughput from 34.99 to 46.83 FPS, but
still measured 34.16 ms p95, a 34.76 ms maximum, and a 22.90 ms maximum GPU
sample.

`/O2` remains in the worktree as the appropriate release speed profile, but
one run does not prove that it solves native guest hotspots. It did not clear
the expensive-frame or GPU gates.

### 6. Destination-snapshot rectangles and redundant D3D12 state (branch `perf/arena-indexed-capture`)

**Root cause:** every manual (destination-aware) draw copied the complete
2048x1088 color target and complete depth target into the destination snapshot,
about 1.18 million times over the run, even though the pixel shader only loads
the destination at fragment positions inside the draw's vertex bounds.

**Changes (runtime only, no generated-code rebuild):**

- copy only the draw rectangle (plus one PSP pixel of margin) for both color
  and depth; `SR_D3D12_LEGACY_DESTINATION_SNAPSHOTS=1` restores full copies for
  differentials and is cleared by the benchmark harness;
- skip `OMSetRenderTargets`/viewport when the color/depth pair is already bound;
- skip `SetPipelineState`, texture/sampler descriptor tables, and scissor
  updates when unchanged within one command-list generation
  (`ged3d12_command_list_generation()`).

**Measured (single paced runs, 4x/2x/full-rate):**

| Case | Metric | Before | After |
|---|---|---:|---:|
| Gameplay | FPS | 51.87 | 56.39 |
| Gameplay | p95 | 33.88 ms | 31.40 ms |
| Gameplay | Maximum GPU | 22.39 ms | 10.98 ms |
| Dead Cell | FPS / p95 | not re-run | 59.94 / 16.71 ms (passes) |

The GPU gate now passes in both windows. Presented frames 37,950, 38,000 and
38,200 are byte-identical between the new and legacy snapshot modes. The
remaining gameplay gap is CPU (frontend/native guest, p95 31.4 ms), so the
ranked investigations below (native hotspot profile, per-draw CPU attribution)
are next. Indexed capture was deliberately not started: the GPU vertex cost it
targets is no longer the bottleneck.

## Experiments rejected or superseded

### Per-vertex cached raster projection

An exact projected position, reciprocal W, and premultiplied UV were stored in
each clip-space vertex so repeated triangle references could avoid another
perspective divide and viewport transform.

The experiment reached 48.38 FPS, 34.07 ms p95, and 21.62 ms maximum GPU time,
but enlarging every clip-space vertex increased decode/cache traffic. Matched
decode plus primitive cost did not improve consistently. The change was
reverted. Clipped/interpolated vertices had retained the original path, and
the exact hash at backend presentation 16,320 matched before the revert.

### Single valid feedback rectangle

Copying only each requested source rectangle reduced copied pixels by more than
99%, but tracked only one valid region. Refreshes increased from 181 to 240
and all 59 safe reuses disappeared. Maximum GPU time improved only to
approximately 22.36 ms. Superseded by dirty-union refreshes.

### Multi-region validity tracking

Tracking several valid source rectangles still produced zero safe reuses and
the old exit bound yielded only 101 host-flip samples. Superseded by the
extended exit bound and dirty-union model.

### Conservative dirty-region refresh

Refreshing requested regions without restoring global snapshot currency was
too conservative. It reached 37.57 FPS, 33.93 ms p95, and 21.39 ms maximum
GPU time, with up to 223 refreshes and only 17 reuses. Superseded by the
current union refresh.

### Per-HLE-call wall-time logging

Temporary wall-time logging attributed the one-time Dead Cell transition
outlier to blocking audio/event HLE calls, but those calls span scheduler
activity and the result was misleading. The logging was removed. A
120-presentation warm-up now excludes fast-forward-to-paced transition work
without hiding steady-state frames.

### Generated-code `/O2` as a standalone fix

`/O2` improves aggregate throughput but does not reduce the current gameplay
p95 below one 30 Hz interval and does not address the GPU limit. Further
compiler-level tuning without a native hotspot profile would be speculative.

## Current measured state

The latest run includes `/O2`, indexed transform deduplication, sequence
reference indirection, triangle-list capture, and dirty-union feedback:

| Metric | Latest gameplay run |
|---|---:|
| Displayed FPS | 33.61 |
| p95 | 34.07 ms |
| Maximum frame | 37.41 ms |
| Maximum GPU | 22.16 ms |
| Maximum generated native guest time | 16.94 ms |
| Maximum vertex decode/transform | 5.62 ms |
| Maximum primitive assembly | 11.20 ms |
| Maximum framebuffer synchronization | 4.19 ms |
| Maximum backend vertices | 118,950 |
| Maximum feedback refreshes / reuses | 181 / 59 |
| Maximum feedback copy area | 16,030,000 physical pixels |

The acceptance gaps are better expressed from the measured distribution than
by adding unrelated maxima:

| Gate comparison | Measured | Target | Required improvement |
|---|---:|---:|---:|
| Average frame time implied by 33.61 FPS | 29.75 ms | 16.95 ms for 59 FPS | 12.80 ms |
| Frame-time p95 | 34.07 ms | 18.00 ms | 16.07 ms |
| Maximum frame | 37.41 ms | 33.40 ms | 4.01 ms |
| Average aligned GPU time | 18.20 ms | 16.68 ms | 1.52 ms |
| Maximum aligned GPU time | 22.16 ms | 16.68 ms | 5.48 ms |

This sample contains more expensive guest frames than the preceding `/O2`
sample, so its 33.61 aggregate FPS is not evidence that the small vertex
indirection change regressed by 13 FPS. On matched 39,972-index frames,
primitive assembly is generally about 0.2-0.3 ms faster and decode time is
unchanged. The important conclusion is that the change is correct but far too
small.

The 16.94 ms native maximum occurs on the same captured host flip as the
37.41 ms maximum frame, so the native outlier is real. The primitive,
decode/transform, and synchronization maxima occur together on another flip,
and the GPU maximum occurs on a third. These maxima still must not be added as
if they were one frame. Representative expensive frames remain around 30 ms
frontend time plus 2.7-3.5 ms backend recording, while aligned GPU work
remains around 18-22 ms.

## Ranked next investigations

### 1. Rank generated native guest hotspots

Generated native guest execution averages approximately 10.3 ms, reaches
roughly 12.5 ms at p95 in the captured gameplay CSV, and peaks at 16.94 ms.
Interpreter fallback remains only about 0.2-0.4 ms. Native profiling is now the
first investigation because it is cheaper and more discriminating than an
architectural geometry or threading change.

System-wide WPR CPU sampling could not be enabled in the current environment
because the process lacks the required performance-profile policy. Use one or
more of:

- a bounded internal sampling thread that records main-thread instruction
  pointers into preallocated storage;
- bounded generated-function entry counters for exact call counts; or
- LLVM instrumentation/PGO data used first for ranking, not immediately as a
  shipped profile.

The guest fibers all execute on the main host thread. A diagnostic sampler
using `SuspendThread` must:

- pair every successful suspend with a resume;
- copy only the instruction pointer while the thread is suspended;
- defer symbolization, allocation, and file output until after resume;
- filter or classify samples outside generated guest address ranges; and
- remain strictly bounded to the presentation-38,000 window.

Instruction-pointer samples provide statistical residency, not exact call
counts or exact self time. Collect call counts separately, then inspect the
assembly of only the highest-ranked generated functions. Also compare a
matched diagnostic run with runtime profiling disabled or compiled out so the
measurement overhead itself is bounded.

Current code inspection rules out several blanket explanations:

- used integer guest registers are already held in host locals inside each
  generated function and synchronized around calls;
- normal guest memory accesses already use an inline masked address and direct
  base-pointer addition, with range and watched-VRAM checks rather than a page
  table;
- direct guest calls become native calls and `jr $ra` becomes a native return,
  while computed transfers still use dispatch-table lookup; and
- scheduler checks remain at function entries and loop backedges.

The profile should therefore test, rather than assume, idle polling loops,
computed-transfer frequency, watched-memory checks, excessive function
boundaries, and inefficient scalar or VFPU floating-point code. Apply only
the structural change demonstrated by the hottest functions.

### 2. Attribute per-draw CPU and GPU work

Do this before choosing indexed capture, texture-cache changes, draw merging,
or a GE worker.

#### CPU primitive and capture attribution

The 1,427-draw maximum is the total of approximately 801 transform draws and
626 through-mode draws. It is not 801 draws being split into 1,427 backend
batches; the backend receives approximately one batch per GE draw.

Across the captured frame rows, primitive time correlates strongly with both
draw count and transformed-vertex count. Those workload counters also move
together, so a frame-level fit cannot distinguish fixed per-draw cost from
per-vertex clipping, projection, and emission. Add bounded subphase timing and
counters for:

- vertex/index lookup, decode, skinning, transform, and lighting/texgen;
- primitive traversal, acceptance, clipping, projection, and ordering;
- framebuffer and pipeline-state capture;
- texture-key construction, quick/full hash bytes, hits, and verification;
- shader-state capture;
- draw and feedback bounds; and
- backend vertex/index emission.

Texture validation is a credible fixed-cost candidate. Textures at or below
64 KiB are fully hashed even by the quick-content path, larger textures are
sampled, and the first verification in a capture generation performs a full
hash. The complete run recorded approximately 1.48 million texture lookups,
1.476 million hits, and only 639 misses. A high hit rate does not make those
pre-hit hashes free.

#### GPU span and snapshot attribution

The measured adapter is an NVIDIA GeForce RTX 5070, not an integrated GPU.
At 4x PSP resolution, the remaining 18-22 ms therefore warrants explicit
draw, copy, barrier, and pixel-work attribution.

Compare the existing whole-frame timestamp span with the sum of timestamp
pairs around:

- direct fixed-function draws;
- manual destination-aware draws;
- destination color and depth snapshots;
- feedback transitions and copies;
- texture sampling and framebuffer-CLUT reconstruction;
- depth/stencil destination reads; and
- presentation.

Partial feedback reduced copied pixels by 97.9% and improved the worst GPU
sample by about 3.25 ms, making fixed refresh cost a credible hypothesis but
not yet proving that the 181 feedback refreshes dominate. Across the complete
run, the backend recorded approximately 1.18 million manual destination
snapshots versus 285,000 feedback snapshots. Add aligned per-frame counters
before comparing those paths, because the cumulative totals include startup
and other scenes.

Framebuffer textures sourced from a non-active target already bind that target
directly. Do not duplicate that optimization. Instead, classify why each
manual draw misses the fixed-function path: stencil behavior, logic operation,
RGB write masks, framebuffer format, dithering, fixed-color factors, or another
destination-dependent operation. If unsupported blend cases dominate, test
expanded fixed-function or dual-source blending. If exact same-target
read/modify/write dominates and hardware capabilities permit it, evaluate a
rasterizer-ordered UAV path. Both require differential output tests and must
remain fallbacks, not assumptions.

xBRZ is unlikely to explain the measured steady-state spikes: the full run
performed only 639 texture uploads, and backend texture preparation peaks near
0.003 ms in the current window.

### 3. Preserve indexing through the PC-native D3D12 capture boundary

This remains the highest-confidence frontend implementation candidate after
the attribution above. The GE now transforms 23,132 unique source vertices but
expands them to as many as 118,950 non-indexed backend vertices.

A proper implementation should:

- add an optional indexed-triangle hook to `GeBackend`;
- build one projected vertex table and an ordered index list per GE draw;
- preserve cull reversal and strip parity in index order;
- append explicit vertices for near-clipped intersections without moving
  clipped triangles out of their original order;
- retain expanded vertices for flat shading unless provoking-color semantics
  are represented exactly;
- upload and bind a D3D12 index buffer;
- issue `DrawIndexedInstanced`;
- compute draw and feedback bounds from referenced vertices;
- preserve the existing software/Vulkan fallback; and
- add unit tests for Gouraud, flat, clipped, rejected, and allocation-failure
  cases.

Do not begin by changing the shader or reducing quality. The current vertex
shader already consumes `SV_VertexID`, which should remain compatible with an
indexed draw because `DrawIndexedInstanced` supplies the resolved index value.
The index format should be selected from the projected table size, using
`DXGI_FORMAT_R16_UINT` only when all referenced vertices fit.
Do not partition a draw into all-unclipped followed by all-clipped triangles:
that changes primitive order when the two kinds are interleaved. Keep one
ordered index stream, or flush mixed indexed/expanded segments in source order.
Likewise, adding HLSL `nointerpolation` alone does not prove PSP last-vertex
provoking-color equivalence. The current backend explicitly copies the third
vertex color to the complete flat-shaded triangle.

For an unclipped flat-shaded triangle, a flat pixel-shader variant plus cyclic
rotation from `(a,b,c)` to `(c,a,b)` can represent PSP last-vertex color while
preserving winding. Clipping may remove that original provoking vertex or
produce multiple triangles, so every emitted triangle must still receive the
original primitive color. Retain duplication or an expanded fallback for
those cases until Gouraud, flat, and clipped differential tests prove exact
behavior.

Evaluate this change on matched expensive frames. In addition to output hashes
and geometry counters, measure primitive assembly, backend recording and
upload time, and aligned GPU vertex work. Retain the indexed path only where it
reduces repeated work without changing output; the expanded path remains
necessary when clipping or provoking-color behavior cannot be represented
exactly. This is the best-supported frontend opportunity, but it may not by
itself clear the remaining GPU budget.

Do not assign the complete 11.20 ms primitive maximum to vertex expansion.
That category also contains primitive traversal, culling, clipping, projection,
and capture. In the current sample, backend vertex staging itself peaks at
0.27 ms. The 5.62 ms `vertex_decode_ms` maximum similarly covers decoding,
skinning, transform, lighting, texture-coordinate generation, and acceptance
checks for unique vertices; it is not a measurement of packed-format
conversion alone. Indexed capture therefore has no defensible 6-8 ms expected
saving until its subphases are measured.

### 4. Evaluate asynchronous GE execution only after tracing safe overlap

The current list manager runs synchronously on the guest host thread. A worker
could overlap GE decode, transform, and assembly with generated guest work, but
a raw command ring is insufficient. Lists stall and resume, raise callbacks,
and reference vertex, index, texture, CLUT, and framebuffer memory that the
guest may subsequently modify.

Before designing a worker, trace:

- list enqueue, first execution, stall, resume, completion, and required sync;
- time between enqueue and `sceGeListSync`, `sceGeDrawSync`, or another
  observable dependency;
- guest writes to ranges referenced by in-flight lists;
- callback and interrupt ordering; and
- the amount of GE work that could actually overlap native execution.

The current D3D12 command recording occurs during presentation, not GE list
processing. Moving the GE frontend alone therefore does not automatically
overlap the 2.7-3.5 ms backend phase. Moving command recording too would also
require thread-safe resource-state, descriptor, upload, and presentation
handoff.

Proceed only if the trace shows substantial safe queue slack. A complete
design needs explicit memory ownership or snapshots, double-buffered capture,
ordered interrupts/readbacks/presentation, and the same floating-point mode on
the worker thread. Validate all acceptance and regression routes; limiting the
runtime to one title does not remove those observable hazards.

## Secondary investigations and correctness gates

### Reduce D3D12 command-recording overhead

The expensive gameplay frame reaches 1,427 backend batches and 118,950
captured vertices. Measure CPU time spent recording commands, changing
pipeline and descriptor state, and uploading geometry. The backend already has
three fenced frame contexts, a 32 MiB per-frame upload ring, and fenced
overflow slabs. If recording costs remain material:

- reuse pipeline and descriptor state when the effective state is unchanged;
- batch only adjacent direct-path operations whose ordering and complete
  render state are identical; and
- specialize alpha/color-test-free direct draws only if GPU attribution shows
  a discard or early-depth cost.

Do not merge manual destination-aware draws merely because their keys match:
each snapshot observes preceding output. Do not merge across feedback,
synchronization, or render-state boundaries, and do not globally sort draws.

### Check CPU-GPU overlap and waits

Use the same bounded timeline to identify queue submissions, waits, and idle
periods. Determine whether the CPU blocks on GPU completion, the GPU is starved
while command recording runs, or synchronization serializes otherwise
independent work. Optimize only the wait or submission pattern demonstrated by
the trace. Backend begin currently peaks near 0.15 ms and measured gameplay
readbacks remain zero, so `sync_ms` does not by itself prove a frame-fence
wait. Split watched-VRAM lookup, transfer, readback, and actual wait time.
Increasing queue depth blindly can add latency without improving throughput.

### Validate partial-feedback visual equivalence

Capture exact aligned Dead Cell and gameplay presentations with current
dirty-union snapshots and with
`SR_D3D12_LEGACY_FEEDBACK_SNAPSHOTS=1`. Compare logical output, internal
resolution output, snapshot/reuse counters, and source host flips. Retain the
partial path only if ordered output matches.

### Close the Dead Cell acceptance result

Run the Dead Cell case without `SR_GEDUMP`, then repeat it three times if the
first run passes. This should be done before any broad native subsystem
replacement so the solved spline workload remains a regression gate.

## Directions to keep deprioritized

- Do not pursue more generic `/O2` tuning before the native hotspot profile.
  The retained `/O2` build improves throughput but has not cleared the frame or
  GPU budgets.
- Do not restore per-vertex projection caching without new evidence. The prior
  experiment increased decode/cache traffic and did not consistently improve
  matched frontend cost.
- Do not treat lower internal resolution, reduced shading, variable-rate
  shading, disabled feedback, or unpaced FPS as acceptance fixes. They remain
  useful diagnostics only.
- Do not prioritize interpreter optimization while fallback remains about
  0.2-0.4 ms on expensive frames.
- Do not reserve a flat 4 GiB guest mapping or enable strict-aliasing changes
  before a hot generated function attributes time to address translation.
- Do not implement a GE worker before enqueue-to-sync tracing demonstrates
  substantial safe overlap.

The practical sequence is: close the clean Dead Cell gate; rank native guest
hotspots and inspect only their assembly; add per-draw CPU and GPU attribution;
apply the measured structural fix; then choose indexed capture, texture-cache
work, or a destination-snapshot reduction from the evidence. Attempt a GE
worker only if queue-slack tracing justifies it. After each candidate, rerun
the fixed-quality acceptance cases and compare matched workload frames, frame
percentiles, aligned GPU samples, and geometry/readback counters rather than
headline FPS alone.

## Assessment of additional architectural proposals

### SIMD vertex decoding

Format-specialized SIMD remains a possible follow-up, but AVX2 intrinsics
should not be added before splitting `vertex_decode_ms` into packed-format
decode, skinning/T&L, lighting/texgen, and acceptance work, with counts by
dominant `vtype`. The source records are variably aligned and interleaved, so
`_mm256_stream_load_si256` is not a safe general load and non-temporal access
may be slower for reused guest data. Any SIMD path must retain a portable
fallback, use unaligned loads where required, and demonstrate a gain on the
actual Arena format mix.

### Draw merging, bindless resources, and alpha-test specialization

The maximum 1,427 GE draws comprise approximately 626 through-mode and 801
transform draws, with approximately one captured backend batch per guest draw.
This does not reveal how many adjacent batches have identical complete state.
Current CPU draw recording averages 2.27 ms and peaks at 4.00 ms, so reducing
redundant binds is measurable. Merge only adjacent direct-path batches with
identical pipeline, framebuffer, texture, sampler, shader constants, and
synchronization semantics.

Manual draws cannot generally be merged even when their visible state keys
match: each one snapshots the destination produced by preceding draws.
Bindless resources also do not remove per-draw texture dimensions, sampler,
CLUT, destination-read, or feedback state. The shaders already target Shader
Model 6.0, but a bindless redesign should remain behind GPU attribution rather
than being treated as a prerequisite for adjacent-state reuse.

A direct-pixel-shader permutation with no discard is a narrower candidate if
PIX shows alpha-test or overdraw cost. It must be selected only when alpha and
color tests are disabled or provably always pass for the complete draw.
Do not sort opaque or alpha-tested draws front-to-back; framebuffer feedback,
blending, and destination reads make order observable.

### CLUT handling

Ordinary paletted textures are already decoded to RGBA8 on the CPU and cached
with the CLUT state in the texture key. Runtime dependent CLUT lookup remains
for framebuffer-feedback aliases, where the source image changes in draw order.
A compute predecode is therefore not a general texture-cache fix and could add
another ordered pass. Profile the framebuffer-CLUT path separately before
changing it.

### Guest address translation and floating-point mode

Guest memory already uses a masked physical address followed by direct
base-pointer addition. The remaining checks preserve scratchpad aliases,
out-of-range behavior, and lazy framebuffer read/write synchronization.
Reserving a flat 4 GiB mapping would not remove those requirements and should
not precede a generated-function profile that attributes time to memory
helpers.

DAZ and FTZ are already enabled by `sr_configure_fpu()` during memory/runtime
initialization. Guest fibers share that host thread and MXCSR state. Configure
the same mode explicitly only if guest or GE work is later moved to another OS
thread.

### Impact estimates

Treat proposed multi-millisecond savings as hypotheses, not roadmap targets.
Indexed capture, native hotspot fixes, draw merging, alpha-test specialization,
and threading all require matched-frame measurements before an expected impact
is recorded.

## Efficient build and measurement loop

Do not clean or regenerate between runtime edits:

```powershell
cmake --build --preset clang-cl --target mga2_driver
```

After a `psp-recomp` `src/rt/ge.c` change, Ninja currently rebuilds one object
and relinks the executable. The no-change command reports
`ninja: no work to do`.

Changing generated-code compiler options rebuilds all 361 generated
translation units. Batch such changes, perform one full build, benchmark that
exact binary, and avoid toggling the option between runtime experiments.

During iteration:

1. build the targeted executable;
2. run one selected Arena case;
3. compare matched workload rows, not only aggregate FPS;
4. verify a known D3D12 vertex hash when geometry code changes;
5. keep a change only when its relevant subphase improves; and
6. defer the full two-case and three-run matrix until a candidate clears the
   single-case gate.

## Validation at this pause point

Completed:

- clang-cl Release build with all 361 generated translation units;
- incremental `mga2_driver` rebuild after the final GE change;
- all eight Python benchmark-helper tests;
- focused `mga2_perf_stats` CTest;
- focused `mga2_d3d12_vertex` CTest;
- shared runtime commit `3de8644` pushed and pinned by full hash; and
- `git diff --check` in both repositories.

Still required:

- Run a clean Dead Cell acceptance sample.
- Perform current-versus-legacy partial-feedback visual differentials.
- Reach all four fixed-quality gates in both Arena windows for three
  consecutive paced runs.
- Re-run the tutorial benchmark and Stage 01 route.
- Smoke-test at least one additional Arena selection.
- Run the relevant shared runtime suite and final Release build.
- Repeat native-versus-interpreted visual checks.

## Local artifact index

The following ignored directories contain the most useful reduced reports and
logs for continued local investigation:

| Directory | Purpose |
|---|---|
| `out\benchmarks\arena-profile-dead-cell` | Initial detailed Dead Cell profile |
| `out\benchmarks\arena-patch-subphase-dead-cell` | Optimized spline subphase profile; diagnostic readbacks |
| `out\benchmarks\arena-gameplay-profile-current` | Gameplay profile before partial feedback |
| `out\benchmarks\arena-gameplay-ordered-partial` | Rejected conservative dirty-region attempt |
| `out\benchmarks\arena-gameplay-union-feedback` | Retained dirty-union feedback at generated `/O1` |
| `out\benchmarks\arena-gameplay-o2` | First generated `/O2` gameplay run |
| `out\benchmarks\arena-gameplay-projection-cache` | Reverted projection-cache experiment |
| `out\benchmarks\arena-gameplay-vertex-indirection` | Current vertex-reference experiment |

The shared runtime changes were committed and pushed as `3de8644`. The title
changes are committed by the repository revision containing this document. Do
not remove the existing untracked runtime `build\` directory or
`interp_fallback_test.misses`.
