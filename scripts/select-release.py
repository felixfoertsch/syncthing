#!/usr/bin/env python3
"""Skip only a complete signed publication of exact reconstructed source."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def select(channel, upstream_tag, source, releases, resolve, verify, latest, main, force=False):
	if force:
		return ''
	pattern = re.escape(upstream_tag) + r'-(\d{4}\.\d{2}\.\d{2}\.[1-9]\d*)'
	for release in releases:
		match = re.fullmatch(pattern, release['tag_name'])
		if not match or release['prerelease'] != (channel == 'nightly'):
			continue
		if resolve(release['tag_name']) != source:
			continue
		if release['draft']:
			return match[1]
		if verify(release) and (latest == release['tag_name'] if channel == 'stable' else main == source):
			return None
	return ''


def run(*args, **kwargs):
	return subprocess.check_output(args, text=True, **kwargs).strip()


def load(name):
	spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


def verify(release, source, upstream, upstream_tag, channel):
	if release['draft']:
		return False
	with tempfile.TemporaryDirectory() as tmp:
		p = Path(tmp)
		tag = release['tag_name']
		expected = {f'syncthing-{platform}-{tag}{extension}' for platform, extension in
			(('macos-arm64', '.zip'), ('linux-amd64', '.tar.gz'), ('linux-arm64', '.tar.gz'))}
		if len(release['assets']) != 4 or {a['name'] for a in release['assets']} != expected | {'SHA256SUMS'}:
			return False
		# Transport/auth errors fail closed, not inferred absence.
		subprocess.run(['gh', 'release', 'download', tag, '--repo', 'felixfoertsch/syncthing', '--dir', tmp], check=True)
		metadata = dict(control=os.environ['CONTROL'], channel=channel, upstream_tag=upstream_tag,
			upstream=upstream, source=source, tag=tag, main=source,
			assets={name: hashlib.sha256((p / name).read_bytes()).hexdigest() for name in expected})
		(p / 'candidate.json').write_text(json.dumps(metadata))
		for name in ('source.bundle', 'release-notes.md'):
			(p / name).touch()
		load('verify-release').verify(p, release)
		checksums = {}
		for line in (p / 'SHA256SUMS').read_text().splitlines():
			digest, name = line.split(maxsplit=1)
			name = name.removeprefix('./')
			assert name not in checksums
			checksums[name] = digest
		assert checksums == metadata['assets']
		candidate = load('verify-candidate')
		candidate.check(p, os.environ['CONTROL'], channel)
		candidate.verify_build_info(p, metadata)
		name = next(n for n in expected if n.endswith('.zip'))
		with zipfile.ZipFile(p / name) as z:
			binary = p / 'syncthing'
			binary.write_bytes(z.read(name.removesuffix('.zip') + '/syncthing'))
		subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
		details = subprocess.run(['codesign', '-dv', '--verbose=4', str(binary)], capture_output=True, text=True, check=True)
		assert 'TeamIdentifier=NG5W75WE8U' in details.stderr
		return True


def main():
	channel = os.environ['CHANNEL']
	assert run('git', 'rev-parse', 'HEAD') == os.environ['CONTROL']
	# Explicit version/suffix/rebuild requests retain normal build behavior.
	if os.environ.get('CUSTOM_RELEASE_SUFFIX') or os.environ.get('CUSTOM_RELEASE_REBUILD_EXISTING') == '1':
		print('build')
		return
	with tempfile.TemporaryDirectory() as tmp:
		subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(ROOT), tmp], check=True)
		# Derive source through same deterministic replay as trusted publisher.
		script = '''set -euo pipefail
source "$ROOT/scripts/update-custom-release.sh"
resolve_upstream_tag
fetch_upstream_tag "$upstream_tag"
printf '%s\\n%s\\n' "$upstream_tag" "$upstream_ref" > "$SELECTION"
prefix="$ROOT/patches/README-prefix.md"
patches=("$ROOT"/patches/[0-9]*.patch)
git checkout --detach "$upstream_ref"
apply_patch_queue "${patches[@]}"
commit_reconstruction "$upstream_ref" "$prefix"
'''
		# Prevent derived fields becoming tracked source content.
		env = dict(os.environ, ROOT=str(ROOT), CUSTOM_RELEASE_CHANNEL=channel, CUSTOM_RELEASE_SUFFIX='2000.01.01.1')
		env['SELECTION'] = str(Path(tmp).parent / (Path(tmp).name + '-selection'))
		try:
			subprocess.run(['bash', '-c', script], cwd=tmp, env=env, check=True, stdout=sys.stderr)
			upstream_tag, upstream = Path(env['SELECTION']).read_text().splitlines()
		finally:
			Path(env['SELECTION']).unlink(missing_ok=True)
		source = run('git', 'rev-parse', 'HEAD', cwd=tmp)
		pages = json.loads(run('gh', 'api', '--paginate', '--slurp', 'repos/felixfoertsch/syncthing/releases?per_page=100'))
		releases = [r for page in pages for r in page]
		# Latest stable is required delivery pointer; missing endpoint cannot prove skip.
		latest = run('gh', 'release', 'view', '--repo', 'felixfoertsch/syncthing', '--json', 'tagName', '--jq', '.tagName') if channel == 'stable' and any(not r['draft'] and not r['prerelease'] for r in releases) else ''
		main_sha = run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0]
		def resolve(tag):
			refs = run('git', 'ls-remote', 'origin', 'refs/tags/' + tag, 'refs/tags/' + tag + '^{}').splitlines()
			return refs[-1].split()[0] if refs else ''
		result = select(channel, upstream_tag, source, releases, resolve,
			lambda r: verify(r, source, upstream, upstream_tag, channel), latest, main_sha,
			os.environ.get('CUSTOM_RELEASE_FORCE') == '1')
		if result is None:
			fresh = dict(os.environ, CUSTOM_RELEASE_AUTOMATION_REF=os.environ['CONTROL'],
				CUSTOM_RELEASE_CHANNEL=channel, CUSTOM_RELEASE_UPSTREAM_TAG=upstream_tag,
				CUSTOM_RELEASE_UPSTREAM_REF=upstream)
			subprocess.run(['bash', str(ROOT / 'scripts/check-freshness.sh')], env=fresh, check=True)
			if channel == 'nightly':
				assert run('git', 'ls-remote', 'origin', 'refs/heads/main').split()[0] == source
			else:
				assert run('gh', 'release', 'view', '--repo', 'felixfoertsch/syncthing', '--json', 'tagName', '--jq', '.tagName') == latest
		print('skip' if result is None else 'build:' + result)


if __name__ == '__main__':
	main()
