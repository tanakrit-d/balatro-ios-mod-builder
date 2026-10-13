# Balatro iOS mod builder

Builds separate **Balatro Multiplayer** and **Balatro Pokermon** IPAs using [Lovely Mobile Maker](https://github.com/WilsontheWolf/lovely-mobile-maker)'s [iOS LÖVE runtime](https://github.com/WilsontheWolf/lmm-love). The runtime is rebuilt with the latest release of [Lovely](https://github.com/ethangreen-dev/lovely-injector), statically linked into patched LuaJIT. The example IPA is used only for local extraction verification; it is not committed or used as the runtime template.

## GitHub Actions

Set the repository Actions secret `BALATRO_GAME_URL` to an HTTPS URL for your own Balatro game archive. Accepted inputs: `.love`, desktop `Balatro.exe`, a ZIP containing one of those, or an IPA containing `game.love`. The URL must be accessible without additional request headers. Then run **Check updates and build iOS streams** from the Actions tab.

The workflow checks every six hours. It rebuilds both streams when any upstream dependency changes; manual runs and relevant pushes always build. Successful locks are retained in the Actions cache, so failed builds retry on the next check. Cache eviction can trigger a harmless rebuild. Download `balatro-ios` from the successful run to obtain both IPAs and their exact dependency lock. Artifacts expire after seven days. The workflow has read-only repository permissions and does not publish releases or push commits. IPAs contain game assets: keep the repository and artifacts appropriately private.

The resulting IPAs require iOS 15 or later, are unsigned, and must be signed with your usual iOS sideloading tool. The streams have distinct bundle identifiers, allowing both to be installed together.

## Versions

`versions.lock.json` records exact dependencies. Multiplayer uses the same [release API](https://balatromp.com/api/releases) as its [launcher](https://github.com/Balatro-Multiplayer/Balatro-Multiplayer-Launcher), selects the highest standard main-stream version (including letter suffixes, excluding named variants), and requires its exact `smods_version`. An unavailable SMODS tag fails the build; there is no fallback. Pokermon and its SMODS use their latest non-prerelease GitHub releases. Lovely uses its latest non-prerelease release. Runtime, Apple dependencies, and LuaJIT commits are also locked.

## App icons

Custom app icons live in `assets/icons/multiplayer-1024.png` and `assets/icons/pokermon-1024.png`. Use opaque 1024 × 1024 PNGs. The runtime build compiles both icon catalogs with Xcode; packaging selects the matching catalog for each stream. Icon changes trigger the GitHub workflow.

## Static mods

Put complete mod directories in:

- `static-mods/common/<ModName>/`: bundled into both streams.
- `static-mods/multiplayer/<ModName>/`: Multiplayer only.
- `static-mods/pokermon/<ModName>/`: Pokermon only.

These files are never updated from upstream. Duplicate file paths and reserved mod folder names (`smods`, `Multiplayer`, `Pokermon`) fail packaging. Ensure your chosen static mods support each stream's SMODS version.

## On-device installation

Native startup code copies bundled mod files into the app's `Documents/game/Mods` directory **before LuaJIT creates its VM and Lovely reads patches**. On upgrades, changed bundled files are replaced and previously bundled files that disappeared are removed. User-created files, saves, and mod-generated configs outside the bundled file manifest are preserved. Editing a bundled file persists until that file's bundled hash changes. Deleting a bundled file restores it on next launch. Installation failure stops startup and logs an error; the state manifest is written only after a successful install so it retries next launch.

The app enables Files sharing, exposing `game/Mods` under its Documents folder. Each stream has its own sandbox and saves. Do not change the game identity in `conf.lua`: Mobile Maker expects `game` on iOS.

## Local build

Requires macOS, Xcode with the iOS SDK, Rust/rustup, Python 3.12+, Git, CMake, and make. The runtime script follows upstream's Apple dependency setup and uses Lovely's provided LuaJIT patch. It rebuilds SDL 2.28.5 with the scene lifecycle backport in `native/sdl2-scenes.patch`, required for launching apps built with the iOS 27 SDK. The app uses a single window scene and forwards scene lifecycle events to SDL. Upstream patch/build incompatibilities intentionally stop the build for review.

```sh
python scripts/builder.py resolve
python scripts/runtime.py
export BALATRO_GAME_URL='https://your-host.example/Balatro.love'
python scripts/builder.py build --stream multiplayer --base .build/base.ipa
python scripts/builder.py build --stream pokermon --base .build/base.ipa
```

Outputs are in `dist/`. Optional `GITHUB_TOKEN` is used only for GitHub API requests. Game URLs and downloads are not printed by the builder. Runtime compilation requires macOS; packaging and resolution also run on Linux.

To test with a local ZIP instead of a URL, pass `--game local_ipa/Balatro.love.zip` to each `build` command. ZIPs containing an extracted game folder are also supported; macOS archive metadata is discarded.

```sh
python -m unittest discover -s tests -v
```

Local tests cover release selection, strict compatibility, unsafe archives, both stream layouts, static mods, runtime lock matching, and (when present) the example IPA. A full Xcode build and on-device launch are still required to validate native linking, mod loading, Multiplayer networking, and gameplay.
