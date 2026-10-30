"""Exercise the production installer with temporary bundle and Documents paths."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    sys.platform == "darwin" and shutil.which("clang++"), "Requires macOS and clang++"
)
class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.work.cleanup)
        root = Path(cls.work.name)
        # Include the real installer; only its path arguments differ from iOS.
        shutil.copy2(ROOT / "native/install-mods.mm", root / "install-mods.mm")
        source = root / "harness.mm"
        source.write_text(
            "#import <Foundation/Foundation.h>\n"
            '#include "install-mods.mm"\n'
            "int main() {\n"
            "    builder_install_mods_at_paths(\n"
            '        [NSString stringWithUTF8String:getenv("INSTALLER_TEST_BUNDLE")],\n'
            '        [NSString stringWithUTF8String:getenv("INSTALLER_TEST_DOCUMENTS")]);\n'
            "    return 0;\n"
            "}\n"
        )
        cls.executable = root / "installer"
        subprocess.run(
            [
                "clang++",
                "-fobjc-arc",
                "-framework",
                "Foundation",
                str(source),
                "-o",
                str(cls.executable),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root / "bundle"
        self.documents = self.root / "Documents"
        self.mods = self.documents / "game/Mods"
        self.state = self.documents / "game/.builder-mods.json"

    def install(self, files):
        if self.bundle.exists():
            shutil.rmtree(self.bundle)
        self.bundle.mkdir()
        manifest = {}
        for name, data in files.items():
            path = self.bundle / "bundled-mods" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            manifest[name] = hashlib.sha256(data).hexdigest()
        (self.bundle / "bundled-mods.json").write_text(json.dumps(manifest))
        env = os.environ.copy()
        env.update(
            INSTALLER_TEST_BUNDLE=str(self.bundle),
            INSTALLER_TEST_DOCUMENTS=str(self.documents),
        )
        result = subprocess.run(
            [str(self.executable)], env=env, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(self.state.read_text()), manifest)

    def test_file_becomes_directory(self):
        self.install({"Test/assets": b"old"})
        self.install({"Test/assets/new.lua": b"new"})
        self.assertEqual((self.mods / "Test/assets/new.lua").read_bytes(), b"new")

    def test_upgrade_replaces_legacy_multiplayer_with_pvp_and_api(self):
        self.install(
            {"Multiplayer/Multiplayer.json": b"legacy", "Multiplayer/core.lua": b"old"}
        )
        config = self.documents / "game/config/Multiplayer.jkr"
        config.parent.mkdir(parents=True)
        config.write_bytes(b"user config")
        self.install(
            {
                "MultiplayerPvP/MultiplayerPvP.json": b"pvp",
                "MultiplayerAPI/MultiplayerAPI.json": b"api",
            }
        )
        self.assertFalse((self.mods / "Multiplayer").exists())
        self.assertTrue((self.mods / "MultiplayerPvP/MultiplayerPvP.json").exists())
        self.assertTrue((self.mods / "MultiplayerAPI/MultiplayerAPI.json").exists())
        self.assertEqual(config.read_bytes(), b"user config")

    def test_directory_becomes_file(self):
        self.install(
            {"Test/assets/nested/old.lua": b"old", "Test/assets/other.lua": b"other"}
        )
        self.install({"Test/assets": b"new"})
        self.assertEqual((self.mods / "Test/assets").read_bytes(), b"new")

    def test_stale_cleanup_preserves_user_files(self):
        self.install({"Test/old.lua": b"old", "Removed/main.lua": b"removed"})
        config = self.mods / "Test/settings/user.json"
        config.parent.mkdir()
        config.write_bytes(b"user settings")
        self.install({"Test/new.lua": b"new"})
        self.assertEqual(config.read_bytes(), b"user settings")
        self.assertFalse((self.mods / "Test/old.lua").exists())
        self.assertFalse((self.mods / "Removed").exists())

    def test_repeated_install_and_changed_files(self):
        self.install({"Test/main.lua": b"original", "Test/restore.lua": b"restore"})
        (self.mods / "Test/main.lua").write_bytes(b"local edit")
        (self.mods / "Test/restore.lua").unlink()
        self.install({"Test/main.lua": b"original", "Test/restore.lua": b"restore"})
        self.assertEqual((self.mods / "Test/main.lua").read_bytes(), b"local edit")
        self.assertEqual((self.mods / "Test/restore.lua").read_bytes(), b"restore")
        self.install({"Test/main.lua": b"updated"})
        self.assertEqual((self.mods / "Test/main.lua").read_bytes(), b"updated")
        self.assertFalse((self.mods / "Test/restore.lua").exists())

    def test_empty_manifest_creates_state(self):
        self.install({})
