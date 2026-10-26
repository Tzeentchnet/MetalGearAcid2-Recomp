from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

from benchmark_arena import (
    ARENA_CASES,
    combine_results,
    require_arena_save,
    select_cases,
)
from benchmark_common import (
    CLEARED_ENVIRONMENT,
    PerformanceThresholds,
    load_samples,
    parse_framebuffer_stats,
    read_graphics_profile,
    summarize,
    validate,
)


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
        self.assertAlmostEqual(float(summary["fps"]), 1000.0 / 15.0)
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
        summary = {
            "fps": 58.0,
            "p95_ms": 19.0,
            "maximum_ms": 40.0,
            "gpu_maximum_ms": 20.0,
            **stats,
        }
        failures = validate(summary, PerformanceThresholds())
        self.assertEqual(len(failures), 4)
        with self.assertRaisesRegex(ValueError, "statistics are missing"):
            parse_framebuffer_stats("no cache line")

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
        self.assertIn("SR_GE_SCALAR_SPLINE", CLEARED_ENVIRONMENT)
        self.assertIn("SR_GE_SPLINE_LOG", CLEARED_ENVIRONMENT)


if __name__ == "__main__":
    unittest.main()
