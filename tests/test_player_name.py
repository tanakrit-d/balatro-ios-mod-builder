"""Exercise the standalone renamer with and without multiplayer integrations."""

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "static-mods/common/PlayerName"


class PlayerNameTests(unittest.TestCase):
    def test_metadata_keeps_multiplayer_optional(self):
        manifest = json.loads((MOD / "PlayerName.json").read_text())
        self.assertEqual(manifest["id"], "PlayerName")
        self.assertEqual(len(manifest["dependencies"]), 1)
        self.assertTrue(manifest["dependencies"][0].startswith("Steamodded "))
        self.assertTrue((MOD / manifest["main_file"]).is_file())

    @unittest.skipUnless(shutil.which("lua"), "Requires Lua with its UTF-8 library")
    def test_profile_sync_and_native_editor(self):
        subprocess.run(
            ["lua", str(ROOT / "tests/player_name_test.lua")], cwd=ROOT, check=True
        )
