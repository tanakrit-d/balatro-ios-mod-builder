import base64
import hashlib
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

    def test_resolution_uses_patched_pair_and_pinned_smods(self):
        pair = {
            "api": {"version": "1.0.5"},
            "mod": {"version": "1.0.5"},
            "source_release": {"tag": "v1.0.5"},
        }
        manifests = {
            name: {"dependencies": ["Steamodded (>=1.0.0~BETA-1814a)"]}
            for name in ("MultiplayerAPI", "MultiplayerPvP")
        }
        with (
            patch.object(
                builder.mobile_release, "resolve", return_value=(pair, manifests)
            ) as resolve,
            patch.object(builder, "get", return_value=[{"sha": "a" * 40}]),
            patch.object(
                builder,
                "release",
                side_effect=lambda repo, tag=None: {"version": tag or "latest"},
            ),
        ):
            lock = builder.resolve()
        resolve.assert_called_once()
        self.assertEqual(
            lock["streams"]["multiplayer"]["smods"]["version"], "1.0.0-beta-1814a"
        )
        self.assertEqual(
            lock["streams"]["multiplayer"]["source_release"]["tag"], "v1.0.5"
        )

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

    def test_missing_mobile_release_does_not_fall_back_to_branches(self):
        with (
            patch.object(
                builder, "get", side_effect=ValueError("mobile release missing")
            ),
            patch.object(builder, "release") as release,
            self.assertRaisesRegex(ValueError, "mobile release missing"),
        ):
            builder.resolve()
        release.assert_not_called()

    def test_package_contains_both_dependencies_and_static_mods(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "static-mods/common/Extra").mkdir(parents=True)
            (root / "static-mods/common/Extra/mod.lua").write_text("static")
            config = b"return { use_custom_server = true, server_host = 'friends.example.com', server_port = 443, server_secure = true }"
            configs = root / "mod-configs/multiplayer/MultiplayerAPI"
            configs.mkdir(parents=True)
            (configs / "config.lua").write_bytes(config)
            app = "Payload/Base.app/"
            common = {"lovely": {"version": "v-test"}}
            ca = b"test certificate bundle"
            tls = {
                "version": builder.ios_openssl.VERSION,
                "source_sha256": builder.ios_openssl.SOURCE_SHA256,
                "platform": "ios-arm64",
                "linkage": "static",
                "ca_sha256": hashlib.sha256(ca).hexdigest(),
            }
            base = builder.zip_bytes(
                {
                    app + "builder-openssl.json": json.dumps(tls).encode(),
                    app + "tls/cacert.pem": ca,
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
                "build": {"version": "1000.32.1"},
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
            mod = builder.zip_bytes(
                {
                    "repo/mod.lua": b"mod",
                    "repo/config.lua": b"return {}",
                    "repo/networking/openssl_ffi.lua": b"-- BMP_IOS_OPENSSL\nssl_lib, crypto_lib = ffi.C, ffi.C\n",
                    "repo/networking/libssl.3.dylib": b"macOS dylib",
                }
            )
            for key in ("api", "mod"):
                lock["streams"]["multiplayer"][key].update(
                    sha256=hashlib.sha256(mod).hexdigest(), size=len(mod), root="repo"
                )
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
                    self.assertEqual(info["CFBundleVersion"], "1000.32.1")
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
                        self.assertEqual(info["CFBundleDisplayName"], "Balatro (PvP-L)")
                        self.assertEqual(info["CFBundleName"], "Balatro (PvP-L)")
                    self.assertIn(app + "bundled-mods/Extra/mod.lua", files)
                    if stream == "multiplayer":
                        prefix = app + "bundled-mods/MultiplayerAPI/"
                        self.assertEqual(files[prefix + "config.lua"], config)
                        hashes = json.loads(files[app + "bundled-mods.json"])
                        self.assertEqual(
                            hashes["MultiplayerAPI/config.lua"],
                            hashlib.sha256(config).hexdigest(),
                        )
                        self.assertIn(
                            b"ssl_lib, crypto_lib = ffi.C, ffi.C",
                            files[prefix + "networking/openssl_ffi.lua"],
                        )
                        self.assertNotIn(prefix + "networking/libssl.3.dylib", files)
                    else:
                        self.assertEqual(
                            files[app + "bundled-mods/" + folder + "/config.lua"],
                            b"return {}",
                        )
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
            stale = builder.archive_files(base)
            del stale[app + "builder-openssl.json"]
            with self.assertRaisesRegex(ValueError, "requires iOS OpenSSL"):
                builder.package(
                    "multiplayer",
                    lock,
                    builder.zip_bytes(stale),
                    game,
                    root / "bad.ipa",
                )
            stale[app + "builder-openssl.json"] = json.dumps(tls).encode()
            stale[app + "tls/cacert.pem"] = b"wrong bundle"
            with self.assertRaisesRegex(ValueError, "Incompatible iOS OpenSSL"):
                builder.package(
                    "multiplayer",
                    lock,
                    builder.zip_bytes(stale),
                    game,
                    root / "bad.ipa",
                )
            lock["common"] = {}
            with self.assertRaisesRegex(ValueError, "match"):
                builder.package("multiplayer", lock, base, game, root / "bad.ipa")

    def test_mod_configs_reject_wrong_paths_and_symlinks(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.object(builder, "ROOT", Path(temp)),
        ):
            configs = Path(temp) / "mod-configs/multiplayer/MultiplayerAPI"
            configs.mkdir(parents=True)
            mods = {"MultiplayerAPI/config.lua": b"original"}
            unknown = configs / "core.lua"
            unknown.write_bytes(b"code")
            with self.assertRaisesRegex(ValueError, "existing.*config.lua"):
                builder.apply_mod_configs("multiplayer", mods)
            unknown.unlink()
            (configs / "config.lua").symlink_to(Path(temp) / "outside")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                builder.apply_mod_configs("multiplayer", mods)
            self.assertEqual(mods["MultiplayerAPI/config.lua"], b"original")

    def test_changed_openssl_loader_aborts_packaging(self):
        with self.assertRaisesRegex(ValueError, "missing the iOS OpenSSL loader"):
            builder.ios_openssl.prepare_mods(
                {
                    "MultiplayerAPI/networking/openssl_ffi.lua": b"changed upstream loader"
                }
            )

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
