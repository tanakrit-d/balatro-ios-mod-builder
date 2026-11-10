import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import releases


class ReplacementTests(unittest.TestCase):
    def fixture(self, root):
        old = {
            "common": {"runtime": {"commit": "a" * 40}},
            "streams": {"pokermon": {"mod": {"version": "3.9.1"}}},
            "build": {"version": "1000.41.1"},
        }
        new = copy.deepcopy(old)
        new["build"] = {
            "replace": True,
            "streams": ["pokermon"],
            "version": "1000.42.1",
            "revision": "42.1",
            "commit": "c" * 40,
            "replaces_release_id": 1,
        }
        lock = root / "versions.lock.json"
        lock.write_text(json.dumps(new))
        ipa = root / "b-pokermon.3.9.1-1000.41.1.ipa"
        ipa.write_bytes(b"new ipa")
        old_files = {lock.name: json.dumps(old).encode(), ipa.name: b"old ipa"}

        def metadata(files):
            return {
                "id": 1,
                "draft": False,
                "prerelease": False,
                "body": "Original notes",
                "assets": [
                    {
                        "name": name,
                        "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                    }
                    for name, raw in files.items()
                ],
            }

        original = metadata(old_files)
        updated = metadata({lock.name: lock.read_bytes(), ipa.name: ipa.read_bytes()})
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            if args[1:3] == ["release", "download"]:
                name = args[args.index("--pattern") + 1]
                directory = Path(args[args.index("--dir") + 1])
                (directory / name).write_bytes(old_files[name])
            if "--clobber" in args:
                backup = root / "backups/tag/42.1"
                self.assertEqual((backup / ipa.name).read_bytes(), b"old ipa")
                self.assertTrue((backup / "release.json").is_file())

        plan = {"tag": "tag", "name": "package", "asset": ipa, "stream": "pokermon"}
        return plan, lock, original, updated, run, calls

    def test_explicit_replacement_backs_up_verifies_and_keeps_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, lock, old, new, run, calls = self.fixture(root)
            with (
                patch.object(releases, "release_exists", return_value=True),
                patch.object(releases, "release_metadata", side_effect=[old, old, new]),
                patch.object(releases.subprocess, "run", side_effect=run),
            ):
                releases.publish(
                    plan,
                    "tanakrit-d/balatro-ios-mod-builder",
                    "c" * 40,
                    lock,
                    True,
                    root / "backups",
                )
            self.assertEqual(sum("--clobber" in c for c in calls), 1)
            self.assertFalse(any("create" in c or "delete" in c for c in calls))
            self.assertIn(
                "Original notes",
                (root / "backups/tag/42.1/replacement-notes.md").read_text(),
            )

    def test_backup_or_dependency_mismatch_never_uploads(self):
        for corruption in ("digest", "pins", "release_id", "build_number"):
            with (
                self.subTest(corruption=corruption),
                tempfile.TemporaryDirectory() as tmp,
            ):
                root = Path(tmp)
                plan, lock, old, _new, run, calls = self.fixture(root)
                manifest = json.loads(lock.read_text())
                if corruption == "digest":
                    old["assets"][0]["digest"] = "sha256:wrong"
                elif corruption == "pins":
                    manifest["common"]["runtime"]["commit"] = "b" * 40
                elif corruption == "release_id":
                    old["id"] = 2
                else:
                    manifest["build"]["version"] = "1000.40.1"
                lock.write_text(json.dumps(manifest))
                with (
                    patch.object(releases, "release_metadata", return_value=old),
                    patch.object(releases.subprocess, "run", side_effect=run),
                    self.assertRaises(ValueError),
                ):
                    releases.replace_assets(plan, "repo", lock, root / "backups")
                self.assertFalse(any("--clobber" in c for c in calls))

    def test_remote_race_or_upload_failure_keeps_backup(self):
        for failure in ("race", "upload"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                plan, lock, old, _new, run, calls = self.fixture(root)
                raced = copy.deepcopy(old)
                raced["assets"][0]["digest"] = "sha256:changed"

                def failing_run(args, runner=run, **kwargs):
                    runner(args, **kwargs)
                    if "--clobber" in args:
                        raise RuntimeError("upload interrupted")

                with (
                    patch.object(
                        releases,
                        "release_metadata",
                        side_effect=[old, raced if failure == "race" else old],
                    ),
                    patch.object(releases.subprocess, "run", side_effect=failing_run),
                    self.assertRaises((ValueError, RuntimeError)),
                ):
                    releases.replace_assets(plan, "repo", lock, root / "backups")
                self.assertTrue((root / "backups/tag/42.1/release.json").is_file())
                self.assertFalse(any("edit" in c for c in calls))
                if failure == "race":
                    self.assertFalse(any("--clobber" in c for c in calls))

    def test_replacement_requires_both_plan_and_cli_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, lock, _old, _new, _run, _calls = self.fixture(root)
            with self.assertRaisesRegex(ValueError, "--replace-existing"):
                releases.publish(
                    plan, "tanakrit-d/balatro-ios-mod-builder", "commit", lock
                )
            manifest = json.loads(lock.read_text())
            manifest["build"]["replace"] = False
            lock.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "single-stream"):
                releases.replace_assets(plan, "repo", lock, root / "backups")

    def test_upload_digest_mismatch_is_reported_with_backup_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan, lock, old, _new, run, calls = self.fixture(root)
            with (
                patch.object(releases, "release_metadata", return_value=old),
                patch.object(releases.subprocess, "run", side_effect=run),
                self.assertRaisesRegex(ValueError, "upload checksum"),
            ):
                releases.replace_assets(plan, "repo", lock, root / "backups")
            self.assertTrue((root / "backups/tag/42.1/release.json").is_file())
            self.assertFalse(any("edit" in c for c in calls))


if __name__ == "__main__":
    unittest.main()
