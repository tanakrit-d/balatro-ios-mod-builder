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
            raise ValueError(
                "Stable PvP publication requires a verified patched source release"
            )
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
                "MultiplayerAPI, Steamodded, Lovely and statically linked iOS OpenSSL. Uses verified BalatroMultiplayerMobile release assets "
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
                        + "`, upstream commit `"
                        + dependency["commit"]
                        + "`, official release `"
                        + official["tag"]
                        + "`.\n"
                    )
        plan.update(asset=asset, notes=notes)
    return plans


def release_metadata(repo, tag):
    return json.loads(
        subprocess.check_output(
            [
                "gh",
                "api",
                "repos/" + repo + "/releases/tags/" + urllib.parse.quote(tag, safe=""),
            ],
            text=True,
        )
    )


def replace_assets(plan, repo, lock, backup_root):
    """Explicit exception: back up and verify before replacing existing assets."""
    from build_plan import source_tags

    manifest = json.loads(lock.read_text())
    build = manifest.get("build", {})
    if not build.get("replace") or build.get("streams") != [plan["stream"]]:
        raise ValueError("Replacement requires a single-stream replacement build plan")
    release = release_metadata(repo, plan["tag"])
    if (
        release["draft"]
        or release["prerelease"]
        or release["id"] != build["replaces_release_id"]
    ):
        raise ValueError("Replacement release changed since planning")
    assets = {asset["name"]: asset for asset in release["assets"]}
    for path in (plan["asset"], lock):
        if path.name not in assets:
            raise ValueError("Replacement requires existing IPA and manifest assets")
    backup = backup_root / plan["tag"] / build["revision"]
    backup.mkdir(parents=True, exist_ok=False)
    (backup / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    for path in (plan["asset"], lock):
        subprocess.run(
            [
                "gh",
                "release",
                "download",
                plan["tag"],
                "--repo",
                repo,
                "--pattern",
                path.name,
                "--dir",
                str(backup),
            ],
            check=True,
        )
        raw = (backup / path.name).read_bytes()
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        if assets[path.name].get("digest") != digest:
            raise ValueError("Backup checksum mismatch: " + path.name)
    old = json.loads((backup / lock.name).read_text())
    stream = plan["stream"]
    if (
        source_tags(old["streams"][stream]) != source_tags(manifest["streams"][stream])
        or old.get("common") != manifest.get("common")
        or {k: v for k, v in old["streams"][stream].items() if k != "release_status"}
        != {
            k: v
            for k, v in manifest["streams"][stream].items()
            if k != "release_status"
        }
    ):
        raise ValueError("Replacement must preserve published dependency pins")
    old_version = old.get("build", {}).get("version", "0.0.0")
    if tuple(map(int, build["version"].split("."))) <= tuple(
        map(int, old_version.split("."))
    ):
        raise ValueError("Replacement iOS build number must increase")
    # Detect a publication racing our backup before any destructive operation.
    current = release_metadata(repo, plan["tag"])
    if current["id"] != release["id"] or current["assets"] != release["assets"]:
        raise ValueError("Release assets changed during backup")
    subprocess.run(
        [
            "gh",
            "release",
            "upload",
            plan["tag"],
            str(plan["asset"]),
            str(lock),
            "--repo",
            repo,
            "--clobber",
        ],
        check=True,
    )
    updated = release_metadata(repo, plan["tag"])
    uploaded = {asset["name"]: asset for asset in updated["assets"]}
    for path in (plan["asset"], lock):
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        if uploaded.get(path.name, {}).get("digest") != digest:
            raise ValueError("Replacement upload checksum mismatch: " + path.name)
    notes = backup / "replacement-notes.md"
    notes.write_text(
        (release.get("body") or "")
        + "\n\nIPA regenerated by builder commit `"
        + build["commit"]
        + "`, iOS build `"
        + build["version"]
        + "`.\n"
    )
    subprocess.run(
        [
            "gh",
            "release",
            "edit",
            plan["tag"],
            "--repo",
            repo,
            "--notes-file",
            str(notes),
        ],
        check=True,
    )
    print("Replaced and verified assets; backup: " + str(backup))


def publish(
    plan,
    repo,
    target,
    lock,
    replace_existing=False,
    backup_root=ROOT / ".build/release-backups",
):
    tag, title = plan["tag"], plan["name"]
    if repo != "tanakrit-d/balatro-ios-mod-builder":
        raise ValueError("Publishing is restricted to the tanakrit-d builder fork")
    if replace_existing:
        if not release_exists(repo, tag):
            raise ValueError("Cannot replace a release that does not exist")
        replace_assets(plan, repo, lock, backup_root)
        return
    if json.loads(lock.read_text()).get("build", {}).get("replace"):
        raise ValueError("Replacement plan requires --replace-existing")
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
                    "Immutable release already exists with different or incomplete assets; inspect it before using the explicit replacement workflow: "
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
        "--replace-existing",
        action="store_true",
        help="Back up and replace a single explicitly planned release",
    )
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
            publish(plan, args.repo, args.target, args.lock, args.replace_existing)


if __name__ == "__main__":
    main()
