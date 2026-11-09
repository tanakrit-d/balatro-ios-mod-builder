"""Verify patched PvP source releases and assign mobile build revisions."""

import argparse
import copy
import json
import os
import re
from pathlib import Path

import builder
import mobile_release


def release_status(lock):
    return mobile_release.verify(
        lock["streams"]["multiplayer"], builder.get, builder.download
    )


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
                "PvP publication requires a verified patched source release.\n\n"
            )
        summary.write(
            "Selected streams: " + ", ".join(result["build"]["streams"]) + "\n"
        )


if __name__ == "__main__":
    main()
