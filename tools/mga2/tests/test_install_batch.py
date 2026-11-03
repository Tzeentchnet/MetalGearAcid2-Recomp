from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
INSTALLER = ROOT / "install.bat"


@unittest.skipUnless(os.name == "nt", "install.bat requires Windows")
class InstallBatchTests(unittest.TestCase):
    def test_preflight_reports_multiple_missing_prerequisites(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "game.iso"
            source.write_bytes(b"not used because preflight fails")
            toolkit = root / "psp-recomp"
            toolkit.mkdir()
            install_dir = root / "install"
            runner = root / "run-installer.bat"
            runner.write_text(
                "@echo off\n"
                f'call "{INSTALLER}" "{source}" '
                f'--toolkit "{toolkit}" --install-dir "{install_dir}"\n'
                "exit /b %ERRORLEVEL%\n",
                encoding="ascii",
            )

            environment = os.environ.copy()
            system_root = Path(
                environment.get("SystemRoot") or environment["SYSTEMROOT"]
            )
            environment["PATH"] = str(system_root / "System32")
            environment["TEMP"] = str(root)
            environment["TMP"] = str(root)
            environment["ProgramFiles(x86)"] = str(root / "missing-program-files")
            environment["VULKAN_SDK"] = str(root / "missing-vulkan-sdk")
            environment["PROCESSOR_ARCHITECTURE"] = "AMD64"
            for name in (
                "PROCESSOR_ARCHITEW6432",
                "PSP_RECOMP_DIR",
                "VCVARS64",
                "VSCMD_ARG_TGT_ARCH",
                "VSCMD_VER",
                "VSINSTALLDIR",
                "WindowsSdkDir",
                "WindowsSDKVersion",
            ):
                environment.pop(name, None)

            result = subprocess.run(
                [
                    environment.get("ComSpec") or environment["COMSPEC"],
                    "/d",
                    "/c",
                    str(runner),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )

            output = result.stdout + result.stderr
            self.assertEqual(result.returncode, 1, output)
            self.assertIn("psp-recomp checkout is incomplete", output)
            self.assertIn("Python 3.11 or newer was not found", output)
            self.assertIn("Git was not found", output)
            self.assertIn("Visual Studio 2022 C++ Build Tools were not found", output)
            self.assertIn("CMake 3.25 or newer was not found", output)
            self.assertIn("Ninja was not found", output)
            self.assertIn("clang-cl was not found", output)
            self.assertIn("Vulkan SDK", output)
            self.assertIn("one or more prerequisites failed", output)
            self.assertNotIn("ISO input is a directory", output)
            self.assertNotIn("[1/6]", output)
