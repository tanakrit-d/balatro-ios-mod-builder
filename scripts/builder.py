"""Resolve upstream versions and package two isolated iOS mod streams."""

import argparse
import hashlib
import io
import json
import os
import plistlib
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/"


def download(url):
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Downloads require HTTPS")
    headers = {"User-Agent": "balatro-ios-mod-builder"}
    # Never send GitHub credentials to game URLs or third-party mod hosts.
    if urllib.parse.urlsplit(url).hostname == "api.github.com" and os.getenv(
        "GITHUB_TOKEN"
    ):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    with urllib.request.urlopen(
        urllib.request.Request(url, headers=headers), timeout=120
    ) as response:
        return response.read()


def get(url):
    return json.loads(download(url))


def release(repo, tag=None):
    endpoint = "tags/" + urllib.parse.quote(tag, safe="") if tag else "latest"
    data = get(API + repo + "/releases/" + endpoint)
    return {"version": data["tag_name"], "url": data["zipball_url"]}


def version_key(value):
    if not re.fullmatch(r"\d+\.\d+\.\d+[a-z]*", value):
        raise ValueError("Unexpected Multiplayer main version: " + value)
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)([a-z]*)", value)
    assert match is not None
    return tuple(map(int, match.groups()[:3])) + (match.group(4),)


def resolve():
    candidates = [
        r
        for r in get("https://balatromp.com/api/releases")
        if r["branchName"] == "main"
        and re.fullmatch(r"\d+\.\d+\.\d+[a-z]*", r["version"])
    ]
    mp = max(candidates, key=lambda r: version_key(r["version"]))
    required = mp.get("smods_version")
    if not required or required == "latest":
        raise ValueError("Multiplayer must specify an exact SMODS version")
    common = {"lovely": release("ethangreen-dev/lovely-injector")}
    # Track runtime/dependency changes as well as mod releases.
    for name, repo in [
        ("runtime", "WilsontheWolf/lmm-love"),
        ("dependencies", "WilsontheWolf/lmm-love-apple-dependencies"),
        ("maker", "WilsontheWolf/lovely-mobile-maker"),
        ("luajit", "LuaJIT/LuaJIT"),
    ]:
        common[name] = {
            "repo": repo,
            "commit": get(API + repo + "/commits?per_page=1")[0]["sha"],
        }
    return {
        "schema": 1,
        "common": common,
        "streams": {
            "multiplayer": {
                "mod": {"version": mp["version"], "url": mp["url"]},
                "smods": release("Steamodded/smods", required),
            },
            "pokermon": {
                "mod": release("InertSteak/Pokermon"),
                "smods": release("Steamodded/smods"),
            },
        },
    }


def archive_files(data, strip_root=False):
    result = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise ValueError("Unsafe archive path: " + info.filename)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("Archive symlinks are unsupported")
            result[path.as_posix()] = archive.read(info)
    if strip_root:
        roots = {p.split("/")[0] for p in result}
        if len(roots) == 1 and all("/" in p for p in result):
            result = {p.split("/", 1)[1]: d for p, d in result.items()}
    return result


def game_files(data):
    files = archive_files(data)
    if "main.lua" in files:
        return files
    nested = [
        p for p in files if p.endswith((".love", "/Balatro.exe")) or p == "Balatro.exe"
    ]
    if len(nested) != 1:
        raise ValueError(
            "Provide a .love, Balatro.exe, or archive/IPA containing exactly one game archive"
        )
    return game_files(files[nested[0]])


def zip_bytes(files):
    executables = set()
    for name, data in files.items():
        if name.endswith(".app/Info.plist"):
            info = plistlib.loads(data)
            if info.get("CFBundleExecutable"):
                executables.add(
                    name.rsplit("/", 1)[0] + "/" + info["CFBundleExecutable"]
                )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            entry = zipfile.ZipInfo(name)
            entry.create_system = 3
            entry.external_attr = (0o100755 if name in executables else 0o100644) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, data)
    return buf.getvalue()


def package(stream, lock, base, game, output):
    files = archive_files(base)
    plists = [p for p in files if re.fullmatch(r"Payload/[^/]+\.app/Info.plist", p)]
    if len(plists) != 1:
        raise ValueError("Base IPA must contain one app")
    app = plists[0].rsplit("/", 1)[0] + "/"
    # Base must come from our rebuilt runtime, not an arbitrary old IPA.
    if json.loads(files[app + "builder-runtime.json"]) != lock["common"]:
        raise ValueError("Base runtime does not match dependency lock")
    mods = {}
    for folder, dependency in [
        ("smods", "smods"),
        ("Multiplayer" if stream == "multiplayer" else "Pokermon", "mod"),
    ]:
        for name, data in archive_files(
            download(lock["streams"][stream][dependency]["url"]), True
        ).items():
            mods[folder + "/" + name] = data
    reserved = {"smods", "multiplayer", "pokermon"}
    for group in ["common", stream]:
        root = ROOT / "static-mods" / group
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Static mod symlinks are unsupported")
            if not path.is_file() or path.name == ".gitkeep":
                continue
            name = path.relative_to(root).as_posix()
            if (
                "/" not in name
                or name.split("/")[0].lower() in reserved
                or name in mods
            ):
                raise ValueError(
                    "Static mods must use unique, nonreserved mod folders: " + name
                )
            mods[name] = path.read_bytes()
    manifest = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(mods.items())
    }
    for name, data in mods.items():
        files[app + "bundled-mods/" + name] = data
    files[app + "bundled-mods.json"] = json.dumps(manifest, sort_keys=True).encode()
    files[app + "build-manifest.json"] = json.dumps(lock, indent=2).encode()
    files[app + "game.love"] = zip_bytes(game_files(game))
    info = plistlib.loads(files[plists[0]])
    info["CFBundleIdentifier"] = "io.balatro.modbuilder." + stream
    info["CFBundleDisplayName"] = "Balatro " + (
        "Multiplayer" if stream == "multiplayer" else "Pokermon"
    )
    info["UIFileSharingEnabled"] = True
    info["LSSupportsOpeningDocumentsInPlace"] = True
    files[plists[0]] = plistlib.dumps(info)
    files = {
        p: d
        for p, d in files.items()
        if "/_CodeSignature/" not in p and not p.endswith("/embedded.mobileprovision")
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(zip_bytes(files))


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    res = sub.add_parser("resolve")
    res.add_argument("--output", type=Path, default=ROOT / "versions.lock.json")
    build = sub.add_parser("build")
    build.add_argument("--stream", choices=["multiplayer", "pokermon"], required=True)
    build.add_argument("--base", type=Path, required=True)
    build.add_argument("--lock", type=Path, default=ROOT / "versions.lock.json")
    build.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "resolve":
        args.output.write_text(json.dumps(resolve(), indent=2, sort_keys=True) + "\n")
    else:
        url = os.environ.get("BALATRO_GAME_URL")
        if not url:
            parser.error("BALATRO_GAME_URL must point to your game archive")
        package(
            args.stream,
            json.loads(args.lock.read_text()),
            args.base.read_bytes(),
            download(url),
            args.output or ROOT / "dist" / ("balatro-" + args.stream + ".ipa"),
        )


if __name__ == "__main__":
    main()
