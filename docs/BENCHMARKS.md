# Performance benchmarks and validation

Run these commands from the repository root after building the combined
renderer.

## Tutorial performance benchmark

Run the deterministic opening-dialog benchmark with:

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
[`ARENA_PERFORMANCE.md`](ARENA_PERFORMANCE.md).

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
