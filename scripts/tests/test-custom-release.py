#!/usr/bin/env python3
"""Offline release-automation regressions: real Git repositories, mocked Go/GitHub."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/custom-release.yml'
RELEASE = ROOT / 'scripts/update-custom-release.sh'
SYNC = ROOT / 'scripts/sync-upstream.sh'
TAG = 'v2.1.5-stignore-sync'


def workflow_script(name):
    """Extract one literal run block without requiring a YAML library on runners."""
    lines = WORKFLOW.read_text().splitlines()
    start = lines.index('      - name: ' + name) + 1
    while lines[start] != '        run: |':
        start += 1
    script = []
    for line in lines[start + 1:]:
        if line and not line.startswith('          '):
            break
        script.append(line[10:])
    return '\n'.join(script) + '\n'


class ReleaseTests(unittest.TestCase):
    def run_cmd(self, *args, cwd=None, check=True, env=None):
        result = subprocess.run(args, cwd=cwd or self.work,
                                env=env or self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if check and result.returncode:
            self.fail(f'{args}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
        return result

    def git(self, *args, cwd=None):
        return self.run_cmd('git', *args, cwd=cwd).stdout.strip()

    def write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.work = self.base / 'work'
        self.upstream = self.base / 'official'
        self.remote = self.base / 'fork.git'
        self.bin = self.base / 'bin'
        self.bin.mkdir()
        self.env = os.environ.copy()
        # Do not inherit the real workflow's credentials, output paths or release inputs.
        for key in list(self.env):
            if key.startswith(('CUSTOM_RELEASE_', 'SYNC_', 'GITHUB_', 'GH_', 'GIT_')):
                self.env.pop(key)
        self.env.update({
            'GIT_AUTHOR_NAME': 'Release regression test',
            'GIT_AUTHOR_EMAIL': 'test@example.invalid',
            'GIT_COMMITTER_NAME': 'Release regression test',
            'GIT_COMMITTER_EMAIL': 'test@example.invalid',
            'GIT_CONFIG_GLOBAL': os.devnull,
            'GIT_CONFIG_NOSYSTEM': '1',
            'PATH': str(self.bin) + os.pathsep + os.environ['PATH'],
            'CUSTOM_RELEASE_UPSTREAM_URL': str(self.upstream),
            'CUSTOM_RELEASE_BUILDS': 'linux/amd64/binary/0',
            'CUSTOM_RELEASE_SIGN_DARWIN': '0',
            'CUSTOM_RELEASE_PUSH': '1',
            'CUSTOM_RELEASE_REBUILD_EXISTING': '1',
            'CUSTOM_RELEASE_CREATE_GITEA_RELEASE': '0',
            'GITHUB_REPOSITORY': 'test/fork',
            'GITHUB_OUTPUT': str(self.base / 'output'),
            'GITHUB_ENV': str(self.base / 'env'),
            'RUNNER_TEMP': str(self.base),
            'MOCK_LOG': str(self.base / 'commands.jsonl'),
            'MOCK_API_STATUS': '404',
            'MOCK_DRAFT': 'false',
        })
        for path in ('output', 'env', 'commands.jsonl'):
            (self.base / path).touch()
        self.run_cmd('git', 'init', '-q', '-b', 'main', str(self.upstream), cwd=self.base)
        for name in ('content.txt', 'marker.txt'):
            self.write(self.upstream / name, 'original\n')
        self.write(self.upstream / 'build.go', '// fixture only\n')
        self.write(self.upstream / '.github/workflows/upstream.yml', 'name: upstream\n')
        self.git('add', '.', cwd=self.upstream)
        self.git('commit', '-qm', 'upstream fixture', cwd=self.upstream)
        for tag in ('v2.1.4', 'v2.1.5', 'v2.2.0-rc.1'):
            self.git('tag', tag, cwd=self.upstream)
        self.run_cmd('git', 'init', '-q', '--bare', '-b', 'main', str(self.remote), cwd=self.base)
        self.run_cmd('git', 'clone', '-q', str(self.upstream), str(self.work), cwd=self.base)
        self.git('remote', 'set-url', 'origin', str(self.remote))
        self.git('branch', 'upstream')
        for name, target in (('sync-stignore.patch', 'content.txt'),
                             ('webui-build-marker.patch', 'marker.txt')):
            self.write(self.work / 'patches' / name,
                       f'diff --git a/{target} b/{target}\n'
                       f'--- a/{target}\n+++ b/{target}\n@@ -1 +1 @@\n-original\n+patched\n')
        self.write(self.work / 'patches/README.md', 'Fixture patch documentation\n')
        for source, destination in ((RELEASE, 'scripts/update-custom-release.sh'),
                                    (SYNC, 'scripts/sync-upstream.sh'),
                                    (WORKFLOW, '.github/workflows/custom-release.yml'),
                                    (Path(__file__), 'scripts/tests/test-custom-release.py')):
            self.write(self.work / destination, source.read_text())
        self.write(self.work / 'scripts/tests/test-custom-release-macos-runner.bats', '# fixture\n')
        self.write(self.work / '.gitea/workflows/custom-release.yml', 'name: fixture\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'fork automation fixture')
        self.git('push', '-q', 'origin', 'main', 'upstream')
        self.git('fetch', '-q', 'origin')
        stub = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
args = sys.argv[1:]
name = pathlib.Path(sys.argv[0]).name
with open(os.environ['MOCK_LOG'], 'a') as f:
    f.write(json.dumps([name] + args) + '\n')
if name == 'go':
    if os.environ.get('MOCK_GO_FAIL') == '1':
        sys.exit(1)
    if '-build-out' in args:
        path = pathlib.Path(args[args.index('-build-out') + 1])
        path.write_text(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True))
    sys.exit(0)
if args[0] == 'api' and any('/actions/workflows' in arg for arg in args):
    path = pathlib.Path(os.environ['MOCK_WORKFLOWS'])
    workflows = json.loads(path.read_text())
    endpoint = next(arg for arg in args if '/actions/workflows' in arg)
    if endpoint.endswith('/disable'):
        if os.environ.get('MOCK_POLICY_FAIL') == 'disable':
            sys.exit(1)
        workflow_id = int(endpoint.split('/')[-2])
        for workflow in workflows:
            if workflow['id'] == workflow_id:
                workflow['state'] = 'disabled_manually'
        path.write_text(json.dumps(workflows))
    else:
        if os.environ.get('MOCK_POLICY_FAIL') == 'list':
            sys.exit(1)
        assert '--paginate' in args
        # Execute the real selector rather than hard-coding its expected output.
        sys.exit(subprocess.run(['jq', '-r', args[args.index('--jq') + 1]],
                                input=json.dumps({'workflows': workflows}), text=True).returncode)
    sys.exit(0)
if args[0] == 'api':
    status = os.environ['MOCK_API_STATUS']
    if status == '200':
        print(json.dumps({'draft': os.environ['MOCK_DRAFT'] == 'true'}))
        sys.exit(0)
    if status == 'transport':
        print('network unavailable', file=sys.stderr)
    else:
        print(json.dumps({'status': status, 'message': 'API fixture error'}))
    sys.exit(1)
if args[:2] == ['release', 'view']:
    print(os.environ['MOCK_DRAFT'])
if args[:2] == ['release', 'upload'] and os.environ.get('MOCK_UPLOAD_FAIL') == '1':
    sys.exit(1)
'''
        for name in ('go', 'gh'):
            self.write(self.bin / name, stub)
            (self.bin / name).chmod(0o755)

    def release(self, check=True):
        return self.run_cmd('bash', str(RELEASE), check=check)

    def commands(self, name):
        return [row for row in map(json.loads, (self.base / 'commands.jsonl').read_text().splitlines())
                if row[0] == name]

    def preflight(self, check=True):
        return self.run_cmd('bash', '-euo', 'pipefail', '-c',
                            workflow_script('Resolve release and check publication'), check=check)

    def publish(self, check=True):
        self.env['RELEASE_TAG'] = TAG
        self.env.setdefault('RELEASE_EXISTS', 'false')
        return self.run_cmd('bash', '-euo', 'pipefail', '-c',
                            workflow_script('Publish GitHub release'), check=check)

    def fake_assets(self):
        self.write(self.work / 'dist/release-notes.md', '# fixture\n')
        self.write(self.work / 'dist/SHA256SUMS', 'fixture checksum\n')
        self.write(self.work / 'dist/syncthing-test.tar.gz', 'fixture archive\n')

    def test_new_release_uses_latest_stable_and_applies_patches(self):
        self.release()
        self.assertEqual(self.git('rev-parse', 'HEAD^'), self.git('rev-parse', 'v2.1.5'))
        self.assertEqual((self.work / 'content.txt').read_text(), 'patched\n')
        self.assertEqual((self.work / 'marker.txt').read_text(), 'patched\n')
        self.assertFalse((self.work / '.github/workflows').exists())
        self.assertEqual(self.git('rev-parse', TAG), self.git('rev-parse', TAG, cwd=self.remote))
        self.assertTrue((self.work / 'dist/syncthing-linux-amd64').is_file())
        self.assertTrue(any(row[1] == 'test' for row in self.commands('go')))

    def test_orphan_remote_tag_rebuilds_exact_commit_without_retagging(self):
        self.release()
        original_tag = self.git('rev-parse', TAG, cwd=self.remote)
        original_commit = self.git('rev-parse', f'{TAG}^{{commit}}', cwd=self.remote)
        fresh = self.base / 'retry'
        self.run_cmd('git', 'clone', '-q', str(self.remote), str(fresh), cwd=self.base)
        self.work = fresh
        # Exercise the remote-only branch, not just the local tag fast path.
        self.run_cmd('git', 'tag', '-d', TAG, check=False)
        self.release()
        self.assertEqual(self.git('rev-parse', 'HEAD'), original_commit)
        self.assertEqual(self.git('rev-parse', TAG, cwd=self.remote), original_tag)
        self.assertEqual(self.git('rev-parse', TAG), original_tag)
        self.assertTrue((self.work / 'dist/syncthing-linux-amd64').is_file())

    def test_existing_local_tag_can_resume_after_failed_build(self):
        self.env['MOCK_GO_FAIL'] = '1'
        self.assertNotEqual(self.release(check=False).returncode, 0)
        original_tag = self.git('rev-parse', TAG)
        self.env.pop('MOCK_GO_FAIL')
        self.release()
        self.assertEqual(self.git('rev-parse', TAG, cwd=self.remote), original_tag)

    def test_default_tag_skip_is_preserved_for_other_hosts(self):
        self.release()
        shutil.rmtree(self.work / 'dist')
        self.env['CUSTOM_RELEASE_REBUILD_EXISTING'] = '0'
        self.release()
        self.assertFalse((self.work / 'dist').exists())

    def test_remote_failure_is_not_treated_as_missing_tag(self):
        self.git('remote', 'set-url', 'origin', str(self.base / 'missing.git'))
        result = self.release(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('could not check tag', result.stderr)
        self.assertEqual(self.commands('go'), [])

    def test_published_release_skips_build(self):
        self.env['MOCK_API_STATUS'] = '200'
        self.preflight()
        outputs = (self.base / 'output').read_text()
        self.assertIn('should_build=false', outputs)
        self.assertIn(f'tag={TAG}', outputs)
        self.assertIn('CUSTOM_RELEASE_UPSTREAM_TAG=v2.1.5', (self.base / 'env').read_text())
        self.assertEqual(self.commands('go'), [])

    def test_404_release_is_built(self):
        self.preflight()
        self.assertIn('should_build=true', (self.base / 'output').read_text())
        self.assertIn('release_exists=false', (self.base / 'output').read_text())

    def test_draft_release_is_resumed(self):
        self.env.update(MOCK_API_STATUS='200', MOCK_DRAFT='true')
        self.preflight()
        self.assertIn('should_build=true', (self.base / 'output').read_text())
        self.assertIn('release_exists=true', (self.base / 'output').read_text())

    def test_authentication_and_transport_errors_fail_closed(self):
        for status in ('401', '403', '500', 'transport'):
            with self.subTest(status=status):
                self.env['MOCK_API_STATUS'] = status
                self.assertNotEqual(self.preflight(check=False).returncode, 0)
        self.assertNotIn('should_build=true', (self.base / 'output').read_text())

    def test_manual_tag_and_suffix_are_resolved_once(self):
        self.env.update(CUSTOM_RELEASE_UPSTREAM_TAG='v2.1.4', CUSTOM_RELEASE_SUFFIX='custom-test')
        self.preflight()
        self.assertIn('tag=v2.1.4-custom-test', (self.base / 'output').read_text())

    def test_invalid_inputs_are_rejected_before_api_call(self):
        for key, value in (('CUSTOM_RELEASE_UPSTREAM_TAG', 'main'),
                           ('CUSTOM_RELEASE_SUFFIX', 'bad\nINJECTED=true')):
            with self.subTest(key=key):
                self.env[key] = value
                self.assertNotEqual(self.preflight(check=False).returncode, 0)
                self.env.pop(key)
        self.assertEqual(self.commands('gh'), [])

    def test_publication_is_draft_then_upload_then_publish(self):
        self.fake_assets()
        self.publish()
        commands = self.commands('gh')
        self.assertEqual([row[2] for row in commands], ['create', 'upload', 'edit'])
        self.assertIn('--draft', commands[0])
        self.assertIn('--verify-tag', commands[0])
        self.assertIn('--clobber', commands[1])
        self.assertIn('--draft=false', commands[2])
        self.assertTrue(all(row[3] == TAG for row in commands))

    def test_upload_failure_does_not_publish_incomplete_release(self):
        self.fake_assets()
        self.env['MOCK_UPLOAD_FAIL'] = '1'
        self.assertNotEqual(self.publish(check=False).returncode, 0)
        self.assertEqual([row[2] for row in self.commands('gh')], ['create', 'upload'])

    def test_draft_retry_does_not_recreate_release(self):
        self.fake_assets()
        self.env.update(RELEASE_EXISTS='true', MOCK_DRAFT='true')
        self.publish()
        self.assertEqual([row[2] for row in self.commands('gh')], ['view', 'upload', 'edit'])

    def test_published_release_is_never_clobbered(self):
        self.fake_assets()
        self.env['RELEASE_EXISTS'] = 'true'
        self.publish()
        self.assertEqual([row[2] for row in self.commands('gh')], ['view'])

    def test_missing_artifacts_fail_before_publication(self):
        self.assertNotEqual(self.publish(check=False).returncode, 0)
        self.assertEqual(self.commands('gh'), [])

    def test_upstream_sync_retains_fixes_and_does_not_self_trigger(self):
        self.write(self.upstream / 'new-upstream-file', 'upstream update\n')
        self.git('add', '.', cwd=self.upstream)
        self.git('commit', '-qm', 'new upstream commit', cwd=self.upstream)
        self.env['SYNC_UPSTREAM_URL'] = str(self.upstream)
        self.run_cmd('bash', str(SYNC))
        self.assertEqual(self.git('rev-parse', 'HEAD^'), self.git('rev-parse', 'HEAD', cwd=self.upstream))
        self.assertIn('[skip ci]', self.git('log', '-1', '--format=%s'))
        self.assertEqual((self.work / '.github/workflows/custom-release.yml').read_text(), WORKFLOW.read_text())
        self.assertEqual((self.work / 'scripts/tests/test-custom-release.py').read_text(), Path(__file__).read_text())
        self.assertEqual((self.work / 'content.txt').read_text(), 'patched\n')
        first = self.git('rev-parse', 'HEAD')
        self.run_cmd('bash', str(SYNC))
        self.assertEqual(self.git('rev-parse', 'HEAD'), first)

    def test_workflow_serializes_runs_and_gates_expensive_steps(self):
        text = WORKFLOW.read_text()
        self.assertIn('concurrency:\n  group: custom-release\n  cancel-in-progress: false', text)
        for name in ('Set up Go', 'Import Developer ID certificate',
                     'Build patched Syncthing release', 'Publish GitHub release'):
            self.assertIn(f"      - name: {name}\n        if: steps.release.outputs.should_build == 'true'", text)
        self.assertIn('python3 scripts/tests/test-custom-release.py', text)
        self.assertIn('CUSTOM_RELEASE_REBUILD_EXISTING: "1"', text)
        self.assertNotIn('ls-remote', workflow_script('Publish GitHub release'))
        self.assertIn('RELEASE_TAG: ${{ steps.release.outputs.tag }}', text)


    def configure_github_policy(self):
        self.env.update(GITHUB_ACTIONS='true', GITHUB_SERVER_URL='https://github.com',
                        GH_TOKEN='test-ephemeral-token', MOCK_WORKFLOWS=str(self.base / 'workflows.json'))
        self.write(self.base / 'workflows.json', json.dumps([
            {'id': 1, 'path': '.github/workflows/custom-release.yml', 'state': 'active'},
            {'id': 2, 'path': '.github/workflows/build-syncthing.yaml', 'state': 'active'},
            {'id': 3, 'path': '.github/workflows/stignore-review.yml', 'state': 'active'},
            {'id': 4, 'path': 'dynamic/security-check', 'state': 'active'},
            {'id': 5, 'path': '.github/workflows/old.yml', 'state': 'disabled_manually'},
            {'id': 6, 'path': '.github/workflows/new-upstream.yml', 'state': 'active'},
        ]))

    def policy(self, check=True):
        return self.run_cmd('bash', '-euo', 'pipefail', '-c',
                            'source "$1"; enforce_github_workflow_policy', 'policy', str(SYNC), check=check)

    def test_policy_disables_inherited_and_review_workflows_only(self):
        self.configure_github_policy()
        self.policy()
        states = {w['id']: w['state'] for w in json.loads((self.base / 'workflows.json').read_text())}
        self.assertEqual(states, {1: 'active', 2: 'disabled_manually', 3: 'disabled_manually',
                                  4: 'active', 5: 'disabled_manually', 6: 'disabled_manually'})
        calls = len(self.commands('gh'))
        self.policy()
        self.assertEqual(len(self.commands('gh')) - calls, 2)  # Two reads; no duplicate disables.

    def test_policy_api_errors_stop_before_any_repository_push(self):
        self.configure_github_policy()
        before = self.git('rev-parse', 'main', cwd=self.remote)
        self.env['SYNC_UPSTREAM_URL'] = str(self.upstream)
        for failure in ('list', 'disable'):
            with self.subTest(failure=failure):
                self.env['MOCK_POLICY_FAIL'] = failure
                result = self.run_cmd('bash', str(SYNC), check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), before)
                self.assertNotIn('official/main', self.git('for-each-ref', '--format=%(refname)'))

    def test_policy_requires_credentials_before_api_requests(self):
        self.configure_github_policy()
        self.env.pop('GH_TOKEN')
        self.assertNotEqual(self.policy(check=False).returncode, 0)
        self.assertEqual(self.commands('gh'), [])

    def test_sync_removes_inherited_workflows_even_without_upstream_changes(self):
        # Reproduce the old early return: exactly one fork commit, unchanged upstream.
        self.env['SYNC_UPSTREAM_URL'] = str(self.upstream)
        self.run_cmd('bash', str(SYNC))
        self.assertEqual(self.git('ls-tree', '-r', '--name-only', 'main', '--', '.github/workflows'),
                         '.github/workflows/custom-release.yml')
        self.assertEqual(self.git('show', 'upstream:.github/workflows/upstream.yml'), 'name: upstream')
        self.assertEqual(self.git('rev-parse', 'upstream', cwd=self.remote),
                         self.git('rev-parse', 'main', cwd=self.upstream))
        first = self.git('rev-parse', 'main')
        self.run_cmd('bash', str(SYNC))
        self.assertEqual(self.git('rev-parse', 'main'), first)

    def test_future_upstream_workflows_stay_only_in_pristine_mirror(self):
        for host in ('.github', '.gitea'):
            self.write(self.upstream / host / 'workflows/future.yaml', 'name: unwanted future build\n')
        self.git('add', '.', cwd=self.upstream)
        self.git('commit', '-qm', 'add upstream workflows', cwd=self.upstream)
        self.env['SYNC_UPSTREAM_URL'] = str(self.upstream)
        self.run_cmd('bash', str(SYNC))
        for host in ('.github', '.gitea'):
            self.assertEqual(self.git('ls-tree', '-r', '--name-only', 'main', '--', host + '/workflows'),
                             host + '/workflows/custom-release.yml')
            self.assertEqual(self.git('show', 'upstream:' + host + '/workflows/future.yaml'),
                             'name: unwanted future build')
        self.assertEqual(self.git('rev-parse', 'upstream^{tree}'),
                         self.git('rev-parse', 'main^{tree}', cwd=self.upstream))

    def instrument_git_pushes(self):
        real_git = shutil.which('git', path=os.environ['PATH'])
        stub = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args and args[0] == 'push':
    config = {key: value for key, value in os.environ.items()
              if key == 'GIT_CONFIG_COUNT' or key.startswith(('GIT_CONFIG_KEY_', 'GIT_CONFIG_VALUE_'))}
    with open(os.environ['MOCK_LOG'], 'a') as f:
        f.write(json.dumps(['git-push', args, config]) + '\n')
    if args[-1] == 'upstream' and os.environ.get('MOCK_MIRROR_PUSH_FAIL') == '1':
        sys.exit(1)
os.execv(REAL_GIT, [REAL_GIT] + args)
""".replace('REAL_GIT', repr(real_git))
        self.write(self.bin / 'git', stub)
        (self.bin / 'git').chmod(0o755)
        self.write(self.upstream / 'new-content', 'upstream change\n')
        self.git('add', '.', cwd=self.upstream)
        self.git('commit', '-qm', 'upstream changed', cwd=self.upstream)
        self.env['SYNC_UPSTREAM_URL'] = str(self.upstream)

    def test_mirror_push_uses_ephemeral_token_without_changing_main_credentials(self):
        self.configure_github_policy()
        self.instrument_git_pushes()
        self.run_cmd('bash', str(SYNC))
        pushes = self.commands('git-push')
        self.assertEqual([row[1][-1] for row in pushes], ['upstream', 'main'])
        self.assertEqual(pushes[0][2]['GIT_CONFIG_COUNT'], '2')
        self.assertEqual(pushes[0][2]['GIT_CONFIG_VALUE_0'], '')
        import base64
        expected = 'AUTHORIZATION: basic ' + base64.b64encode(b'x-access-token:test-ephemeral-token').decode()
        self.assertEqual(pushes[0][2]['GIT_CONFIG_VALUE_1'], expected)
        self.assertEqual(pushes[1][2], {})

    def test_failed_ephemeral_push_never_retries_with_pat(self):
        self.configure_github_policy()
        self.instrument_git_pushes()
        before = self.git('rev-parse', 'main', cwd=self.remote)
        self.env['MOCK_MIRROR_PUSH_FAIL'] = '1'
        self.assertNotEqual(self.run_cmd('bash', str(SYNC), check=False).returncode, 0)
        self.assertEqual(len(self.commands('git-push')), 1)
        self.assertEqual(self.git('rev-parse', 'main', cwd=self.remote), before)

    def test_policy_runs_even_when_upstream_sync_is_a_noop(self):
        self.env['SYNC_UPSTREAM_URL'] = str(self.upstream)
        self.run_cmd('bash', str(SYNC))
        before = self.git('rev-parse', 'main')
        self.configure_github_policy()
        result = self.run_cmd('bash', str(SYNC))
        self.assertIn('Workflow policy verified', result.stdout)
        self.assertIn('Upstream is current', result.stdout)
        self.assertEqual(self.git('rev-parse', 'main'), before)

    def test_workflow_scope_keeps_only_custom_release_and_its_existing_gates(self):
        self.assertEqual(sorted(p.name for p in WORKFLOW.parent.iterdir()), ['custom-release.yml'])
        workflow = WORKFLOW.read_text()
        self.assertIn('  actions: write', workflow)
        sync_step = workflow.split('      - name: Mirror upstream and rebuild patched main')[1].split('      - name:')[0]
        self.assertIn('GH_TOKEN: ${{ github.token }}', sync_step)
        self.assertIn('darwin/$darwin_arch/zip/1 linux/amd64/tar/0 linux/arm64/tar/0', workflow)
        self.assertIn("go test -race -count=3 -run '^TestStignoreSync' ./lib/model", RELEASE.read_text())
        self.assertIn('./lib/watchaggregator', RELEASE.read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
