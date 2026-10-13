"""Rebuild Mobile Maker's iOS runtime with locked Lovely and startup installer (macOS)."""

import json
import shutil
import subprocess
import sys

from builder import ROOT, zip_bytes


def run(*args, cwd=None, env=None):
    subprocess.run(args, cwd=cwd, env=env, check=True)


def sources(repo, ref, dest):
    run("git", "clone", "https://github.com/" + repo + ".git", str(dest))
    run("git", "checkout", ref, cwd=dest)


def main():
    if sys.platform != "darwin":
        raise SystemExit("Runtime compilation requires macOS and Xcode")
    lock = json.loads((ROOT / "versions.lock.json").read_text())["common"]
    work = ROOT / ".build/runtime"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    for name in ["runtime", "luajit"]:
        sources(lock[name]["repo"], lock[name]["commit"], work / name)
    sources(
        "ethangreen-dev/lovely-injector", lock["lovely"]["version"], work / "lovely"
    )
    love, deps, jit, lovely = [
        work / n for n in ["runtime", "dependencies", "luajit", "lovely"]
    ]
    # Upstream archives include symlinks; use git checkouts for Apple framework bundles.
    run(
        "git",
        "clone",
        "https://github.com/" + lock["dependencies"]["repo"] + ".git",
        str(deps),
    )
    run("git", "checkout", lock["dependencies"]["commit"], cwd=deps)
    run("rustup", "target", "add", "aarch64-apple-ios", cwd=lovely)
    run(
        "cargo",
        "build",
        "--locked",
        "--release",
        "--package",
        "liblovely",
        "--target",
        "aarch64-apple-ios",
        cwd=lovely,
    )
    run("git", "apply", str(lovely / "crates/liblovely/luajit.patch"), cwd=jit)
    sdk = subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True
    ).strip()
    compiler = subprocess.check_output(
        ["xcrun", "--sdk", "iphoneos", "--find", "clang"], text=True
    ).strip()
    run(
        "make",
        "-j4",
        "HOST_CC=cc",
        f"CROSS={compiler.removesuffix('clang')}",
        "TARGET_SYS=iOS",
        "TARGET_FLAGS=-arch arm64 -isysroot " + sdk + " -miphoneos-version-min=13.0",
        "BUILDMODE=static",
        "XCFLAGS=-DLUAJIT_DISABLE_JIT",
        "-C",
        "src",
        "libluajit.a",
        cwd=jit,
    )
    library = deps / "iOS/libraries/Lua.xcframework/ios-arm64/libluajit_device.a"
    run(
        "libtool",
        "-static",
        "-o",
        str(library),
        str(jit / "src/libluajit.a"),
        str(lovely / "target/aarch64-apple-ios/release/liblovely.a"),
    )
    for header in (jit / "src").glob("*.h"):
        shutil.copy2(header, library.parent / "Headers" / header.name)
    shutil.copytree(
        deps / "iOS/libraries", love / "platform/xcode/ios/libraries", symlinks=True
    )
    ios = love / "src/common/ios.mm"
    ios.write_text(
        ios.read_text()
        + "\n#ifdef LOVE_IOS\n"
        + (ROOT / "native/install-mods.mm").read_text()
        + "\n#endif\n"
    )
    cpp = love / "src/love.cpp"
    text = cpp.read_text()
    anchor = "\t\tputenv(strdup(env.c_str()));"
    if text.count(anchor) != 1:
        raise RuntimeError("Upstream iOS startup changed; inspect installer placement")
    text = 'extern "C" void builder_install_mods();\n' + text.replace(
        anchor, anchor + "\n\t\tbuilder_install_mods();", 1
    )
    cpp.write_text(text)
    run(
        "xcodebuild",
        "-project",
        "platform/xcode/love.xcodeproj",
        "-scheme",
        "love-ios",
        "-configuration",
        "Release",
        "-derivedDataPath",
        "ios-build",
        "-destination",
        "generic/platform=iOS",
        "ARCHS=arm64",
        "ONLY_ACTIVE_ARCH=YES",
        "IPHONEOS_DEPLOYMENT_TARGET=13.0",
        "CODE_SIGNING_ALLOWED=NO",
        "OTHER_LDFLAGS=$(inherited) -framework Security -framework SystemConfiguration -liconv -lresolv",
        cwd=love,
    )
    apps = list((love / "ios-build/Build/Products/Release-iphoneos").glob("*.app"))
    if len(apps) != 1:
        raise RuntimeError("Expected one built app")
    app = apps[0]
    (app / "builder-runtime.json").write_text(json.dumps(lock, sort_keys=True))
    files = {
        "Payload/" + app.name + "/" + p.relative_to(app).as_posix(): p.read_bytes()
        for p in app.rglob("*")
        if p.is_file()
    }
    (ROOT / ".build/base.ipa").write_bytes(zip_bytes(files))


if __name__ == "__main__":
    main()
