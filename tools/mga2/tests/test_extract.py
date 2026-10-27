from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import extract


class FakeIso:
    def __init__(self, data: dict[str, bytes]):
        self.data = data
        self.entries = {
            path: SimpleNamespace(path="/" + path, lba=index)
            for index, path in enumerate(data, 1)
        }
        self.reads: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def lookup(self, path):
        return self.entries[path]

    def files(self):
        return list(self.entries.values())

    def read(self, entry):
        path = entry.path.lstrip("/")
        self.reads.append(path)
        return self.data[path]


class ExtractionTests(unittest.TestCase):
    def test_missing_iso_is_reported_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.toml"
            config.write_text("[disc]\niso_size = 1\n", encoding="ascii")
            with redirect_stderr(StringIO()) as stderr:
                result = extract.main([
                    "extract.py", str(root / "missing.iso"),
                    "--config", str(config),
                ])
            self.assertEqual(result, 1)
            self.assertIn("extraction failed", stderr.getvalue())

    def test_verifies_every_input_before_publishing(self) -> None:
        main_path = "PSP_GAME/SYSDIR/BOOT.BIN"
        module_path = "PSP_GAME/USRDIR/modules/example.prx"
        main_bytes = b"\x7fELF synthetic main"
        module_bytes = b"\x7fELF synthetic module"
        iso_bytes = b"synthetic iso"

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            iso = root / "disc.iso"
            iso.write_bytes(iso_bytes)
            config = root / "config.toml"
            config.write_text(
                "[disc]\n"
                f"iso_size = {len(iso_bytes)}\n"
                f'iso_sha1 = "{hashlib.sha1(iso_bytes).hexdigest()}"\n'
                'plaintext_module_roots = ["PSP_GAME/USRDIR/modules"]\n'
                "[disc.files]\n"
                f'"{main_path}" = "{hashlib.sha1(main_bytes).hexdigest()}"\n'
                "[[native_module]]\n"
                f'file = "{module_path}"\n'
                f'sha1 = "{hashlib.sha1(module_bytes).hexdigest()}"\n',
                encoding="utf-8",
            )
            output = root / "disc"
            old_main = output / Path(main_path)
            old_main.parent.mkdir(parents=True)
            old_main.write_bytes(b"previous verified output")
            inventory = root / "disc_inventory.json"
            inventory.write_text("previous inventory", encoding="utf-8")

            def run(fake):
                with mock.patch.object(extract, "Iso", return_value=fake):
                    with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                        return extract.main(
                            ["extract.py", str(iso), "--config", str(config),
                             "--out", str(output)]
                        )

            bad_module = FakeIso({main_path: main_bytes, module_path: b"wrong"})
            self.assertEqual(run(bad_module), 1)
            self.assertEqual(old_main.read_bytes(), b"previous verified output")
            self.assertEqual(inventory.read_text(encoding="utf-8"), "previous inventory")
            self.assertFalse((output / Path(module_path)).exists())

            missing_module = FakeIso({main_path: main_bytes})
            self.assertEqual(run(missing_module), 1)
            self.assertEqual(old_main.read_bytes(), b"previous verified output")

            verified = FakeIso({main_path: main_bytes, module_path: module_bytes})
            self.assertEqual(run(verified), 0)
            self.assertEqual(verified.reads, [main_path, module_path])
            self.assertEqual(old_main.read_bytes(), main_bytes)
            self.assertEqual((output / Path(module_path)).read_bytes(), module_bytes)
            result = json.loads(inventory.read_text(encoding="utf-8"))
            self.assertEqual(result["files"][0]["sha1"], hashlib.sha1(module_bytes).hexdigest())


if __name__ == "__main__":
    unittest.main()
