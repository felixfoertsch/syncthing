#!/usr/bin/env python3
"""Real Git refresh checks with no network, credentials or global Git identity."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('refresh', ROOT / 'scripts/control-refresh.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


class RefreshTests(unittest.TestCase):
	def git(self, *args):
		return refresh.git(*args)

	def commit(self):
		self.git('add', '-A')
		return self.git('commit', '-qm', 'fixture') or self.git('rev-parse', 'HEAD')

	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.directory = Path(self.tmp.name)
		old = Path.cwd()
		self.addCleanup(os.chdir, old)
		os.chdir(self.directory)
		self.env = patch.dict(os.environ, refresh.clean_env(), clear=True)
		self.env.start()
		self.addCleanup(self.env.stop)
		self.git('init', '-q', '-b', 'main')
		Path('README.md').write_text('complete upstream readme\n')
		Path('README-Docker.md').write_text('complete docker readme\n')
		Path('content').write_text('old\n')
		Path('marker').write_text('old\n')
		Path('.github/workflows').mkdir(parents=True)
		Path('.github/workflows/upstream.yml').write_text('upstream publisher\n')
		self.base = self.commit()
		legacy = patch.object(refresh, 'LEGACY_BASE', self.base)
		legacy.start()
		self.addCleanup(legacy.stop)
		for path in refresh.OWNED:
			p = Path(path)
			p.parent.mkdir(parents=True, exist_ok=True)
			p.write_bytes((ROOT / path).read_bytes())
		for number, target in ((1, 'content'), (2, 'marker')):
			p = Path(refresh.OWNED[number])
			p.write_text(f'diff --git a/{target} b/{target}\n--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-old\n+patched\n')
		self.git('add', '-A')
		self.git('commit', '-qm', 'overlay')
		self.overlay = self.git('rev-parse', 'HEAD')
		# Existing reconstruction seam provides actual queue and README behavior.
		refresh.run('bash', '-c', 'set -e; die() { exit 1; }; source scripts/reconstruct.sh; apply_patch_queue patches/[0-9]*.patch; commit_reconstruction "$1" patches/README-prefix.md', 'fixture', self.base)
		self.git('checkout', self.overlay, '--', *refresh.OWNED)
		self.commit()
		self.control = self.git('rev-parse', 'HEAD')
		self.git('branch', 'patch-queue')
		self.patch_upstream = patch.object(refresh, 'UPSTREAM', str(self.directory))
		self.patch_upstream.start()
		self.addCleanup(self.patch_upstream.stop)

	def candidate(self, source=None):
		with patch.object(refresh, 'upstream', return_value=('refs/heads/main', source or self.base)):
			return refresh.candidate(self.control, source or self.base, self.directory / 'candidate.bundle')

	def test_noop_and_next_upstream_deterministic(self):
		initial = self.candidate()
		self.git('fetch', str(self.directory / 'candidate.bundle'), 'refs/heads/refreshed-control')
		self.control = initial
		self.git('checkout', '--detach', initial)
		Path('candidate.bundle').unlink()
		with patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)):
			self.assertEqual(self.candidate(), self.control)
		Path('candidate.bundle').unlink()
		self.git('checkout', '--detach', self.base)
		Path('new-upstream').write_text('new source\n')
		selected = self.commit()
		self.git('checkout', '--detach', self.control)
		result = self.candidate(selected)
		refresh.verify_bundle(self.directory / 'candidate.bundle', result)
		self.git('fetch', str(self.directory / 'candidate.bundle'), 'refs/heads/refreshed-control')
		self.assertEqual(self.git('show', result + ':content'), 'patched')
		self.assertEqual(self.git('show', result + ':marker'), 'patched')
		self.assertEqual(self.git('show', result + ':new-upstream'), 'new source')
		self.assertEqual(self.git('rev-parse', result + '^'), selected)
		self.assertEqual(refresh.tree('.', result, '.github/workflows'), refresh.tree('.', self.control, '.github/workflows'))
		readme = self.git('show', result + ':README.md')
		self.assertEqual(readme.count('complete upstream readme'), 1)
		self.assertEqual(readme.count('complete docker readme'), 1)
		Path('candidate.bundle').unlink()
		self.assertEqual(self.candidate(selected), result)

	def test_empty_upstream_commit_refreshes_once(self):
		first = self.candidate()
		self.git('fetch', str(self.directory / 'candidate.bundle'), 'refs/heads/refreshed-control')
		self.git('checkout', '--detach', self.base)
		self.git('commit', '--allow-empty', '-qm', 'empty upstream advance')
		selected = self.git('rev-parse', 'HEAD')
		self.control = first
		self.git('checkout', '--detach', first)
		Path('candidate.bundle').unlink()
		result = self.candidate(selected)
		self.assertNotEqual(result, first)
		self.git('fetch', str(self.directory / 'candidate.bundle'), 'refs/heads/refreshed-control')
		self.control = result
		self.git('checkout', '--detach', result)
		Path('candidate.bundle').unlink()
		self.assertEqual(self.candidate(selected), result)

	def test_prerequisite_bundle_cannot_restore_empty(self):
		bundle = self.directory / 'partial.bundle'
		self.git('bundle', 'create', str(bundle), 'HEAD', '^' + self.base)
		with self.assertRaises(subprocess.CalledProcessError):
			refresh.verify_bundle(bundle, self.control)

	def test_archive_tags_removed_before_build(self):
		archive = 'archive/patch-queue/' + self.control
		self.git('tag', archive, self.control)
		self.git('tag', 'v2.1.6', self.control)
		script = (ROOT / 'scripts/build-candidate.sh').read_text()
		cleanup = script[script.index('git for-each-ref'):script.index('# This process retains')]
		refresh.run('bash', '-euo', 'pipefail', '-c', cleanup)
		self.assertEqual(self.git('tag'), 'v2.1.6')

	def test_credential_free_reconstruction_environment(self):
		with patch.dict(os.environ, GH_TOKEN='must-not-reach-source', DEVELOPER_ID_APPLICATION_P12_BASE64='must-not-reach-source'):
			env = refresh.clean_env()
			self.assertNotIn('GH_TOKEN', env)
			self.assertNotIn('DEVELOPER_ID_APPLICATION_P12_BASE64', env)
			self.assertEqual(env['GIT_CONFIG_GLOBAL'], os.devnull)

	def test_unknown_source_fails(self):
		Path('content').write_text('unaccepted\n')
		self.control = self.commit()
		with self.assertRaisesRegex(RuntimeError, 'unknown customization'):
			self.candidate()

	def test_upstream_overlay_collision_fails(self):
		self.git('checkout', '--detach', self.base)
		Path('scripts').mkdir()
		Path('scripts/control-refresh.py').write_text('upstream owns this\n')
		selected = self.commit()
		self.git('checkout', '--detach', self.control)
		with self.assertRaisesRegex(RuntimeError, 'ownership collision'):
			self.candidate(selected)

	def test_corrupt_backup_fails(self):
		bundle = self.directory / 'old-control.bundle'
		self.git('bundle', 'create', str(bundle), 'HEAD')
		Path('backup.json').write_text(json.dumps({'control': self.control, 'sha256': refresh.digest(bundle)}))
		refresh.verify_backup(self.directory, self.control)
		bundle.write_bytes(b'corrupt')
		with self.assertRaisesRegex(RuntimeError, 'digest'):
			refresh.verify_backup(self.directory, self.control)

	def promotion_fixture(self):
		remote = self.directory / 'remote.git'
		self.git('init', '--bare', '-q', str(remote))
		self.git('remote', 'add', 'origin', str(remote))
		self.git('push', '-q', 'origin', self.control + ':refs/heads/patch-queue')
		directory = self.directory / 'artifact'
		directory.mkdir()
		with patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)):
			result = refresh.candidate(self.control, self.base, directory / 'candidate.bundle')
		(directory / 'candidate.json').write_text(json.dumps(dict(control=self.control, upstream=self.base, upstream_ref='refs/heads/main', result=result)))
		self.git('bundle', 'create', str(directory / 'old-control.bundle'), 'HEAD')
		(directory / 'backup.json').write_text(json.dumps(dict(control=self.control, sha256=refresh.digest(directory / 'old-control.bundle'))))
		return directory, result

	def test_atomic_archive_promotion_and_wrong_archive_rejected(self):
		directory, expected = self.promotion_fixture()
		archive = 'refs/tags/archive/patch-queue/' + self.control
		self.git('push', '-q', 'origin', self.base + ':' + archive)
		with patch.dict(os.environ, CONTROL=self.control, GH_TOKEN='fixture-job-token'), patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)), patch.object(refresh, 'dispatch') as dispatch:
			with self.assertRaisesRegex(RuntimeError, 'archive tag'):
				refresh.promote(directory)
			dispatch.assert_not_called()
			self.assertEqual(refresh.head('origin', 'refs/heads/patch-queue'), self.control)
			self.git('push', '-q', 'origin', ':' + archive)
			self.assertEqual(refresh.promote(directory), expected)
			dispatch.assert_called_once_with(expected)
			self.assertEqual(refresh.head('origin', archive), self.control)
			self.assertEqual(refresh.head('origin', 'refs/heads/patch-queue'), expected)

	def test_control_race_stops_before_atomic_push(self):
		directory, expected = self.promotion_fixture()
		self.git('push', '-q', '--force', 'origin', self.base + ':refs/heads/patch-queue')
		with patch.dict(os.environ, CONTROL=self.control, GH_TOKEN='fixture-job-token'), patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)), patch.object(refresh, 'dispatch') as dispatch:
			with self.assertRaisesRegex(RuntimeError, 'control changed'):
				refresh.promote(directory)
			dispatch.assert_not_called()
			self.assertEqual(refresh.head('origin', 'refs/heads/patch-queue'), self.base)

	def test_atomic_rejection_leaves_both_refs_unchanged(self):
		directory, expected = self.promotion_fixture()
		remote = self.directory / 'remote.git'
		hook = remote / 'hooks/update'
		hook.write_text('#!/bin/sh\n[ "$1" != refs/heads/patch-queue ]\n')
		hook.chmod(0o755)
		archive = 'refs/tags/archive/patch-queue/' + self.control
		with patch.dict(os.environ, CONTROL=self.control, GH_TOKEN='fixture-job-token'), patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)), patch.object(refresh, 'dispatch') as dispatch:
			with self.assertRaises(subprocess.CalledProcessError):
				refresh.promote(directory)
			dispatch.assert_not_called()
			self.assertEqual(refresh.head('origin', 'refs/heads/patch-queue'), self.control)
			self.assertEqual(self.git('ls-remote', 'origin', archive), '')

	def test_annotated_archive_rejected_even_with_correct_target(self):
		directory, expected = self.promotion_fixture()
		archive = 'archive/patch-queue/' + self.control
		self.git('tag', '-a', archive, self.control, '-m', 'not lightweight')
		self.git('push', '-q', 'origin', 'refs/tags/' + archive)
		with patch.dict(os.environ, CONTROL=self.control, GH_TOKEN='fixture-job-token'), patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)), patch.object(refresh, 'dispatch') as dispatch:
			with self.assertRaisesRegex(RuntimeError, 'archive tag'):
				refresh.promote(directory)
			dispatch.assert_not_called()

	def test_dispatch_failure_next_schedule_noop_recovers(self):
		directory, expected = self.promotion_fixture()
		with patch.dict(os.environ, CONTROL=self.control, GH_TOKEN='fixture-job-token'), patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)), patch.object(refresh, 'dispatch', side_effect=RuntimeError('dispatch failed')):
			with self.assertRaisesRegex(RuntimeError, 'dispatch failed'):
				refresh.promote(directory)
		self.git('fetch', 'origin', 'refs/heads/patch-queue')
		self.git('checkout', '--detach', expected)
		self.control = expected
		next_run = self.directory / 'next-run'
		with patch.dict(os.environ, CONTROL=expected), patch.object(refresh, 'upstream', return_value=('refs/heads/main', self.base)), patch.object(refresh, 'dispatch') as dispatch:
			self.assertEqual(refresh.prepare(next_run), expected)
			self.assertEqual(refresh.promote(next_run), expected)
			dispatch.assert_not_called()

	def test_dispatch_default_does_not_force_rebuild(self):
		with patch.dict(os.environ, GITHUB_REPOSITORY='test/fork'), patch.object(refresh, 'run') as run:
			refresh.dispatch(self.control)
			self.assertEqual(json.loads(run.call_args.kwargs['data'])['inputs']['rebuild'], 'false')

	def test_dispatch_exact_sha_preserves_intent(self):
		with patch.dict(os.environ, GITHUB_REPOSITORY='test/fork', REFRESH_REBUILD='true', REFRESH_SUFFIX='2026.10.18.1'), patch.object(refresh, 'run') as run:
			refresh.dispatch(self.control)
			payload = json.loads(run.call_args.kwargs['data'])
			self.assertEqual(payload['inputs']['expected_control'], self.control)
			self.assertEqual(payload['inputs']['rebuild'], 'true')
			self.assertEqual(payload['ref'], 'patch-queue')


if __name__ == '__main__':
	unittest.main()
