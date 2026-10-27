# Code audit

Date: 2026-10-26  
Reviewed project revision: `e35b365`

## Scope and method

This audit covers the project-owned Python tools, title-specific C hooks,
installer and launchers, CMake integration, configuration, CI, tests, and
related documentation. Generated game code, game media and saves, and the
separate `psp-recomp` runtime were not audited as a whole. Selected source
from the pinned runtime revision was checked to verify integration behavior.

The findings below distinguish observed defects from conditional risks. In
particular, a weakness in an acceptance tool does **not** establish that a
previously reported gameplay or performance result was wrong; it means that
the tool alone cannot establish the stated result in the described cases.

Validation performed:

- `python -m unittest discover -s tools\mga2\tests -p "test_*.py"`: 26 tests
  passed.
- `python -m compileall -q tools\mga2`: passed.
- Synthetic performance samples, mocked subprocesses, temporary image and
  memory-stick fixtures, Windows batch-file probes, and a synthetic CMake
  configuration reproduced the cases identified below. No game data was
  needed for those probes.
- No live gameplay, renderer, native build, or native test suite was run. The
  available runtime checkout was not a clean checkout of the pinned revision;
  results from existing build artifacts would not establish a current build.

Priority reflects impact on this project, not a security severity rating.

## Findings

| ID | Priority | Finding |
|---|---|---|
| A01 | High | Inherited or diagnostic environment settings can produce a false fixed-profile benchmark pass. |
| A02 | High | A freeze at the end of the sample is omitted from delivered-frame statistics. |
| A03 | Medium | Relaxed or non-finite thresholds can still yield a passing acceptance result. |
| A04 | Medium | Incomplete GPU timings and zero audio playback can pass the benchmark gate. |
| A05 | Medium | The required presentation and input pulse are not proven to have been sampled. |
| A06 | Medium | Single-file generation is incompatible with the project's CMake source selection. |
| A07 | Medium | Installed ISO paths fail for some valid Windows filenames. |
| A08 | Medium | Benchmark runs use the supplied memory stick directly and share it between cases. |
| A09 | Medium | The visual gate can pass without validating the intended scenes. |
| A10 | Medium | Vulkan validation-layer errors do not fail or surface in the visual result. |
| A11 | Medium | Failed extraction can leave unverified inputs that generation does not recheck. |
| A12 | Medium | The configured toolkit revision is not enforced or recorded by the build pipeline. |
| A13 | Low | Current benchmark documentation describes an obsolete fast-forward path. |

### A01 - Benchmark environment can invalidate a claimed fixed-profile pass

