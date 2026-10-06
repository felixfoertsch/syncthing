#!/usr/bin/env bash
set -euo pipefail

upstream_url="${SYNC_UPSTREAM_URL:-https://github.com/syncthing/syncthing.git}"
remote="${SYNC_REMOTE:-origin}"
main_branch="${SYNC_MAIN_BRANCH:-main}"
tmp=""

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

cleanup() {
	[[ -z "$tmp" ]] || rm -rf "$tmp"
}

# Disable inherited workflows repository-wide, including old review branches.
is_github_actions() {
	[[ "${GITHUB_ACTIONS:-}" == "true" && "${GITHUB_SERVER_URL:-}" == "https://github.com" ]]
}

enforce_github_workflow_policy() {
	[[ -n "${GH_TOKEN:-}" && -n "${GITHUB_REPOSITORY:-}" ]] || die "GitHub workflow policy requires GH_TOKEN and GITHUB_REPOSITORY"
	local obsolete
	local id
	local path
	local selector='.workflows[] | select(.path | startswith(".github/workflows/")) | select(.path != ".github/workflows/custom-release.yml" and .state == "active") | [.id, .path] | @tsv'
	obsolete="$(gh api --paginate "repos/$GITHUB_REPOSITORY/actions/workflows?per_page=100" --jq "$selector")" || die "could not inspect workflow policy"
	while IFS=$'\t' read -r id path; do
		[[ -n "$id" ]] || continue
		[[ "$id" =~ ^[0-9]+$ ]] || die "invalid workflow ID: $id"
		printf 'Disabling unrelated workflow: %s\n' "$path"
		gh api --method PUT "repos/$GITHUB_REPOSITORY/actions/workflows/$id/disable" || die "could not disable $path"
	done <<< "$obsolete"
	obsolete="$(gh api --paginate "repos/$GITHUB_REPOSITORY/actions/workflows?per_page=100" --jq "$selector")" || die "could not verify workflow policy"
	[[ -z "$obsolete" ]] || die "unrelated workflows are still active: $obsolete"
	printf 'Workflow policy verified: only custom-release.yml is allowed to run.\n'
}

main() {
	[[ -z "$(git status --porcelain)" ]] || die "working tree has uncommitted changes"

	if is_github_actions; then
		enforce_github_workflow_policy
	fi

	local current_main
	local new_upstream
	local upstream_date
	# Checkout may be on automation or detached; lease the published main, not HEAD.
	current_main="$(git rev-parse "refs/remotes/$remote/$main_branch")"

	git fetch "$upstream_url" "refs/heads/main:refs/remotes/official/main"
	new_upstream="$(git rev-parse refs/remotes/official/main)"
	# Always replay: automation patches may change even when upstream does not.
	upstream_date="$(git show -s --format=%cI "$new_upstream")"

	tmp="$(mktemp -d)"
	trap cleanup EXIT
	mkdir -p "$tmp/.gitea/workflows" "$tmp/.github/workflows" "$tmp/patches" "$tmp/scripts/tests"
	cp patches/*.patch patches/README.md "$tmp/patches/"
	cp scripts/update-custom-release.sh scripts/sync-upstream.sh "$tmp/scripts/"
	cp scripts/tests/test-custom-release-macos-runner.bats scripts/tests/test-custom-release.py "$tmp/scripts/tests/"

	git checkout -B "$main_branch" "$new_upstream"
	# Recreate only fork-owned workflows; an upstream update must never restore CI.
	rm -rf .github/workflows .gitea/workflows
	cp -R "$tmp/patches" "$tmp/scripts" .
	git apply patches/sync-stignore.patch patches/webui-build-marker.patch
	git add -A
	# This workflow continues to build; its PAT-authenticated push must not start another run.
	GIT_AUTHOR_DATE="$upstream_date" GIT_COMMITTER_DATE="$upstream_date" \
		git -c user.name="Syncthing .stignore Fork" \
		-c user.email="actions@felixfoertsch.de" \
		commit -m "apply stignore synchronization patch [skip ci]"
	if [[ "$(git rev-parse HEAD)" == "$current_main" ]]; then
		printf 'Upstream is current and patch replay is unchanged at %s.\n' "$new_upstream"
		return
	fi
	git push --force-with-lease="$main_branch:$current_main" "$remote" "$main_branch"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	main "$@"
fi
