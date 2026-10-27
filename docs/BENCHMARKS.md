# Performance benchmarks and validation

Run these commands from the repository root after building the combined
renderer. The source-only tests do not require game data; the benchmarks and
live captures do.

## Performance benchmarks

Run the opening tutorial:

```powershell
python tools\mga2\benchmark_tutorial.py
```

For the completed-save Arena route, supply a memory-stick root containing
`PSP\SAVEDATA\ULUS10077003`, including `PARAM.SFO` and a `00000000.000` file
of exactly 48,800 bytes:

```powershell
python tools\mga2\benchmark_arena.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick
```

Each benchmark case starts from a fresh temporary copy of the supplied
memory stick; the original is not passed to the runtime. The copy is removed
after the run, and a hash of its paths, directories, and file contents is
recorded in the summary. If the
tutorial's default memory stick does not exist, it starts with an empty copy.
Fixtures containing symbolic links or Windows reparse points (including
junctions) are rejected. Output directories must be outside the fixture.

Acceptance runs start in real time, without fast-forward, and can take several
minutes. The tutorial samples 120 host flips starting at presentation 30,900
and checks the replay's CIRCLE pulse at 31,000. The default Arena cases sample
the Dead Cell introduction and Arena gameplay around presentations 28,000
and 38,000. `--case fortune` selects the additional transition case;
`--case all` runs all three.

The fixed profile is D3D12, 4x internal resolution, 2x xBRZ, full-rate
shading, anti-aliasing off, and startup skip off. The runner checks both
`graphics.ini` and the effective profile reported by the runtime. Its gates
require:

- at least 59 host flips/s and 29 newly delivered game frames/s;
- host-frame p95 at most 18 ms and maximum at most 33.4 ms;
- delivered-frame p95 at most 35 ms and maximum at most 50 ms, including an
  ongoing interval at the end of the observation window;
- a valid aligned GPU timing for every sampled flip, with a maximum of
  16.68 ms;
- positive XAudio2 playback at least as long as the sample, no dropped frames
  or underruns, at most one padding transition, and no voice error; and
- at most four framebuffer readbacks, with nonzero aliases and feedback
  snapshots.

Audio statistics are aggregate shutdown counters. They do **not** prove that
audio was continuous during the specific sample window. Likewise, the input
log confirms that the runtime exposed the expected replay pulse, not that the
game reacted to it or that a scene was visually correct. A checkpoint may
fall between host flips: the summary records whether it was observed directly
or crossed between adjacent samples.

Inherited `SR_*` and `PSP_*` settings are cleared before the controlled
environment is established. Custom thresholds, windows, replay contents, runtime
`--env` settings, fast-forward, alternate profiles, and extended tails are
diagnostic rather than fixed-contract acceptance runs. Their summaries set
`validated` to `false` and `passed` to `null`; a successful diagnostic command
does not imply an acceptance pass. `--include-unpaced` adds separate
diagnostic runs without changing the paced acceptance cases.

Logs, the performance CSV, effective settings, thresholds, input/fixture
identities, and `summary.json` are written under `out\benchmarks` by default.
See [ARENA_PERFORMANCE.md](ARENA_PERFORMANCE.md) for historical measurements
and remaining bottlenecks.

## Vulkan pixel comparison and scene validation

Capture the completed-save route with:

```powershell
python tools\mga2\validate_vulkan.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick `
  --output out\validation\arena-reference
```

The command captures software and Vulkan presentations 28,000 and 38,000,
using separate memory-stick copies retained in the output directory. It
compares 480x272 whole frames and focused character, stage/player,
map-preview, and card-UI regions. `--include-d3d12` adds a live D3D12
cross-check. Output directories contain game-derived saves, logs, and
captures; keep them private and do not commit them.

Pixel agreement alone does not establish which scene was captured. Without a
trusted reference manifest, a successful comparison is explicitly
**comparison-only**: `validated` is `false`, `passed` is `null`, and scene
identity is unverified. Comparing a file to itself, including through a hard
link, is rejected.

For a scene-validation run, first inspect the software captures yourself and
confirm they are the intended cinematic and Arena scenes. Then create a local
JSON manifest containing the SHA-256 values from the first run's summary:

```json
{
  "schema": 1,
  "scene_verified": true,
  "captures": {
    "28000": "<reference_sha256 for presentation 28000>",
    "38000": "<reference_sha256 for presentation 38000>"
  },
  "memstick_sha256": "<runs.software.memstick_sha256>",
  "replay_sha256": "<replay_sha256>"
}
```

Replace every placeholder with the corresponding 64-digit hash. Keep the
manifest and the personally verified reference captures locally. A subsequent
run can use that reference and capture Vulkan again:

```powershell
python tools\mga2\validate_vulkan.py `
  --memstick build\mga2\arena-d3d12-shadow-fix\memstick `
  --reference-dir out\validation\arena-reference\software `
  --reference-manifest out\validation\trusted-reference.json
```

The manifest is a **user attestation**, not an independent proof of scene
identity. The runner checks its reference, fixture, and replay hashes, confirms
the Vulkan renderer and expected input event, and applies the fixed comparison
limits. Existing Vulkan or D3D12 capture directories and custom limits remain
comparison-only because their provenance or contract is not established.
Use `--reference-dir`, `--vulkan-dir`, and `--d3d12-dir` for those comparisons;
if every requested capture already exists, an executable, ISO, and memory
stick are not required.

Set `SR_VK_VALIDATION=1` to request the Khronos validation layer. The command
requires confirmation that the layer was enabled and fails on logged Vulkan
validation errors, even if the renderer exits successfully. Warnings are
counted and reported but do not fail the comparison.
