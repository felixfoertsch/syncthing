# Local Syncthing patches

`patch-queue` owns control scripts, workflows and ordered `NNNN` patches.
`main` contains upstream default-branch source plus all accepted patches, without
control scripts, queue files or workflows. Stable archives use latest numeric
upstream release; nightly archives use upstream default-branch commit. Both
channels replay identical queue and stop on conflicts; exact reverse application
alone proves absorption.

GitHub workflow uses built-in job token, macos-14 ARM64 runner, Developer ID
signing, Darwin ARM64 zip and Linux amd64/arm64 tar archives. Nightly releases
are prereleases, never latest. Future stable tags use
`<upstream-tag>-YYYY.MM.DD.N` with Europe/Berlin date and first free same-day
counter. Existing tags/assets remain immutable. Set explicit suffix to resume
an interrupted draft; retry checks existing asset bytes before filling gaps.
Build jobs hold read-only token, no persisted checkout credentials and no signing
secrets. Separate fresh hosted ARM64 publisher checks exact event control SHA,
complete archive hashes, safe member paths, embedded Go version metadata and
reconstructed source commit before importing production key. Publisher signs
existing Darwin binary without executing it or downloaded source scripts.
Only validated nightly candidate advances `main`, with expected-SHA lease and
fresh queue/upstream checks. Hosted jobs are isolated; no persistent runner used.

Offline regressions:

```fish
python3 scripts/tests/test-custom-release.py
bats scripts/tests/test-custom-release-macos-runner.bats
```

Local release builds change checkout to detached generated source; use disposable
clone. Explicit `CUSTOM_RELEASE_SUFFIX` must match `YYYY.MM.DD.N`.

The patch makes root-level `.stignore` sync like regular folder content while
keeping `.stfolder` and `.stversions` protected as internal Syncthing paths.
The web UI patch adds `It syncs .stignore now!` to the GUI footer so the custom
binary is visually distinguishable from upstream builds. The release test fails
if the generated GUI asset bundle does not contain that marker.

## Patch review and operating limits

The production changes are deliberately limited to removing `.stignore` from
`fs.IsInternal`, invalidating the ignore-file metadata cache, and scheduling
a full scan after a valid remote `.stignore` update. This uses Syncthing's
existing transfer, atomic replacement, conflict, versioning and ignore-loading
machinery. `.stfolder`, `.stversions` and transfer
temporary files retain their existing protection. Nothing changes the protocol.

A full scan after remote creation, replacement or deletion is necessary: the
filesystem watcher can suppress puller-generated events, and periodic scans can
be disabled. Invalid/ignored index entries do not schedule another scan. The
scan is queued, not run concurrently with the puller or while holding its I/O
limiter. The regression test covers unchanged timestamps, disables both watcher
and periodic scans, and checks that files become ignored and unignored without
an API call or manual rescan.
The release gate also checks serving `.stignore` to peers and rejecting requests
for the protected internal paths, with repeated race-detector runs.

This remains regular-file synchronization, not unconditional or transactional
configuration distribution:

- All peers that should exchange `.stignore` need this fork. Stock Syncthing
  still excludes the file. Keep upstream auto-upgrades disabled when using
  these custom binaries; installing an official binary removes the patch.
- Normal ignore rules can exclude `.stignore` itself. With broad rules such as
  `.*` or `*`, place `!/.stignore` before the matching rule on every peer.
  An explicit `/.stignore` rule remains a supported opt-out.
- Only the root `.stignore` configures the folder. Nested `.stignore` files
  remain ordinary content; they do not introduce recursive ignore scopes.
- Shared rules are not a privacy boundary. Peers can change them; simultaneous
  edits use ordinary conflict handling, not a semantic merge. A new device may
  scan existing content before it receives the shared rules, and rules do not
  apply atomically ahead of every other file in a transfer. Pre-seed rules on
  new peers before sharing sensitive existing content.
- Prefer a self-contained, valid `.stignore`. Syncthing stops scanning/pulling
  on malformed rules or a missing `#include` target. Ensure include files exist
  on every peer before referencing them; a later remote edit cannot be relied
  upon to repair a folder that is already stopped by an invalid ignore file.

Run the focused behavior tests after regenerating embedded assets:

```bash
go run build.go assets
go test -race -count=3 -run '^TestStignoreSync' ./lib/model
```
