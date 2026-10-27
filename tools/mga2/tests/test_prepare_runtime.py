from __future__ import annotations

from pathlib import Path
import shutil
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import prepare_runtime


@unittest.skipUnless(shutil.which("git"), "Git is required for runtime patches")
class PrepareRuntimeTests(unittest.TestCase):
    def test_patch_is_isolated_verified_and_rejected_on_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toolkit = root / "toolkit"
            for relative in prepare_runtime.COPIED_DIRECTORIES:
                (toolkit / relative).mkdir(parents=True, exist_ok=True)
            source = toolkit / "src" / "rt" / "probe.c"
            source.write_bytes(b"old value\r\n")
            for relative in prepare_runtime.SHADERS.values():
                (toolkit / relative).parent.mkdir(parents=True, exist_ok=True)
                (toolkit / relative).write_bytes(b"old shader")

            shaders = root / "shaders"
            shaders.mkdir()
            for name in prepare_runtime.SHADERS:
                (shaders / name).write_bytes(name.encode("ascii"))
            patch = root / "change.patch"
            patch.write_text(
                "diff --git a/src/rt/probe.c b/src/rt/probe.c\n"
                "--- a/src/rt/probe.c\n"
                "+++ b/src/rt/probe.c\n"
                "@@ -1 +1 @@\n"
                "-old value\n"
                "+new value\n",
                encoding="ascii",
                newline="\n",
            )
            overlay = root / "build" / "mga2-runtime-overlay"
            prepare_runtime.prepare(toolkit, overlay, patch, shaders)
            self.assertEqual(source.read_bytes(), b"old value\r\n")
            self.assertEqual(
                (overlay / "src" / "rt" / "probe.c").read_text(
                    encoding="ascii"
                ),
                "new value\n",
            )
            for name, relative in prepare_runtime.SHADERS.items():
                self.assertEqual(
                    (overlay / relative).read_bytes(), name.encode("ascii")
                )
            prepare_runtime.verify(overlay, patch, shaders)

            changed = overlay / "src" / "rt" / "probe.c"
            changed.write_text("tampered\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "differs"):
                prepare_runtime.verify(overlay, patch, shaders)
            prepare_runtime.prepare(toolkit, overlay, patch, shaders)
            prepare_runtime.verify(overlay, patch, shaders)

            patch.write_text("not a patch\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "cannot apply"):
                prepare_runtime.prepare(toolkit, overlay, patch, shaders)
            self.assertEqual(
                changed.read_text(encoding="ascii"), "new value\n"
            )

    def test_refuses_unowned_overlay_and_toolkit_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toolkit = root / "toolkit"
            toolkit.mkdir()
            unowned = root / "build" / "mga2-runtime-overlay"
            unowned.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "unowned"):
                prepare_runtime.prepare(
                    toolkit, unowned, root / "patch", root / "shaders"
                )
            self.assertTrue(unowned.is_dir())
            with self.assertRaisesRegex(ValueError, "overlap"):
                prepare_runtime.prepare(
                    toolkit, toolkit / "mga2-runtime-overlay",
                    root / "patch", root / "shaders",
                )


if __name__ == "__main__":
    unittest.main()
