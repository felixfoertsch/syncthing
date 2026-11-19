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
	# Lease published main, not control checkout HEAD.
	current_main="$(git rev-parse "refs/remotes/$remote/$main_branch")"

	source scripts/reconstruct.sh
	local upstream_default
	upstream_default="$(upstream_default_ref)"
	git fetch "$upstream_url" "$upstream_default:refs/remotes/official/main"
	new_upstream="$(git rev-parse refs/remotes/official/main)"
	# Replay queue even when upstream has not changed.

	tmp="$(mktemp -d)"
	trap cleanup EXIT
	mkdir -p "$tmp/patches"
	cp patches/[0-9]*.patch patches/README-prefix.md "$tmp/patches/"

	git checkout -B "$main_branch" "$new_upstream"
	apply_patch_queue "$tmp"/patches/[0-9]*.patch
	commit_reconstruction "$new_upstream" "$tmp/patches/README-prefix.md"
	if [[ -n "${CUSTOM_RELEASE_AUTOMATION_REF:-}" ]]; then
		[[ "$(git ls-remote "$remote" refs/heads/patch-queue | awk '{print $1}')" == "$CUSTOM_RELEASE_AUTOMATION_REF" ]] || die "automation changed during reconstruction"
	fi
	[[ "$(git ls-remote "$upstream_url" "$upstream_default" | awk '{print $1}')" == "$new_upstream" ]] || die "upstream changed during reconstruction"
	[[ "$(git ls-remote "$remote" "refs/heads/$main_branch" | awk '{print $1}')" == "$current_main" ]] || die "main changed during reconstruction"
	if [[ "$(git rev-parse HEAD)" == "$current_main" ]]; then
		printf 'Upstream is current and patch replay is unchanged at %s.\n' "$new_upstream"
		return
	fi
	if [[ "${SYNC_PUSH:-1}" == 1 ]]; then
		git push --force-with-lease="$main_branch:$current_main" "$remote" "$main_branch"
	fi
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	main "$@"
fi
