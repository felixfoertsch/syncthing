#!/usr/bin/env bash
set -euo pipefail
[[ "$(uname -m)" == arm64 && "$(git rev-parse HEAD)" == "$CONTROL" ]] || exit 1
for tool in git python3 gh jq codesign security openssl shasum zip unzip tar; do
	command -v "$tool" >/dev/null || exit 1
done
if [[ -f candidate/unchanged ]]; then
	[[ "$(python3 scripts/select-release.py)" == skip ]] || exit 1
	printf 'skipped=true\n' >> "$GITHUB_OUTPUT"
	exit 0
fi
python3 scripts/verify-candidate.py candidate "$CONTROL" "$CHANNEL" > "$RUNNER_TEMP/verified-fields"
while IFS='=' read -r key value; do
	case "$key" in
		upstream_tag) export CUSTOM_RELEASE_UPSTREAM_TAG="$value" ;;
		upstream) export CUSTOM_RELEASE_UPSTREAM_REF="$value" ;;
		source) export CANDIDATE_SOURCE="$value" ;;
		tag) export RELEASE_TAG="$value" ;;
		main) export EXPECTED_MAIN="$value" ;;
		*) exit 1 ;;
	esac
done < "$RUNNER_TEMP/verified-fields"
export CUSTOM_RELEASE_CHANNEL="$CHANNEL" CUSTOM_RELEASE_AUTOMATION_REF="$CONTROL"
bash scripts/check-freshness.sh
# Bundle is data. Import only expected source object into isolated repository.
verify="$RUNNER_TEMP/verify-source"
git clone --quiet --no-hardlinks . "$verify"
git -C "$verify" bundle verify "$GITHUB_WORKSPACE/candidate/source.bundle" >/dev/null
git -C "$verify" fetch "$GITHUB_WORKSPACE/candidate/source.bundle" "refs/tags/$RELEASE_TAG"
[[ "$(git -C "$verify" rev-parse 'FETCH_HEAD^{commit}')" == "$CANDIDATE_SOURCE" ]] || exit 1
upstream_url=https://github.com/syncthing/syncthing.git
git -C "$verify" fetch "$upstream_url" "$CUSTOM_RELEASE_UPSTREAM_REF"
[[ "$(git -C "$verify" rev-parse FETCH_HEAD)" == "$CUSTOM_RELEASE_UPSTREAM_REF" ]] || exit 1
prefix="$GITHUB_WORKSPACE/patches/README-prefix.md"
source scripts/reconstruct.sh
die() { printf '%s\n' "$*" >&2; exit 1; }
patches=("$GITHUB_WORKSPACE"/patches/[0-9]*.patch)
pushd "$verify" >/dev/null
git checkout --detach "$CUSTOM_RELEASE_UPSTREAM_REF"
apply_patch_queue "${patches[@]}"
commit_reconstruction "$CUSTOM_RELEASE_UPSTREAM_REF" "$prefix"
[[ "$(git rev-parse HEAD)" == "$CANDIDATE_SOURCE" ]] || die 'candidate source differs from trusted reconstruction'
popd >/dev/null
# Export validated scalar fields only; no candidate text enters shell evaluation.
for key in CUSTOM_RELEASE_UPSTREAM_TAG CUSTOM_RELEASE_UPSTREAM_REF CANDIDATE_SOURCE RELEASE_TAG EXPECTED_MAIN; do
	printf '%s=%s\n' "$key" "${!key}" >> "$GITHUB_ENV"
done
printf 'tag=%s\n' "$RELEASE_TAG" >> "$GITHUB_OUTPUT"
