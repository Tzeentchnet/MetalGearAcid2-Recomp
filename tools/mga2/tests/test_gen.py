from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import gen


class GeneratorTests(unittest.TestCase):
    def test_public_environment_does_not_require_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": temporary},
                clear=True,
            ):
                environment = gen.prepare_environment()

        self.assertIn("PSP_RECOMP_CODEGEN_CACHE", environment)
        self.assertNotIn("PSP_RECOMP_FUNCTION_CATALOG", environment)

    def test_existing_local_catalog_is_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            catalog = (
                Path(temporary)
                / "psp-recomp"
                / "function-catalog"
                / "catalog.toml"
            )
            catalog.parent.mkdir(parents=True)
            catalog.write_text("schema_version = 1\n", encoding="ascii")
            with mock.patch.dict(
                os.environ,
                {"LOCALAPPDATA": temporary},
                clear=True,
            ):
                environment = gen.prepare_environment()

        self.assertEqual(
            Path(environment["PSP_RECOMP_FUNCTION_CATALOG"]),
            catalog,
        )

    def test_explicit_catalog_path_is_required(self) -> None:
        tools = Path("toolkit") / "tools"
        catalog, required = gen.resolve_function_catalog(
            tools,
            {"PSP_RECOMP_FUNCTION_CATALOG": "missing-catalog.toml"},
        )

        self.assertEqual(catalog, Path("missing-catalog.toml"))
        self.assertTrue(required)

    def test_catalog_can_be_disabled_explicitly(self) -> None:
        catalog, required = gen.resolve_function_catalog(
            Path("toolkit") / "tools",
            {"PSP_RECOMP_FUNCTION_CATALOG": "0"},
        )

        self.assertIsNone(catalog)
        self.assertFalse(required)

    def test_missing_public_default_catalog_is_optional(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary) / "tools"
            tools.mkdir()
            catalog, required = gen.resolve_function_catalog(tools, {})

        self.assertIsNone(catalog)
        self.assertFalse(required)

    def test_hash_verification_rejects_modified_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            prx = Path(temporary) / "module.prx"
            prx.write_bytes(b"synthetic module")
            expected = hashlib.sha1(b"synthetic module").hexdigest()
            gen.verify_prx(prx, expected)
            prx.write_bytes(b"modified module")
            with self.assertRaisesRegex(ValueError, "SHA-1 mismatch"):
                gen.verify_prx(prx, expected)

    def test_single_file_mode_is_not_offered(self) -> None:
        with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as result:
            gen.parse_args(["gen.py", "--single"])
        self.assertEqual(result.exception.code, 2)

    def test_staged_generation_uses_only_current_split_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            toolkit = root / "toolkit"
            (toolkit / "tools").mkdir(parents=True)
            (toolkit / "tools" / "codegen.py").touch()
            main_bytes = b"synthetic main"
            module_bytes = b"synthetic module"
            disc = root / "build" / "mga2" / "disc"
            disc.mkdir(parents=True)
            (disc / "main.bin").write_bytes(main_bytes)
            (disc / "module.prx").write_bytes(module_bytes)
            (root / "config").mkdir()
            (root / "config" / "mga2.toml").write_text(
                "[runtime]\n"
                f'commit = "{"a" * 40}"\n'
                "[disc.files]\n"
                f'"main.bin" = "{hashlib.sha1(main_bytes).hexdigest()}"\n'
                "[module]\n"
                'file = "main.bin"\nbase = 1\n'
                "[[native_module]]\n"
                'file = "module.prx"\nbase = 2\n'
                'symbol_prefix = "mga2_test"\n'
                f'sha1 = "{hashlib.sha1(module_bytes).hexdigest()}"\n',
                encoding="utf-8",
            )
            output = root / "generated"
            output.mkdir()
            (output / "mga2_recomp.c").write_text("old single", encoding="ascii")
            (output / "mga2_recomp_999.c").write_text("old split", encoding="ascii")
            chunk = "000"
            fail_native = False

            def fake_generate(**kwargs):
                if kwargs["stem"] == "mga2_test" and fail_native:
                    return 1
                directory = kwargs["out_dir"]
                directory.mkdir(parents=True, exist_ok=True)
                stem = kwargs["stem"]
                for name in (
                    f"{stem}_recomp.h",
                    f"{stem}_recomp_{chunk}.c",
                    f"{stem}_recomp_register.c",
                ):
                    (directory / name).write_text(stem, encoding="ascii")
                if kwargs.get("image_name"):
                    (directory / kwargs["image_name"]).write_bytes(b"image")
                return 0

            argv = ["gen.py", "--toolkit", str(toolkit), "--out", str(output)]
            with mock.patch.object(gen, "ROOT", root), mock.patch.object(
                gen, "identify_toolkit", return_value={"source_sha256": None}
            ), mock.patch.object(
                gen, "generate_prx", side_effect=fake_generate
            ) as generate_prx, redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                self.assertEqual(gen.main(argv), 0)
                manifest = output / gen.SOURCE_MANIFEST
                first = manifest.read_text(encoding="utf-8").splitlines()
                self.assertIn("mga2_recomp_000.c", first)
                self.assertIn("modules/mga2_test/mga2_test_recomp_000.c", first)
                self.assertNotIn("mga2_recomp.c", first)
                self.assertNotIn("mga2_recomp_999.c", first)

                source = output / "mga2_recomp_000.c"
                original_mtime = source.stat().st_mtime_ns
                self.assertEqual(gen.main(argv), 0)
                self.assertEqual(source.stat().st_mtime_ns, original_mtime)

                chunk = "001"
                self.assertEqual(gen.main(argv), 0)
                second = manifest.read_text(encoding="utf-8").splitlines()
                self.assertIn("mga2_recomp_001.c", second)
                self.assertNotIn("mga2_recomp_000.c", second)
                self.assertTrue((output / "mga2_recomp_000.c").exists())
                self.assertTrue((output / "mga2_recomp.c").exists())

                fail_native = True
                self.assertEqual(gen.main(argv), 1)
                self.assertEqual(manifest.read_text(encoding="utf-8").splitlines(), second)

                fail_native = False
                (disc / "module.prx").write_bytes(b"corrupted")
                previous_calls = generate_prx.call_count
                self.assertEqual(gen.main(argv), 1)
                self.assertEqual(generate_prx.call_count, previous_calls)
                self.assertEqual(manifest.read_text(encoding="utf-8").splitlines(), second)


if __name__ == "__main__":
    unittest.main()
