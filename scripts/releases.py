"""Publish each built stream as a separately versioned GitHub release."""

import argparse
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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


def prepare(lock_path, dist, output, target):
    lock = json.loads(lock_path.read_text())
    plans = []
    for stream in ("multiplayer", "pokermon"):
        version = lock["streams"][stream]["mod"]["version"].removeprefix("v")
        if "/" in version or "\\" in version:
            raise ValueError("Invalid release version")
        tag = stream + "-" + version
        subprocess.run(["git", "check-ref-format", "refs/tags/" + tag], check=True)
        name = "b-" + stream + "." + version
        source = dist / ("balatro-" + stream + ".ipa")
        if not source.is_file():
            raise ValueError("Missing built IPA: " + str(source))
        plans.append({"tag": tag, "name": name, "source": source})
    # Validate both streams before staging or publishing either release.
    output.mkdir(parents=True, exist_ok=True)
    for plan in plans:
        asset = output / (plan["name"] + ".ipa")
        shutil.copy2(plan["source"], asset)
        notes = output / (plan["tag"] + ".md")
        notes.write_text(
            "Unsigned iOS IPA. Requires iOS 15 or later and signing for sideloading.\n\n"
            + "Build commit: `"
            + target
            + "`. Exact dependencies are recorded in `versions.lock.json`.\n"
        )
        plan.update(asset=asset, notes=notes)
    return plans


def publish(plan, repo, target, lock):
    tag, title = plan["tag"], plan["name"]
    if release_exists(repo, tag):
        # Resolve branch names as well as commit SHAs before replacing any assets.
        sha = subprocess.check_output(
            [
                "gh",
                "api",
                "repos/" + repo + "/commits/" + urllib.parse.quote(target, safe=""),
                "--jq",
                ".sha",
            ],
            text=True,
        ).strip()
        subprocess.run(
            [
                "gh",
                "release",
                "upload",
                tag,
                str(plan["asset"]),
                str(lock),
                "--repo",
                repo,
                "--clobber",
            ],
            check=True,
        )
        # Editing a release's target does not move an existing Git tag.
        subprocess.run(
            [
                "gh",
                "api",
                "repos/" + repo + "/git/refs/tags/" + urllib.parse.quote(tag, safe=""),
                "--method",
                "PATCH",
                "--raw-field",
                "sha=" + sha,
                "--field",
                "force=true",
            ],
            check=True,
        )
        subprocess.run(
            [
                "gh",
                "release",
                "edit",
                tag,
                "--repo",
                repo,
                "--title",
                title,
                "--notes-file",
                str(plan["notes"]),
                "--draft=false",
            ],
            check=True,
        )
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
    args = parser.parse_args()
    if not args.target or (not args.dry_run and not args.repo):
        parser.error(
            "--target and --repo (or their GitHub Actions environment variables) are required"
        )
    plans = prepare(args.lock, args.dist, args.output, args.target)
    for plan in plans:
        print(plan["name"] + " → " + plan["tag"] + " → " + plan["asset"].name)
        if not args.dry_run:
            publish(plan, args.repo, args.target, args.lock)


if __name__ == "__main__":
    main()
