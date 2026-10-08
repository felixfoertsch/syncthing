#!/usr/bin/env bash
# Shared strict replay for generated main and both archive channels.
upstream_default_ref() {
	local ref
	ref="$(git ls-remote --symref "$upstream_url" HEAD | awk '$1 == "ref:" {print $2}')"
	[[ "$ref" == refs/heads/* ]] || die "could not resolve upstream default branch"
	printf '%s\n' "$ref"
}

apply_patch_queue() {
	local patch
	for patch in "$@"; do
		if git apply --check "$patch"; then
			git apply "$patch"
		elif git apply --reverse --check "$patch"; then
			printf 'Upstream absorbed exact patch: %s\n' "$(basename "$patch")"
		else
			die "patch conflict: $(basename "$patch")"
		fi
	done
}

commit_reconstruction() {
	local source="$1"
	local prefix="$2"
	local date
	date="$(git show -s --format=%cI "$source")"
	rm -rf .github/workflows .gitea/workflows
	cat "$prefix" README.md > README.fork.tmp
	# Consolidate root variant without changing either upstream document's bytes.
	if [[ -f README-Docker.md ]]; then
		printf '\n\n---\n\n<a id="docker-container-for-syncthing"></a>\n\n' >> README.fork.tmp
		cat README-Docker.md >> README.fork.tmp
		rm README-Docker.md
	fi
	mv README.fork.tmp README.md
	git add -A
	GIT_AUTHOR_DATE="$date" GIT_COMMITTER_DATE="$date" \
		git -c user.name='Syncthing patch queue' -c user.email='actions@felixfoertsch.de' \
		-c commit.gpgsign=false commit -m 'apply Syncthing patch queue [skip ci]'
}
