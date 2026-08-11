#!/usr/bin/env bash
set -euo pipefail

# Description: create a patched Syncthing release from the latest upstream tag.
# Usage: ./scripts/update-custom-release.sh

upstream_url="${CUSTOM_RELEASE_UPSTREAM_URL:-https://github.com/syncthing/syncthing.git}"
upstream_tag="${CUSTOM_RELEASE_UPSTREAM_TAG:-}"
suffix="${CUSTOM_RELEASE_SUFFIX:-stignore.7}"
branch_prefix="${CUSTOM_RELEASE_BRANCH_PREFIX:-custom}"
dist_dir="${CUSTOM_RELEASE_DIST_DIR:-dist}"
target="${CUSTOM_RELEASE_TARGET:-syncthing}"
archive_kind="${CUSTOM_RELEASE_ARCHIVE:-tar}"
build_specs="${CUSTOM_RELEASE_BUILDS:-}"
default_cgo_enabled="${CUSTOM_RELEASE_CGO_ENABLED:-0}"
codesign_identity="${CUSTOM_RELEASE_CODESIGN_IDENTITY:-}"
codesign_team_id="${CUSTOM_RELEASE_CODESIGN_TEAM_ID:-NG5W75WE8U}"
sign_darwin="${CUSTOM_RELEASE_SIGN_DARWIN:-1}"
require_gatekeeper_assessment="${CUSTOM_RELEASE_REQUIRE_GATEKEEPER_ASSESSMENT:-0}"
push_release="${CUSTOM_RELEASE_PUSH:-0}"
push_branch="${CUSTOM_RELEASE_PUSH_BRANCH:-0}"
push_remote="${CUSTOM_RELEASE_REMOTE:-origin}"
run_tests="${CUSTOM_RELEASE_TEST:-1}"
force="${CUSTOM_RELEASE_FORCE:-0}"
publish_gitea_release="${CUSTOM_RELEASE_CREATE_GITEA_RELEASE:-0}"
tea_repo="${CUSTOM_RELEASE_TEA_REPO:-}"
patch_tmp_dir=""
patch_files=()
assets_rebuilt=0

if [[ -n "${CUSTOM_RELEASE_PATCHES:-}" ]]; then
	read -r -a patch_files <<< "$CUSTOM_RELEASE_PATCHES"
elif [[ -n "${CUSTOM_RELEASE_PATCH:-}" ]]; then
	patch_files=("$CUSTOM_RELEASE_PATCH")
else
	patch_files=(
		patches/sync-stignore.patch
		patches/webui-build-marker.patch
	)
fi

log() {
	printf '%s\n' "$*"
}

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

require_clean_worktree() {
	if [[ -n "$(git status --porcelain)" ]]; then
		die "working tree has uncommitted changes"
	fi
}

latest_stable_tag() {
	git ls-remote --refs --tags --sort='version:refname' "$upstream_url" 'v[0-9]*' \
		| awk '{ tag = $2; sub("refs/tags/", "", tag); if (tag ~ /^v[0-9]+\.[0-9]+\.[0-9]+$/) latest = tag } END { print latest }'
}

tag_exists() {
	local tag="$1"

	if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null; then
		return 0
	fi

	git ls-remote --quiet --exit-code --tags "$push_remote" "refs/tags/$tag" >/dev/null 2>&1
}

copy_patches_to_temp() {
	local patch_tmp_dir="$1"
	local patch_file
	local patch_name
	local patch_index=0

	mkdir -p "$patch_tmp_dir"
	for patch_file in "${patch_files[@]}"; do
		[[ -f "$patch_file" ]] || die "patch file not found: $patch_file"
		printf -v patch_name '%03d-%s' "$patch_index" "$(basename "$patch_file")"
		cp "$patch_file" "$patch_tmp_dir/$patch_name"
		patch_index=$((patch_index + 1))
	done
}

fetch_upstream_tag() {
	local tag="$1"

	git fetch --force "$upstream_url" "refs/tags/$tag:refs/tags/$tag"
}

