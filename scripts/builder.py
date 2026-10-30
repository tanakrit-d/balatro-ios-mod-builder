"""Resolve upstream versions and package isolated iOS mod streams."""

import argparse
import base64
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

import ios_openssl
from game_archive import decrypt

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.github.com/repos/"
STREAMS = ("multiplayer", "multiplayer-legacy", "pokermon")

# Frozen launcher-era dependencies. Only built/released when explicitly selected.
LEGACY_MULTIPLAYER = {
    "mod": {
        "version": "0.5.5",
        "url": "https://s3.andrii.es/balatro-mp-releases/1786733782648-BalatroMultiplayer.zip",
    },
    "smods": {
        "version": "1.0.0-beta-1620a",
        "url": "https://api.github.com/repos/Steamodded/smods/zipball/1.0.0-beta-1620a",
    },
}


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


def mod_manifest(repo, tag, filename):
    # Read requirements from the exact release tag or commit being bundled.
    data = get(
        API
        + repo
        + "/contents/"
        + filename
        + "?ref="
        + urllib.parse.quote(tag, safe="")
    )
    if data.get("encoding") != "base64":
        raise ValueError("Unsupported manifest encoding for " + repo)
    manifest = json.loads(base64.b64decode(data["content"]))
    dependencies = manifest.get("dependencies")
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ValueError("Missing or invalid dependencies in " + filename)
    return manifest


def smods_version_key(value):
    # Steamodded uses '~BETA-' in mod manifests and '-beta-' in Git tags.
    match = re.fullmatch(
        r"(\d+)\.(\d+)\.(\d+)(?:[~-][Bb][Ee][Tt][Aa]-(\d+)([a-z]*))?", value
    )
    if match is None:
        raise ValueError("Unsupported Steamodded version: " + value)
    major, minor, patch, beta, suffix = match.groups()
    return (
        int(major),
        int(minor),
        int(patch),
        beta is None,
        int(beta or 0),
        suffix or "",
    )


def required_smods(manifests):
    minimums = []
    for name, manifest in manifests.items():
        requirements = [
            item for item in manifest["dependencies"] if re.match(r"Steamodded\b", item)
        ]
        if len(requirements) != 1:
            raise ValueError(name + " must declare one Steamodded minimum")
        match = re.fullmatch(r"Steamodded\s+\(>=([^\s()]+)\)", requirements[0])
        if match is None:
            raise ValueError(
                "Unsupported Steamodded requirement in " + name + ": " + requirements[0]
            )
        minimums.append(match[1])
    minimum = max(minimums, key=smods_version_key)
    # Pin the declared minimum rather than silently upgrading to SMODS latest.
    tag = re.sub(r"[~-]beta-", "-beta-", minimum, flags=re.IGNORECASE)
    return release("Steamodded/smods", tag)


def branch_mod(repo, filename, branch="mobile"):
    # Resolve once, then fetch both metadata and archive at that immutable SHA.
    commit = get(API + repo + "/commits/" + urllib.parse.quote(branch, safe=""))["sha"]
    manifest = mod_manifest(repo, commit, filename)
    version = manifest.get("version")
    if not isinstance(version, str) or not re.fullmatch(
        r"v?\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version
    ):
        raise ValueError("Missing or invalid mod version in " + filename)
    return {
        "repo": repo,
        "branch": branch,
        "commit": commit,
        "version": version,
        "url": API + repo + "/zipball/" + commit,
    }, manifest


