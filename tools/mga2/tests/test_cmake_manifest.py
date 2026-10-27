from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
CMAKE = shutil.which("cmake")


@unittest.skipUnless(CMAKE, "CMake is required for manifest integration tests")
class CMakeManifestTests(unittest.TestCase):
    def test_selects_only_manifest_sources_and_rejects_invalid_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            generated = root / "generated"
            module = generated / "modules" / "mga2_test"
            module.mkdir(parents=True)
            sources = [
                "mga2_recomp_000.c",
                "mga2_recomp_register.c",
                "modules/mga2_test/mga2_test_recomp_000.c",
                "modules/mga2_test/mga2_test_recomp_register.c",
            ]
            for name in sources + ["mga2_recomp.c", "mga2_recomp_999.c"]:
                (generated / name).write_text("/* synthetic */\n", encoding="ascii")
            manifest = generated / "mga2_generated_sources.txt"
            script = root / "probe.cmake"
            script.write_text(
                'cmake_minimum_required(VERSION 3.25)\n'
                'include("${MODULE}")\n'
                'mga2_read_generated_sources("${GENERATED_DIR}" sources)\n'
                'foreach(source IN LISTS sources)\n'
                '  message(STATUS "MANIFEST_SOURCE=${source}")\n'
                'endforeach()\n',
                encoding="utf-8",
            )

            def run(entries):
                manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")
                return subprocess.run(
                    [
                        CMAKE,
                        f"-DMODULE={ROOT / 'cmake' / 'GeneratedSources.cmake'}",
                        f"-DGENERATED_DIR={generated}",
                        "-P",
                        str(script),
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )

            valid = run(sources)
            self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
            self.assertNotIn("mga2_recomp_999.c", valid.stdout)
            self.assertNotIn("mga2_recomp.c", valid.stdout)
            for entries, error in (
                (sources + ["../outside.c"], "Invalid generated source"),
                (sources + [sources[0]], "Duplicate generated source"),
                (sources[:-1] + ["modules/mga2_test/mga2_test_recomp_999.c"],
                 "Missing generated source"),
                (sources[:2], "manifest is incomplete"),
            ):
                with self.subTest(entries=entries):
                    result = run(entries)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(error, result.stderr)


if __name__ == "__main__":
    unittest.main()
