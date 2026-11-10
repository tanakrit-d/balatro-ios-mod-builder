import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_plan
import package_version


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.lock = {
            "common": {"runtime": {"commit": "a" * 40}},
            "streams": {
                "multiplayer": {
                    "source_release": {"repo": "owner/mobile", "tag": "v1.0.5"},
                    "mod": {"version": "1.0.5", "commit": "a" * 40},
                    "api": {"version": "1.0.5", "commit": "b" * 40},
                },
                "pokermon": {"mod": {"version": "3.9.1"}},
                "multiplayer-legacy": {"mod": {"version": "0.5.5"}},
            },
        }
        self.previous = {
            stream: {
                "lock": copy.deepcopy(self.lock),
                "release_version": data["mod"]["version"] + "-1000.41.1",
                "id": i + 1,
            }
            for i, (stream, data) in enumerate(self.lock["streams"].items())
        }

    def plan(
        self,
        previous=None,
        event="schedule",
        ready=True,
        requested="current",
        replace=False,
        number="42",
        attempt="1",
        target="c" * 40,
    ):
        return build_plan.plan(
            self.lock,
            self.previous if previous is None else previous,
            event,
            requested,
            number,
            attempt,
            target,
            {"ready": ready},
            replace,
        )

    def test_initial_build_uses_source_tag_names_and_separate_ios_build(self):
        result = self.plan(previous={})
        self.assertEqual(result["build"]["streams"], ["multiplayer", "pokermon"])
        self.assertEqual(
            package_version.release_version(result, "multiplayer"), "1.0.5-1000.42.1"
        )
        self.assertEqual(
            package_version.versions(result, "multiplayer"), ("1.0.5", "1000.42.1")
        )

    def test_commits_runtime_changes_and_manual_runs_do_not_create_releases(self):
        self.lock["streams"]["multiplayer"]["api"]["commit"] = "d" * 40
        self.lock["common"]["runtime"]["commit"] = "e" * 40
        for event in ("schedule", "workflow_dispatch", "push"):
            self.assertEqual(self.plan(event=event)["build"]["streams"], [])

    def test_only_changed_stream_builds(self):
        self.lock["streams"]["pokermon"]["mod"]["version"] = "3.9.2"
        result = self.plan()
        self.assertEqual(result["build"]["streams"], ["pokermon"])
        self.assertEqual(
            package_version.release_version(result, "pokermon"), "3.9.2-1000.42.1"
        )

    def test_new_mobile_source_tag_builds_pvp_even_with_same_mod_version(self):
        self.lock["streams"]["multiplayer"]["source_release"]["tag"] = "v1.0.5-mobile.2"
        result = self.plan()
        self.assertEqual(result["build"]["streams"], ["multiplayer"])
        self.assertEqual(
            package_version.release_version(result, "multiplayer"), "1.0.5-1000.42.1"
        )

    def test_push_never_builds_even_new_tags(self):
        self.assertEqual(self.plan(previous={}, event="push")["build"]["streams"], [])

    def test_waiting_pvp_does_not_block_pokermon(self):
        self.assertEqual(
            self.plan(previous={}, ready=False)["build"]["streams"], ["pokermon"]
        )

    def test_manual_without_replacement_skips_legacy(self):
        self.assertEqual(
            self.plan(event="workflow_dispatch", requested="multiplayer-legacy")[
                "build"
            ]["streams"],
            [],
        )

    def test_replacement_keeps_exact_pins_and_existing_release_name(self):
        self.lock["common"]["runtime"]["commit"] = "f" * 40
        result = self.plan(
            event="workflow_dispatch", requested="multiplayer-legacy", replace=True
        )
        self.assertEqual(result["common"]["runtime"]["commit"], "a" * 40)
        self.assertEqual(result["build"]["streams"], ["multiplayer-legacy"])
        self.assertEqual(
            package_version.release_version(result, "multiplayer-legacy"),
            "0.5.5-1000.41.1",
        )
        self.assertEqual(result["build"]["version"], "1000.42.1")
        self.assertEqual(result["build"]["replaces_release_id"], 3)

    def test_replacement_requires_explicit_single_stream_and_existing_release(self):
        for kw in (
            {"requested": "current", "event": "workflow_dispatch"},
            {"requested": "pokermon", "event": "schedule"},
            {"requested": "pokermon", "event": "workflow_dispatch", "previous": {}},
        ):
            with self.subTest(kw=kw), self.assertRaises(ValueError):
                self.plan(replace=True, **kw)

    def test_replacement_cannot_lower_build_number(self):
        self.previous["pokermon"]["lock"]["build"] = {"version": "1000.44.1"}
        with self.assertRaisesRegex(ValueError, "increase"):
            self.plan(event="workflow_dispatch", requested="pokermon", replace=True)

    def test_published_state_is_paginated_and_stream_specific(self):
        def release(stream, version, number):
            return {
                "tag_name": stream + "-" + version,
                "id": number,
                "draft": False,
                "prerelease": False,
                "assets": [
                    {"name": "b-" + stream + "." + version + ".ipa"},
                    {"name": "versions.lock.json", "browser_download_url": "manifest"},
                ],
            }

        get = Mock(
            side_effect=[
                [release("multiplayer-legacy", "0.5.5", 1)],
                [
                    release("multiplayer", "1.0.5-1000.41.1", 2),
                    release("pokermon", "3.9.1", 3),
                ],
            ]
        )
        result = build_plan.published_state(
            get, lambda _: json.dumps(self.lock).encode()
        )
        self.assertEqual(result["multiplayer"]["release_version"], "1.0.5-1000.41.1")
        self.assertEqual(result["multiplayer-legacy"]["id"], 1)
        self.assertEqual(get.call_count, 2)

    def test_incomplete_release_fails_closed(self):
        get = Mock(
            return_value=[
                {
                    "tag_name": "pokermon-3.9.1",
                    "id": 1,
                    "draft": False,
                    "prerelease": False,
                    "assets": [],
                }
            ]
        )
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            build_plan.published_state(get, Mock())

    def test_release_gate_verifies_pinned_mobile_source(self):
        with patch.object(
            build_plan.mobile_release, "verify", return_value={"ready": True}
        ) as verify:
            self.assertTrue(build_plan.release_status(self.lock)["ready"])
            verify.assert_called_once_with(
                self.lock["streams"]["multiplayer"],
                build_plan.builder.get,
                build_plan.builder.download,
            )

    def test_invalid_revision_is_rejected(self):
        with self.assertRaises(ValueError):
            self.plan(number="0")


if __name__ == "__main__":
    unittest.main()
