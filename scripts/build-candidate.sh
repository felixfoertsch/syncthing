#!/usr/bin/env bash
set -euo pipefail
[[ "$(git rev-parse HEAD)" == "$CONTROL" ]] || exit 1
[[ "$(uname -m)" == arm64 ]] || exit 1
expected_main="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
export CUSTOM_RELEASE_CHANNEL="$CHANNEL" CUSTOM_RELEASE_SIGN_DARWIN=0 CUSTOM_RELEASE_PUSH=0
export CUSTOM_RELEASE_BUILDS='darwin/arm64/zip/1 linux/amd64/tar/0 linux/arm64/tar/0'
source scripts/update-custom-release.sh
resolve_upstream_tag
export CUSTOM_RELEASE_UPSTREAM_TAG="$upstream_tag" CUSTOM_RELEASE_SUFFIX="$suffix" CUSTOM_RELEASE_UPSTREAM_REF="$upstream_ref"
# This process retains trusted control script even after source checkout changes.
main
source_sha="$(git rev-parse HEAD)"
source_tag="${upstream_tag}-${suffix}"
git bundle create dist/source.bundle "$source_tag"
export CANDIDATE_MAIN="$expected_main" CANDIDATE_SOURCE="$source_sha" CANDIDATE_TAG="$source_tag" CANDIDATE_UPSTREAM_TAG="$upstream_tag"
export CANDIDATE_UPSTREAM="$(git rev-parse HEAD^)"
python3 - <<'PY'
import hashlib, json, os
from pathlib import Path
p = Path('dist')
data = {key: os.environ[env] for key, env in [('control','CONTROL'),('channel','CHANNEL'),('main','CANDIDATE_MAIN'),('source','CANDIDATE_SOURCE'),('tag','CANDIDATE_TAG'),('upstream_tag','CANDIDATE_UPSTREAM_TAG'),('upstream','CANDIDATE_UPSTREAM')]}
data['assets'] = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in p.iterdir() if f.name.endswith(('.zip','.tar.gz'))}
(p / 'candidate.json').write_text(json.dumps(data, sort_keys=True))
PY
mv dist candidate
