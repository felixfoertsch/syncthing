#!/usr/bin/env python3
"""Publisher trust boundary checks, no signing credentials required."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest

sys.dont_write_bytecode = True
import zipfile
import tarfile
import io

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('candidate', ROOT / 'scripts/verify-candidate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublisherTests(unittest.TestCase):
	def test_workflow_separates_untrusted_build_from_signing_and_write(self):
		text = (ROOT / '.github/workflows/custom-release.yml').read_text()
		build, publish = text.split('  publish:', 1)
		self.assertNotIn('contents: write', build)
		self.assertNotIn('secrets.', build)
		self.assertNotIn('actions: write', text)
		self.assertNotIn('sync-upstream.sh\n', text)
		self.assertEqual(text.count('ref: ${{ github.sha }}'), 2)
		self.assertEqual(text.count('persist-credentials: false'), 2)
		self.assertLess(publish.index('Verify candidate'), publish.index('Import Developer ID'))
		self.assertLess(publish.index('Sign verified archive'), publish.index('Publish verified source'))
		self.assertNotIn('go run', publish)
		self.assertNotIn('"$binary" --version', (ROOT / 'scripts/verify-candidate.py').read_text())

	def test_uploaded_asset_set_and_digests_fail_closed(self):
		spec = importlib.util.spec_from_file_location('release', ROOT / 'scripts/verify-release.py')
		release_module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(release_module)
		with tempfile.TemporaryDirectory() as tmp:
			p = Path(tmp)
			metadata = dict(tag='v2.1.5-2026.10.08.1', channel='stable', assets={'archive.zip': 'unused'})
			(p / 'candidate.json').write_text(json.dumps(metadata))
			assets = []
			for name in ('archive.zip', 'SHA256SUMS'):
				(p / name).write_bytes(b'bytes')
				assets.append(dict(name=name, size=5, digest='sha256:'+hashlib.sha256(b'bytes').hexdigest(), browser_download_url=f'https://github.com/felixfoertsch/syncthing/releases/download/{metadata["tag"]}/{name}'))
			release = dict(tag_name=metadata['tag'], prerelease=False, assets=assets)
			release_module.verify(p, release)
			draft_assets = [dict(a, id=i, url=f'https://api.github.com/repos/felixfoertsch/syncthing/releases/assets/{i}', browser_download_url='https://github.com/felixfoertsch/syncthing/releases/download/untagged-draft/'+a['name']) for i, a in enumerate(assets)]
			release_module.verify(p, dict(release, draft=True, assets=draft_assets))
			for bad in (assets[:1], assets + [assets[0]], [dict(assets[0], digest='sha256:'+'0'*64), assets[1]]):
				with self.assertRaises(AssertionError): release_module.verify(p, dict(release, assets=bad))
		text = (ROOT / '.github/workflows/custom-release.yml').read_text()
		self.assertEqual(text.count("github.repository == 'felixfoertsch/syncthing'"), 2)
		self.assertIn('--draft=false --prerelease --latest=false', text)

	def test_hash_identity_and_archive_traversal_fail_closed(self):
		with tempfile.TemporaryDirectory() as tmp:
			p = Path(tmp)
			data = dict(control='a'*40, channel='stable', upstream_tag='v2.1.5', upstream='b'*40,
				source='c'*40, main='d'*40, tag='v2.1.5-2026.10.08.1', assets={})
			for platform, ext in [('macos-arm64','.zip'),('linux-amd64','.tar.gz'),('linux-arm64','.tar.gz')]:
				name = f'syncthing-{platform}-{data["tag"]}{ext}'
				member = f'syncthing-{platform}-{data["tag"]}/syncthing'
				if ext == '.zip':
					with zipfile.ZipFile(p / name, 'w') as z:
						z.writestr(member, b'binary')
				else:
					with tarfile.open(p / name, 'w:gz') as t:
						i = tarfile.TarInfo(member); i.size = 6
						t.addfile(i, io.BytesIO(b'binary'))
				data['assets'][name] = hashlib.sha256((p / name).read_bytes()).hexdigest()
			for name in ['source.bundle','SHA256SUMS','release-notes.md']:
				(p / name).write_text('fixture')
			(p / 'candidate.json').write_text(json.dumps(data))
			module.check(p, 'a'*40, 'stable')
			with self.assertRaises(AssertionError): module.check(p, 'e'*40, 'stable')
			with self.assertRaises(AssertionError): module.check(p, 'a'*40, 'nightly')
			name = next(iter(data['assets']))
			with zipfile.ZipFile(p / name, 'w') as z: z.writestr('../syncthing', b'binary')
			with self.assertRaises(AssertionError): module.check(p, 'a'*40, 'stable')
			data['assets'][name] = hashlib.sha256((p / name).read_bytes()).hexdigest()
			(p / 'candidate.json').write_text(json.dumps(data))
			with self.assertRaises(AssertionError): module.check(p, 'a'*40, 'stable')


if __name__ == '__main__':
	unittest.main(verbosity=2)
