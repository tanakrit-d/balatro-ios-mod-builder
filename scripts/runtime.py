"""Rebuild Mobile Maker's iOS runtime with locked Lovely and startup installer (macOS)."""

import json
import os
import shutil
import subprocess
import sys

from builder import ROOT, zip_bytes
from icons import compile_icons


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
    sdl = work / "sdl"
    sources(lock["sdl"]["repo"], lock["sdl"]["commit"], sdl)
    run("git", "apply", str(ROOT / "native/sdl2-scenes.patch"), cwd=sdl)
    run(
        "cmake",
        "-S",
        str(sdl),
        "-B",
        str(work / "sdl-build"),
        "-DCMAKE_SYSTEM_NAME=iOS",
        "-DCMAKE_OSX_SYSROOT=iphoneos",
        "-DCMAKE_OSX_ARCHITECTURES=arm64",
        "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0",
        "-DCMAKE_BUILD_TYPE=Release",
        "-DSDL_SHARED=OFF",
        "-DSDL_STATIC=ON",
        "-DSDL_TEST=OFF",
        "-DSDL_HIDAPI=OFF",
        "-DCMAKE_POLICY_VERSION_MINIMUM=3.5",
    )
    run("cmake", "--build", str(work / "sdl-build"), "--parallel", "4")
    run(
        "libtool",
        "-static",
        "-o",
        str(deps / "iOS/libraries/SDL2.xcframework/ios-arm64/libSDL2.a"),
        str(work / "sdl-build/libSDL2.a"),
        str(work / "sdl-build/libSDL2main.a"),
    )
    run("rustup", "target", "add", "aarch64-apple-ios", cwd=lovely)
    ios_env = os.environ.copy()
    ios_env["IPHONEOS_DEPLOYMENT_TARGET"] = "15.0"
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
        env=ios_env,
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
        "TARGET_CC=" + compiler,
        "TARGET_LD=" + compiler,
        "TARGET_SYS=iOS",
        "TARGET_FLAGS=-arch arm64 -isysroot " + sdk + " -miphoneos-version-min=15.0",
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
        "IPHONEOS_DEPLOYMENT_TARGET=15.0",
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
    files.update(compile_icons(love / "platform/xcode/Images.xcassets"))
    (ROOT / ".build/base.ipa").write_bytes(zip_bytes(files))


if __name__ == "__main__":
    main()
