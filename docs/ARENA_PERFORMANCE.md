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

This sample contains more expensive guest frames than the preceding `/O2`
sample, so its 33.61 aggregate FPS is not evidence that the small vertex
indirection change regressed by 13 FPS. On matched 39,972-index frames,
primitive assembly is generally about 0.2-0.3 ms faster and decode time is
unchanged. The important conclusion is that the change is correct but far too
small.

Maxima above occur on different host flips and must not be added as if they
were one frame. Representative expensive frames remain around 30 ms frontend
time plus 2.7-3.5 ms backend recording, while aligned GPU work remains around
18-22 ms.

## Ranked next investigations

### 1. Preserve indexing through the PC-native D3D12 capture boundary

This is the highest-confidence frontend opportunity. The GE now transforms
23,132 unique source vertices but expands them to as many as 118,950
non-indexed backend vertices.

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
indexed draw after the D3D12 buffer and batch metadata are wired correctly.
Do not partition a draw into all-unclipped followed by all-clipped triangles:
that changes primitive order when the two kinds are interleaved. Keep one
ordered index stream, or flush mixed indexed/expanded segments in source order.
Likewise, adding HLSL `nointerpolation` alone does not prove PSP last-vertex
provoking-color equivalence. The current backend explicitly copies the third
vertex color to the complete flat-shaded triangle.

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

### 2. Add a low-overhead native guest hotspot profile

Generated native guest execution still reaches roughly 11-17 ms on expensive
gameplay frames. Interpreter fallback is only about 0.2-0.4 ms.

System-wide WPR CPU sampling could not be enabled in the current environment
because the process lacks the required performance-profile policy. The next
profile should therefore use one of:

- an internal sampling thread that records native instruction pointers and
  symbolizes them against generated functions;
- bounded generated-function instrumentation in a diagnostic build; or
- LLVM instrumentation/PGO data used first for ranking, not immediately as a
  shipped profile.

The guest fibers all execute on the main host thread. A diagnostic sampler that
uses `SuspendThread` must preallocate its storage, guarantee that every
successful suspend is paired with a resume, and remain strictly bounded to the
benchmark window. It yields statistical sample counts, not exact function call
counts. Collect call counts separately with bounded entry instrumentation; do
not report sampled instruction pointers as exact exclusive timings.

The objective is a ranked list of generated guest functions with self time and
call count during the presentation-38,000 window. Only then should a PSP
subsystem be replaced with PC-native code. Start with targeted changes in the
highest-ranked functions, such as removing redundant state loads, bounds
checks, or repeated calculations, and measure each change against the same
gameplay window. Instrumentation and PGO are ranking tools first, not presumed
runtime fixes.

### 3. Attribute the remaining 4x GPU time

Partial feedback removed most copy area but only about 3.25 ms of maximum GPU
time. A bounded PIX or timestamp profile should separate:

- direct fixed-function draws;
- manual destination-snapshot draws;
- feedback copy/barrier work;
- texture sampling and CLUT reconstruction;
- depth/stencil destination reads; and
- overdraw from the 1,427-draw Arena frame.

Full-rate shading and 4x internal resolution are fixed acceptance
requirements. Variable-rate shading, lower resolution, and disabled feedback
are diagnostics, not fixes.

Do not globally sort or reorder draws while pursuing the dominant GPU
category. PSP blending, destination reads, and framebuffer feedback make draw
order observable.

## Secondary investigations and correctness gates

### Reduce D3D12 command-recording and upload overhead

The expensive gameplay frame reaches 1,427 backend batches and 118,950
captured vertices. Measure CPU time spent recording commands, changing
pipeline and descriptor state, and allocating or uploading geometry. If those
costs are material:

- reuse pipeline and descriptor state when the effective state is unchanged;
- use a well-sized upload ring rather than creating avoidable transient
  allocations; and
- batch only adjacent operations whose ordering and complete render state are
  identical.

Do not merge across observable feedback, synchronization, or render-state
boundaries.

### Check CPU-GPU overlap and waits

Use the same bounded timeline to identify queue submissions, waits, and idle
periods. Determine whether the CPU blocks on GPU completion, the GPU is starved
while command recording runs, or synchronization serializes otherwise
independent work. Optimize only the wait or submission pattern demonstrated by
the trace. Increasing queue depth blindly can add latency without improving
throughput.

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

The practical optimization sequence is indexed D3D12 capture, generated-code
hotspot ranking, GPU attribution, and then a targeted change to the measured
dominant cost. After each candidate, rerun the fixed-quality acceptance cases
and compare matched workload frames, frame percentiles, aligned GPU samples,
and geometry/readback counters rather than headline FPS alone.

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

The maximum 1,427 GE draws and 1,427 backend batches indicate approximately
one captured batch per guest draw, but not how many adjacent batches have
identical complete state. Current CPU draw recording averages 2.27 ms and
peaks at 4.00 ms, so reducing redundant binds is measurable. Merge only
adjacent direct-path batches with identical pipeline, framebuffer, texture,
sampler, shader constants, and synchronization semantics.

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

### Asynchronous GE execution and synchronization

The current GE list manager executes synchronously on the guest host thread.
Moving it to a worker could overlap work, but a raw command ring is
insufficient: lists can stall and resume, raise callbacks, and reference
vertex, texture, CLUT, and framebuffer memory that the guest can subsequently
modify. A worker design needs explicit ownership or snapshots for all referenced
memory plus ordered interrupt, readback, and present handoff.

The D3D12 backend already has three fenced frame contexts, a 32 MiB per-frame
upload ring with fenced overflow slabs, and records destination/feedback copies
and barriers on the direct command list. In the current gameplay sample,
backend begin peaks at 0.15 ms and per-frame framebuffer readbacks remain zero.
The 4.19 ms `sync_ms` maximum therefore does not by itself prove a GPU fence
stall. Split it into watched-VRAM lookup, transfer, readback, and actual wait
subphases before considering a GE worker or deeper queueing.

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
