"""Publish each built stream as a separately versioned GitHub release."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import NotRequired, TypedDict

from package_version import release_version

ROOT = Path(__file__).resolve().parents[1]


class ReleasePlan(TypedDict):
    tag: str
    name: str
    source: Path
    stream: str
    asset: NotRequired[Path]
    notes: NotRequired[Path]


def release_exists(repo, tag):
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise ValueError("GH_TOKEN is required to publish releases")
    url = (
        "https://api.github.com/repos/"
        + repo
        + "/releases/tags/"
        + urllib.parse.quote(tag, safe="")
    )
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "User-Agent": "balatro-ios-mod-builder",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60):
            return True
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise


def prepare(lock_path, dist, output, target, streams=("multiplayer", "pokermon")):
    lock = json.loads(lock_path.read_text())
    plans: list[ReleasePlan] = []
    for stream in streams:
        if (
            stream == "multiplayer"
            and "build" in lock
            and not lock["streams"][stream]
            .get("release_status", {})
            .get("ready", False)
        ):
            raise ValueError("Stable PvP publication is waiting for official releases")
        version = release_version(lock, stream)
        if "/" in version or "\\" in version:
            raise ValueError("Invalid release version")
        tag = stream + "-" + version
        subprocess.run(["git", "check-ref-format", "refs/tags/" + tag], check=True)
        name = "b-" + stream + "." + version
        source = dist / ("balatro-" + stream + ".ipa")
        if not source.is_file():
            raise ValueError("Missing built IPA: " + str(source))
        plans.append(
            {
                "tag": tag,
                "name": name,
                "source": source,
                "stream": stream,
            }
        )
    # Validate every selected stream before staging or publishing any release.
    output.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        asset = output / (plan["name"] + ".ipa")
        shutil.copy2(plan["source"], asset)
        notes = output / (plan["tag"] + ".md")
        notes.write_text(
            "Build commit: `"
            + target
            + "`. Exact dependencies are recorded in `versions.lock.json`.\n"
            + (
                "\nMobile package revision: `"
                + lock["build"]["revision"]
                + "`. iOS build: `"
                + lock["build"]["version"]
                + "`.\n"
                if "build" in lock
                else ""
            )
            + (
                "\nBalatro (PvP) (Legacy). Multiplayer 0.5.5 with its pinned Steamodded dependency "
                "and dedicated Legacy icon. Retains the original bundle identifier "
                "for existing installs. This stream does not track new mod releases.\n"
                if plan["stream"] == "multiplayer-legacy"
                else ""
            )
            + (
                "\nBalatro (PvP). Includes MultiplayerPvP, "
                "MultiplayerAPI, Steamodded, Lovely and statically linked iOS OpenSSL. Uses the forks’ mobile branches "
                "with Steam-free login for custom Community servers; configure "
                "mod-configs/multiplayer/MultiplayerAPI/config.lua before building "
                "to bundle your server defaults.\n"
                if plan["stream"] == "multiplayer"
                else ""
            )
        )
        if plan["stream"] == "multiplayer" and "dependencies" in lock["streams"][
            "multiplayer"
        ].get("release_status", {}):
            dependencies = lock["streams"]["multiplayer"]
            with notes.open("a") as notes_file:
                for key in ("api", "mod"):
                    dependency = dependencies[key]
                    official = dependencies["release_status"]["dependencies"][key]
                    notes_file.write(
                        "\n"
                        + dependency["repo"]
                        + ": mod `"
                        + dependency["version"]
                        + "`, mobile commit `"
                        + dependency["commit"]
                        + "`, official release `"
                        + official["tag"]
                        + "`.\n"
                    )
        plan.update(asset=asset, notes=notes)
    return plans


def publish(plan, repo, target, lock):
    tag, title = plan["tag"], plan["name"]
    if repo != "tanakrit-d/balatro-ios-mod-builder":
        raise ValueError("Publishing is restricted to the tanakrit-d builder fork")
    if release_exists(repo, tag):
        # A retry may reuse an identical complete publication, but never edit it.
        release = json.loads(
            subprocess.check_output(
                [
                    "gh",
                    "api",
                    "repos/"
                    + repo
                    + "/releases/tags/"
                    + urllib.parse.quote(tag, safe=""),
                ],
                text=True,
            )
        )
        assets = {asset["name"]: asset for asset in release["assets"]}
        for path in (plan["asset"], lock):
            digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
            if release["draft"] or assets.get(path.name, {}).get("digest") != digest:
                raise ValueError(
                    "Immutable release already exists with different or incomplete assets; start a new workflow run: "
                    + tag
                )
        print("Verified existing immutable release: " + tag)
    else:
        subprocess.run(
            [
                "gh",
                "release",
                "create",
                tag,
                str(plan["asset"]),
                str(lock),
                "--repo",
                repo,
                "--target",
                target,
                "--title",
                title,
                "--notes-file",
                str(plan["notes"]),
                "--latest=false",
                "--prerelease=false",
            ],
            check=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=ROOT / "versions.lock.json")
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / ".build/release-assets")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--target", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--stream",
        action="append",
        choices=("multiplayer", "multiplayer-legacy", "pokermon"),
        help="Publish only selected streams; legacy is excluded by default",
    )
    args = parser.parse_args()
    if not args.target or (not args.dry_run and not args.repo):
        parser.error(
            "--target and --repo (or their GitHub Actions environment variables) are required"
        )
    plans = prepare(
        args.lock,
        args.dist,
        args.output,
        args.target,
        streams=args.stream or ("multiplayer", "pokermon"),
    )
    for plan in plans:
        print(plan["name"] + " → " + plan["tag"] + " → " + plan["asset"].name)
        if not args.dry_run:
            publish(plan, args.repo, args.target, args.lock)


if __name__ == "__main__":
    main()
