# Mobile releases

The builder consumes published stable releases from
`tanakrit-d/BalatroMultiplayerMobile`. It pins the release manifest, patch commit,
upstream commits and asset SHA-256 hashes, then verifies both mod ZIPs before
packaging. Steamodded is selected from the bundled mod manifests. The API already
contains the iOS loader; the builder supplies the native runtime and removes
desktop libraries.

Each actual build gets revision `<workflow run number>.<attempt>` and numeric
iOS build `1000.<run number>.<attempt>`. The leading 1000 keeps new build numbers
above the old mod-derived build numbers. The mod version stays unchanged, so
an API-only fix or packaging change does not invent a new PvP mod version.

For example, mod 1.0.3 at mobile revision 32.1 produces:

- GitHub tag: `multiplayer-1.0.3-1000.32.1`
- IPA: `b-multiplayer.1.0.3-1000.32.1.ipa`
- iOS version: `1.0.3`; iOS build: `1000.32.1`

`versions.lock.json` records the exact API, PvP, official-release and runtime
commits plus the builder commit and package revision. It is uploaded with each
release and embedded as `build-manifest.json` inside the IPA. The committed
lockfile is a snapshot; Actions regenerates it before planning a build.

The daily run skips unchanged inputs, including the builder commit. Manual runs
can rebuild unchanged sources; workflow retries get a new attempt number. A
successful publication is cached only after every selected stream is published.
Legacy remains a separate, manually selected stream.

Published assets and tags are never replaced or moved. A publication retry can
verify an identical complete release using its SHA-256 digests; different or
incomplete assets require a new full workflow run. Historical releases are left
untouched. The AltStore source retains the mod version as `version` and maps the
numeric mobile build to `buildVersion`, so mobile revisions are distinct updates.