**Evidence:** The runner copies the parent environment and clears only a
selected list of variables in
[`benchmark_common.py`](../tools/mga2/benchmark_common.py#L33) and
[`benchmark_common.py`](../tools/mga2/benchmark_common.py#L506). In
particular, inherited `SR_FAST_FORWARD_PRESENT` and `SR_D3D12_SCALE` survive.
The pinned runtime treats `SR_D3D12_SCALE` as an override of `graphics.ini`.
The runner also applies arbitrary `--env` settings after clearing the
environment, while [`benchmark_arena.py`](../tools/mga2/benchmark_arena.py#L271)
does not make such a run diagnostic-only.

**Reproduction:** With a mocked runtime, inherited fast-forward and 1x D3D12
scale were passed to the process while its summary said `startup: real-time`
and `passed: true`. A separate mocked Arena invocation with
`--env SR_NOVBPACE=1`, `--env SR_GEDUMP=1`, and
`--env SR_FAST_FORWARD_PRESENT=27800` still set `fixed_profile: true` and
enabled acceptance validation. These settings conflict with the
[acceptance contract](ARENA_PERFORMANCE.md#L52).

**Impact:** A result can be labeled as a paced, real-time, 4x acceptance run
while executing a different workload. Inherited overrides are not included
in the recorded `extra_environment`.

**Recommendation:** Construct a controlled acceptance environment, clear or
explicitly set every workload-affecting override, and verify the effective
runtime profile. Treat diagnostic `--env` overrides as non-gating unless
explicitly proven safe. Record the effective settings and add tests for both
inherited and command-line overrides.

### A02 - Terminal delivery stalls are discarded

**Evidence:** [`describe_delivery`](../tools/mga2/benchmark_common.py#L190)
adds an interval only when the guest presentation changes. The final
`elapsed_ms` is discarded if the window ends on repeated host flips; the
reported FPS and maximum use only completed intervals.

**Reproduction:** A 120-flip synthetic sample delivered at 30 FPS initially
and then repeated its last guest frame for approximately 1,017 ms. With
otherwise complete, passing GPU and audio data, the gate returned no
failures and reported a 33.33 ms maximum delivered interval.

**Impact:** A temporary freeze beginning near the end of a measurement window
can evade both the delivered-frame FPS and maximum-latency gates.

**Recommendation:** Account for the full observation interval in delivered
FPS and explicitly report the final censored interval. Fail the maximum-stall
gate when an ongoing interval already exceeds the limit, and test freezes at
both window boundaries.

### A03 - Custom and non-finite limits can masquerade as acceptance

**Evidence:** The Arena driver constructs thresholds from command-line
arguments in [`benchmark_arena.py`](../tools/mga2/benchmark_arena.py#L298),
but its `fixed_profile` decision does not consider changed limits or window
sizes. The tutorial driver likewise accepts custom limits. Applied benchmark
thresholds are not included in the per-case summary. Floating-point CLI
options in both the benchmark and
[`validate_vulkan.py`](../tools/mga2/validate_vulkan.py#L401) also accept
`nan`, for which ordinary limit comparisons are false.

**Reproduction:** A synthetic 40 ms frame failed the default 33.4 ms gate but
passed with `--maximum-frame-ms 999`; a mocked Arena invocation still labeled
the latter fixed-profile and validated. Separately, a 100 ms GPU sample passed
when its maximum was `nan`, and visual comparisons with `nan` limits produced
no threshold failures.

**Impact:** A result may look like a fixed-contract pass without satisfying
the published thresholds, and a non-finite value can silently disable a
comparison.

**Recommendation:** Reject non-finite and invalid limits, record all applied
thresholds and sample sizes, and distinguish diagnostic/custom-limit success
from a pass against the fixed acceptance contract. Add boundary and `nan`
regressions for both benchmark and visual gates.

### A04 - Missing timing and audio evidence can pass

**Evidence:** [`summarize`](../tools/mga2/benchmark_common.py#L281) drops
missing GPU timings and records `gpu_samples`, but
[`validate`](../tools/mga2/benchmark_common.py#L440) only requires a
non-negative maximum. [`parse_audio_stats`](../tools/mga2/benchmark_common.py#L378)
records played frames and duration, but validation checks error counters
without requiring playback to have occurred.

**Reproduction:** An otherwise passing 120-flip sample with one GPU timing
and 119 missing timings passed. A validly formatted XAudio2 shutdown line
reporting zero played frames and zero errors also passed.

**Impact:** The gate can report success without enough GPU evidence to assess
the window, or without evidence of the continuous audio playback described by
the [Arena contract](ARENA_PERFORMANCE.md#L36).

**Recommendation:** Define and enforce GPU sample coverage after delayed
query alignment. Require positive playback and an appropriate duration or
per-window audio-activity signal, allowing explicitly documented startup
tolerances. Test missing samples and zero-duration audio separately.

### A05 - Checkpoint and replay claims are not verified

**Evidence:** [`summarize`](../tools/mga2/benchmark_common.py#L274) only
checks that the requested presentation lies between the minimum and maximum
observed values. The tutorial's `--pulse` selects that requested number; it
does not modify or validate the input replay
([`benchmark_tutorial.py`](../tools/mga2/benchmark_tutorial.py#L68),
[`new_game_runtime.pad`](../tools/mga2/new_game_runtime.pad#L11)).
Custom replay files are also accepted without checking the expected event.

**Reproduction:** A passing synthetic sample whose presentation numbers were
all even bracketed required presentation 129, but never contained that
presentation. The gate accepted it.

**Impact:** A report cannot establish that the exact checkpoint was sampled
or that the intended input event occurred. A changed pulse or replay can
therefore validate a different workload.

**Recommendation:** Define whether the contract requires an observed host
sample or an event crossed between samples, and verify that property
explicitly. Validate replay identity or instrument the required input/scene
event; classify unverified custom replays as diagnostic.

### A06 - `--single` output does not match CMake's inputs

**Evidence:** [`gen.py`](../tools/mga2/gen.py#L28) offers `--single` and
omits `--split` for that mode. The pinned generator emits
`mga2_recomp.c` in single-file mode, whereas
[`CMakeLists.txt`](../CMakeLists.txt#L114) requires numbered main translation
units and `mga2_recomp_register.c`. The native-module glob also accepts both
single and split sources.

**Reproduction:** A clean synthetic generation directory containing
`mga2_recomp.c` was rejected at CMake configuration with "No generated code".
Switching modes in an existing output directory can also leave the other
mode's files: CMake can select stale main split files or both native source
forms, causing stale builds or duplicate definitions.

**Recommendation:** Either support both layouts deliberately or remove the
unsupported option. Generate into a clean, mode-specific staging directory
and publish a manifest of exactly the current sources. Test clean and
split-to-single-to-split transitions.

### A07 - ISO path persistence is not Unicode-safe

**Evidence:** [`install.bat`](../install.bat#L262) writes the ISO path using
the Windows ANSI `mbcs` codec. Both
[`launch-installed.bat`](../tools/mga2/launch-installed.bat#L9) and
[`play.bat`](../play.bat#L29) read it using `cmd.exe`'s `set /p`.

**Reproduction:** On Windows with ANSI code page 1252, writing a path
containing characters outside that code page raised `UnicodeEncodeError`.
With console code page 437, an actual existing ISO fixture in an accented
directory was not found after the same write/read sequence; an ASCII path
worked.

**Impact:** Installation can fail late, or a completed installation can fail
to locate an ISO whose valid path was changed by the encoding round trip.

**Recommendation:** Use a single Unicode-safe path representation and
wide-character handling end-to-end, including the launcher and runtime; do
not merely change the writer's encoding. Add Windows tests for non-ASCII and
non-ANSI paths under differing ANSI and console code pages.

### A08 - Benchmarks do not isolate memory-stick state

**Evidence:** The tutorial defaults to the project `memstick` directory in
[`benchmark_tutorial.py`](../tools/mga2/benchmark_tutorial.py#L54), and
[`run_benchmark_case`](../tools/mga2/benchmark_common.py#L515) gives the
runtime that directory directly. Arena cases reuse the same supplied
directory. The visual validator already makes per-run copies in
[`validate_vulkan.py`](../tools/mga2/validate_vulkan.py#L276).

**Impact:** Any guest save write would affect the supplied source, and earlier
cases can change the state seen by later cases. No actual save corruption was
observed in this audit; the risk follows from passing a writable original
through to the runtime. Arena documentation asks for an isolated stick, but
the tutorial default can be the user's normal developer stick.

**Recommendation:** Run each case against a fresh copy of the intended
fixture, preserve the original, and record fixture identity. Keep copied game
data in ignored or temporary locations. If direct mutation remains supported,
require an explicit opt-in and document it.

### A09 - Visual similarity does not establish scene identity

**Evidence:** [`require_memstick`](../tools/mga2/validate_vulkan.py#L247)
checks for two files and a size, while the
[comparison loop](../tools/mga2/validate_vulkan.py#L485) only compares images
and thresholds. Existing reference and Vulkan directories may resolve to the
same location.

**Reproduction:** Two separate directories containing all-black synthetic
480x272 captures passed as Vulkan validation for both required presentations.
Using the same directory as both reference and Vulkan also passed.

**Impact:** A wrong save, wrong route, stale captures, or self-comparison can
produce a successful visual result without showing the intended cinematic or
Arena scene. Pixel agreement remains useful for comparing renderers, but is
not by itself proof that the software reference is the right scene.

**Recommendation:** Reject identical reference and actual paths, establish
reference provenance and scene identity with trusted local fixtures, hashes,
or explicit runtime checkpoints, and record those identities in the result.
Do not commit game-derived captures to provide this check.

### A10 - Vulkan validation errors are buried in a successful run

**Evidence:** [`run_renderer`](../tools/mga2/validate_vulkan.py#L312)
redirects stderr to a log and reads it only when the process exits nonzero.
The pinned runtime's validation callback logs `sdl3vk validation error:` and
returns without forcing process failure. The
[benchmark documentation](BENCHMARKS.md#L76) directs users to enable the
validation layer for error reporting.

**Reproduction:** A mocked successful renderer process wrote a validation
error in the pinned runtime's format and produced the required capture names.
`run_renderer` returned successfully and left the error only in `stderr.log`.

**Impact:** If the images also meet the metric limits, the command can print
that visual validation passed despite Vulkan validation errors.

**Recommendation:** When validation is requested, report and gate on
structured error counts, or reliably parse the runtime's diagnostic format.
Include the count and log path in the summary, with an explicit policy for
warnings.

### A11 - Extraction and generation do not preserve input verification

**Evidence:** [`extract.py`](../tools/mga2/extract.py#L99) writes a file
before comparing its hash and writes the inventory before returning failure.
[`generate_prx`](../tools/mga2/gen.py#L77) checks that the file exists but
does not compare it with the configured main or native-module hash.

**Reproduction:** A mocked ISO entry with a mismatching file hash caused
extraction to return failure while leaving the mismatched `BOOT.BIN` in the
output directory. With tool invocations mocked, `generate_prx` accepted an
existing module whose configured hash did not match.

**Impact:** The installer stops on extraction failure, and the full ISO hash
is checked initially. However, a later manual generation can consume a
failed, modified, or stale extraction without re-establishing the identity
that the configuration claims.

**Recommendation:** Verify extracted bytes before publishing them and avoid
publishing a success-shaped inventory on failure. Hash every configured
generation input immediately before use and fail clearly on mismatches; test
that a failed extraction preserves or removes outputs predictably.

### A12 - The toolkit pin is advisory rather than an integration check

**Evidence:** [`config/mga2.toml`](../config/mga2.toml#L3) records a runtime
commit, but [`gen.py`](../tools/mga2/gen.py#L224),
[`install.bat`](../install.bat#L97), and
[`CMakeLists.txt`](../CMakeLists.txt#L15) check for files rather than that
revision. `gen.py` defaults to the `PSP_RECOMP_DIR` environment variable,
while CMake has its own cached default
([`gen.py`](../tools/mga2/gen.py#L20),
[`CMakeLists.txt`](../CMakeLists.txt#L6)).

**Reproduction:** With generation calls mocked, the generator accepted a
directory containing `tools/codegen.py` but no Git metadata or verified
revision. The installer normally passes one path to both stages, but manual
generation and CMake configuration can select different checkouts.

**Impact:** Unsupported or mixed code-generator/runtime versions can build
without a clear warning, undermining the documented reproducibility pin.
Dirty checkouts are likewise not identified in results.

**Recommendation:** Record and verify toolkit identity for generation and
builds, including dirty state where available, and bind generated outputs to
that identity. Provide an explicit, clearly labeled override for deliberate
development against other revisions or non-Git source archives.

### A13 - Benchmark documentation describes obsolete behavior

[`BENCHMARKS.md`](BENCHMARKS.md#L15) says the tutorial and default Arena
benchmarks fast-forward, while the current runner defaults to real-time and
Arena treats `--fast-forward` as diagnostic. It also omits the newer
delivered-frame and audio gates documented in
[`ARENA_PERFORMANCE.md`](ARENA_PERFORMANCE.md#L36).

Update the current usage document alongside the benchmark fixes so users know
the actual duration, audio behavior, and acceptance criteria. Historical
measurements should remain labeled as historical rather than rewritten.

## Streamlining opportunities

1. **Use one source of truth for title identity and module policy.**
   [`config/mga2.toml`](../config/mga2.toml#L48),
   [`module_policy.c`](../tools/mga2/module_policy.c#L16), and
   [`CMakeLists.txt`](../CMakeLists.txt#L263) repeat paths, hashes, addresses,
   boot values, and disc identity. The audit compared 11 configured guest
   load paths and seven HLE hashes with the C policy and found no differences;
   17 configured module hashes also matched the existing extraction inventory.
   Generate the corresponding tables/constants from configuration or add a
   consistency test, including the raw-LBN aliases.
2. **Avoid rereading each PRX during extraction.** The inventory loop reads
   bytes in [`extract.py`](../tools/mga2/extract.py#L119), then
   [`write_entry`](../tools/mga2/extract.py#L32) reads the same entry again.
   The existing inventory contains 107 PRXs totaling 8,196,350 bytes, so this
   is a modest I/O improvement, not a substitute for hashing the full ISO.
   Pass the already-read bytes to the writer while retaining hash checks.
3. **Share fixture and file validation.**
   [`benchmark_arena.py`](../tools/mga2/benchmark_arena.py#L211) and
   [`validate_vulkan.py`](../tools/mga2/validate_vulkan.py#L247) independently
   validate the same Arena save, and both define `require_file`. A neutral
   shared helper with common tests would prevent those rules drifting.
4. **Avoid duplicating the installed launcher.**
   [`play.bat`](../play.bat#L24) reimplements much of
   [`launch-installed.bat`](../tools/mga2/launch-installed.bat#L1) instead of
   invoking it. Delegate the installed path to that launcher while preserving
   argument precedence, error codes, and the separate developer-build
   fallback.
5. **Make existing-capture comparisons independent of unused run inputs.**
   [`validate_vulkan.py`](../tools/mga2/validate_vulkan.py#L415) requires an
   executable, generated image, ISO, replay, and memory stick even when all
   requested capture directories already exist. Validate those prerequisites
   only for renderers that actually need to run.

## Coverage priorities

The [source-only CI job](../.github/workflows/source-checks.yml#L23) exercises
Python tests but not the Windows batch paths, title-specific C hooks, or native
integration. CMake registers native tests with `EXCLUDE_FROM_ALL`
([example](../CMakeLists.txt#L324)); a normal driver build alone does not
build those test executables. Add or document a targeted test-build step, and
prioritize automated regressions for the synthetic failures above, Windows
path handling, extraction failure cleanup, module-policy consistency, and
generation-mode transitions.
