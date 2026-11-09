"""Consume published, checksummed BalatroMultiplayerMobile source releases."""

import hashlib
import json
import re
from urllib.parse import quote

REPO = "tanakrit-d/BalatroMultiplayerMobile"
API = "https://api.github.com/repos/" + REPO
PROJECTS = {"api": ("api", "MultiplayerAPI"), "pvp": ("mod", "MultiplayerPvP")}


def checksum(data, expected):
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Missing mobile release SHA-256")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Mobile release checksum mismatch")


def metadata(get, download, tag=None):
    endpoint = "tags/" + quote(tag, safe="") if tag else "latest"
    release = get(API + "/releases/" + endpoint)
    if release.get("draft") or release.get("prerelease"):
        raise ValueError("Expected a published stable mobile release")
    tag = release["tag_name"]
    assets = {a["name"]: a for a in release["assets"]}
    if len(assets) != len(release["assets"]):
        raise ValueError("Duplicate mobile release assets")
    base = f"https://github.com/{REPO}/releases/download/{quote(tag, safe='')}/"
    asset = assets["release-manifest.json"]
    if asset["browser_download_url"] != base + "release-manifest.json":
        raise ValueError("Unexpected mobile manifest URL")
    raw = download(asset["browser_download_url"])
    checksum(raw, asset.get("digest", "").removeprefix("sha256:"))
    manifest = json.loads(raw)
    if (
        manifest.get("schema") != 1
        or manifest.get("repository") != REPO
        or manifest.get("tag") != tag
    ):
        raise ValueError("Invalid mobile release manifest")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["patch_repository_commit"]):
        raise ValueError("Missing patch repository commit")
    if type(manifest["mobile_revision"]) is not int or manifest["mobile_revision"] < 1:
        raise ValueError("Invalid mobile revision")
    if set(manifest["projects"]) != set(PROJECTS):
        raise ValueError("Mobile release must contain API and PvP")
    stream = {
        "source_release": {
            "repo": REPO,
            "tag": tag,
            "id": release["id"],
            "commit": manifest["patch_repository_commit"],
            "mobile_revision": manifest["mobile_revision"],
            "manifest_url": asset["browser_download_url"],
            "manifest_sha256": hashlib.sha256(raw).hexdigest(),
        }
    }
    for key, (dependency, root) in PROJECTS.items():
        project = manifest["projects"][key]
        version = project["version"]
        if (
            not re.fullmatch(r"\d+\.\d+\.\d+", version)
            or project["tag"].removeprefix("v") != version
            or not re.fullmatch(r"[0-9a-f]{40}", project["commit"])
            or project["repository"] != "Balatro-Multiplayer/Balatro" + root
            or project["root"] != root
        ):
            raise ValueError("Invalid upstream identity in mobile release")
        name = project["asset"]
        if not re.fullmatch(re.escape(root) + r"-[A-Za-z0-9.+-]+\.zip", name):
            raise ValueError("Invalid mobile asset name")
        asset = assets[name]
        if (
            project["download_url"] != base + name
            or asset["browser_download_url"] != base + name
        ):
            raise ValueError("Unexpected mobile asset URL")
        if asset.get("digest") != "sha256:" + project["sha256"]:
            raise ValueError("Mobile asset digest differs from release manifest")
        stream[dependency] = {
            "repo": project["repository"],
            "tag": project["tag"],
            "commit": project["commit"],
            "version": version,
            "url": base + name,
            "sha256": project["sha256"],
            "size": project["size"],
            "root": root,
        }
    return stream


def files(dependency, download, archive_files):
    raw = download(dependency["url"])
    checksum(raw, dependency.get("sha256"))
    if len(raw) != dependency["size"]:
        raise ValueError("Mobile asset size mismatch")
    contents = archive_files(raw)
    prefix = dependency["root"] + "/"
    if not contents or any(not name.startswith(prefix) for name in contents):
        raise ValueError("Unexpected mobile archive root")
    return {name.removeprefix(prefix): data for name, data in contents.items()}


def resolve(get, download, archive_files):
    stream = metadata(get, download)
    manifests = {}
    for key, (dependency, root) in PROJECTS.items():
        contents = files(stream[dependency], download, archive_files)
        mod = json.loads(contents[root + ".json"])
        if mod.get("version") != stream[dependency]["version"]:
            raise ValueError("Mod version differs from mobile release")
        requirements = mod.get("dependencies")
        if not isinstance(requirements, list) or not all(
            isinstance(r, str) for r in requirements
        ):
            raise ValueError("Invalid mobile mod dependencies")
        provenance = json.loads(contents["mobile-build-manifest.json"])
        if (
            provenance["patch_repository_commit"] != stream["source_release"]["commit"]
            or provenance["patch_repository_dirty"]
        ):
            raise ValueError("Mobile source provenance differs from release")
        if provenance["sources"][key]["commit"] != stream[dependency]["commit"]:
            raise ValueError("Mobile upstream provenance differs from release")
        manifests[root] = mod
    requirements = [
        r
        for r in manifests["MultiplayerPvP"]["dependencies"]
        if r.startswith("MultiplayerAPI")
    ]
    if len(requirements) != 1:
        raise ValueError("PvP must declare one API minimum")
    match = re.fullmatch(r"MultiplayerAPI \(>=(\d+\.\d+\.\d+)\)", requirements[0])
    if not match or tuple(map(int, stream["api"]["version"].split("."))) < tuple(
        map(int, match[1].split("."))
    ):
        raise ValueError("Incompatible API/PvP release pair")
    return stream, manifests


def verify(stream, get, download):
    pinned = metadata(get, download, stream["source_release"]["tag"])
    if any(stream.get(key) != value for key, value in pinned.items()):
        raise ValueError("Pinned mobile release changed; resolve a new lock")
    return {
        "ready": True,
        "dependencies": {
            key: {
                **{
                    field: stream[key][field]
                    for field in ("repo", "tag", "commit", "version")
                },
                "ready": True,
            }
            for key in ("api", "mod")
        },
    }
