#!/usr/bin/env bash
set -euo pipefail
bash scripts/check-freshness.sh
git fetch candidate/source.bundle "refs/tags/$RELEASE_TAG"
[[ "$(git rev-parse 'FETCH_HEAD^{commit}')" == "$CANDIDATE_SOURCE" ]] || exit 1
# Short-lived job token supplied only to trusted Git transport, never checkout config.
header="$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')"
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=http.https://github.com/.extraheader GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $header"
existing="$(git ls-remote origin "refs/tags/$RELEASE_TAG" | awk '{print $1}')"
if [[ -n "$existing" ]]; then
	git fetch origin "refs/tags/$RELEASE_TAG"
	[[ "$(git rev-parse 'FETCH_HEAD^{commit}')" == "$CANDIDATE_SOURCE" ]] || exit 1
else
	git -c user.name='Syncthing patch queue' -c user.email='actions@felixfoertsch.de' -c tag.gpgsign=false tag -a "$RELEASE_TAG" "$CANDIDATE_SOURCE" -m "Syncthing $CUSTOM_RELEASE_UPSTREAM_TAG; patch-queue $CUSTOM_RELEASE_AUTOMATION_REF"
	git push --force-with-lease="refs/tags/$RELEASE_TAG:" origin "refs/tags/$RELEASE_TAG"
fi
if [[ "$CUSTOM_RELEASE_CHANNEL" == nightly ]]; then
	bash scripts/check-freshness.sh
	[[ "$(git ls-remote origin refs/heads/main | awk '{print $1}')" == "$EXPECTED_MAIN" ]] || exit 1
	git push --force-with-lease="refs/heads/main:$EXPECTED_MAIN" origin "$CANDIDATE_SOURCE:refs/heads/main"
fi
