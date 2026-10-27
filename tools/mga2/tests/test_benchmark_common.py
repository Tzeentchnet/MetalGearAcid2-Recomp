from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import benchmark_arena
import benchmark_tutorial
from benchmark_arena import (
    ARENA_CASES,
    ARENA_REPLAY_SHA256,
    build_extra_environment,
    combine_results,
    require_arena_save,
    select_cases,
)
from benchmark_common import (
    BenchmarkCase,
    FIXED_GRAPHICS_PROFILE,
    PerformanceThresholds,
    clean_runtime_environment,
    copy_memstick_fixture,
    describe,
    describe_delivery,
    ensure_output_outside_fixture,
    find_input_event,
    load_samples,
    parse_audio_stats,
    parse_framebuffer_stats,
    parse_runtime_profile,
    read_graphics_profile,
    replay_sha256,
    run_benchmark_case,
    split_alternation,
    summarize,
    validate,
    validate_run_options,
)
from benchmark_tutorial import TUTORIAL_REPLAY_SHA256


class BenchmarkCommonTests(unittest.TestCase):
    def test_loads_comments_and_extra_columns(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "perf.csv"
            path.write_text(
                "# psp-recomp display performance v3\n"
                "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms,"
                "native_ms\n"
                "1,99,16,10,6,-1,4\n"
                "2,100,17,11,6,8,5\n",
                encoding="ascii",
            )
            samples = load_samples(path, 2)
        self.assertEqual(samples[1]["present"], 100.0)
        self.assertEqual(samples[1]["native_ms"], 5.0)

    def test_realigns_delayed_gpu_samples(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "perf.csv"
            path.write_text(
                "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms,"
                "gpu_source_flip\n"
                "10,100,16,10,6,-1,0\n"
                "11,101,16,10,6,-1,0\n"
                "12,102,16,10,6,7.5,10\n"
                "13,103,16,10,6,8.5,11\n",
                encoding="ascii",
            )
            samples = load_samples(path, 2)
        self.assertEqual(samples[0]["gpu_ms"], 7.5)
        self.assertEqual(samples[1]["gpu_ms"], 8.5)

    def test_acceptance_requires_unique_gpu_source_identities(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "perf.csv"
            path.write_text(
                "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms\n"
                "1,99,16,10,6,7\n"
                "2,100,16,10,6,8\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "source-flip identities are missing"):
                load_samples(path, 2, require_gpu_sources=True)
            path.write_text(
                "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms,gpu_source_flip\n"
                "1,99,16,10,6,7,1\n"
                "2,100,16,10,6,8,1\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "duplicate GPU"):
                load_samples(path, 2, require_gpu_sources=True)

    def test_rejects_short_and_malformed_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "perf.csv"
            path.write_text(
                "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms\n"
                "1,2,not-a-number,4,5,6\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "contains 1 samples"):
                load_samples(path, 2)
            with self.assertRaisesRegex(ValueError, "invalid performance row"):
                load_samples(path, 1)

    def test_summarizes_required_present_and_extra_metrics(self) -> None:
        samples = [
            {
                "flip": 1.0,
                "present": 99.0,
                "frame_ms": 10.0,
                "frontend_ms": 7.0,
                "backend_ms": 3.0,
                "gpu_ms": -1.0,
                "native_ms": 2.0,
            },
            {
                "flip": 2.0,
                "present": 100.0,
                "frame_ms": 20.0,
                "frontend_ms": 15.0,
                "backend_ms": 5.0,
                "gpu_ms": 8.0,
                "native_ms": 4.0,
            },
        ]
        summary = summarize(samples, 100)
        self.assertAlmostEqual(
            float(summary["host_flip_fps"]), 1000.0 / 15.0
        )
        self.assertAlmostEqual(float(summary["delivered_fps"]), 50.0)
        self.assertEqual(summary["gpu_samples"], 1)
        self.assertEqual(summary["gpu_maximum_ms"], 8.0)
        self.assertEqual(
            summary["extra_metrics"]["native_ms"]["average"],
            3.0,
        )
        with self.assertRaisesRegex(ValueError, "does not include"):
            summarize(samples, 101)

    def test_reads_and_validates_graphics_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / "mga2.exe"
            executable.touch()
            executable.with_name("graphics.ini").write_text(
                "renderer=d3d12\n"
                "internal_resolution=4\n"
                "texture_scale=2\n"
                "d3d12_full_rate=1\n",
                encoding="ascii",
            )
            profile = read_graphics_profile(executable)
            self.assertEqual(profile["internal_resolution"], "4")
            executable.with_name("graphics.ini").write_text(
                "renderer=d3d12\ninternal_resolution=1\n",
                encoding="ascii",
            )
            with self.assertRaisesRegex(ValueError, "required benchmark profile"):
                read_graphics_profile(executable)

    def test_parses_framebuffer_stats_and_validates_thresholds(self) -> None:
        stats = parse_framebuffer_stats(
            "ged3d12: framebuffer cache captures=2 readbacks=3 aliases=4 "
            "invalidations=5 feedback_snapshots=6 feedback_reuses=7\n"
        )
        self.assertEqual(
            stats,
            {"readbacks": 3, "aliases": 4, "feedback_snapshots": 6},
        )
        audio = parse_audio_stats(
            "audio: XAudio2 shutdown played=44100 frames (1000.00 ms), "
            "clock_drift=-2.50 ms, device_buffers=6..8, "
            "max_guest_queue=8192, dropped=0, resynced=256, "
            "silent_blocks=0, underruns=0, padding_blocks=4, "
            "padding_transitions=1\n"
        )
        self.assertEqual(audio["audio_underruns"], 0)
        self.assertFalse(audio["audio_voice_error"])
        summary = {
            "samples": 120,
            "sample_duration_ms": 1000.0,
            "host_flip_fps": 58.0,
            "delivered_fps": 28.0,
            "p95_ms": 19.0,
            "maximum_ms": 40.0,
            "delivered_p95_ms": 36.0,
            "delivered_maximum_ms": 51.0,
            "terminal_delivery_interval_ms": 0.0,
            "gpu_maximum_ms": 20.0,
            "gpu_samples": 120,
            "required_input_event": {"frame": 31000},
            "runtime_profile": FIXED_GRAPHICS_PROFILE,
            **stats,
            **audio,
        }
        failures = validate(summary, PerformanceThresholds())
        self.assertEqual(len(failures), 7)
        with self.assertRaisesRegex(ValueError, "statistics are missing"):
            parse_framebuffer_stats("no cache line")
        self.assertEqual(
            parse_framebuffer_stats("no cache line", required=False),
            {"readbacks": 0, "aliases": 0, "feedback_snapshots": 0},
        )
        with self.assertRaisesRegex(ValueError, "Audio|audio"):
            parse_audio_stats("no audio statistics")

    def test_describes_delivered_frames_not_repeated_host_flips(self) -> None:
        samples = [
            {"present": 10.0, "frame_ms": 16.0},
            {"present": 10.0, "frame_ms": 17.0},
            {"present": 12.0, "frame_ms": 16.0},
            {"present": 12.0, "frame_ms": 17.0},
            {"present": 14.0, "frame_ms": 16.0},
        ]
        delivery = describe_delivery(samples)
        self.assertEqual(delivery["delivered_frames"], 2)
        self.assertEqual(delivery["repeated_host_flips"], 2)
        self.assertAlmostEqual(delivery["delivered_fps"], 1000.0 / 33.0)

    def test_terminal_stall_is_included_in_delivery_rate(self) -> None:
        samples = [
            {"present": 10.0, "frame_ms": 16.0},
            {"present": 11.0, "frame_ms": 16.0},
            {"present": 11.0, "frame_ms": 16.0},
            {"present": 11.0, "frame_ms": 16.0},
            {"present": 11.0, "frame_ms": 16.0},
            {"present": 11.0, "frame_ms": 16.0},
        ]
        delivery = describe_delivery(samples)
        self.assertAlmostEqual(delivery["delivered_fps"], 12.5)
        self.assertEqual(delivery["delivered_maximum_ms"], 16.0)
        self.assertEqual(delivery["terminal_delivery_interval_ms"], 64.0)

    def test_checkpoint_can_be_crossed_between_host_flips(self) -> None:
        samples = [
            {
                "flip": float(index),
                "present": float(present),
                "frame_ms": 16.0,
                "frontend_ms": 8.0,
                "backend_ms": 8.0,
                "gpu_ms": 7.0,
            }
            for index, present in enumerate((100, 102, 104), start=1)
        ]
        self.assertEqual(summarize(samples, 102)["checkpoint_evidence"], "observed")
        self.assertEqual(summarize(samples, 103)["checkpoint_evidence"], "crossed")
        samples[2]["present"] = 99
        with self.assertRaisesRegex(ValueError, "not in order"):
            summarize(samples, 101)

    def test_thresholds_and_windows_reject_invalid_values(self) -> None:
        for value in (float("nan"), float("inf"), -1.0, 0.0):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PerformanceThresholds(maximum_gpu_ms=value)
        with self.assertRaises(ValueError):
            PerformanceThresholds(maximum_readbacks=-1)
        for window, timeout in ((1, 1.0), (601, 1.0), (120, float("nan"))):
            with self.subTest(window=window, timeout=timeout):
                with self.assertRaises(ValueError):
                    validate_run_options(window, timeout)

    def test_checks_runtime_profile_and_input_log(self) -> None:
        stderr = (
            "graphics: loaded graphics.ini (renderer d3d12, internal "
            "resolution 4x, texture scale 2x, D3D12 full-rate on, "
            "anti-aliasing off, startup skip off)\n"
            "PADSCRIPT clock=present frame=31002 present=31002 "
            "vblank=62004 mask=0x2000\n"
        )
        case = BenchmarkCase("tutorial", 30900, 31000, 31400, input_pulse=31000)
        self.assertEqual(parse_runtime_profile(stderr), FIXED_GRAPHICS_PROFILE)
        self.assertEqual(find_input_event(stderr, case)["frame"], 31002)
        self.assertIsNone(find_input_event(stderr.replace("31002", "31021"), case))
        self.assertIsNone(find_input_event(stderr.replace("0x2000", "0x4000"), case))

    def test_replay_digests_are_independent_of_checkout_line_endings(self) -> None:
        self.assertEqual(replay_sha256(TOOLS / "arena_runtime.pad"), ARENA_REPLAY_SHA256)
        self.assertEqual(
            replay_sha256(TOOLS / "new_game_runtime.pad"), TUTORIAL_REPLAY_SHA256
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "replay.pad"
            path.write_bytes(b"one\r\ntwo\r\n")
            windows = replay_sha256(path)
            path.write_bytes(b"one\ntwo\n")
            self.assertEqual(replay_sha256(path), windows)

    def test_environment_discards_all_inherited_runtime_overrides(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "SR_FAST_FORWARD_PRESENT": "28000",
                "SR_D3D12_SCALE": "1",
                "SR_GEDUMP": "1",
                "PSP_ISO": "other.iso",
                "PATH": "kept",
            },
            clear=True,
        ):
            environment = clean_runtime_environment()
        self.assertEqual(environment, {"PATH": "kept"})

    def test_memstick_copy_has_stable_identity_and_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "save.bin").write_bytes(b"original")
            first = root / "first"
            second = root / "second"
            first_hash = copy_memstick_fixture(source, first)
            self.assertEqual(
                first_hash,
                copy_memstick_fixture(source, second),
            )
            (first / "save.bin").write_bytes(b"changed")
            self.assertEqual((source / "save.bin").read_bytes(), b"original")
            (source / "empty-directory").mkdir()
            self.assertNotEqual(
                first_hash, copy_memstick_fixture(source, root / "third")
            )
            empty = root / "empty"
            copy_memstick_fixture(root / "missing", empty)
            self.assertTrue(empty.is_dir())
            with self.assertRaisesRegex(ValueError, "inside the memory-stick"):
                ensure_output_outside_fixture(source / "results", source)
            self.assertFalse((source / "results").exists())

    def test_full_case_uses_isolated_state_and_effective_gates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            memstick = root / "source"
            memstick.mkdir()
            (memstick / "save.bin").write_bytes(b"original")
            replay = root / "replay.pad"
            replay.write_bytes(b"fixture\n")
            diagnostic = False

            def fake_run(command, *, cwd, env, stdout, stderr, timeout, check):
                if diagnostic:
                    self.assertEqual(env["SR_FAST_FORWARD_PRESENT"], "100")
                    self.assertEqual(env["SR_NOVBPACE"], "1")
                else:
                    self.assertNotIn("SR_FAST_FORWARD_PRESENT", env)
                self.assertNotIn("SR_D3D12_SCALE", env)
                self.assertEqual(env["SR_PADLOG"], "1")
                self.assertNotEqual(Path(env["SR_MEMSTICK"]), memstick)
                (Path(env["SR_MEMSTICK"]) / "save.bin").write_bytes(b"changed")
                Path(env["SR_PERF_FILE"]).write_text(
                    "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms,"
                    "gpu_source_flip\n"
                    + "".join(
                        f"{index},{100 + index},16,8,8,7,{index}\n"
                        for index in range(1, 121)
                    ),
                    encoding="ascii",
                )
                stderr.write(
                    b"graphics: loaded graphics.ini (renderer d3d12, internal "
                    b"resolution 4x, texture scale 2x, D3D12 full-rate on, "
                    b"anti-aliasing off, startup skip off)\n"
                    b"PADSCRIPT clock=present frame=105 present=105 "
                    b"vblank=210 mask=0x2000\n"
                    b"ged3d12: framebuffer cache captures=2 readbacks=0 "
                    b"aliases=4 invalidations=5 feedback_snapshots=6\n"
                    b"audio: XAudio2 shutdown played=441000 frames (10000.00 ms), "
                    b"clock_drift=0.00 ms, device_buffers=6..8, "
                    b"max_guest_queue=8192, dropped=0, resynced=0, "
                    b"silent_blocks=0, underruns=0, padding_blocks=0, "
                    b"padding_transitions=0\n"
                )
                return SimpleNamespace(returncode=0)

            with mock.patch.dict(
                os.environ,
                {"SR_FAST_FORWARD_PRESENT": "100", "SR_D3D12_SCALE": "1"},
            ), mock.patch("benchmark_common.subprocess.run", side_effect=fake_run):
                summary = run_benchmark_case(
                    case=BenchmarkCase("test", 100, 110, 220, input_pulse=105),
                    executable=root / "game.exe",
                    image=root / "image.bin",
                    iso=root / "game.iso",
                    memstick=memstick,
                    pad_script=replay,
                    output=root / "result",
                    profile=FIXED_GRAPHICS_PROFILE,
                    thresholds=PerformanceThresholds(),
                    window=120,
                    timeout=30.0,
                )
            self.assertTrue(summary["passed"])
            self.assertEqual(summary["gpu_samples"], 120)
            self.assertEqual((memstick / "save.bin").read_bytes(), b"original")
            self.assertFalse(Path(
                summary["effective_runtime_environment"]["SR_MEMSTICK"]
            ).exists())

            diagnostic = True
            with mock.patch("benchmark_common.subprocess.run", side_effect=fake_run):
                diagnostic_summary = run_benchmark_case(
                    case=BenchmarkCase("test", 100, 110, 220, input_pulse=105),
                    executable=root / "game.exe",
                    image=root / "image.bin",
                    iso=root / "game.iso",
                    memstick=memstick,
                    pad_script=replay,
                    output=root / "diagnostic",
                    profile=FIXED_GRAPHICS_PROFILE,
                    thresholds=PerformanceThresholds(),
                    window=120,
                    timeout=30.0,
                    validate_result=False,
                    extra_environment={
                        "SR_FAST_FORWARD_PRESENT": "100",
                        "SR_NOVBPACE": "1",
                    },
                )
            self.assertEqual(diagnostic_summary["startup"], "fast-forward")
            self.assertEqual(diagnostic_summary["mode"], "unpaced")
            self.assertIsNone(diagnostic_summary["passed"])

            for field, value, expected in (
                ("gpu_samples", 1, "GPU timing coverage"),
                ("audio_played_frames", 0, "insufficient XAudio2"),
                ("required_input_event", None, "input event"),
                ("terminal_delivery_interval_ms", 51.0, "terminal delivery"),
                ("runtime_profile", None, "runtime graphics profile"),
            ):
                changed = {**summary, field: value}
                self.assertTrue(
                    any(expected in failure for failure in validate(
                        changed, PerformanceThresholds()
                    )),
                    field,
                )

    def test_requires_complete_arena_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            save = root / "PSP" / "SAVEDATA" / "ULUS10077003"
            save.mkdir(parents=True)
            (save / "PARAM.SFO").write_bytes(b"sfo")
            (save / "00000000.000").write_bytes(b"\0" * 48_800)
            self.assertEqual(require_arena_save(root), root.resolve())
            (save / "00000000.000").write_bytes(b"short")
            with self.assertRaisesRegex(ValueError, "expected 48800"):
                require_arena_save(root)

    def test_combines_only_validated_results(self) -> None:
        passing = {
            "case": "dead-cell",
            "validated": True,
            "passed": True,
            "failures": [],
        }
        failing = {
            "case": "gameplay",
            "validated": True,
            "passed": False,
            "failures": ["slow"],
        }
        diagnostic = {
            "case": "gameplay",
            "validated": False,
            "passed": None,
            "failures": [],
        }
        combined = combine_results(
            [passing, failing, diagnostic],
            fixed_profile=True,
        )
        self.assertFalse(combined["passed"])
        self.assertEqual(combined["failures"], ["gameplay: slow"])
        json.dumps(combined)

    def test_selects_fortune_without_changing_both(self) -> None:
        self.assertEqual(
            [case.name for case in select_cases("both")],
            ["dead-cell", "gameplay"],
        )
        self.assertEqual(
            [case.name for case in select_cases("all")],
            ["dead-cell", "fortune", "gameplay"],
        )
        fortune = select_cases("fortune")
        self.assertEqual([case.name for case in fortune], ["fortune"])
        self.assertLess(fortune[0].start, 29_293)
        self.assertEqual(fortune[0].required_present, 29_307)
        self.assertGreater(fortune[0].exit_after, fortune[0].required_present)
        self.assertEqual(tuple(case.name for case in ARENA_CASES), (
            "dead-cell",
            "fortune",
            "gameplay",
        ))


class AlternationTests(unittest.TestCase):
    @staticmethod
    def row(frame: float, alt_off: int) -> dict[str, float]:
        return {
            "frame_ms": frame,
            "frontend_ms": frame - 2.0,
            "backend_ms": 2.0,
            "alt_off": float(alt_off),
        }

    def test_splits_on_off_and_discards_transitions(self) -> None:
        rows = [
            self.row(16.0, 0),
            self.row(16.0, 0),
            self.row(30.0, 0x80000002),
            self.row(20.0, 2),
            self.row(22.0, 2),
        ]
        result = split_alternation(rows)
        assert result is not None
        self.assertEqual(result["discarded"], 1)
        self.assertEqual(result["on"]["samples"], 2)
        self.assertEqual(result["off"]["samples"], 2)
        self.assertAlmostEqual(result["delta"]["average_ms"], 5.0)

    def test_reports_only_the_side_that_has_rows(self) -> None:
        result = split_alternation([self.row(16.0, 0)])
        assert result is not None
        self.assertIn("on", result)
        self.assertNotIn("off", result)
        self.assertNotIn("delta", result)

    def test_returns_none_without_the_alt_off_column(self) -> None:
        self.assertIsNone(
            split_alternation(
                [{"frame_ms": 16.0, "frontend_ms": 10.0, "backend_ms": 2.0}]
            )
        )
        with self.assertRaises(ValueError):
            describe([])

    def test_keep_all_returns_rows_beyond_the_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "perf.csv"
            path.write_text(
                "flip,present,frame_ms,frontend_ms,backend_ms,gpu_ms,"
                "alt_off\n"
                "1,1,16,10,6,-1,0\n"
                "2,2,17,11,6,-1,2\n"
                "3,3,18,12,6,-1,2\n",
                encoding="ascii",
            )
            self.assertEqual(len(load_samples(path, 2)), 2)
            self.assertEqual(len(load_samples(path, 2, keep_all=True)), 3)

    def test_builds_the_runtime_environment(self) -> None:
        class Args:
            env = ["SR_FOO=bar=baz"]
            alternate = "merge,texdecode"
            alternate_presents = 30
            pso_keys = None

        environment = build_extra_environment(Args())
        self.assertEqual(environment["SR_FOO"], "bar=baz")
        self.assertEqual(environment["SR_PERF_ALTERNATE"], "merge,texdecode")
        self.assertEqual(environment["SR_PERF_ALTERNATE_PRESENTS"], "30")
        Args.env = ["missing-separator"]
        with self.assertRaises(ValueError):
            build_extra_environment(Args())


class BenchmarkDriverTests(unittest.TestCase):
    def test_only_default_workloads_are_acceptance_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "mga2.exe"
            executable.touch()
            executable.with_name("graphics.ini").write_text(
                "renderer=d3d12\ninternal_resolution=4\n"
                "texture_scale=2\nd3d12_full_rate=1\n",
                encoding="ascii",
            )
            image = root / "image.bin"
            image.touch()
            iso = root / "disc.iso"
            iso.touch()
            memstick = root / "memstick"
            save = memstick / "PSP" / "SAVEDATA" / "ULUS10077003"
            save.mkdir(parents=True)
            (save / "PARAM.SFO").write_bytes(b"sfo")
            (save / "00000000.000").write_bytes(b"\0" * 48_800)
            base = [
                "--executable", str(executable), "--image", str(image),
                "--iso", str(iso), "--memstick", str(memstick),
            ]
            calls = []

            def fake_case(**kwargs):
                calls.append(kwargs)
                accepted = kwargs["validate_result"]
                return {
                    "case": kwargs["case"].name,
                    "validated": accepted,
                    "passed": True if accepted else None,
                    "failures": [],
                }

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with mock.patch.object(
                    benchmark_arena, "run_benchmark_case", side_effect=fake_case
                ):
                    for index, (options, expected) in enumerate((
                        ([], True),
                        (["--env", "SR_GEDUMP=1"], False),
                        (["--maximum-frame-ms", "999"], False),
                        (["--window", "119"], False),
                    )):
                        result = benchmark_arena.main(
                            base + ["--case", "dead-cell", "--output",
                                    str(root / f"arena-{index}")] + options
                        )
                        self.assertEqual(result, 0)
                        self.assertEqual(calls[-1]["validate_result"], expected)
                    self.assertEqual(
                        benchmark_arena.main(base + ["--maximum-gpu-ms", "nan"]),
                        2,
                    )

                with mock.patch.object(
                    benchmark_tutorial, "run_benchmark_case", side_effect=fake_case
                ):
                    for options, expected in (
                        ([], True),
                        (["--pulse", "31001"], False),
                        (["--maximum-frame-ms", "999"], False),
                    ):
                        self.assertEqual(benchmark_tutorial.main(base + options), 0)
                        self.assertEqual(calls[-1]["validate_result"], expected)


if __name__ == "__main__":
    unittest.main()
