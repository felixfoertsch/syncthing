#!/usr/bin/env python3
"""Trusted old-control reconstruction and atomic promotion; never run candidate code."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

# Explicit files, not directories: upstream may own other scripts tomorrow.
OWNED = (
	'.github/workflows/custom-release.yml',
	'patches/0001-sync-stignore.patch', 'patches/0002-webui-build-marker.patch',
	'patches/README-prefix.md', 'patches/README.md',
	'scripts/build-candidate.sh', 'scripts/check-freshness.sh',
	'scripts/publish-source.sh', 'scripts/reconstruct.sh', 'scripts/reuse-draft.py',
	'scripts/select-release.py', 'scripts/sync-upstream.sh',
	'scripts/update-custom-release.sh', 'scripts/verify-candidate.py',
	'scripts/verify-release.py', 'scripts/verify-source.sh',
	'scripts/control-refresh.py', 'scripts/tests/test-control-refresh.py',
	'scripts/tests/test-custom-release-macos-runner.bats',
	'scripts/tests/test-custom-release.py', 'scripts/tests/test-publisher.py',
	'scripts/tests/test-unchanged-release.py',
)
UPSTREAM = os.environ.get('SYNC_UPSTREAM_URL', 'https://github.com/syncthing/syncthing.git')
# Only reviewed pre-migration lineage may lack recorded upstream metadata.
LEGACY_BASE = '4461a1ce354d3990660966ad70176e00246adb61'
IDENTITY = {'GIT_AUTHOR_NAME': 'Syncthing patch queue', 'GIT_AUTHOR_EMAIL': 'actions@felixfoertsch.de',
	'GIT_COMMITTER_NAME': 'Syncthing patch queue', 'GIT_COMMITTER_EMAIL': 'actions@felixfoertsch.de'}


def run(*args, cwd=None, env=None, data=None):
	return subprocess.check_output(args, cwd=cwd, env=env, input=data).decode().strip()


def git(*args, cwd=None, env=None, data=None):
	return run('git', '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', *args,
		cwd=cwd, env=env, data=data)


def require(condition, message):
	if not condition:
		raise RuntimeError(message)


def sha(value):
	require(re.fullmatch('[0-9a-f]{40}', value), 'invalid commit SHA')
	return value


def head(url, ref):
	lines = git('ls-remote', url, ref).splitlines()
	require(len(lines) == 1 and lines[0].split()[1] == ref, 'missing or ambiguous ref: ' + ref)
	return sha(lines[0].split()[0])


def upstream():
	lines = git('ls-remote', '--symref', UPSTREAM, 'HEAD').splitlines()
	refs = [line.split()[1] for line in lines if line.startswith('ref: ')]
	require(len(refs) == 1 and refs[0].startswith('refs/heads/'), 'upstream default unavailable')
	return refs[0], head(UPSTREAM, refs[0])


def clean_env():
	# Reconstruction gets neither job token nor inherited checkout credential helpers.
	env = {k: v for k, v in os.environ.items() if not k.startswith(('GH_', 'GITHUB_', 'GIT_', 'DEVELOPER_ID_'))}
	env.update(IDENTITY, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1', GIT_TERMINAL_PROMPT='0')
	return env


def tree(repo, revision, path=None):
	return git('rev-parse', revision + (':' + path if path else '^{tree}'), cwd=repo)


def paths(repo, revision):
	return set(subprocess.check_output(['git', 'ls-tree', '-rz', '--name-only', revision], cwd=repo).decode().split('\0')) - {''}


def reconstruct(repo, control, source, owned, trusted, env):
	upstream_paths = paths(repo, source)
	for path in owned:
		require(not any(p == path or p.startswith(path + '/') or path.startswith(p + '/') for p in upstream_paths),
			'upstream control ownership collision: ' + path)
	git('checkout', '--detach', '--force', source, cwd=repo, env=env)
	# Existing shell seam supplies strict forward/reverse replay and README consolidation.
	script = 'set -euo pipefail\ndie() { printf "%s\\n" "$*" >&2; exit 1; }\nsource "$1/scripts/reconstruct.sh"\napply_patch_queue "$1"/patches/[0-9]*.patch\ncommit_reconstruction "$2" "$1/patches/README-prefix.md"\n'
	run('bash', '-c', script, 'reconstruct', str(trusted), source, cwd=repo, env=env)
	git('checkout', control, '--', *owned, cwd=repo, env=env)
	git('add', '-A', cwd=repo, env=env)
	return git('write-tree', cwd=repo, env=env)


def candidate(control, selected, destination):
	"""Prove old source ownership, then replay unchanged queue onto selected upstream."""
	sha(control); sha(selected)
	env = clean_env()
	with tempfile.TemporaryDirectory() as tmp:
		tmp = Path(tmp)
		repo, trusted = tmp / 'repo', tmp / 'trusted'
		git('clone', '--quiet', '--no-local', '--no-checkout', str(Path.cwd()), str(repo), env=env)
		git('fetch', '--no-tags', UPSTREAM, selected, cwd=repo, env=env)
		owned = [p for p in OWNED if p in paths(repo, control)]
		require(set(OWNED) <= paths(repo, control), 'incomplete control overlay')
		trusted.mkdir()
		for path in owned:
			file = trusted / path
			file.parent.mkdir(parents=True, exist_ok=True)
			file.write_bytes(subprocess.check_output(['git', 'show', control + ':' + path], cwd=repo))
		metadata_path = 'scripts/control-upstream.json'
		require(metadata_path not in paths(repo, selected), 'upstream control metadata collision')
		previous = None
		if metadata_path in paths(repo, control):
			previous = json.loads(git('show', control + ':' + metadata_path, cwd=repo, env=env))
			require(previous['repository'] == UPSTREAM, 'upstream repository changed')
			current_ref, current_head = upstream()
			require(previous['default_ref'] == current_ref, 'upstream default ref changed')
			base = sha(previous['upstream'])
			git('merge-base', '--is-ancestor', base, selected, cwd=repo, env=env)
		else:
			# Initial migration only: full reconstructed-tree equality classifies every delta.
			base = git('merge-base', control, selected, cwd=repo, env=env)
			require(base == LEGACY_BASE, 'missing upstream metadata outside reviewed migration lineage')
		old_tree = reconstruct(repo, control, base, owned, trusted, env)
		if previous:
			(repo / metadata_path).write_text(json.dumps(previous, sort_keys=True) + '\n')
			git('add', metadata_path, cwd=repo, env=env)
			old_tree = git('write-tree', cwd=repo, env=env)
		require(old_tree == tree(repo, control), 'unknown customization outside accepted queue/control overlay')
		new_tree = reconstruct(repo, control, selected, owned, trusted, env)
		ref, _ = upstream()
		(repo / metadata_path).write_text(json.dumps(dict(repository=UPSTREAM, default_ref=ref, upstream=selected), sort_keys=True) + '\n')
		git('add', metadata_path, cwd=repo, env=env)
		new_tree = git('write-tree', cwd=repo, env=env)
		ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', selected, control], cwd=repo, env=env).returncode == 0
		if new_tree == tree(repo, control) and ancestor:
			result = control
		else:
			date = git('show', '-s', '--format=%cI', selected, cwd=repo, env=env)
			env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
			result = git('commit-tree', new_tree, '-p', selected, cwd=repo, env=env,
				data=b'refresh upstream source, preserve accepted queue and trusted control\n')
		git('update-ref', 'refs/heads/refreshed-control', result, cwd=repo, env=env)
		require(tree(repo, result, '.github/workflows') == tree(repo, control, '.github/workflows'), 'workflow tree changed')
		git('bundle', 'create', str(destination), 'refs/heads/refreshed-control', cwd=repo, env=env)
		return result


def verify_bundle(bundle, revision):
	with tempfile.TemporaryDirectory() as tmp:
		git('init', '--quiet', '--bare', tmp)
		git('bundle', 'verify', str(bundle), cwd=tmp)
		git('fetch', '--quiet', str(bundle), revision, cwd=tmp)
		require(git('rev-parse', 'FETCH_HEAD', cwd=tmp) == revision, 'backup restore mismatch')
		git('fsck', '--full', '--no-dangling', cwd=tmp)


def digest(path):
	with path.open('rb') as stream:
		hash_value = hashlib.sha256()
		for block in iter(lambda: stream.read(1024 * 1024), b''):
			hash_value.update(block)
		return hash_value.hexdigest()


def verify_backup(directory, control):
	manifest = json.loads((directory / 'backup.json').read_text())
	require(manifest == {'control': control, 'sha256': digest(directory / 'old-control.bundle')}, 'backup digest/identity mismatch')
	verify_bundle(directory / 'old-control.bundle', control)


def prepare(directory):
	control = sha(os.environ['CONTROL'])
	require(git('rev-parse', 'HEAD') == control, 'checkout differs from exact old control')
	ref, selected = upstream()
	directory.mkdir(parents=True, exist_ok=False)
	result = candidate(control, selected, directory / 'candidate.bundle')
	(directory / 'candidate.json').write_text(json.dumps(dict(control=control, upstream=selected, upstream_ref=ref, result=result), sort_keys=True))
	if result != control:
		git('bundle', 'create', str(directory / 'old-control.bundle'), 'HEAD')
		(directory / 'backup.json').write_text(json.dumps({'control': control, 'sha256': digest(directory / 'old-control.bundle')}, sort_keys=True))
		verify_backup(directory, control)
	return result


def dispatch(result):
	payload = {'ref': 'patch-queue', 'inputs': {'expected_control': result,
		'rebuild': os.environ.get('REFRESH_REBUILD', 'false'),
		'upstream_tag': os.environ.get('REFRESH_UPSTREAM_TAG', ''),
		'suffix': os.environ.get('REFRESH_SUFFIX', '')}}
	run('gh', 'api', '--method', 'POST', 'repos/' + os.environ['GITHUB_REPOSITORY'] + '/actions/workflows/custom-release.yml/dispatches',
		'--input', '-', data=json.dumps(payload).encode())


def promote(directory):
	control = sha(os.environ['CONTROL'])
	require(git('rev-parse', 'HEAD') == control, 'promoter checkout differs from old control')
	metadata = json.loads((directory / 'candidate.json').read_text())
	require(set(metadata) == {'control', 'upstream', 'upstream_ref', 'result'} and metadata['control'] == control, 'candidate identity mismatch')
	ref, selected = upstream()
	require((ref, selected) == (metadata['upstream_ref'], metadata['upstream']), 'upstream changed')
	with tempfile.TemporaryDirectory() as tmp:
		bundle = Path(tmp) / 'verified.bundle'
		result = candidate(control, selected, bundle)
		require(result == metadata['result'], 'candidate differs from trusted independent reconstruction')
		if result == control:
			require(upstream() == (ref, selected), 'upstream changed before no-op')
			require(head('origin', 'refs/heads/patch-queue') == control, 'control changed before no-op')
			return result
		verify_backup(directory, control)  # Downloaded artifact, not original workspace bytes.
		archive = 'refs/tags/archive/patch-queue/' + control
		existing = git('ls-remote', 'origin', archive)
		require(not existing or existing == control + '\t' + archive, 'archive tag is not exact lightweight old head')
		git('fetch', '--no-tags', str(bundle), 'refs/heads/refreshed-control')
		require(upstream() == (ref, selected), 'upstream changed before promotion')
		require(head('origin', 'refs/heads/patch-queue') == control, 'control changed before promotion')
		args = ['push', '--atomic', '--force-with-lease=refs/heads/patch-queue:' + control]
		if not existing:
			args += ['--force-with-lease=' + archive + ':']
		args += ['origin', result + ':refs/heads/patch-queue']
		if not existing:
			args += [control + ':' + archive]
		env = os.environ.copy()
		token = env['GH_TOKEN']
		require(bool(token), 'missing built-in job token')
		env.update(GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
			GIT_CONFIG_VALUE_0='AUTHORIZATION: basic ' + base64.b64encode(('x-access-token:' + token).encode()).decode(),
			GIT_CONFIG_KEY_1='core.hooksPath', GIT_CONFIG_VALUE_1=os.devnull)
		git(*args, env=env)
		require(head('origin', 'refs/heads/patch-queue') == result and head('origin', archive) == control, 'post-push verification failed')
		dispatch(result)
		return result


if __name__ == '__main__':
	command, directory = sys.argv[1:]
	print({'prepare': prepare, 'promote': promote}[command](Path(directory).resolve()))
