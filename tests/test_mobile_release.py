import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import builder
import mobile_release as mobile


class MobileReleaseTests(unittest.TestCase):
    def setUp(self):
        self.blobs = {}
        self.base = f"https://github.com/{mobile.REPO}/releases/download/v1.0.5/"
        self.manifest = {
            "schema": 1,
            "repository": mobile.REPO,
            "tag": "v1.0.5",
            "patch_repository_commit": "c" * 40,
            "mobile_revision": 1,
            "projects": {},
        }
        self.release = {
            "id": 42,
            "tag_name": "v1.0.5",
            "draft": False,
            "prerelease": False,
            "assets": [],
        }
        for key, (_, root) in mobile.PROJECTS.items():
            mod = {
                "version": "1.0.5",
                "dependencies": ["Steamodded (>=1.0.0~BETA-1814a)"],
            }
            if key == "pvp":
                mod["dependencies"].append("MultiplayerAPI (>=1.0.2)")
            provenance = {
                "patch_repository_commit": "c" * 40,
                "patch_repository_dirty": False,
                "sources": {key: {"commit": "a" * 40}},
            }
            raw = builder.zip_bytes(
                {
                    root + "/" + root + ".json": json.dumps(mod).encode(),
                    root + "/mobile-build-manifest.json": json.dumps(
                        provenance
                    ).encode(),
                }
            )
            name = root + "-v1.0.5-mobile.1.zip"
            digest = hashlib.sha256(raw).hexdigest()
            self.blobs[self.base + name] = raw
            self.manifest["projects"][key] = {
                "repository": "Balatro-Multiplayer/Balatro" + root,
                "commit": "a" * 40,
                "version": "1.0.5",
                "tag": "v1.0.5",
                "root": root,
                "asset": name,
                "sha256": digest,
                "size": len(raw),
                "download_url": self.base + name,
            }
            self.release["assets"].append(
                {
                    "name": name,
                    "browser_download_url": self.base + name,
                    "digest": "sha256:" + digest,
                }
            )
        self.refresh()

    def refresh(self):
        name = "release-manifest.json"
        raw = json.dumps(self.manifest).encode()
        self.blobs[self.base + name] = raw
        self.release["assets"] = [
            a for a in self.release["assets"] if a["name"] != name
        ]
        self.release["assets"].append(
            {
                "name": name,
                "browser_download_url": self.base + name,
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
            }
        )

    def get(self, url):
        self.assertIn("/releases/", url)
        self.assertNotIn("/commits/", url)
        return self.release

    def resolve(self):
        return mobile.resolve(self.get, self.blobs.__getitem__, builder.archive_files)

    def test_resolves_both_assets_and_checks_pinned_release(self):
        stream, manifests = self.resolve()
        self.assertEqual(stream["source_release"]["commit"], "c" * 40)
        self.assertEqual(manifests["MultiplayerPvP"]["version"], "1.0.5")
        self.assertTrue(
            mobile.verify(stream, self.get, self.blobs.__getitem__)["ready"]
        )
        self.manifest["mobile_revision"] = 2
        self.refresh()
        with self.assertRaisesRegex(ValueError, "changed"):
            mobile.verify(stream, self.get, self.blobs.__getitem__)

    def test_corrupt_asset_fails_resolution_and_packaging(self):
        stream, _ = self.resolve()
        self.blobs[stream["api"]["url"]] = b"corrupt"
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.resolve()
        with self.assertRaisesRegex(ValueError, "checksum"):
            mobile.files(stream["api"], self.blobs.__getitem__, builder.archive_files)

    def test_draft_and_prerelease_rejected(self):
        for flag in ("draft", "prerelease"):
            self.release[flag] = True
            with self.assertRaisesRegex(ValueError, "stable"):
                self.resolve()
            self.release[flag] = False

    def test_wrong_identity_and_url_rejected(self):
        original = copy.deepcopy(self.manifest)
        for field, value in [
            ("root", "wrong"),
            ("commit", "mobile"),
            ("download_url", "https://example.com/mod.zip"),
        ]:
            self.manifest = copy.deepcopy(original)
            self.manifest["projects"]["api"][field] = value
            self.refresh()
            with self.assertRaises(ValueError):
                self.resolve()

    def test_unpatched_api_rejected_and_patched_loader_unchanged(self):
        raw = b"-- BMP_IOS_OPENSSL\nssl_lib, crypto_lib = ffi.C, ffi.C\n"
        path = "MultiplayerAPI/networking/openssl_ffi.lua"
        mods = {path: raw, "MultiplayerAPI/networking/libssl.dll": b"desktop"}
        builder.ios_openssl.prepare_mods(mods)
        self.assertEqual(mods, {path: raw})


if __name__ == "__main__":
    unittest.main()
