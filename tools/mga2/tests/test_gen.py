from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
