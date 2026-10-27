from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import toolkit_identity


class ToolkitIdentityTests(unittest.TestCase):
    def test_requires_pinned_clean_checkout_and_detects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            toolkit = Path(temporary)
            (toolkit / "tools").mkdir()
            source = toolkit / "tools" / "codegen.py"
            source.write_text("first\n", encoding="ascii")
            commit = "a" * 40
            state = {"revision": commit, "dirty": False}

            def fake_git(path, *args):
                if args[:2] == ("rev-parse", "--show-toplevel"):
                    return SimpleNamespace(returncode=0, stdout=str(toolkit), stderr="")
                if args[:2] == ("rev-parse", "--verify"):
                    return SimpleNamespace(
                        returncode=0, stdout=state["revision"], stderr=""
                    )
                return SimpleNamespace(
                    returncode=0,
                    stdout=" M tools/codegen.py" if state["dirty"] else "",
                    stderr="",
                )

            with mock.patch.object(toolkit_identity, "git_output", side_effect=fake_git):
                clean = toolkit_identity.identify_toolkit(toolkit, commit)
                self.assertEqual(clean["revision"], commit)
                self.assertFalse(clean["dirty"])
                self.assertIsNone(clean["source_sha256"])

                state["revision"] = "b" * 40
                with self.assertRaisesRegex(ValueError, "expected"):
                    toolkit_identity.identify_toolkit(toolkit, commit)

                state["revision"] = commit
                state["dirty"] = True
                with self.assertRaisesRegex(ValueError, "uncommitted"):
                    toolkit_identity.identify_toolkit(toolkit, commit)
                first = toolkit_identity.identify_toolkit(
                    toolkit, commit, allow_unsupported=True
                )
                source.write_text("second\n", encoding="ascii")
                second = toolkit_identity.identify_toolkit(
                    toolkit, commit, allow_unsupported=True
                )
                self.assertNotEqual(first["source_sha256"], second["source_sha256"])
                (toolkit / "assets").mkdir()
                third = toolkit_identity.identify_toolkit(
                    toolkit, commit, allow_unsupported=True
                )
                self.assertNotEqual(second["source_sha256"], third["source_sha256"])

                manifest = toolkit / "identity.json"
                manifest.write_text(json.dumps(first), encoding="utf-8")
                toolkit_identity.check_manifest(manifest, first)
                with self.assertRaisesRegex(ValueError, "differs"):
                    toolkit_identity.check_manifest(manifest, second)

    def test_source_archive_needs_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            toolkit = Path(temporary)
            (toolkit / "tools").mkdir()
            (toolkit / "tools" / "codegen.py").write_text("", encoding="ascii")
            not_git = SimpleNamespace(returncode=128, stdout="", stderr="not a repo")
            with mock.patch.object(toolkit_identity, "git_output", return_value=not_git):
                with self.assertRaisesRegex(ValueError, "not a verifiable Git"):
                    toolkit_identity.identify_toolkit(toolkit, "a" * 40)
                identity = toolkit_identity.identify_toolkit(
                    toolkit, "a" * 40, allow_unsupported=True
                )
            self.assertIsNone(identity["revision"])
            self.assertIsNotNone(identity["source_sha256"])


if __name__ == "__main__":
    unittest.main()
