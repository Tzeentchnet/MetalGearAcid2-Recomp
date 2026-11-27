from __future__ import annotations

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


class ManifestTests(unittest.TestCase):
    def test_manifest_names_this_entry_point_and_known_settings(self) -> None:
        manifest = json.loads(
            (ROOT / "recomplauncher.json").read_text(encoding="utf-8")
        )
        for part in ("start", "prepare"):
            self.assertEqual(manifest[part]["program"], ["play.bat"])
            self.assertEqual(manifest[part]["args"][0], f"--{part.replace('start', 'play')}")
        known = {
            "renderer", "internal_resolution", "texture_scale",
            "d3d12_full_rate", "anti_aliasing", "skip_startup", "outlines",
        }
        self.assertEqual(set(manifest["config"][0]["new"]), known)
        for setting in manifest["settings"]:
            for choice in setting.get("choices", []):
                self.assertLessEqual(set(choice.get("set", {})), known)


if __name__ == "__main__":
    unittest.main()
