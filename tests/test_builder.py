import base64
import io
import json
import plistlib
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import builder


class BuilderTests(unittest.TestCase):
    def test_invalid_game_input_has_safe_diagnostics(self):
        for data, message in [
            (b"", "empty"),
            (b" <!DOCTYPE html><html>secret sharing URL</html>", "HTML"),
            (b"PK\x03\x04truncated", "truncated or corrupt"),
            (b"not an archive", "not a valid ZIP"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message) as error:
                    builder.game_files(data)
                self.assertNotIn("secret sharing URL", str(error.exception))

    def test_game_extraction_from_macos_folder_zip(self):
        archive = builder.zip_bytes(
            {
                "Balatro.love/main.lua": b"game",
                "Balatro.love/resources/card.png": b"image",
                "__MACOSX/._Balatro.love": b"metadata",
                "Balatro.love/._main.lua": b"metadata",
                "Balatro.love/.DS_Store": b"metadata",
            }
        )
        self.assertEqual(
            builder.game_files(archive),
            {
                "main.lua": b"game",
                "resources/card.png": b"image",
            },
        )

    def test_game_extraction_from_zip(self):
        files = {"main.lua": b"game", "conf.lua": b"identity"}
        game = builder.zip_bytes(files)
        for name, data in [
            ("Balatro.love", game),
            ("Balatro/Balatro.exe", b"MZ executable stub" + game),
            ("Balatro.app/Contents/Resources/game.love", game),
        ]:
            with self.subTest(name=name):
                archive = builder.zip_bytes({name: data, "README.txt": b"readme"})
                self.assertEqual(builder.game_files(archive), files)

    def test_reject_traversal_and_symlinks(self):
        for name in ["../escape", "/absolute", "foo\\bar"]:
            with self.assertRaises(ValueError):
                builder.archive_files(builder.zip_bytes({name: b"x"}))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            info = zipfile.ZipInfo("link")
            info.external_attr = 0o120777 << 16
            z.writestr(info, b"/etc/passwd")
        with self.assertRaises(ValueError):
            builder.archive_files(buf.getvalue())

    def test_resolution_tracks_pvp_api_and_manifest_pinned_smods(self):
        versions = {
            "Balatro-Multiplayer/BalatroMultiplayerPvP": "v1.0.1",
            "Balatro-Multiplayer/BalatroMultiplayerAPI": "v1.0.2",
            "Steamodded/smods": "26.1002.0",
        }

        def get(url):
            self.assertTrue(url.startswith(builder.API))
            if "/commits?" in url:
                return [{"sha": "commit"}]
            if "/contents/" in url:
                repo, query = url.removeprefix(builder.API).split("/contents/")
                self.assertTrue(query.endswith("?ref=" + versions[repo]))
                return {
                    "encoding": "base64",
                    "content": base64.b64encode(
                        json.dumps(
                            {"dependencies": ["Steamodded (>=1.0.0~BETA-1814a)"]}
                        ).encode()
                    ).decode(),
                }
            if "/releases/tags/" in url:
                self.assertTrue(url.endswith("/releases/tags/1.0.0-beta-1814a"))
                return {
                    "tag_name": "1.0.0-beta-1814a",
                    "zipball_url": "https://example.com/pinned-smods",
                }
            self.assertTrue(url.endswith("/releases/latest"))
            repo = url.removeprefix(builder.API).removesuffix("/releases/latest")
            version = versions.get(repo, "v-test")
            return {
                "tag_name": version,
                "zipball_url": builder.API + repo + "/zipball/" + version,
            }

        with patch.object(builder, "get", side_effect=get):
            lock = builder.resolve()
            mp = lock["streams"]["multiplayer"]
            self.assertEqual(mp["mod"]["version"], "v1.0.1")
            self.assertEqual(mp["api"]["version"], "v1.0.2")
            self.assertEqual(mp["smods"]["version"], "1.0.0-beta-1814a")
            self.assertEqual(
                lock["streams"]["pokermon"]["smods"]["version"], "26.1002.0"
            )
            self.assertNotIn("latest", json.dumps(lock))
            versions["Balatro-Multiplayer/BalatroMultiplayerAPI"] = "v1.0.3"
            updated = builder.resolve()
            self.assertNotEqual(lock, updated)
            self.assertEqual(mp["mod"], updated["streams"]["multiplayer"]["mod"])

    def test_smods_pin_uses_stricter_minimum_from_both_mods(self):
        for pvp, api, expected in [
            ("1.0.0~BETA-1814a", "1.0.0~BETA-1814b", "1.0.0-beta-1814b"),
            ("1.0.0~BETA-2000a", "1.0.0~BETA-900a", "1.0.0-beta-2000a"),
            ("1.0.0~BETA-1814a", "26.1002.0", "26.1002.0"),
            ("1.0.0~BETA-1814a", "1.0.0", "1.0.0"),
        ]:
            with (
                self.subTest(pvp=pvp, api=api),
                patch.object(builder, "release") as release,
            ):
                manifests = {
                    name: {"dependencies": [f"Steamodded (>={minimum})"]}
                    for name, minimum in [("PvP", pvp), ("API", api)]
                }
                builder.required_smods(manifests)
                release.assert_called_once_with("Steamodded/smods", expected)

    def test_smods_requirements_fail_closed_instead_of_using_latest(self):
        for requirements in [
            [],
            ["Lovely (>=0.10)"],
            ["Steamodded"],
            ["Steamodded (<=1.0.0)"],
            ["Steamodded (>=1.0.0) (<=2.0.0)"],
            ["Steamodded (>=unknown)"],
            ["Steamodded (>=1.0.0)", "Steamodded (>=2.0.0)"],
        ]:
            with (
                self.subTest(requirements=requirements),
                patch.object(builder, "release") as release,
                self.assertRaisesRegex(ValueError, "Steamodded"),
            ):
                builder.required_smods({"PvP": {"dependencies": requirements}})
            release.assert_not_called()

    def test_missing_manifest_dependencies_abort_resolution(self):
        for dependencies in (None, "Steamodded (>=1.0.0)", [None]):
            with (
                self.subTest(dependencies=dependencies),
                patch.object(
                    builder,
                    "get",
                    return_value={
                        "encoding": "base64",
                        "content": base64.b64encode(
                            json.dumps({"dependencies": dependencies}).encode()
                        ).decode(),
                    },
                ),
                self.assertRaisesRegex(ValueError, "dependencies"),
            ):
                builder.mod_manifest("owner/repo", "v1.0.1", "mod.json")

    def test_missing_api_release_does_not_fall_back_to_legacy(self):
        with (
            patch.object(
                builder,
                "release",
                side_effect=[{"version": "v1.0.1"}, ValueError("API release missing")],
            ),
            self.assertRaisesRegex(ValueError, "API release missing"),
        ):
            builder.resolve()

    def test_package_contains_both_dependencies_and_static_mods(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "static-mods/common/Extra").mkdir(parents=True)
            (root / "static-mods/common/Extra/mod.lua").write_text("static")
            app = "Payload/Base.app/"
            common = {"lovely": {"version": "v-test"}}
            base = builder.zip_bytes(
                {
                    app + "Info.plist": plistlib.dumps({"CFBundleExecutable": "Base"}),
                    app + "builder-runtime.json": json.dumps(common).encode(),
                    app + "Base": b"executable",
                    app + "Assets.car": b"old icons",
                    app + "_CodeSignature/CodeResources": b"old",
                    **{
                        "builder-icons/" + stream + "/" + name: data
                        for stream in builder.STREAMS
                        for name, data in {
                            "Assets.car": stream.encode(),
                            "NewIcon.png": stream.encode() + b" icon",
                            "icon-info.plist": plistlib.dumps(
                                {
                                    "CFBundleIcons": {
                                        "CFBundlePrimaryIcon": {
                                            "CFBundleIconName": "iOS AppIcon",
                                        }
                                    },
                                }
                            ),
                        }.items()
                    },
                }
            )
            lock = {
                "common": common,
                "streams": {
                    s: {
                        "mod": {
                            "url": "https://example.com/mod",
                            "version": {
                                "multiplayer": "v1.0.1",
                                "multiplayer-legacy": "0.5.5",
                                "pokermon": "v3.9.1",
                            }[s],
                        },
                        "smods": {"url": "https://example.com/smods"},
                        **(
                            {
                                "api": {
                                    "url": "https://example.com/api",
                                    "version": "v1.0.1",
                                }
                            }
                            if s == "multiplayer"
                            else {}
                        ),
                    }
                    for s in builder.STREAMS
                },
            }
            mod = builder.zip_bytes({"repo/mod.lua": b"mod"})
            game = builder.zip_bytes(
                {
                    "Balatro/game.love": builder.zip_bytes(
                        {"main.lua": b"game", "conf.lua": b"identity"}
                    )
                }
            )
            with (
                patch.object(builder, "ROOT", root),
                patch.object(builder, "download", return_value=mod),
            ):
                for stream, folder in [
                    ("multiplayer", "MultiplayerPvP"),
                    ("multiplayer-legacy", "Multiplayer"),
                    ("pokermon", "Pokermon"),
                ]:
                    output = root / (stream + ".ipa")
                    builder.package(stream, lock, base, game, output)
                    with zipfile.ZipFile(output) as archive:
                        self.assertEqual(
                            (archive.getinfo(app + "Base").external_attr >> 16) & 0o777,
                            0o755,
                        )
                    files = builder.archive_files(output.read_bytes())
                    info = plistlib.loads(files[app + "Info.plist"])
                    version = {
                        "multiplayer": "1.0.1",
                        "multiplayer-legacy": "0.5.5",
                        "pokermon": "3.9.1",
                    }[stream]
                    self.assertEqual(info["CFBundleShortVersionString"], version)
                    self.assertEqual(info["CFBundleVersion"], version)
                    self.assertEqual(files[app + "Assets.car"], stream.encode())
                    self.assertEqual(
                        files[app + "NewIcon.png"], stream.encode() + b" icon"
                    )
                    self.assertFalse(any(p.startswith("builder-icons/") for p in files))
                    self.assertIn(app + "bundled-mods/" + folder + "/mod.lua", files)
                    self.assertIn(app + "bundled-mods/smods/mod.lua", files)
                    self.assertEqual(
                        app + "bundled-mods/MultiplayerAPI/mod.lua" in files,
                        stream == "multiplayer",
                    )
                    self.assertEqual(
                        app + "bundled-mods/Multiplayer/mod.lua" in files,
                        stream == "multiplayer-legacy",
                    )
                    if stream == "multiplayer-legacy":
                        self.assertEqual(
                            info["CFBundleDisplayName"], "Balatro (MP) (Legacy)"
                        )
                    self.assertIn(app + "bundled-mods/Extra/mod.lua", files)
                    self.assertNotIn(app + "_CodeSignature/CodeResources", files)
                    self.assertEqual(
                        builder.game_files(files[app + "game.love"]),
                        builder.game_files(game),
                    )
                    self.assertEqual(
                        plistlib.loads(files[app + "Info.plist"])["CFBundleIdentifier"],
                        {
                            "multiplayer": "mod.balatro.multiplayer.pvp",
                            "multiplayer-legacy": "mod.balatro.multiplayer",
                            "pokermon": "mod.balatro.pokermon",
                        }[stream],
                    )
                    scenes = plistlib.loads(files[app + "Info.plist"])[
                        "UIApplicationSceneManifest"
                    ]
                    self.assertFalse(scenes["UIApplicationSupportsMultipleScenes"])
                    for key in (
                        "UISupportedInterfaceOrientations",
                        "UISupportedInterfaceOrientations~ipad",
                    ):
                        self.assertEqual(
                            info[key],
                            [
                                "UIInterfaceOrientationLandscapeLeft",
                                "UIInterfaceOrientationLandscapeRight",
                            ],
                        )
                    self.assertEqual(
                        scenes["UISceneConfigurations"][
                            "UIWindowSceneSessionRoleApplication"
                        ][0]["UISceneDelegateClassName"],
                        "SDLUIKitSceneDelegate",
                    )
            lock["common"] = {}
            with self.assertRaisesRegex(ValueError, "match"):
                builder.package("multiplayer", lock, base, game, root / "bad.ipa")

    def test_example_game_extraction(self):
        example = builder.ROOT / "built-example-ipa/game.ipa"
        if not example.exists():
            self.skipTest("Local example not committed")
        self.assertIn("main.lua", builder.game_files(example.read_bytes()))

    def test_local_game_zip_extraction(self):
        example = builder.ROOT / "local_ipa/Balatro.love.zip"
        if not example.exists():
            self.skipTest("Local game ZIP not committed")
        files = builder.game_files(example.read_bytes())
        self.assertIn("main.lua", files)
        self.assertFalse(any(p.startswith("__MACOSX/") for p in files))


if __name__ == "__main__":
    unittest.main()
