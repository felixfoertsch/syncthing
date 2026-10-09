#!/usr/bin/env python3
"""Offline unchanged-publication decisions; no signing or network credentials."""
import importlib.util
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('unchanged', ROOT / 'scripts/select-release.py')
module = importlib.util.module_from_spec(spec)


class SelectionTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		spec.loader.exec_module(module)

	def select(self, **changes):
		args = dict(channel='stable', upstream_tag='v2.1.5', source='a'*40,
			releases=[dict(tag_name='v2.1.5-2026.10.08.1', draft=False, prerelease=False)],
			resolve=lambda tag: 'a'*40, verify=lambda release: True, latest='v2.1.5-2026.10.08.1', main='a'*40, force=False)
		args.update(changes)
		return module.select(**args)

	def test_complete_unchanged_skips_both_channels(self):
		self.assertIsNone(self.select())
		tag = 'v2.1.5-nightly.'+'b'*40
		self.assertIsNone(self.select(channel='nightly', upstream_tag=tag,
			releases=[dict(tag_name=tag+'-2026.10.08.1', draft=False, prerelease=True)]))

	def test_changed_missing_force_and_delivery_build(self):
		for changes in (dict(source='c'*40), dict(releases=[]), dict(force=True),
			dict(verify=lambda release: False), dict(latest='old')):
			self.assertEqual(self.select(**changes), '')
		tag = 'v2.1.5-nightly.'+'b'*40
		self.assertEqual(self.select(channel='nightly', upstream_tag=tag, main='c'*40,
			releases=[dict(tag_name=tag+'-2026.10.08.1', draft=False, prerelease=True)]), '')

	def test_draft_resumes_same_identity(self):
		self.assertEqual(self.select(releases=[dict(tag_name='v2.1.5-2026.10.08.1', draft=True, prerelease=False)]), '2026.10.08.1')

	def test_workflow_rechecks_skip_before_loading_signing_credentials(self):
		text = (ROOT / '.github/workflows/custom-release.yml').read_text()
		self.assertEqual(text.count("if: steps.verify.outputs.skipped != 'true'"), 5)
		self.assertIn("steps.selection.outputs.suffix || github.event.inputs.suffix", text)
		self.assertIn('CUSTOM_RELEASE_REBUILD_EXISTING=1', text)
		verify = (ROOT / 'scripts/verify-source.sh').read_text()
		self.assertLess(verify.index('scripts/select-release.py'), verify.index('scripts/verify-candidate.py'))

	def test_missing_asset_set_never_skips(self):
		self.assertFalse(module.verify(dict(draft=False, tag_name='v2.1.5-2026.10.08.1', assets=[]),
			'a'*40, 'b'*40, 'v2.1.5', 'stable'))

	def test_verification_errors_do_not_become_skip(self):
		def denied(release):
			raise RuntimeError('permission denied')
		with self.assertRaises(RuntimeError):
			self.select(verify=denied)


if __name__ == '__main__':
	unittest.main(verbosity=2)
