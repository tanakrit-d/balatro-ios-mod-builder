import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_plan
import package_version


class BuildPlanTests(unittest.TestCase):
    def setUp(self):
        self.lock = {
            "streams": {
                "multiplayer": {
                    "mod": {
                        "version": "1.0.3",
                        "repo": "tanakrit-d/BalatroMultiplayerPvP",
                        "commit": "a" * 40,
                    },
                    "api": {
                        "version": "1.0.3",
                        "repo": "tanakrit-d/BalatroMultiplayerAPI",
                        "commit": "b" * 40,
                    },
                },
                "pokermon": {"mod": {"version": "3.9.1"}},
            }
        }

    def plan(
        self,
        previous=None,
        event="schedule",
        ready=True,
        number="32",
        attempt="1",
        target="c" * 40,
    ):
        return build_plan.plan(
            self.lock,
            previous or {},
            event,
            "current",
            number,
            attempt,
            target,
            {"ready": ready},
        )

    def test_waiting_for_releases_does_not_block_pokermon(self):
        result = self.plan(ready=False)
        self.assertEqual(result["build"]["streams"], ["pokermon"])
        self.assertEqual(result["build"]["version"], "1000.32.1")

    def test_unchanged_schedule_skips_even_with_a_new_run_number(self):
        previous = self.plan()
        result = self.plan(previous, number="33")
        self.assertEqual(result["build"]["streams"], [])

    def test_source_or_builder_change_rebuilds_without_a_mod_version_bump(self):
        previous = self.plan()
        self.lock["streams"]["multiplayer"]["api"]["commit"] = "d" * 40
        self.assertEqual(
            self.plan(previous)["build"]["streams"], ["multiplayer", "pokermon"]
        )
        self.assertTrue(self.plan(previous, target="e" * 40)["build"]["streams"])

    def test_manual_rebuild_and_retry_have_distinct_release_identities(self):
        previous = self.plan()
        retry = self.plan(previous, event="workflow_dispatch", attempt="2")
        self.assertTrue(retry["build"]["streams"])
        self.assertNotEqual(
            package_version.release_version(previous, "multiplayer"),
            package_version.release_version(retry, "multiplayer"),
        )
        self.assertEqual(
            package_version.versions(retry, "multiplayer"), ("1.0.3", "1000.32.2")
        )

    def test_release_catching_up_changes_state_and_enables_pvp(self):
        waiting = self.plan(ready=False)
        self.assertIn("multiplayer", self.plan(waiting, ready=True)["build"]["streams"])

    def test_official_release_behind_mobile_does_not_run_ancestry_checks(self):
        def get(url):
            if url.endswith("/releases/latest"):
                return {"tag_name": "v1.0.1"}
            if "/commits/" in url:
                return {"sha": "e" * 40}
            self.fail("Unexpected ancestry lookup: " + url)

        with (
            patch.object(build_plan.builder, "get", side_effect=get),
            patch.object(
                build_plan.builder, "mod_manifest", return_value={"version": "1.0.1"}
            ),
        ):
            status = build_plan.release_status(self.lock)
        self.assertFalse(status["ready"])

    def test_matching_manifest_requires_both_ancestry_checks(self):
        for comparison in ("ahead", "identical", "behind", "diverged"):
            calls = []

            def get(url, calls=calls, comparison=comparison):
                calls.append(url)
                if url.endswith("/releases/latest"):
                    return {"tag_name": "v1.0.3"}
                if "/commits/" in url:
                    return {"sha": "e" * 40}
                return {"status": comparison}

            with (
                self.subTest(comparison=comparison),
                patch.object(build_plan.builder, "get", side_effect=get),
                patch.object(
                    build_plan.builder,
                    "mod_manifest",
                    return_value={"version": "1.0.3"},
                ),
            ):
                status = build_plan.release_status(self.lock)
                self.assertEqual(status["ready"], comparison in ("ahead", "identical"))
                self.assertEqual(len([url for url in calls if "/compare/" in url]), 4)

    def test_invalid_revision_is_rejected(self):
        for number in ("0", "-1", "bad"):
            with self.subTest(number=number), self.assertRaises(ValueError):
                self.plan(number=number)


if __name__ == "__main__":
    unittest.main()
