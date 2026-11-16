#!/usr/bin/env python3
"""Verify remote release bytes before publication, including already published tags."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def verify(candidate, release, archives_only=False):
	candidate = Path(candidate)
	metadata = json.loads((candidate / 'candidate.json').read_text())
	expected = set(metadata['assets'])
	if not archives_only:
		expected.add('SHA256SUMS')
	assets = [a for a in release['assets'] if not archives_only or a['name'] != 'SHA256SUMS']
	assert len(assets) == len(expected) and {a['name'] for a in assets} == expected
	assert release['tag_name'] == metadata['tag']
	assert release['prerelease'] == (metadata['channel'] == 'nightly')
	prefix = f'https://github.com/felixfoertsch/syncthing/releases/download/{metadata["tag"]}/'
	for asset in assets:
		local = candidate / asset['name']
		if release.get('draft'):
			assert asset['url'] == f'https://api.github.com/repos/felixfoertsch/syncthing/releases/assets/{asset["id"]}'
		else:
			assert asset['browser_download_url'] == prefix + asset['name']
		assert asset['size'] == local.stat().st_size
		assert asset['digest'] == 'sha256:' + hashlib.sha256(local.read_bytes()).hexdigest()


if __name__ == '__main__':
	# GitHub tag endpoint omits drafts; authenticated release listing includes them.
	pages = json.loads(subprocess.check_output(['gh', 'api', '--paginate', '--slurp', 'repos/felixfoertsch/syncthing/releases?per_page=100']))
	matches = [release for page in pages for release in page if release['tag_name'] == sys.argv[2]]
	assert len(matches) == 1
	assert len(sys.argv) == 3 or (len(sys.argv) == 4 and sys.argv[3] == 'archives')
	verify(sys.argv[1], matches[0], archives_only=len(sys.argv) == 4)
