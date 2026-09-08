# Local Syncthing Patches

Apply the local patches manually after pulling a new upstream Syncthing release:

```bash
git apply patches/sync-stignore.patch patches/webui-build-marker.patch
go run build.go -build-out bin/syncthing-stignore build syncthing
```

The automated release flow uses:

```bash
./scripts/update-custom-release.sh
```

By default the script finds the latest stable upstream tag, creates a local
`custom/<version>-<suffix>` branch, applies all local patches, removes upstream
GitHub/Gitea workflow files from the release commit, tags
`<upstream>-stignore.7`, regenerates embedded GUI assets, runs focused tests,
and writes build artifacts to `dist/`.

Useful options:

```bash
CUSTOM_RELEASE_UPSTREAM_TAG=v2.1.0 ./scripts/update-custom-release.sh
CUSTOM_RELEASE_REBUILD_EXISTING=1 ./scripts/update-custom-release.sh
CUSTOM_RELEASE_PATCHES="patches/sync-stignore.patch patches/webui-build-marker.patch" ./scripts/update-custom-release.sh
CUSTOM_RELEASE_PUSH=1 CUSTOM_RELEASE_REMOTE=gitea ./scripts/update-custom-release.sh
CUSTOM_RELEASE_PUSH=1 CUSTOM_RELEASE_PUSH_BRANCH=1 CUSTOM_RELEASE_REMOTE=gitea ./scripts/update-custom-release.sh
CUSTOM_RELEASE_CREATE_GITEA_RELEASE=1 CUSTOM_RELEASE_TEA_REPO=felixfoertsch/syncthing ./scripts/update-custom-release.sh
CUSTOM_RELEASE_BUILDS="darwin/amd64/zip darwin/arm64/zip linux/amd64/tar linux/arm64/tar" ./scripts/update-custom-release.sh
```

The Gitea and GitHub workflows run the script on their respective CI hosts when
the local patchset changes on `main`, on a schedule, and on manual dispatch.
The repository's `upstream` branch stays a clean upstream mirror.
Before building, each host updates its own `upstream` branch from official
Syncthing `main` and rebuilds its patched `main` directly on that commit.
The script detects the latest upstream Syncthing stable tag, pushes only the
`<upstream>-stignore.7` tag by default, and publishes release assets on the CI
host running the workflow. The local `custom/<version>` branch is only pushed
when `CUSTOM_RELEASE_PUSH_BRANCH=1` is set. The workflow builds macOS arm64,
Linux amd64, and Linux arm64 archives. Both hosts sign their macOS builds with
their configured Developer ID certificate.

## Retry-safe GitHub releases

GitHub serializes release runs and the automated upstream-sync commit uses
`[skip ci]`, so its push does not recursively start another build. Scheduled
and manually dispatched runs are unaffected. The upstream tag and suffix are
resolved once and reused for both the build and publication.

A published GitHub release is skipped before Go setup, signing or building.
A tag without a published release is not considered complete: the workflow
rebuilds artifacts from that exact tagged commit, without moving or recreating
the tag. Assets are uploaded to a draft, which is published only after every
upload succeeds. A later run resumes an interrupted draft upload.

Outside the GitHub workflow, the script still skips existing tags by default.
Set `CUSTOM_RELEASE_REBUILD_EXISTING=1` to rebuild their artifacts. Use a new
`CUSTOM_RELEASE_SUFFIX` for changed patches; do not force-replace published tags.

Offline automation regression tests (Python standard library, Git and jq;
Go and GitHub API operations are mocked):

```bash
python3 scripts/tests/test-custom-release.py
```

The patch makes root-level `.stignore` sync like regular folder content while
keeping `.stfolder` and `.stversions` protected as internal Syncthing paths.
The web UI patch adds `It syncs .stignore now!` to the GUI footer so the custom
binary is visually distinguishable from upstream builds. The release test fails
if the generated GUI asset bundle does not contain that marker.
