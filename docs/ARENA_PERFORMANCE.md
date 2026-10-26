# Arena Performance Optimization Ledger

This document is the investigation handoff for the fixed-quality Arena
performance work. It records what was measured, which changes remain in the
worktree, which experiments were rejected, and where the next investigation
should begin.

The retained configuration passes the fixed profile for the Dead Cell
introduction and Fortune transition. Arena gameplay remains the limiting case:
the latest post-`/O2` run is substantially improved over the unoptimized
runtime, but still misses the fixed gameplay gate.

The benchmark driver now supports `--tail-presents` to keep the runtime alive
long enough to collect a complete sample window after a slow scene, and
`--fortune-extra-presents` plus `--fortune-window` for longer transition
diagnostics. The runtime currently caps `SR_PERF_WINDOW` at 600 samples.
Each result records wall-clock duration so startup/iteration cost is visible
separately from frame time.

Vulkan now passes the software-referenced visual gate at the Dead Cell and
Arena gameplay checkpoints, including the player, stage, and map preview. It
is therefore a valid native-resolution visual control. It remains unsuitable
for attributing D3D12 performance regressions because Vulkan still renders its
GE targets at native resolution and uses a different synchronization model;
performance comparisons must not treat those workloads as equivalent.

The historical focused post-`/O2` measurements counted host flips, including
repeated copies of the same guest frame. They therefore did not represent
gameplay FPS:

| Case | Host-flip FPS | Delivered FPS | Delivered p95 | Result |
|---|---:|---:|---:|---|
| Fortune transition | 59.94 | 36.11 | 33.81 ms | Historical run; not valid for acceptance |
| Arena gameplay | 49.58 | 30.79 | 34.47 ms | Historical run; not valid for acceptance |

The old harness also fast-forwarded to the sample, suppressing XAudio2 until
the warm-up point and changing cache and timing history. Acceptance now starts
and plays the route in real time, reports host-flip and newly delivered guest
frame rates separately, and fails on XAudio2 dropped frames, underruns, excess
padding transitions, or voice errors. `--fast-forward` remains available only
for diagnostics and cannot produce an acceptance pass.

The first corrected full-route Fortune run
(`out\benchmarks\arena-delivery-realtime`) measured 59.94 host flips/s but
30.99 newly delivered frames/s. Delivered-frame p95 was 33.37 ms and the
maximum was 34.76 ms. Continuous XAudio2 playback covered 196.97 seconds with
zero dropped frames, underruns, extra padding transitions, or voice errors.
This establishes that the former 59.94 result was refresh cadence, not game
FPS, while this run's Fortune segment maintained a stable approximately
30 FPS delivery cadence.

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

The Fortune transition is an explicit third case so the historical meaning of
`--case both` remains unchanged:

| Case | Measurement start | Required presentation | Exit bound | Warm-up |
|---|---:|---:|---:|---:|
| Vamp-to-Fortune transition | 29,280 | 29,307 | 30,000 | 480 guest presentations |

Use `--case fortune` for its focused gate or `--case all` for all three cases.
Each case measures 120 host flips and derives delivered-frame intervals from
changes in the guest presentation associated with each flip. Acceptance uses
the production paced path, full real-time startup and audio playback, and the
following fixed profile:

- D3D12 renderer;
- 4x internal resolution;
- 2x xBRZ texture scaling;
- full-rate 1x1 shading;
- at least 59 displayed FPS;
- at least 29 newly delivered game frames per second;
- p95 no greater than 18 ms;
- no frame above 33.4 ms;
- delivered-frame p95 no greater than 35 ms;
- no delivered frame above 50 ms;
- no GPU sample above 16.68 ms;
- no audio drops, underruns, excess post-startup padding transitions, or
  XAudio2 voice errors;
- at most four cumulative framebuffer readbacks; and
- nonzero framebuffer aliases and ordered feedback snapshots.

`SR_NOVBPACE=1`, `SR_GEDUMP=1`, legacy feedback snapshots, forced fallback,
and reduced-quality profiles are diagnostic only and cannot produce an
acceptance pass.

## Measurement infrastructure added

The title now has shared benchmark support in
[`benchmark_common.py`](../tools/mga2/benchmark_common.py), the two-window
Arena driver plus the explicit Fortune case in
[`benchmark_arena.py`](../tools/mga2/benchmark_arena.py), and
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

