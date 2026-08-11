#!/usr/bin/env bash
set -euo pipefail

upstream_url="${SYNC_UPSTREAM_URL:-https://github.com/syncthing/syncthing.git}"
remote="${SYNC_REMOTE:-origin}"
upstream_branch="${SYNC_UPSTREAM_BRANCH:-upstream}"
main_branch="${SYNC_MAIN_BRANCH:-main}"
tmp=""

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

cleanup() {
	[[ -z "$tmp" ]] || rm -rf "$tmp"
}

main() {
	[[ -z "$(git status --porcelain)" ]] || die "working tree has uncommitted changes"

	local current_main
	local current_upstream
	local main_ahead_count
	local main_parent
	local new_upstream
	local upstream_date
	current_main="$(git rev-parse "refs/heads/$main_branch")"
	current_upstream="$(git rev-parse "refs/remotes/$remote/$upstream_branch")"
	main_ahead_count="$(git rev-list --count "$current_upstream..$current_main")"
	main_parent="$(git rev-parse "$current_main^" 2>/dev/null || true)"

	git fetch "$upstream_url" "refs/heads/main:refs/remotes/official/main"
	new_upstream="$(git rev-parse refs/remotes/official/main)"
	if [[ "$new_upstream" == "$current_upstream" && "$main_ahead_count" == "1" && "$main_parent" == "$current_upstream" ]]; then
		printf 'Upstream is current and main is exactly one commit ahead at %s.\n' "$new_upstream"
		return
	fi
	upstream_date="$(git show -s --format=%cI "$new_upstream")"

	tmp="$(mktemp -d)"
	trap cleanup EXIT
	mkdir -p "$tmp/.gitea/workflows" "$tmp/.github/workflows" "$tmp/patches" "$tmp/scripts/tests"
	cp .gitea/workflows/custom-release.yml "$tmp/.gitea/workflows/"
	cp .github/workflows/custom-release.yml "$tmp/.github/workflows/"
	cp patches/*.patch patches/README.md "$tmp/patches/"
	cp scripts/update-custom-release.sh scripts/sync-upstream.sh "$tmp/scripts/"
	cp scripts/tests/test-custom-release-macos-runner.bats "$tmp/scripts/tests/"

	if [[ "$new_upstream" != "$current_upstream" ]]; then
		git branch -f "$upstream_branch" "$new_upstream"
		git push --force-with-lease="$upstream_branch:$current_upstream" "$remote" "$upstream_branch"
	fi

	git checkout -B "$main_branch" "$new_upstream"
	cp -R "$tmp/.gitea" "$tmp/.github" "$tmp/patches" "$tmp/scripts" .
	git apply patches/sync-stignore.patch patches/webui-build-marker.patch
	git add -A
	GIT_AUTHOR_DATE="$upstream_date" GIT_COMMITTER_DATE="$upstream_date" \
		git -c user.name="Syncthing .stignore Fork" \
		-c user.email="actions@felixfoertsch.de" \
		commit -m "apply stignore synchronization patch"
	git push --force-with-lease="$main_branch:$current_main" "$remote" "$main_branch"
}

main "$@"
