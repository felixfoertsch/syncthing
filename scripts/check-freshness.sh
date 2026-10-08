#!/usr/bin/env bash
set -euo pipefail
upstream_url=https://github.com/syncthing/syncthing.git
[[ "$(git ls-remote origin refs/heads/patch-queue | awk '{print $1}')" == "$CUSTOM_RELEASE_AUTOMATION_REF" ]] || exit 1
if [[ "$CUSTOM_RELEASE_CHANNEL" == nightly ]]; then
	ref="$(git ls-remote --symref "$upstream_url" HEAD | awk '$1 == "ref:" {print $2}')"
	[[ "$ref" == refs/heads/* ]] || exit 1
	[[ "$(git ls-remote "$upstream_url" "$ref" | awk '{print $1}')" == "$CUSTOM_RELEASE_UPSTREAM_REF" ]] || exit 1
else
	selected="$(git ls-remote "$upstream_url" "refs/tags/$CUSTOM_RELEASE_UPSTREAM_TAG" "refs/tags/$CUSTOM_RELEASE_UPSTREAM_TAG^{}" | awk 'NR == 1 {sha=$1} /\^\{\}$/ {sha=$1} END {print sha}')"
	[[ "$selected" == "$CUSTOM_RELEASE_UPSTREAM_REF" ]] || exit 1
	if [[ -z "${CUSTOM_RELEASE_EXPLICIT_TAG:-}" ]]; then
		latest="$(git ls-remote --refs --tags --sort=version:refname "$upstream_url" 'v[0-9]*' | awk '{t=$2; sub("refs/tags/", "", t); if(t ~ /^v[0-9]+\.[0-9]+\.[0-9]+$/) latest=t} END {print latest}')"
		[[ "$latest" == "$CUSTOM_RELEASE_UPSTREAM_TAG" ]] || exit 1
	fi
fi