**Historical caveat:** that run used `SR_GEDUMP=1`, produced 118 readbacks,
and therefore intentionally failed the readback gate. The clean current-profile
rerun recorded below passes every acceptance gate with two cumulative
readbacks.

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

### 7. Native sampling result: texture hashing and per-iteration `getenv`

The section-1 IP sampler is now in the runtime (`SR_SAMPLE_START=<present>`,
`SR_SAMPLE_WINDOW=<presents>`, `SR_SAMPLE_FILE=<path>`; helper thread
suspends the main thread, copies only RIP, resumes). The executable now links
with `/MAP` (link-only change); out-of-executable samples are classified by
module in `<file>.modules.txt`. A paced gameplay window showed:

- about 18% of all samples (about 25% of in-executable time) in
  `texture_content_hash` and the CLUT hash in `ged3d12_texture_key_build`,
  because textures up to 64 KiB and the 2 KiB CLUT were hashed with byte-wise
  FNV on every draw. Replaced by a four-lane 64-bit-word hash
  (`ged3d12_hash64`); texture hash share fell to about 1%.
- about 45-55% of main-thread samples inside CRT `getenv`: the scheduler loop,
  HLE calls, and GE ops queried the environment on every iteration. A cached
  `getenv` for string literals (`sr_env.h`) removes it.
- `project_cvtx` and the acceptance block decoded six viewport floats per
  vertex; they now share a viewport/offset cache.

Presented frames 37,950, 38,000 and 38,200 remain byte-identical to the
earlier build. No generated translation unit was rebuilt.

| Run (4x/2x/full-rate, paced) | Dead Cell FPS / p95 | Gameplay FPS / p95 | Gameplay max GPU |
|---|---:|---:|---:|
| Before section 6 | not run | 51.87 / 33.88 ms | 22.39 ms |
| After section 6 | 59.94 / 16.71 ms | 56.39 / 31.40 ms | 10.98 ms |
| After section 7, runs 1-3 | 59.94 / 16.8-17.6 ms | 59.94 / 16.8-17.6 ms | about 10.4 ms |

Both Arena windows passed all gates in three consecutive paced runs, and the
tutorial benchmark passes (60.42 FPS, 17.33 ms p95).

### 8. Indexed triangle capture, attribution, and validation

