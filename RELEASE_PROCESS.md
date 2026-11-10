# Mobile releases

Automatic publication follows stable source release tags: the verified paired
release from `tanakrit-d/BalatroMultiplayerMobile` for PvP, and the Pokermon
release tag for Pokermon. Legacy stays pinned to Multiplayer 0.5.5 and must be
selected manually. Only streams whose source release identity changed build.

Pushes to `main` run tests only. Daily checks and ordinary manual runs skip
already-published source tags, even after builder commits, runtime changes or
new workflow attempts. Published release manifests provide per-stream state;
Actions cache eviction cannot cause a rebuild. Exact source and builder commits
remain recorded for reproducibility, but do not trigger publication.

The existing package naming format stays compatible with the AltStore source:
`<stream>-<mod version>-1000.<run number>.<attempt>`. The numeric iOS build remains
separate from the mod version. These numbers identify packages, not release
triggers. Existing releases are neither renamed nor removed during migration.

## Regenerate a bundled-mod fix

In **Actions → Check updates and build iOS streams → Run workflow**:

1. Select one stream: `multiplayer`, `pokermon`, or `multiplayer-legacy`.
2. Enable **replace_ipa**. This option is off by default and rejects `current`.
3. Run from the builder revision containing the bundled-mod changes.

Replacement uses that stream's most recent published manifest, retaining its
exact mod and runtime dependency pins. It rebuilds with the selected builder
revision and a higher internal iOS build number, then replaces the existing IPA
and `versions.lock.json` under the same release tag and filenames. The Git tag
is not moved. Release notes record the replacement commit and iOS build.

Before uploading, the publisher downloads and SHA-256-verifies the old IPA and
manifest and saves release metadata. It rejects changed pins, a stale release
ID, non-increasing build numbers and assets changed during backup. Uploaded
assets are checksum-verified. Backups are uploaded as a workflow artifact even
if publication fails, retained for 90 days. GitHub asset replacement is not
atomic; if a step fails after an upload, inspect the preserved backup and remote
assets before retrying. Ordinary publication still refuses to overwrite assets.

The AltStore repository currently skips complete mirrors and derives build
numbers from filenames. After a replacement, refresh its mirrored IPA and update
its build metadata from the new manifest before distributing through AltStore;
rerunning the existing mirror alone does not accomplish that. This workflow
updates only the builder release.

PvP still verifies the published paired source release and asset hashes before
packaging. Steamodded requirements come from its mod manifests. The release
manifest is uploaded alongside the IPA and embedded as `build-manifest.json`.
