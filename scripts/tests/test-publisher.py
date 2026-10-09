#!/usr/bin/env python3
"""Publisher trust boundary checks, no signing credentials required."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch
import os
import subprocess

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

	def test_checksum_first_incomplete_draft_fails_with_remedy_before_download(self):
		spec = importlib.util.spec_from_file_location('reuse', ROOT / 'scripts/reuse-draft.py')
		reuse_module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(reuse_module)
		with tempfile.TemporaryDirectory() as tmp:
			p = Path(tmp)
			(p / 'candidate.json').write_text(json.dumps(dict(tag='v2.1.5-2026.10.08.1', channel='stable', assets={'missing.tar.gz':'unused'})))
			with self.assertRaisesRegex(RuntimeError, 'Restore original missing bytes.*rebuild=true.*Never overwrite'):
				reuse_module.reuse(p, dict(tag_name='v2.1.5-2026.10.08.1', draft=True, prerelease=False,
					assets=[dict(name='SHA256SUMS')]), lambda a: self.fail('must reject before download'))
		text = (ROOT / '.github/workflows/custom-release.yml').read_text()
		self.assertLess(text.index('python3 scripts/verify-release.py candidate "$tag" archives'),
			text.index('gh release upload "$tag" candidate/SHA256SUMS'))

	def test_partial_signed_draft_retry_keeps_original_bytes_and_fills_gap(self):
		spec = importlib.util.spec_from_file_location('reuse', ROOT / 'scripts/reuse-draft.py')
		reuse_module = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(reuse_module)
		with tempfile.TemporaryDirectory() as tmp:
			p = Path(tmp)
			data = dict(control='a'*40, channel='stable', upstream_tag='v2.1.5', upstream='b'*40,
				source='c'*40, main='d'*40, tag='v2.1.5-2026.10.08.1', assets={})
			for platform, ext in [('macos-arm64','.zip'),('linux-amd64','.tar.gz'),('linux-arm64','.tar.gz')]:
				name = f'syncthing-{platform}-{data["tag"]}{ext}'
				member = name.removesuffix(ext) + '/syncthing'
				binary = ('new-host '+data['tag']).encode()
				if ext == '.zip':
					with zipfile.ZipFile(p / name, 'w') as z: z.writestr(member, binary)
				else:
					with tarfile.open(p / name, 'w:gz') as t:
						i = tarfile.TarInfo(member); i.size = len(binary)
						t.addfile(i, io.BytesIO(binary))
				data['assets'][name] = hashlib.sha256((p / name).read_bytes()).hexdigest()
			for name in ('source.bundle', 'release-notes.md', 'SHA256SUMS'): (p / name).touch()
			(p / 'candidate.json').write_text(json.dumps(data))
			darwin = next(n for n in data['assets'] if n.endswith('.zip'))
			buffer = io.BytesIO()
			with zipfile.ZipFile(buffer, 'w') as z:
				z.writestr(darwin.removesuffix('.zip')+'/syncthing', ('old-host signed '+data['tag']).encode())
			original = buffer.getvalue()
			asset = dict(name=darwin, id=42, url='https://api.github.com/repos/felixfoertsch/syncthing/releases/assets/42',
				size=len(original), digest='sha256:'+hashlib.sha256(original).hexdigest())
			release = dict(tag_name=data['tag'], draft=True, prerelease=False, assets=[asset])
			info = '\n'.join(('vcs.revision='+data['source'], 'vcs.modified=false', 'GOOS=darwin', 'GOOS=linux', 'GOARCH=arm64', 'GOARCH=amd64', 'CGO_ENABLED=1'))
			with patch.object(reuse_module.candidate_module.subprocess, 'check_output', return_value=info), patch.object(reuse_module.candidate_module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stderr='TeamIdentifier=NG5W75WE8U')) as commands:
				self.assertTrue(reuse_module.reuse(p, release, lambda a: original))
				self.assertEqual((p / darwin).read_bytes(), original)
				metadata = json.loads((p / 'candidate.json').read_text())
				with patch.dict(os.environ, {'CUSTOM_RELEASE_REUSE_DARWIN': '1'}):
					reuse_module.candidate_module.sign(p, metadata)
				self.assertFalse(any('--sign' in call.args[0] for call in commands.call_args_list))
				self.assertEqual((p / darwin).read_bytes(), original)
				self.assertEqual(len((p / 'SHA256SUMS').read_text().splitlines()), 3)
				with self.assertRaises(AssertionError):
					reuse_module.reuse(p, release, lambda a: b'wrong bytes')
				with patch.object(reuse_module.candidate_module.subprocess, 'check_output', return_value=info.replace(data['source'], 'e'*40)):
					with self.assertRaises(AssertionError): reuse_module.reuse(p, release, lambda a: original)
				with patch.object(reuse_module.candidate_module.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, stderr='TeamIdentifier=WRONG')):
					with self.assertRaises(AssertionError): reuse_module.reuse(p, release, lambda a: original)
				bad = io.BytesIO()
				with zipfile.ZipFile(bad, 'w') as z: z.writestr('../syncthing', b'bad')
				payload = bad.getvalue()
				bad_asset = dict(asset, size=len(payload), digest='sha256:'+hashlib.sha256(payload).hexdigest())
				with self.assertRaises(AssertionError): reuse_module.reuse(p, dict(release, assets=[bad_asset]), lambda a: payload)

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
