import hashlib
import json
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import releases


class ReleaseTests(unittest.TestCase):
    def test_legacy_can_be_published_without_other_stream_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / "versions.lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "streams": {
                            "multiplayer-legacy": {"mod": {"version": "0.5.5"}},
                        }
                    }
                )
            )
            (root / "balatro-multiplayer-legacy.ipa").write_bytes(b"legacy")
            plans = releases.prepare(
                lock, root, root / "output", "commit", streams=("multiplayer-legacy",)
            )
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0]["tag"], "multiplayer-legacy-0.5.5")
            self.assertEqual(plans[0]["asset"].name, "b-multiplayer-legacy.0.5.5.ipa")
            self.assertIn("Balatro (PvP) (Legacy)", plans[0]["notes"].read_text())

    def test_pvp_is_published_as_a_regular_release(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / "versions.lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "streams": {
                            "multiplayer": {
                                "mod": {"version": "v1.0.1"},
                                "api": {"version": "v1.0.1"},
                            },
                            "pokermon": {"mod": {"version": "3.9.1"}},
                        }
                    }
                )
            )
            for stream in ("multiplayer", "pokermon"):
                (root / ("balatro-" + stream + ".ipa")).write_bytes(b"package")
            plans = releases.prepare(lock, root, root / "output", "commit")
            self.assertIn(
                "Steam-free login for custom Community servers",
                plans[0]["notes"].read_text(),
            )
            self.assertIn("Balatro (PvP)", plans[0]["notes"].read_text())
            self.assertNotIn("experimental", plans[0]["notes"].read_text().lower())
            with (
                patch.object(releases, "release_exists", return_value=False),
                patch.object(releases.subprocess, "run") as run,
            ):
                releases.publish(
                    plans[0], "tanakrit-d/balatro-ios-mod-builder", "commit", lock
                )
                self.assertIn("--prerelease=false", run.call_args.args[0])

    def test_names_and_missing_stream_prevent_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / "versions.lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "streams": {
                            "multiplayer": {"mod": {"version": "0.5.5"}},
                            "pokermon": {"mod": {"version": "v3.9.1"}},
                        }
                    }
                )
            )
            (root / "balatro-multiplayer.ipa").write_bytes(b"multiplayer")
            with self.assertRaisesRegex(ValueError, "Missing built IPA"):
                releases.prepare(lock, root, root / "output", "commit")
            self.assertFalse((root / "output").exists())
            (root / "balatro-pokermon.ipa").write_bytes(b"pokermon")
            plans = releases.prepare(lock, root, root / "output", "commit")
            self.assertEqual(
                [p["tag"] for p in plans], ["multiplayer-0.5.5", "pokermon-3.9.1"]
            )
            self.assertEqual(
                [p["asset"].name for p in plans],
                ["b-multiplayer.0.5.5.ipa", "b-pokermon.3.9.1.ipa"],
            )

    def test_existing_release_is_verified_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            asset, lock = root / "game.ipa", root / "versions.lock.json"
            asset.write_bytes(b"package")
            lock.write_bytes(b"{}")
            plan = {
                "tag": "multiplayer-1.0.3-1000.32.1",
                "name": "package",
                "asset": asset,
                "notes": root / "notes.md",
            }
            data = {
                "draft": False,
                "assets": [
                    {
                        "name": path.name,
                        "digest": "sha256:"
                        + hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                    for path in (asset, lock)
                ],
            }
            with (
                patch.object(releases, "release_exists", return_value=True),
                patch.object(
                    releases.subprocess, "check_output", return_value=json.dumps(data)
                ),
                patch.object(releases.subprocess, "run") as run,
            ):
                releases.publish(
                    plan, "tanakrit-d/balatro-ios-mod-builder", "commit", lock
                )
                run.assert_not_called()
                asset.write_bytes(b"different package")
                with self.assertRaisesRegex(ValueError, "Immutable release"):
                    releases.publish(
                        plan, "tanakrit-d/balatro-ios-mod-builder", "commit", lock
                    )
                run.assert_not_called()

    def test_revision_is_in_release_tag_asset_and_notes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            lock = root / "versions.lock.json"
            lock.write_text(
                json.dumps(
                    {
                        "build": {"version": "1000.32.1", "revision": "32.1"},
                        "streams": {
                            "multiplayer": {
                                "mod": {"version": "1.0.3"},
                                "release_status": {"ready": True},
                            }
                        },
                    }
                )
            )
            (root / "balatro-multiplayer.ipa").write_bytes(b"package")
            plan = releases.prepare(
                lock, root, root / "output", "commit", streams=("multiplayer",)
            )[0]
            self.assertEqual(plan["tag"], "multiplayer-1.0.3-1000.32.1")
            self.assertEqual(plan["asset"].name, "b-multiplayer.1.0.3-1000.32.1.ipa")
            self.assertIn("32.1", plan["notes"].read_text())

    def test_publishing_to_any_other_repository_is_rejected(self):
        with (
            patch.object(releases, "release_exists") as lookup,
            self.assertRaisesRegex(ValueError, "restricted"),
        ):
            releases.publish(
                {"tag": "tag", "name": "name"},
                "Balatro-Multiplayer/BalatroMultiplayerPvP",
                "commit",
                Path("lock"),
            )
        lookup.assert_not_called()

    def test_only_404_means_missing_release(self):
        for code in (404, 403, 500):
            error = urllib.error.HTTPError(
                "https://api.github.com", code, "error", Message(), None
            )
            with (
                patch.dict(releases.os.environ, {"GH_TOKEN": "test-token"}),
                patch.object(releases.urllib.request, "urlopen", side_effect=error),
            ):
                if code == 404:
                    self.assertFalse(releases.release_exists("owner/repo", "tag"))
                else:
                    with self.assertRaises(urllib.error.HTTPError):
                        releases.release_exists("owner/repo", "tag")