**Indexed capture (section 3 of the ranked list).** `GeBackend` has an optional
`tri_indexed` hook. For unclipped Gouraud triangles whose vertices come from the
indexed transform cache, `ge.c` records one projected vertex table plus an
ordered 16-bit index list per run of such triangles; the D3D12 backend uploads
the table and an index buffer and issues `DrawIndexedInstanced` (the vertex
shader's `SV_VertexID` raw load works unchanged). Clipped triangles, flat
shading, clear mode, non-cache vertices, tables above 65,535 vertices and
`SR_RTRACE` keep the expanded path; the two kinds flush in submission order
whenever the kind changes, and a declined backend call replays through
`raster_tri`. `SR_D3D12_NO_INDEXED=1` disables it for differentials.

- The expensive gameplay frame's backend vertices fall from 118,950 to 44,644.
- Primitive-assembly time is essentially unchanged (mean 1.93 -> 1.68 ms, max
  4.65 -> 5.03 ms), confirming the doc's warning that vertex expansion was only
  a small part of that category. Gameplay p95 is now pinned at the 16.69 ms
  vblank interval (previously 16.8-17.6 ms).
- Three consecutive paced runs of both windows passed after the change.
- New unit test `test_indexed_triangles` (valid list, out-of-range index,
  partial triangle, merge isolation, index upload) passes.
- Presented frames are byte-identical with indexed capture on and off.

**Manual-draw attribution (section 2, GPU side).** `SR_D3D12_VERTEX_LOG=1` now
prints why draws miss the fixed-function path. Cumulative over the first 38,300
presentations (1,138,834 manual vs 773,551 direct draws): non-8888 framebuffer
format with blending 62%, stencil state 31%, stencil-write plus source/dest
alpha factors 3%, clear 1%, logic op / RGB mask / dither / equation 0%. A
fixed-function path for blending into 16-bit framebuffers is therefore the
largest remaining GPU opportunity; it needs quantization-exact differential
tests and was not attempted because the GPU gate already passes (about 10.4 ms).

**Validation completed on this branch.**

- Legacy-versus-current feedback snapshots (`SR_D3D12_LEGACY_FEEDBACK_SNAPSHOTS`)
  and destination snapshots (`SR_D3D12_LEGACY_DESTINATION_SNAPSHOTS`):
  presented frames 27,950/28,000/28,200 (Dead Cell), 37,950/38,000/38,200
  (gameplay) and 45,000/45,200 (later Arena route) are byte-identical.
- Dead Cell passed three consecutive paced runs (59.94 FPS; p95 16.82, 17.21,
  16.69 ms; max frame at most 17.75 ms).
- Tutorial benchmark passes (60.44 FPS, 16.92 ms p95).
- Python helper tests (8) and all five CTests pass.
- Not repeated: native-versus-interpreted comparison (no change touches
  generated code or the interpreter) and the Stage 01 route (no change touches
  its paths beyond the shared GE/D3D12 code exercised above).

### 9. Draw merging, capture subphases, and GE overlap trace

**Draw merging.** `record_vertex_batches` now draws adjacent direct-path batches
as one call when the list, primitive, perspective, color/depth handles,
pipeline key, shader constants and texture binding are identical, the vertex
ranges are contiguous, the batch is not indexed, and neither the texture nor
the CLUT is a framebuffer alias. Dirty bounds are unioned for the framebuffer
mark. Manual (destination-aware) draws are never merged. Over the first 38,300
presentations 193,164 of 765,000 direct batches (about 25%) were merged
(`SR_D3D12_VERTEX_LOG=1` prints the running count). Presented frames remain
byte-identical.

**Per-draw CPU subphases (section 2).** The performance CSV gains
`capture_ms`, `texture_capture_ms` and `state_capture_ms` (backend list/index
capture; texture key, hash and lookup; pipeline key, framebuffer capture and
shader-constant build), and `vertex_ms` includes them. On the busiest
gameplay frame (profiling on): vertex decode/transform 4.3-4.8 ms, state
capture 2.0 ms, texture capture 0.7 ms, backend capture 0.3 ms, primitive
traversal 0.6 ms. Framebuffer capture is now memoized per capture generation
(no change in output); the remainder of state capture is pipeline-key and
shader-constant construction per draw, which would need register-dirty
tracking to avoid.

**Asynchronous GE (section 4) - trace only.** `SR_GETRACE=1` estimates how much
GE list execution could overlap guest execution (time in guest/scheduler code
between an unsynchronized chunk and the next `sceGeDrawSync`/`ListSync`). In a
paced gameplay window the GE spent about 6.4 ms per sync interval against about
10.9 ms of guest/idle time, so up to about 94% of the GE time sits behind slack
that a worker could use. That slack includes scheduler idle time and the trace
does not cover guest writes to memory referenced by in-flight lists, list
stall/resume ordering, or interrupt ordering, all of which the doc requires
before a design. No worker was implemented: the gates already pass without one,
and the correctness hazards are not yet measured.

**Native versus interpreted.** Without a pad script (so input timing cannot
diverge), `SR_DISABLE_NATIVE_MODULES=*` and the native build produce
byte-identical presented frames at presentations 2,000, 2,400, 8,000 and 8,400
(the latter pair is a non-trivial 32-color image). With the Arena pad script the
interpreted run diverges in input timing, so only visual equivalence applies there.

**Not implemented.** Fixed-function blending into 16-bit framebuffers (62% of
manual draws): the shader reads the 565/5551/4444 destination, blends in 8-bit,
and re-quantizes with PSP rounding; fixed-function blending on the internal
8888 target cannot reproduce that final quantization bit-exactly, so it is not a
safe replacement, and the GPU gate already passes with about 10.4 ms maximum.

**State memo.** The pipeline key and shader constants are pure functions of the
GE state and captured texture binding, so `begin_primitive` reuses the previous
result when the complete `GeState` (ignoring vertex/index pointers) and the
texture binding are unchanged. `SR_D3D12_VERIFY_STATE_MEMO=1` rebuilds on every
reuse and aborts on a mismatch; it ran clean over presentations 27,000-28,201,
37,000-38,201 and 44,000-45,201. State capture on the busiest gameplay frame
fell from about 2.0 ms to about 1.6 ms (profiling on). Three consecutive paced
runs of both windows then passed, with gameplay maximum frame 16.69-16.81 ms
(no missed vblanks) and p95 16.68 ms.

Final matrix: three more paced runs of both windows passed 2/3; run 3 had a
sustained stretch of 33.4 ms frames in gameplay (58.0 FPS) at an unchanged
workload, so the margin over the vblank interval is still thin on heavy frames.

## Current-profile Dead Cell acceptance rerun (2026-10-25)

The current `mga2.exe` was tested with the production paced path and the active
graphics profile: D3D12, 4x internal resolution, 2x texture scaling, and
full-rate 1x1 shading.

```powershell
python tools\mga2\benchmark_arena.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick `
  --case dead-cell `
  --output out\benchmarks\dead-cell-current-20261025-0936
```

| Metric | Result | Gate |
|---|---:|---:|
| Host-flip samples | 120 | 120 |
| Displayed FPS | 59.94 | at least 59 |
| Frame-time p95 | 17.03 ms | at most 18 ms |
| Maximum frame | 17.39 ms | at most 33.4 ms |
| Average aligned GPU time | 1.60 ms | informational |
| Maximum aligned GPU time | 3.24 ms | at most 16.68 ms |
| Cumulative framebuffer readbacks | 2 | at most 4 |
| Framebuffer aliases | 63,120 | nonzero |
| Ordered feedback snapshots | 47,422 | nonzero |

The run passed every acceptance gate. Frontend time averaged 15.88 ms and
backend recording averaged 0.81 ms. Patch evaluation averaged 2.76 ms and
peaked at 5.63 ms; patch drawing averaged 0.69 ms and peaked at 1.46 ms.

## Vamp-to-Fortune transition diagnosis (2026-10-25)

The passing Dead Cell window does not include the later camera cut reported as
a slowdown. Its latest sample ends at presentation 28,319. A visual-only
capture sweep located the relevant boundary:

- presentation 29,292 is the last Vamp frame;
- presentation 29,293 begins the new camera shot; and
- Fortune first enters the frame at presentation 29,307.

Three capture-free paced profiles used the production D3D12 4x/2x/full-rate
configuration. Each recorded 300 host flips from presentation 28,802 through
29,845. The GE workload begins increasing on the flip recorded at presentation
29,287, immediately before the visible cut. The first post-cut render sample at
presentation 29,294 contains:

| Workload | Vamp | First post-cut sample |
|---|---:|---:|
| Total GE draw commands | 920 | 1,918 |
| Through-mode primitive draws | 243 | 243 |
| Transform primitive draws | 87 | 67 |
| Derived spline commands | 590 | 1,608 |
| Derived spline control vertices | 9,440 | 25,728 |

`ge_draws` counts primitive, Bezier, and spline commands, while the through and
transform counters count primitive commands only. Bezier time is zero in both
shots, so subtracting the two primitive counts gives the spline count. Every
spline command in this sequence consumes 16 control vertices. Fortune settles
at 1,473-1,581 spline commands and 23,568-25,296 spline control vertices per
rendered frame, versus exactly 590 and 9,440 for Vamp.

The two runs without unrelated host outliers measured the following matched
render-row averages:

| Metric | Vamp | Fortune |
|---|---:|---:|
| Heavy render-frame time | 16.66-16.87 ms | 22.10-22.45 ms |
| Active CPU time excluding scheduler idle | 10.77-11.47 ms | 21.86-22.18 ms |
| Complete vertex/patch phase | 8.51-8.92 ms | 20.02-20.32 ms |
| Patch evaluation | 5.55-5.86 ms | 14.22-14.46 ms |
| Patch drawing | 1.40-1.44 ms | 3.38-3.42 ms |
| Aligned GPU time | 3.19-3.51 ms | 3.14-3.17 ms |
| Host-frame p95 for the surrounding shot | 16.86-17.47 ms | 22.53-23.27 ms |

Run 1 encountered two non-repeatable CPU outliers, but its command counts and
phase attribution were identical. The per-spline median cost remains stable:
9.655 microseconds of evaluation and 2.385 microseconds of patch drawing for
Vamp, versus 9.530 and 2.235 microseconds for Fortune. The slowdown is
therefore not a new per-patch slow path. Fortune and her railgun introduce
approximately 2.6 times as many four-by-four spline surfaces, exhausting the
roughly 5 ms of scheduler slack present during Vamp and pushing alternating
render frames past one vblank interval.

The responsible CPU path is the `GE_SPLINE` handler in
`psp-recomp\src\rt\ge.c`: `draw_spline` calls `build_patch_columns` and
`evaluate_patch_columns` under `SR_PERF_PATCH_EVAL`, then `draw_patch_grid`
under `SR_PERF_PATCH_DRAW`. Vertex decoding remains about 0.63 ms, aligned GPU
time does not increase, and the through-mode/background workload is unchanged.
This rules out D3D12 GPU saturation, xBRZ, framebuffer feedback, interpreter
fallback, and a camera-transition HLE stall as the source.

The average paced host-frame interval remains near 16.7 ms because short
catch-up flips alternate with the 22-25 ms render flips. The visible symptom is
therefore a frame-pacing/p95 regression rather than sustained GPU-limited
throughput. No runtime change was made as part of this diagnosis.

## Exact four-lane spline optimization (2026-10-25)

The retained fix adapts PPSSPP's GPL-compatible GE-exact SIMD implementation
from `GPU/Common/SplineCommon.cpp` revision `ce97cb120182`. Provenance is
recorded in the shared runtime `CREDITS.md`.

`ge_patch_math.h` contains the current scalar arithmetic as the reference and
SSE2 helpers for four GE lerps, spline de Boor evaluation, color evaluation,
and GE tangent addition at once. `draw_spline` now:

1. evaluates four adjacent control columns vertically in SIMD;
2. gathers the four control values required by each generated U lane, including
   groups that cross segment boundaries;
3. evaluates four generated vertices horizontally in SIMD; and
4. retains the scalar GE product/row-sum normal cross product and the existing
   patch-grid draw path.

The interpolation order, six integer alpha values, fixed-point conversion,
exponent selection, endpoint handling, generated UVs, color rounding, normal
facing, tessellation limits, axis caches, and output ordering are unchanged.
The final one to three U samples use padded input lanes but write only valid
vertices. Non-SSE2 builds retain the scalar path, and
`SR_GE_SCALAR_SPLINE=1` selects it at runtime for differential testing.
Benchmark subprocesses clear both that override and the opt-in
`SR_GE_SPLINE_LOG` vertex-hash diagnostic.

The focused `mga2_ge_patch_math` CTest compares raw float bits, not epsilon:

- 100,000 randomized four-lane GE lerps;
- 100,000 randomized four-lane GE additions;
- 30,000 randomized spline evaluations with before/after tangents;
- 30,000 randomized color evaluations; and
- 10,000 cross-segment gather cases.

The inputs cover signs, zero and negative zero, subnormals, tiny and maximum
finite exponents, alpha endpoints 0 and 256, and arbitrary alpha tuples. The
test also verifies endpoint preservation for infinity and NaN bit patterns.

End-to-end scalar/SIMD differential runs from presentation 28,800 through
29,420 produced:

- 12,869 identical per-GE-frame spline draw/vertex/content hashes;
- 109 identical periodic D3D12 vertex-count/batch/content hashes; and
- byte-identical framebuffer captures at presentations 29,292, 29,293,
  29,307, and 29,400.

The four capture SHA-256 values are respectively
`52d4398e5c872b83d35db27b76903356df506892ae5cba8e09077f3ef40722d7`,
`049ff6f45486ecb0c68e36d0d4631cc68bbc0b95c13c641f6e953ec250bf030c`,
`f7fbe6a7cdfeb9009980f9470d50c44b9fc0653caf72e9ff5017ff32b0245fa5`,
and
`9dace9f6af7e5b522857ed5fbcfbd8f71c4c521d069e184e6adcb29634c3cb6e`.

The focused fixed-profile result is:

| Path/run | FPS | p95 | Maximum | Patch evaluation average / maximum | Patch draw average / maximum | Vertex phase average / maximum | Maximum GPU |
|---|---:|---:|---:|---:|---:|---:|---:|
| Scalar reference | 59.94 | 24.25 ms | 25.79 ms | 7.16 / 16.50 ms | 1.69 / 4.38 ms | 10.05 / 23.16 ms | 3.65 ms |
| SIMD run 4 | 59.96 | 17.35 ms | 18.02 ms | 3.86 / 9.05 ms | 1.67 / 4.10 ms | 6.72 / 15.68 ms | 3.65 ms |
| SIMD run 5 | 59.94 | 17.06 ms | 19.21 ms | 3.87 / 8.73 ms | 1.68 / 4.34 ms | 6.73 / 16.71 ms | 3.29 ms |
| SIMD run 6 | 59.94 | 17.44 ms | 19.00 ms | 3.85 / 8.58 ms | 1.67 / 4.25 ms | 6.70 / 16.18 ms | 3.26 ms |

The first SIMD matrix, before four-lane GE tangent addition, passed two of
three runs at 17.18, 18.42, and 17.19 ms p95. Completing that exact part of the
upstream design produced the three consecutive passing runs above. Average
patch evaluation is now about 46% of the scalar reference in the identical
window, while patch drawing and GPU time remain unchanged. Deterministic
workload counts also remain unchanged: the sample averages 888.742 total GE
draws per host flip and peaks at 1,918.

The p95 gate is met without tessellation reduction, memoization, indexed patch
drawing, threading, or GPU tessellation, so those higher-risk candidates were
not implemented.

Regression validation after the final build includes:

- all 6 configured CTests and all 9 Python benchmark-helper tests;
- three consecutive default Arena matrices:

  | Case | FPS range | p95 range | Maximum range | Maximum GPU range |
  |---|---:|---:|---:|---:|
  | Dead Cell | 59.93-59.94 | 16.93-17.09 ms | 17.37-17.78 ms | 3.23-3.95 ms |
  | Gameplay | 59.94 | 16.68-16.77 ms | 16.69-17.79 ms | 10.87-11.35 ms |

- the tutorial benchmark at 60.44 FPS, 17.23 ms p95, a 17.87 ms maximum,
  and a 4.09 ms maximum GPU sample; and
- the Stage 01 route at 59.94 FPS, 17.02 ms p95, a 17.56 ms maximum, and a
  0.68 ms maximum GPU sample.

Stage 01 has no spline commands in this window. Its generic benchmark result
reports only the expected absence of framebuffer aliases and feedback
snapshots; timing, execution, and the route itself pass.

## Yakumo-derived tooling and prewarm (branch `perf/yakumo-borrowed-ideas`)

A review of the other completed PSP recompilations (Ace Combat X and Yakumo) found
little performance work in the former and a mature toolchain in the latter. Yakumo's
Vulkan renderer was used as the design reference because this project's Vulkan backend
is not trustworthy (it can omit the map and player scene); everything below targets the
D3D12 backend, and no Yakumo source was copied. The shared runtime changes are in
psp-recomp `7fee88f`/`7708476`.

**Measurement tooling**

- `SR_TRACE_STALLS=1` prints a `[slow-frame]` line for each host flip over
  `SR_SLOW_FRAME_MS` (default 1.25 x the budget): the three largest exclusive phases,
  scheduler idle, texture misses and decode wait, PSO fallback binds, and the previous
  flip's backend stages. It works without a sample window.
- `SR_PERF_ALTERNATE=texdecode,merge,memo,indexed` switches output-identical paths off
  every `SR_PERF_ALTERNATE_PRESENTS` (default 60) guest presentations. The performance CSV
  is now v4 (`texture_misses`, `texture_decode_wait_us`, `pso_fallbacks`, `alt_off`; bit
  31 of `alt_off` marks a flip that straddled a change). The harness exposes it as
  `--alternate PATHS [--alternate-presents N]`, reports the on/off split under
  `alternation` in `summary.json`, and treats the run as diagnostic (never an acceptance
  pass). `--env NAME=VALUE` passes other runtime variables and `--pso-keys PATH` enables a
  persistent key list; benchmarks otherwise start with none so they stay comparable.
- Example, gameplay window, all four paths alternating every 30 presentations (200
  flips): frame average 16.68 ms on versus 16.95 ms off, frontend average 14.84 versus
  15.15 ms. Vblank pacing pins frame time near 16.68 ms, so the frontend average and the
  maximum are the informative columns.

**Optimizations (all kill-switched and output-identical)**

- *Background texture decode.* A miss copies the level bytes, palette and decode state on
  the GE thread (`ge_tex_snapshot_*`); workers decode and xBRZ-scale the copy and texture
  preparation waits before recording the upload. `SR_D3D12_SYNC_TEXTURE_DECODE=1`
  restores in-line decode. `SR_D3D12_VERIFY_TEXTURE_DECODE=1` decodes every texture both
  ways and aborts on a difference; it passed over the Dead Cell, Fortune and gameplay
  runs from boot. Verification found that a buffer width narrower than the texture (a
  64x256 8-bit texture with a 48-texel buffer) makes the live decoder read past the
  declared span; the snapshot now copies the same extent so both decode the same bytes.
  The measured gain is small: the Fortune cut has eight misses in one frame and the
  in-line decode cost 0.8-1.4 ms of `texture_capture_ms` against 0.5-0.6 ms now, with no
  decode wait. Steady-state windows contain no misses.
- *Persistent PSO key list.* The serialized pipeline library is unstable across launches,
  but pipeline keys are plain state. Each run records the keys it requests and the next
  run queues them on the existing PSO worker at startup. In the Dead Cell run a cold start
  made 3 asynchronous requests (3 misses); a warm start queued the 3 recorded keys and
  made none. The keys are 16 bytes each, so the file is a few hundred bytes.

**Acceptance**

All six CTests pass (the vertex and perf-stats tests were extended), as do the 14 Python
helper tests and the tutorial benchmark (60.44 FPS, 16.84 ms p95, 18.09 ms maximum,
3.76 ms maximum GPU). With the default configuration, Dead Cell and Fortune passed in
every run. Of six default gameplay runs (four with the stall trace on), five passed at
59.94 FPS with a 17.5-18.0 ms maximum frame, and one reported 58.48 FPS with a 33.37 ms
maximum frame; the single in-line decode run also passed. That miss is the already
documented thin margin on a host outlier, not a decode wait: decode wait was zero in the
measured windows.

**Findings from the new stall trace (not yet acted on)**

- A periodic backend `begin` stall of 8-10 ms recurs roughly every 17 flips in the
  gameplay lead-in (for example presentations 34,167, 34,175, 34,215 and 37,007 onward)
  while the aligned GPU time stays at or below 11 ms. This looks like a wait on an
  in-flight frame and is the next thing to attribute.
- The first frames of a run wait about 21 ms for decode (`decode wait=21469 us`), so
  background decode does not hide a cold start; it only overlaps work within a frame.
- Presentation 37,790 loses 31.5 ms inside one HLE call just before the gameplay
  window, and presentation 38,542 shows 14.8 ms of scheduler idle with little work.
  Both are pacing or HLE events rather than render cost.

**Begin-stall attribution (branches `test/stall-trace-begin-stall` and psp-recomp `test/begin-stall-attribution`)**

- With `SR_D3D12_STAGE_LOG=1` the backend now prints a `slow begin` line (over 4 ms)
  that splits `begin` into input poll, swapchain resize, frame-fence wait and the rest.
  In the gameplay lead-in the 5-9 ms `begin` stalls are entirely the frame-fence wait
  (`fence_wait`, with one frame still outstanding); poll, resize, allocator reset and
  descriptor setup are each under 0.2 ms. A second, rarer source is the SDL input poll
  (6-43 ms, far from the gameplay window). The stage log itself perturbs the run (one
  trace run fell to 43 FPS), so use it for attribution only.
- The fence wait is on a frame whose GPU time is at most 11 ms, so the extra wait is
  outside the timestamped span: most likely the queue waiting for DWM to release a
  back buffer under windowed flip-model `Present(0, 0)` on a 59 Hz display.
- `SR_D3D12_TEARING=1` (default off) creates the swapchain with allow-tearing and presents
  with `DXGI_PRESENT_ALLOW_TEARING`. Result: **inconclusive**. Three paired gameplay runs
  gave baseline 57.5/59.4/59.9 FPS and tearing 43.5/59.9/59.0 FPS (maximum frame 33.4 ms
  in two of three runs on both sides, and 82 ms in one tearing run). Host noise is larger
  than the effect. An earlier set of runs that looked like a clear win was invalid: the
  swapchain edit had not applied, so both arms were the same code.
- Next: a longer interleaved A/B (the harness `--alternate` cannot toggle swapchain
  flags), a waitable swapchain with frame latency 1 as a second candidate, and the
  cold-start decode wait and 31.5 ms HLE call still untouched.

**Deliberately not done**

- *Native fast paths* (Yakumo's `register_native_fast_path`) need a measured hot guest
  leaf, and the section 7 sampling shows none worth replacing.
- *Vulkan.* The same ideas are not ported to `gpu_sdl3vk`; its correctness bug has to be
  isolated first.

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

## Historical pre-sections 6-9 measured state

This retained snapshot predates the destination-snapshot, hashing, indexed
capture, draw-merging, and state-memo work in sections 6-9. The then-latest run
included `/O2`, indexed transform deduplication, sequence reference
indirection, triangle-list capture, and dirty-union feedback:

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

## Historical ranked investigations

This was the ranking at the historical snapshot above. Items 1-3 were
completed in sections 7-9. Item 4 received the bounded overlap trace described
in section 9, but a worker remains deferred because the acceptance gates do
not justify its unresolved correctness risk.

### 1. Rank generated native guest hotspots (completed)

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

### 2. Attribute per-draw CPU and GPU work (completed)

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

### 3. Preserve indexing through the PC-native D3D12 capture boundary (completed)

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

### 4. Evaluate asynchronous GE execution only after tracing safe overlap (trace completed; worker deferred)

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

### Validate partial-feedback visual equivalence (completed)

Current and legacy feedback snapshots are byte-identical at aligned Dead Cell,
gameplay, and later Arena presentations. The destination-snapshot differential
is also byte-identical at those points.

### Close the Dead Cell acceptance result (completed)

Three consecutive paced matrices passed earlier, and the fresh current-profile
run recorded above passes every gate at 59.94 FPS, 17.03 ms p95, 17.39 ms
maximum frame time, 3.24 ms maximum GPU time, and two cumulative readbacks.

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

- Recover enough CPU margin that the latest gameplay matrix passes three
  consecutive paced runs; the most recent final matrix passed only 2/3.
- Re-run the Stage 01 route.
- Run a paced smoke test of at least one additional Arena selection; the
  presentation-45,000 checks currently establish visual equivalence only.
- Run the relevant shared runtime suite and a final Release build after the
  last runtime change.

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
| `out\benchmarks\perf-memo2-r1` through `perf-memo2-r3` | Three consecutive passing state-memo matrices |
| `out\benchmarks\perf-final-r1` through `perf-final-r3` | Final repeat matrix; run 3 gameplay misses only the FPS gate |
| `out\benchmarks\dead-cell-current-20261025-0936` | Fresh clean Dead Cell acceptance run at the current graphics profile |
| `out\benchmarks\arena-fortune-transition-locator-*` | Coarse, fine, and exact visual sweeps locating the Fortune cut |
| `out\benchmarks\arena-fortune-transition-baseline-r1` through `arena-fortune-transition-baseline-r3` | Three capture-free paced transition profiles |
| `out\benchmarks\arena-fortune-transition-analysis` | Matched render rows and reduced transition summary |
| `out\benchmarks\arena-fortune-scalar-reference` | Scalar reference for the permanent Fortune benchmark case |
| `out\benchmarks\arena-fortune-simd-r4` through `arena-fortune-simd-r6` | Three consecutive passing optimized Fortune runs |
| `out\benchmarks\arena-fortune-simd-diff-scalar` and `arena-fortune-simd-diff-vector-add4` | Exact scalar/SIMD spline hashes, D3D12 hashes, and captures |
| `out\benchmarks\arena-simd-regression-r3` through `arena-simd-regression-r5` | Three consecutive passing Dead Cell/gameplay matrices |
| `out\benchmarks\tutorial-simd-regression` | Passing tutorial benchmark |
| `out\benchmarks\stage01-simd-regression` | Stage 01 route and timing smoke test |

The earlier shared runtime baseline was committed as `3de8644`; the spline SIMD
changes described here are the current runtime worktree changes. Do not remove
the existing untracked runtime `build\` directory or
`interp_fallback_test.misses`.
