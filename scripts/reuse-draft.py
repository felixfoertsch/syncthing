#!/usr/bin/env python3
"""Retain verified immutable draft archives; newly built bytes fill gaps only."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location('candidate', Path(__file__).with_name('verify-candidate.py'))
candidate_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(candidate_module)


def reuse(candidate, release, download):
	p = Path(candidate)
	metadata = json.loads((p / 'candidate.json').read_text())
	assert release['draft'] and release['tag_name'] == metadata['tag']
	assert release['prerelease'] == (metadata['channel'] == 'nightly')
	assets = release['assets']
	assert len({a['name'] for a in assets}) == len(assets)
	names = {a['name'] for a in assets}
	assert names <= set(metadata['assets']) | {'SHA256SUMS'}
	if 'SHA256SUMS' in names and not set(metadata['assets']) <= names:
		raise RuntimeError('Legacy checksum-first draft has missing archives. Restore original missing bytes from retained verified candidate, or request rebuild=true with a new release identity. Never overwrite existing draft assets.')
	with tempfile.TemporaryDirectory() as tmp:
		staged = Path(tmp) / 'candidate'
		shutil.copytree(p, staged)
		for asset in assets:
			name = asset['name']
			assert asset['url'] == f'https://api.github.com/repos/felixfoertsch/syncthing/releases/assets/{asset["id"]}'
			data = download(asset)
			assert len(data) == asset['size']
			assert asset['digest'] == 'sha256:' + hashlib.sha256(data).hexdigest()
			(staged / name).write_bytes(data)
			if name != 'SHA256SUMS':
				metadata['assets'][name] = hashlib.sha256(data).hexdigest()
		(staged / 'candidate.json').write_text(json.dumps(metadata, sort_keys=True))
		candidate_module.check(staged, metadata['control'], metadata['channel'])
		candidate_module.verify_build_info(staged, metadata)
		darwin = next(name for name in metadata['assets'] if name.endswith('.zip'))
		reused_darwin = any(a['name'] == darwin for a in assets)
		if reused_darwin:
			candidate_module.verify_signature(staged / darwin)
		# Commit verified bytes only. Publisher's existing cmp protects SHA256SUMS too.
		for asset in assets:
			if asset['name'] != 'SHA256SUMS':
				shutil.copyfile(staged / asset['name'], p / asset['name'])
		(p / 'candidate.json').write_text(json.dumps(metadata, sort_keys=True))
		return reused_darwin


if __name__ == '__main__':
	p = Path(sys.argv[1])
	metadata = json.loads((p / 'candidate.json').read_text())
	pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp', 'repos/felixfoertsch/syncthing/releases?per_page=100']))
	matches = [r for page in pages for r in page if r['tag_name'] == metadata['tag']]
	assert len(matches) <= 1
	if matches and matches[0]['draft']:
		def download(asset):
			return subprocess.check_output(['gh', 'api', '-H', 'Accept: application/octet-stream', asset['url']])
		if reuse(p, matches[0], download):
			with open(os.environ['GITHUB_ENV'], 'a') as output:
				output.write('CUSTOM_RELEASE_REUSE_DARWIN=1\n')