create_release_commit() {
	local tag="$1"
	local custom_tag="$2"
	local branch="$3"
	local patch_tmp_dir="$4"
	local patch_file

	git checkout -B "$branch" "$tag"
	rm -rf "$dist_dir"
	for patch_file in "$patch_tmp_dir"/*; do
		[[ -f "$patch_file" ]] || continue
		log "Applying $(basename "$patch_file")"
		git apply --3way "$patch_file"
	done
	remove_upstream_workflows
	git add -A
	git commit -m "apply local Syncthing patches for $tag"
	git tag -a "$custom_tag" -m "Syncthing $tag with local patches"
}

remove_upstream_workflows() {
	local workflow_dir

	for workflow_dir in .github/workflows .gitea/workflows; do
		if [[ -e "$workflow_dir" ]]; then
			log "Removing upstream workflow directory $workflow_dir from release commit"
			rm -rf "$workflow_dir"
		fi
	done
}

delete_local_tag_if_forced() {
	local tag="$1"

	if [[ "$force" != "1" ]]; then
		return
	fi
	if git rev-parse --quiet --verify "refs/tags/$tag" >/dev/null; then
		git tag -d "$tag"
	fi
}

test_release() {
	if [[ "$run_tests" != "1" ]]; then
		log "Skipping tests because CUSTOM_RELEASE_TEST=$run_tests"
		return
	fi

	rebuild_assets_once
	go test ./lib/api/auto ./lib/fs ./lib/ignore ./lib/scanner ./lib/model
}

rebuild_assets_once() {
	if [[ "$assets_rebuilt" == "1" ]]; then
		return
	fi

	log "Regenerating embedded GUI assets"
	go run build.go assets
	assets_rebuilt=1
}

format_build_specs() {
	local spec

	for spec in $build_specs; do
		printf -- '- %s\n' "$spec"
	done
}

build_release() {
	local custom_tag="$1"

	rebuild_assets_once
	rm -rf "$dist_dir"
	mkdir -p "$dist_dir"

	if [[ -z "$build_specs" ]]; then
		build_specs="$(go env GOOS)/$(go env GOARCH)/$archive_kind"
	fi

	local spec
	for spec in $build_specs; do
		build_one "$custom_tag" "$spec"
	done

	cat > "$dist_dir/release-notes.md" <<EOF
# $custom_tag

Syncthing $upstream_tag with the local patches applied.

Builds:
$(format_build_specs)

Patches:
$(printf -- '- %s\n' "${patch_files[@]}")

Patch behavior:
- Root-level .stignore syncs like regular folder content.
- .stfolder and .stversions stay protected as Syncthing internals.
- The web GUI footer includes "It syncs .stignore now!" as a custom build marker.
EOF

	(
		cd "$dist_dir"
		if command -v sha256sum >/dev/null 2>&1; then
			sha256sum ./* > SHA256SUMS
		else
			shasum -a 256 ./* > SHA256SUMS
		fi
	)
}

build_one() {
	local custom_tag="$1"
	local spec="$2"
	local goos
	local goarch
	local kind
	local cgo_enabled

	IFS=/ read -r goos goarch kind cgo_enabled <<< "$spec"
	[[ -n "$goos" && -n "$goarch" && -n "$kind" ]] || die "invalid build spec: $spec"
	cgo_enabled="${cgo_enabled:-$default_cgo_enabled}"

	log "Building $target for $goos/$goarch as $kind with CGO_ENABLED=$cgo_enabled"

	case "$kind" in
		tar|zip)
			local archive
			archive="$(CGO_ENABLED="$cgo_enabled" go run build.go -version "$custom_tag" -goos "$goos" -goarch "$goarch" "$kind" "$target" | tail -n 1)"
			if [[ "$goos" == "darwin" && "$sign_darwin" == "1" ]]; then
				sign_and_validate_darwin_archive "$archive" "$kind"
			fi
			mv "$archive" "$dist_dir/"
			;;
		binary)
			CGO_ENABLED="$cgo_enabled" go run build.go -version "$custom_tag" -goos "$goos" -goarch "$goarch" -build-out "$dist_dir/$target-$goos-$goarch" build "$target"
			if [[ "$goos" == "darwin" && "$sign_darwin" == "1" ]]; then
				sign_and_validate_darwin_binary "$dist_dir/$target-$goos-$goarch"
			fi
			;;
		*)
			die "unknown build archive kind in $spec"
			;;
	esac
}

find_release_binary() {
	local root="$1"
	local candidate

	while IFS= read -r candidate; do
		if [[ -x "$candidate" ]]; then
			printf '%s\n' "$candidate"
			return
		fi
	done < <(find "$root" -type f -name "$target")

	die "could not find executable $target in $root"
}

sign_and_validate_darwin_archive() {
	local archive="$1"
	local kind="$2"
	local tmp
	local archive_abs
	local binary

	[[ -n "$codesign_identity" ]] || die "CUSTOM_RELEASE_CODESIGN_IDENTITY is required for darwin builds"

	tmp="$(mktemp -d)"
	archive_abs="$(cd "$(dirname "$archive")" && pwd -P)/$(basename "$archive")"
	case "$kind" in
		zip)
			unzip -q "$archive_abs" -d "$tmp"
			;;
		tar)
			tar -xf "$archive_abs" -C "$tmp"
			;;
		*)
			die "cannot sign archive kind $kind"
			;;
	esac

	binary="$(find_release_binary "$tmp")"
	sign_and_validate_darwin_binary "$binary"

	rm -f "$archive_abs"
	case "$kind" in
		zip)
			(
				cd "$tmp"
				zip -qr "$archive_abs" .
			)
			;;
		tar)
			(
				cd "$tmp"
				tar -czf "$archive_abs" .
			)
			;;
	esac
	rm -rf "$tmp"
}

sign_and_validate_darwin_binary() {
	local binary="$1"
	local version_output
	local codesign_details
	local codesign_args

	[[ -n "$codesign_identity" ]] || die "CUSTOM_RELEASE_CODESIGN_IDENTITY is required for darwin builds"

	codesign_args=(--force --sign "$codesign_identity")
	if [[ -n "${CUSTOM_RELEASE_KEYCHAIN_PATH:-}" ]]; then
		if [[ -n "${CUSTOM_RELEASE_KEYCHAIN_PASSWORD:-}" ]]; then
			security unlock-keychain -p "$CUSTOM_RELEASE_KEYCHAIN_PASSWORD" "$CUSTOM_RELEASE_KEYCHAIN_PATH"
		fi
		security find-identity -v -p codesigning "$CUSTOM_RELEASE_KEYCHAIN_PATH"
		security find-identity -v -p codesigning
		codesign_args+=(--keychain "$CUSTOM_RELEASE_KEYCHAIN_PATH")
	fi
	codesign_args+=(--options runtime --timestamp)
	codesign "${codesign_args[@]}" "$binary"

	version_output="$("$binary" --version)"
	if [[ "$version_output" == *modernc-sqlite* ]]; then
		die "darwin build unexpectedly reports [modernc-sqlite]: $version_output"
	fi

	codesign --verify --strict --verbose=2 "$binary"
	codesign_details="$(codesign -dv --verbose=4 "$binary" 2>&1)"
	if [[ "$codesign_team_id" == "NG5W75WE8U" && "$codesign_details" != *"TeamIdentifier=NG5W75WE8U"* ]]; then
		printf '%s\n' "$codesign_details" >&2
		die "darwin build is not signed by TeamIdentifier=NG5W75WE8U"
	fi
	if [[ "$codesign_details" != *"TeamIdentifier=$codesign_team_id"* ]]; then
		printf '%s\n' "$codesign_details" >&2
		die "darwin build is not signed by TeamIdentifier=$codesign_team_id"
	fi
	if [[ "$require_gatekeeper_assessment" == "1" ]]; then
		spctl -a -vv --type execute "$binary"
	else
		log "Skipping Gatekeeper assessment because CUSTOM_RELEASE_REQUIRE_GATEKEEPER_ASSESSMENT=$require_gatekeeper_assessment"
	fi
}

push_refs() {
	local branch="$1"
	local custom_tag="$2"

	if [[ "$push_release" != "1" ]]; then
		log "Skipping push because CUSTOM_RELEASE_PUSH=$push_release"
		return
	fi

	if [[ "$push_branch" == "1" ]]; then
		git push "$push_remote" "$branch"
	else
		log "Skipping release branch push because CUSTOM_RELEASE_PUSH_BRANCH=$push_branch"
	fi
	git push "$push_remote" "$custom_tag"
}

publish_release() {
	local custom_tag="$1"

	if [[ "$publish_gitea_release" != "1" ]]; then
		log "Skipping Gitea release publishing because CUSTOM_RELEASE_CREATE_GITEA_RELEASE=$publish_gitea_release"
		return
	fi

	command -v tea >/dev/null 2>&1 || die "tea is required for Gitea release publishing"

	local args=(releases create "$custom_tag" --title "$custom_tag" --note-file "$dist_dir/release-notes.md")
	if [[ -n "$tea_repo" ]]; then
		args+=(--repo "$tea_repo")
	else
		args+=(--remote "$push_remote")
	fi

	local asset
	for asset in "$dist_dir"/*; do
		[[ -f "$asset" ]] || continue
		[[ "$(basename "$asset")" == "release-notes.md" ]] && continue
		args+=(--asset "$asset")
	done

	tea "${args[@]}"
}

main() {
	require_clean_worktree

	if [[ -z "$upstream_tag" ]]; then
		upstream_tag="$(latest_stable_tag)"
	fi
	[[ -n "$upstream_tag" ]] || die "could not determine latest upstream tag"

	local custom_tag="${upstream_tag}-${suffix}"
	local branch="${branch_prefix}/${upstream_tag#v}-${suffix}"

	if tag_exists "$custom_tag" && [[ "$force" != "1" ]]; then
		log "Custom release $custom_tag already exists; nothing to do."
		return
	fi

	patch_tmp_dir="$(mktemp -d)"
	trap 'rm -rf "$patch_tmp_dir"' EXIT

	copy_patches_to_temp "$patch_tmp_dir"
	fetch_upstream_tag "$upstream_tag"
	delete_local_tag_if_forced "$custom_tag"
	create_release_commit "$upstream_tag" "$custom_tag" "$branch" "$patch_tmp_dir"
	test_release
	build_release "$custom_tag"
	push_refs "$branch" "$custom_tag"
	publish_release "$custom_tag"

	log "Built custom release $custom_tag from upstream $upstream_tag"
	log "Artifacts are in $dist_dir/"
}

main "$@"
