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

    def test_create_and_existing_release_update(self):
        plan = {
            "tag": "multiplayer-0.5.5",
            "name": "b-multiplayer.0.5.5",
            "asset": Path("game.ipa"),
            "notes": Path("notes.md"),
        }
        for existing in (False, True):
            with (
                self.subTest(existing=existing),
                patch.object(releases, "release_exists", return_value=existing),
                patch.object(
                    releases.subprocess,
                    "check_output",
                    return_value="resolved-build-sha\n",
                ) as resolve,
                patch.object(releases.subprocess, "run") as run,
            ):
                releases.publish(
                    plan, "owner/repo", "exact-build-commit", Path("versions.lock.json")
                )
                commands = [call.args[0] for call in run.call_args_list]
                if existing:
                    self.assertEqual(
                        [c[:3] for c in commands],
                        [
                            ["gh", "release", "upload"],
                            [
                                "gh",
                                "api",
                                "repos/owner/repo/git/refs/tags/multiplayer-0.5.5",
                            ],
                            ["gh", "release", "edit"],
                        ],
                    )
                    self.assertIn("--clobber", commands[0])
                    self.assertIn("sha=resolved-build-sha", commands[1])
                    self.assertIn("force=true", commands[1])
                    resolve.assert_called_once_with(
                        [
                            "gh",
                            "api",
                            "repos/owner/repo/commits/exact-build-commit",
                            "--jq",
                            ".sha",
                        ],
                        text=True,
                    )
                else:
                    resolve.assert_not_called()
                    self.assertEqual(commands[0][:3], ["gh", "release", "create"])
                    self.assertIn("exact-build-commit", commands[0])

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

    def test_invalid_target_does_not_replace_release_assets(self):
        plan = {
            "tag": "multiplayer-0.5.5",
            "name": "b-multiplayer.0.5.5",
            "asset": Path("game.ipa"),
            "notes": Path("notes.md"),
        }
        with (
            patch.object(releases, "release_exists", return_value=True),
            patch.object(
                releases.subprocess,
                "check_output",
                side_effect=releases.subprocess.CalledProcessError(1, "gh"),
            ),
            patch.object(releases.subprocess, "run") as run,
            self.assertRaises(releases.subprocess.CalledProcessError),
        ):
            releases.publish(
                plan, "owner/repo", "missing-commit", Path("versions.lock.json")
            )
        run.assert_not_called()
