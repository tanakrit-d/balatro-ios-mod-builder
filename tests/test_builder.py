import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

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
        archive = builder.zip_bytes({
            "Balatro.love/main.lua": b"game",
            "Balatro.love/resources/card.png": b"image",
            "__MACOSX/._Balatro.love": b"metadata",
            "Balatro.love/._main.lua": b"metadata",
            "Balatro.love/.DS_Store": b"metadata",
        })
        self.assertEqual(builder.game_files(archive), {
            "main.lua": b"game", "resources/card.png": b"image",
        })

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

    def test_multiplayer_requires_exact_smods(self):
        records = [
            {"branchName": "main", "version": "0.5.0", "smods_version": "latest"}
        ]
        with patch.object(builder, "get", return_value=records):
            with self.assertRaisesRegex(ValueError, "exact"):
                builder.resolve()

    def test_resolution_uses_version_and_exact_tag(self):
        records = [
            {
                "branchName": "main",
                "version": v,
                "smods_version": "strict",
                "url": "https://example.com/mod",
            }
            for v in ["0.5.1", "0.2.13c", "0.2.13c~smallworld", "0.5.0"]
        ]

        def get(url):
            return records if "balatromp" in url else [{"sha": "commit"}]

        with (
            patch.object(builder, "get", side_effect=get),
            patch.object(
                builder,
                "release",
                side_effect=lambda repo, tag=None: {
                    "version": tag or "latest-resolved",
                    "url": "https://example.com/source",
                },
            ) as release,
        ):
            lock = builder.resolve()
            self.assertEqual(lock["streams"]["multiplayer"]["mod"]["version"], "0.5.1")
            release.assert_any_call("Steamodded/smods", "strict")

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
                        for stream in ("multiplayer", "pokermon")
                        for name, data in {
                            "Assets.car": stream.encode(),
                            "icon-info.plist": plistlib.dumps({
                                "CFBundleIcons": {"CFBundlePrimaryIcon": {
                                    "CFBundleIconName": "iOS AppIcon",
                                }},
                            }),
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
                            "version": "0.5.5" if s == "multiplayer" else "v3.9.1",
                        },
                        "smods": {"url": "https://example.com/smods"},
                    }
                    for s in ["multiplayer", "pokermon"]
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
                    ("multiplayer", "Multiplayer"),
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
                    version = "0.5.5" if stream == "multiplayer" else "3.9.1"
                    self.assertEqual(info["CFBundleShortVersionString"], version)
                    self.assertEqual(info["CFBundleVersion"], version)
                    self.assertEqual(files[app + "Assets.car"], stream.encode())
                    self.assertFalse(any(p.startswith("builder-icons/") for p in files))
                    self.assertIn(app + "bundled-mods/" + folder + "/mod.lua", files)
                    self.assertIn(app + "bundled-mods/smods/mod.lua", files)
                    self.assertIn(app + "bundled-mods/Extra/mod.lua", files)
                    self.assertNotIn(app + "_CodeSignature/CodeResources", files)
                    self.assertEqual(
                        builder.game_files(files[app + "game.love"]),
                        builder.game_files(game),
                    )
                    self.assertEqual(
                        plistlib.loads(files[app + "Info.plist"])["CFBundleIdentifier"],
                        "mod.balatro." + stream,
                    )
                    scenes = plistlib.loads(files[app + "Info.plist"])[
                        "UIApplicationSceneManifest"
                    ]
                    self.assertFalse(scenes["UIApplicationSupportsMultipleScenes"])
                    for key in (
                        "UISupportedInterfaceOrientations",
                        "UISupportedInterfaceOrientations~ipad",
                    ):
                        self.assertEqual(info[key], [
                            "UIInterfaceOrientationLandscapeLeft",
                            "UIInterfaceOrientationLandscapeRight",
                        ])
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