def resolve():
    # Mobile patches live in our forks. Track commit changes independently of
    # manifest versions so API-only fixes also invalidate the build state.
    mp, mp_manifest = branch_mod(
        "tanakrit-d/BalatroMultiplayerPvP", "MultiplayerPvP.json"
    )
    mp_api, api_manifest = branch_mod(
        "tanakrit-d/BalatroMultiplayerAPI", "MultiplayerAPI.json"
    )
    mp_smods = required_smods(
        {"MultiplayerPvP": mp_manifest, "MultiplayerAPI": api_manifest}
    )
    common = {
        "openssl": ios_openssl.lock_entry(),
        "lovely": release("ethangreen-dev/lovely-injector"),
        # Match Mobile Maker's SDL ABI, with our UIKit scene lifecycle backport.
        "sdl": {
            "repo": "libsdl-org/SDL",
            "commit": "15ead9a40d09a1eb9972215cceac2bf29c9b77f6",
        },
    }
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
            "multiplayer-legacy": LEGACY_MULTIPLAYER,
            "multiplayer": {
                "mod": mp,
                "api": mp_api,
                "smods": mp_smods,
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
    try:
        extracted = archive_files(data)
    except zipfile.BadZipFile:
        prefix = data[:512].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
        if not data:
            reason = "The game input is empty."
        elif prefix.startswith((b"<!doctype html", b"<html")):
            reason = "The game input is HTML, likely a sharing, login, or error page."
        elif data.startswith(b"PK"):
            reason = "The game ZIP appears truncated or corrupt."
        else:
            reason = "The game input is not a valid ZIP-compatible archive."
        raise ValueError(
            reason
            + " Provide a complete .love, Balatro.exe, ZIP, or IPA containing the game."
        ) from None
    files = {
        p: d
        for p, d in extracted.items()
        if not p.startswith("__MACOSX/")
        and not any(
            part.startswith("._") or part == ".DS_Store"
            for part in PurePosixPath(p).parts
        )
    }
    if "main.lua" in files:
        return files
    mains = [p for p in files if p.endswith("/main.lua")]
    if len(mains) == 1:
        root = mains[0].removesuffix("main.lua")
        return {p[len(root) :]: d for p, d in files.items() if p.startswith(root)}
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


def apply_mod_configs(stream, mods):
    # Stream-specific config defaults for downloaded or static mods. Keep code
    # overrides separate from this directory: only existing config.lua files fit.
    root = ROOT / "mod-configs" / stream
    if root.is_symlink():
        raise ValueError("Mod config symlinks are unsupported")
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Mod config symlinks are unsupported")
        if not path.is_file() or path.name == ".gitkeep":
            continue
        relative = path.relative_to(root)
        name = relative.as_posix()
        if len(relative.parts) != 2 or path.name != "config.lua" or name not in mods:
            raise ValueError(
                "Mod config must replace an existing <mod>/config.lua: " + name
            )
        mods[name] = path.read_bytes()


def package(stream, lock, base, game, output):
    files = archive_files(base)
    plists = [p for p in files if re.fullmatch(r"Payload/[^/]+\.app/Info.plist", p)]
    if len(plists) != 1:
        raise ValueError("Base IPA must contain one app")
    app = plists[0].rsplit("/", 1)[0] + "/"
    # Base must come from our rebuilt runtime, not an arbitrary old IPA.
    if json.loads(files[app + "builder-runtime.json"]) != lock["common"]:
        raise ValueError("Base runtime does not match dependency lock")
    if stream == "multiplayer":
        ios_openssl.validate_runtime(files, app)
    game_archive = zip_bytes(game_files(game))
    mods = {}
    dependencies = [("smods", "smods")]
    if stream == "multiplayer":
        dependencies += [("MultiplayerAPI", "api"), ("MultiplayerPvP", "mod")]
    elif stream == "multiplayer-legacy":
        dependencies.append(("Multiplayer", "mod"))
    else:
        dependencies.append(("Pokermon", "mod"))
    for folder, dependency in dependencies:
        for name, data in archive_files(
            download(lock["streams"][stream][dependency]["url"]), True
        ).items():
            mods[folder + "/" + name] = data
    if stream == "multiplayer":
        ios_openssl.patch_mods(mods)
    reserved = {"smods", "multiplayer", "multiplayerapi", "multiplayerpvp", "pokermon"}
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
    apply_mod_configs(stream, mods)
    manifest = {
        name: hashlib.sha256(data).hexdigest() for name, data in sorted(mods.items())
    }
    for name, data in mods.items():
        files[app + "bundled-mods/" + name] = data
    files[app + "bundled-mods.json"] = json.dumps(manifest, sort_keys=True).encode()
    files[app + "build-manifest.json"] = json.dumps(lock, indent=2).encode()
    files[app + "game.love"] = game_archive
    info = plistlib.loads(files[plists[0]])
    # Keep PvP installs separate from the frozen 0.5.x Multiplayer app.
    info["CFBundleIdentifier"] = {
        "multiplayer": "mod.balatro.multiplayer.pvp",
        "multiplayer-legacy": "mod.balatro.multiplayer",
        "pokermon": "mod.balatro.pokermon",
    }[stream]
    name = {
        "multiplayer": "Balatro (PVP)",
        "multiplayer-legacy": "Balatro (MP) (Legacy)",
        "pokermon": "Balatro (PK)",
    }[stream]
    info["CFBundleDisplayName"] = name
    info["CFBundleName"] = name
    version = lock["streams"][stream]["mod"]["version"].removeprefix("v")
    info["CFBundleShortVersionString"] = version
    info["CFBundleVersion"] = version
    icon_root = "builder-icons/" + stream + "/"
    icon_info = files.get(icon_root + "icon-info.plist")
    if icon_info is None:
        raise ValueError("Base IPA is missing compiled app icons; rebuild the runtime")
    info.update(plistlib.loads(icon_info))
    files.update(
        {
            app + path.removeprefix(icon_root): data
            for path, data in files.items()
            if path.startswith(icon_root) and path != icon_root + "icon-info.plist"
        }
    )
    files = {p: d for p, d in files.items() if not p.startswith("builder-icons/")}
    info["UIApplicationSceneManifest"] = {
        "UIApplicationSupportsMultipleScenes": False,
        "UISceneConfigurations": {
            "UIWindowSceneSessionRoleApplication": [
                {
                    "UISceneConfigurationName": "Game",
                    "UISceneDelegateClassName": "SDLUIKitSceneDelegate",
                }
            ]
        },
    }
    info["UIFileSharingEnabled"] = True
    landscapes = [
        "UIInterfaceOrientationLandscapeLeft",
        "UIInterfaceOrientationLandscapeRight",
    ]
    info["UISupportedInterfaceOrientations"] = landscapes
    info["UISupportedInterfaceOrientations~ipad"] = landscapes
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
    build.add_argument("--stream", choices=STREAMS, required=True)
    build.add_argument("--base", type=Path, required=True)
    build.add_argument(
        "--game",
        type=Path,
        help="Local plaintext game archive instead of the encrypted archive",
    )
    build.add_argument(
        "--encrypted-game", type=Path, default=ROOT / "assets/game/B.love.zip.enc"
    )
    build.add_argument("--lock", type=Path, default=ROOT / "versions.lock.json")
    build.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.command == "resolve":
        args.output.write_text(json.dumps(resolve(), indent=2, sort_keys=True) + "\n")
    else:
        if args.game:
            game = args.game.read_bytes()
        else:
            key = os.environ.get("BALATRO_GAME_KEY")
            if not key:
                parser.error(
                    "Set BALATRO_GAME_KEY to decrypt the committed game archive"
                )
            try:
                game = decrypt(args.encrypted_game.read_bytes(), key)
            except ValueError as error:
                parser.error(str(error))
        package(
            args.stream,
            json.loads(args.lock.read_text()),
            args.base.read_bytes(),
            game,
            args.output or ROOT / "dist" / ("balatro-" + args.stream + ".ipa"),
        )


if __name__ == "__main__":
    main()
