"""Gate stable PvP builds on official releases and assign mobile build revisions."""

import argparse
import copy
import json
import os
import re
from pathlib import Path
from urllib.parse import quote

import builder

# Preserve the already-published 1.0.3 baseline without resetting fork history.
MOBILE_BASELINES = {
    "api": (
        "BalatroMultiplayerAPI",
        "MultiplayerAPI.json",
        "c514424cd450cfbb9c165d2b2c6e16e6d2bc8f7c",
    ),
    "mod": (
        "BalatroMultiplayerPvP",
        "MultiplayerPvP.json",
        "44fb52f545fb25399ee8d12d3154edb99d91eb68",
    ),
}


def release_status(lock):
    checks = {}
    for key, (name, filename, baseline) in MOBILE_BASELINES.items():
        upstream = "Balatro-Multiplayer/" + name
        mobile = lock["streams"]["multiplayer"][key]
        release = builder.get(builder.API + upstream + "/releases/latest")
        if release.get("draft") or release.get("prerelease"):
            raise ValueError("Expected a published stable upstream release")
        tag = release["tag_name"]
        sha = builder.get(builder.API + upstream + "/commits/" + quote(tag, safe=""))[
            "sha"
        ]
        manifest = builder.mod_manifest(upstream, sha, filename)
        version = manifest["version"].removeprefix("v")
        ready = version == mobile["version"].removeprefix("v")
        if ready:
            # The official release must include our existing source baseline,
            # and its commit must already have been merged into mobile.
            for repo, base, head in (
                (upstream, baseline, sha),
                (mobile["repo"], sha, mobile["commit"]),
            ):
                comparison = builder.get(
                    builder.API + repo + "/compare/" + base + "..." + head
                )
                ready = ready and comparison["status"] in ("ahead", "identical")
        checks[key] = {
            "repo": upstream,
            "tag": tag,
            "commit": sha,
            "version": version,
            "ready": ready,
        }
    return {
        "ready": all(item["ready"] for item in checks.values()),
        "dependencies": checks,
    }


def inputs(lock):
    result = copy.deepcopy(lock)
    result.pop("build", None)
    return result


def plan(lock, previous, event, requested, number, attempt, target, status):
    if not re.fullmatch(r"[1-9]\d*", str(number)) or not re.fullmatch(
        r"[1-9]\d*", str(attempt)
    ):
        raise ValueError("Build number and attempt must be positive integers")
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError("An exact builder commit is required")
    result = inputs(lock)
    result["builder_commit"] = target
    result["streams"]["multiplayer"]["release_status"] = status
    selected = (
        ["multiplayer-legacy"]
        if requested == "multiplayer-legacy"
        else ["multiplayer", "pokermon"]
    )
    if not status["ready"]:
        selected = [stream for stream in selected if stream != "multiplayer"]
    if event == "schedule" and inputs(previous) == result:
        selected = []
    result["build"] = {
        "revision": f"{number}.{attempt}",
        "version": f"1000.{number}.{attempt}",
        "commit": target,
        "streams": selected,
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock", type=Path, default=builder.ROOT / "versions.lock.json"
    )
    parser.add_argument(
        "--previous", type=Path, default=builder.ROOT / ".build/last-success.json"
    )
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text())
    status = release_status(lock)
    result = plan(
        lock,
        json.loads(args.previous.read_text()) if args.previous.exists() else {},
        os.environ["GITHUB_EVENT_NAME"],
        os.getenv("BUILD_STREAM", "current"),
        os.environ["GITHUB_RUN_NUMBER"],
        os.environ["GITHUB_RUN_ATTEMPT"],
        os.environ["GITHUB_SHA"],
        status,
    )
    args.lock.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("build=" + str(bool(result["build"]["streams"])).lower() + "\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write("Mobile build: `" + result["build"]["version"] + "`\n\n")
        if not status["ready"]:
            summary.write(
                "PvP publication is waiting for official release tags to include the existing mobile baseline and be merged into mobile. Existing releases are unchanged.\n\n"
            )
        summary.write(
            "Selected streams: " + ", ".join(result["build"]["streams"]) + "\n"
        )


if __name__ == "__main__":
    main()
