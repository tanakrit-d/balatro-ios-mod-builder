"""Build new source release tags, or explicitly replace one published package."""

import argparse
import copy
import json
import os
import re
from pathlib import Path

import builder
import mobile_release

REPO = "tanakrit-d/balatro-ios-mod-builder"


def release_status(lock):
    return mobile_release.verify(
        lock["streams"]["multiplayer"], builder.get, builder.download
    )


def source_tags(stream):
    """Only release identities trigger builds; hashes remain provenance."""
    if "source_release" in stream:
        source = stream["source_release"]
        return (source["repo"], source["tag"])
    return tuple(
        (key, stream[key].get("repo"), stream[key].get("tag", stream[key]["version"]))
        for key in ("mod", "api")
        if key in stream
    )


def published_state(get=builder.get, download=builder.download):
    """Read durable per-stream publication state, including pre-policy releases."""
    found = {}
    page = 1
    while len(found) < len(builder.STREAMS):
        releases = get(f"{builder.API}{REPO}/releases?per_page=100&page={page}")
        if not releases:
            break
        for release in releases:
            if release["draft"] or release["prerelease"]:
                continue
            for stream in sorted(builder.STREAMS, key=len, reverse=True):
                prefix = stream + "-"
                if not release["tag_name"].startswith(prefix):
                    continue
                if stream in found:
                    break
                version = release["tag_name"][len(prefix) :]
                assets = {asset["name"]: asset for asset in release["assets"]}
                expected = "b-" + stream + "." + version + ".ipa"
                if expected not in assets or "versions.lock.json" not in assets:
                    raise ValueError(
                        "Incomplete published release: " + release["tag_name"]
                    )
                lock = json.loads(
                    download(assets["versions.lock.json"]["browser_download_url"])
                )
                if stream not in lock["streams"]:
                    raise ValueError("Published manifest is missing stream: " + stream)
                found[stream] = {
                    "lock": lock,
                    "release_version": version,
                    "id": release["id"],
                }
                break
        page += 1
    return found


def plan(
    lock, previous, event, requested, number, attempt, target, status, replace=False
):
    if not re.fullmatch(r"[1-9]\d*", str(number)) or not re.fullmatch(
        r"[1-9]\d*", str(attempt)
    ):
        raise ValueError("Build number and attempt must be positive integers")
    if not re.fullmatch(r"[0-9a-f]{40}", target):
        raise ValueError("An exact builder commit is required")
    if requested not in ("current", *builder.STREAMS):
        raise ValueError("Unknown stream")
    if replace and (event != "workflow_dispatch" or requested == "current"):
        raise ValueError("Replacement requires a manual run selecting one stream")
    selected = ["multiplayer", "pokermon"] if requested == "current" else [requested]
    result = copy.deepcopy(lock)
    release_versions = {}
    if replace:
        if requested not in previous:
            raise ValueError("No existing release to replace: " + requested)
        result = copy.deepcopy(previous[requested]["lock"])
        release_versions[requested] = previous[requested]["release_version"]
    else:
        selected = [
            stream
            for stream in selected
            if stream not in previous
            or source_tags(result["streams"][stream])
            != source_tags(previous[stream]["lock"]["streams"][stream])
        ]
        for stream in selected:
            dependency = result["streams"][stream]
            # Keep existing AltStore-compatible package names. Run numbers identify
            # packages; they never decide whether a new release is needed.
            release_versions[stream] = (
                dependency["mod"]["version"].removeprefix("v")
                + f"-1000.{number}.{attempt}"
            )
    if event not in ("schedule", "workflow_dispatch"):
        selected = []
    if not status["ready"]:
        selected = [stream for stream in selected if stream != "multiplayer"]
    if "multiplayer" in result["streams"]:
        result["streams"]["multiplayer"]["release_status"] = status
    version = f"1000.{number}.{attempt}"
    if replace:
        old = previous[requested]["lock"].get("build", {}).get("version", "0.0.0")
        if tuple(map(int, version.split("."))) <= tuple(map(int, old.split("."))):
            raise ValueError("Replacement iOS build number must increase")
    result["builder_commit"] = target
    result["build"] = {
        "revision": f"{number}.{attempt}",
        "version": version,
        "commit": target,
        "streams": selected,
        "release_versions": release_versions,
        "replace": replace,
    }
    if replace:
        result["build"]["replaces_release_id"] = previous[requested]["id"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock", type=Path, default=builder.ROOT / "versions.lock.json"
    )
    args = parser.parse_args()
    previous = published_state()
    requested = os.getenv("BUILD_STREAM", "current")
    replace = os.getenv("REPLACE_IPA", "false") == "true"
    if replace:
        if requested == "current" or requested not in previous:
            raise ValueError("Replacement requires one existing stream")
        lock = previous[requested]["lock"]
    else:
        lock = builder.resolve()
    status = (
        release_status(lock)
        if requested in ("current", "multiplayer")
        else {"ready": True}
    )
    result = plan(
        lock,
        previous,
        os.environ["GITHUB_EVENT_NAME"],
        requested,
        os.environ["GITHUB_RUN_NUMBER"],
        os.environ["GITHUB_RUN_ATTEMPT"],
        os.environ["GITHUB_SHA"],
        status,
        replace,
    )
    args.lock.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    with open(os.environ["GITHUB_OUTPUT"], "a") as output:
        output.write("build=" + str(bool(result["build"]["streams"])).lower() + "\n")
    with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as summary:
        summary.write(
            "Selected streams: " + ", ".join(result["build"]["streams"]) + "\n\n"
        )
        summary.write("Replace existing assets: " + str(replace) + "\n")


if __name__ == "__main__":
    main()
