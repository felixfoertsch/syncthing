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

# The upstream branch is a byte-for-byte mirror, including upstream workflows.
# Disable inherited workflows repository-wide (also covers old review branches)
# and use GITHUB_TOKEN for mirror pushes so they cannot spawn new CI runs.
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

only_custom_workflows() {
	local unexpected
	unexpected="$(git ls-tree -r --name-only "refs/heads/$main_branch" -- .github/workflows .gitea/workflows |
		awk '$0 != ".github/workflows/custom-release.yml" && $0 != ".gitea/workflows/custom-release.yml"')" || return 1
	[[ -z "$unexpected" ]]
}

push_upstream_mirror() {
	local expected="$1"
	if is_github_actions; then
		[[ -n "${GH_TOKEN:-}" ]] || die "GitHub mirror push requires the workflow GITHUB_TOKEN"
		local auth
		auth="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\r\n')"
		printf '::add-mask::%s\n' "$auth"
		# Clear checkout's PAT header for this command only. Never fall back to
		# the PAT if this push fails: that would trigger upstream's full CI.
		GIT_CONFIG_COUNT=2 \
		GIT_CONFIG_KEY_0=http.https://github.com/.extraheader GIT_CONFIG_VALUE_0= \
		GIT_CONFIG_KEY_1=http.https://github.com/.extraheader GIT_CONFIG_VALUE_1="AUTHORIZATION: basic $auth" \
			git push --force-with-lease="$upstream_branch:$expected" "$remote" "$upstream_branch"
	else
		git push --force-with-lease="$upstream_branch:$expected" "$remote" "$upstream_branch"
	fi
}

main() {
	[[ -z "$(git status --porcelain)" ]] || die "working tree has uncommitted changes"

	if is_github_actions; then
		enforce_github_workflow_policy
	fi

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
	if [[ "$new_upstream" == "$current_upstream" && "$main_ahead_count" == "1" && "$main_parent" == "$current_upstream" ]] && only_custom_workflows; then
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
	cp scripts/tests/test-custom-release-macos-runner.bats scripts/tests/test-custom-release.py "$tmp/scripts/tests/"

	if [[ "$new_upstream" != "$current_upstream" ]]; then
		git branch -f "$upstream_branch" "$new_upstream"
		push_upstream_mirror "$current_upstream"
	fi

	git checkout -B "$main_branch" "$new_upstream"
	# Recreate only fork-owned workflows; an upstream update must never restore CI.
	rm -rf .github/workflows .gitea/workflows
	cp -R "$tmp/.gitea" "$tmp/.github" "$tmp/patches" "$tmp/scripts" .
	git apply patches/sync-stignore.patch patches/webui-build-marker.patch
	git add -A
	# This workflow continues to build; its PAT-authenticated push must not start another run.
	GIT_AUTHOR_DATE="$upstream_date" GIT_COMMITTER_DATE="$upstream_date" \
		git -c user.name="Syncthing .stignore Fork" \
		-c user.email="actions@felixfoertsch.de" \
		commit -m "apply stignore synchronization patch [skip ci]"
	git push --force-with-lease="$main_branch:$current_main" "$remote" "$main_branch"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	main "$@"
fi
