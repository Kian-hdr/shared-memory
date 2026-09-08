"""Real packaged setup acceptance; synthetic local projects, no provider accounts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): digest(p) for p in root.rglob('*') if p.is_file()}


class OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = tempfile.TemporaryDirectory(prefix='shared-memory-onboarding-build-')
        cls.addClassCleanup(cls.built.cleanup)
        cls.package = Path(cls.built.name).resolve() / 'runtime.pyz'
        result = subprocess.run([sys.executable, str(REPO / 'scripts/build_product.py'), '--output', str(cls.package)],
                                capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-onboarding-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'Private vault/Projects/Shared notes'
        self.project.mkdir(parents=True)
        self.state = self.root / 'private-state'
        self.sentinels = {
            self.root / 'Private vault/Home.md': b'# Private parent\r\n',
            self.root / 'Private vault/Private.md': b'PRIVATE SIBLING\n',
            self.root / 'Private vault/.obsidian/app.json': b'{"fixture":true}\n',
            self.project / 'Home.md': '# Grüß 世界\r\nOriginal\n'.encode(),
            self.project / 'AGENTS.md': b'# Existing instructions\r\nKeep originals.',
            self.project / 'image.bin': b'\x00\xffUNCHANGED',
        }
        for path, content in self.sentinels.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    def cli(self, command, *arguments, expected=0, env=None):
        result = subprocess.run([sys.executable, str(self.package), command, *map(str, arguments)],
                                capture_output=True, text=True, timeout=30, env=env)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        value = json.loads(result.stdout)
        self.assertEqual(value['ok'], expected == 0)
        return value['data'] if expected == 0 else value

    def setup(self, *arguments, expected=0, project=None, state=None):
        return self.cli('setup', project or self.project, '--state-dir', state or self.state,
                        *arguments, expected=expected)

    def coord(self, operation, payload):
        request = self.root / 'payload.json'
        request.write_text(json.dumps(payload), encoding='utf-8')
        return self.cli('coord', self.project, '--state-dir', self.state,
                        operation, '--payload-file', request)

    def assert_preserved(self):
        for path, content in self.sentinels.items():
            self.assertEqual(path.read_bytes(), content, str(path))

    def test_fresh_selected_subfolder_and_repeated_setup_keep_identity_history_and_bytes(self):
        first = self.setup('--actor', 'owner', '--person', 'Fixture Owner')
        self.assertEqual(first['route'], 'init')
        self.assertEqual(first['readiness'], 'ready')
        self.assertEqual(first['workspace_scope'], 'local')
        self.assertTrue(first['current_authority_match'])
        db, token = digest(self.state / 'coordinator.sqlite3'), (self.state / 'member.token').read_bytes()
        second = self.setup()
        self.assertEqual(second['route'], 'resume_init')
        self.assertEqual(second['project_id'], first['project_id'])
        self.assertEqual(second['receipt'], first['receipt'])
        self.assertEqual(digest(self.state / 'coordinator.sqlite3'), db)
        self.assertEqual((self.state / 'member.token').read_bytes(), token)
        self.assert_preserved()
        self.assertNotIn(token.decode().strip(), json.dumps(second))

    def test_default_state_is_platform_private_deterministic_and_usable(self):
        home = self.root / 'fake-home'; home.mkdir()
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
                   LOCALAPPDATA=str(home / 'AppData/Local'), XDG_STATE_HOME=str(home / '.local/state'))
        first = self.cli('setup', self.project, env=env)
        second = self.cli('setup', self.project, env=env)
        selected = Path(first['state_dir'])
        self.assertTrue(selected.is_relative_to(home))
        self.assertFalse(selected.is_relative_to(self.project))
        self.assertEqual(second['state_dir'], first['state_dir'])
        self.assertEqual(second['project_id'], first['project_id'])
        self.assertEqual(len(selected.name), 64)
        self.assert_preserved()

    def test_missing_generated_files_restored_from_exact_saved_intent(self):
        first = self.setup()
        token = (self.state / 'member.token').read_bytes()
        connection = (self.state / 'connection.json').read_bytes()
        intent = (self.state / 'setup-intent.json').read_bytes()
        (self.state / 'member.token').unlink()
        (self.state / 'connection.json').unlink()
        second = self.setup()
        self.assertEqual(second['project_id'], first['project_id'])
        self.assertEqual((self.state / 'member.token').read_bytes(), token)
        self.assertEqual((self.state / 'connection.json').read_bytes(), connection)
        self.assertEqual((self.state / 'setup-intent.json').read_bytes(), intent)
        self.assertEqual({r['file'] for r in second['repairs']}, {'member.token', 'connection.json'})
        self.assertEqual(second['readiness'], 'ready')

    def test_edited_live_note_is_recoverable_and_reported_after_resume(self):
        self.setup()
        edited = b'POST-SETUP WORK\r\nKeep me recoverable.'
        (self.project / 'Home.md').write_bytes(edited)
        result = self.setup()
        self.assertTrue(result['preserved_drafts'])
        self.assertIsNotNone(result['recovery_note'])
        self.assertTrue(any(json.loads(p.read_text())['changes'].get('Home.md') == edited.decode()
                            for p in (self.state / 'client/drafts').glob('*.json')))
        self.assertTrue(any(p.read_bytes() == edited for p in (self.state / 'client/backups').iterdir()))
        self.assert_preserved()

    def test_missing_completed_history_never_recreated_or_credentials_restored_first(self):
        self.setup()
        (self.state / 'coordinator.sqlite3').unlink()
        (self.state / 'member.token').unlink()
        before = inventory(self.root)
        result = self.setup(expected=3)
        self.assertEqual(result['code'], 'authority_missing')
        self.assertEqual(inventory(self.root), before)

    def test_copied_team_marker_requires_access_never_initializes_authority(self):
        first = self.setup()
        other = self.root / 'Other private parent/Shared project'; other.mkdir(parents=True)
        shutil.copyfile(self.project / '.shared-memory.json', other / '.shared-memory.json')
        private = self.root / 'other-state'
        before = inventory(self.root)
        result = self.setup(project=other, state=private, expected=4)
        self.assertEqual(result['code'], 'setup_access_required')
        self.assertEqual(set(result['data']['missing_inputs']), {'token_file', 'endpoint_or_database'})
        self.assertFalse(private.exists())
        self.assertEqual(inventory(self.root), before)
        self.assertEqual(json.loads((other / '.shared-memory.json').read_text())['project_id'], first['project_id'])

    def test_recipient_joins_using_own_issued_member_and_reruns_without_inputs(self):
        first = self.setup('--actor', 'owner')
        token = self.root / 'recipient.token'
        self.cli('member-add', self.project, '--state-dir', self.state, '--actor', 'recipient',
                 '--person', 'Recipient', '--agent', 'Own agent', '--token-output', token)
        recipient = self.root / 'Recipient folder'; recipient.mkdir()
        private = self.root / 'recipient-state'
        attached = self.setup('--database', self.state / 'coordinator.sqlite3', '--token-file', token,
                              '--expected-project-id', first['project_id'], project=recipient, state=private)
        self.assertEqual(attached['route'], 'attach')
        self.assertEqual(attached['readiness'], 'ready')
        self.assertEqual(attached['workspace_scope'], 'joined')
        self.assertEqual(attached['host_and_sharing'], 'unverified')
        self.assertEqual(attached['provider_delivery'], 'unverified')
        again = self.setup(project=recipient, state=private)
        self.assertEqual(again['route'], 'resume_attach')
        self.assertEqual((private / 'member.token').read_bytes(), token.read_bytes())
        self.assertNotEqual(token.read_bytes(), (self.state / 'member.token').read_bytes())
        self.assertEqual((recipient / 'Home.md').read_bytes(), (self.project / 'Home.md').read_bytes())

    def test_conflicting_explicit_resume_values_never_mutate_saved_setup(self):
        self.setup('--actor', 'owner', '--person', 'Original')
        before = inventory(self.root)
        for arguments in [('--actor', 'other'), ('--person', 'Other'), ('--provider', 'google-drive'),
                          ('--purpose', 'Changed'), ('--endpoint', 'https://example.invalid')]:
            with self.subTest(arguments=arguments):
                error = self.setup(*arguments, expected=3)
                self.assertEqual(error['code'], 'setup_mismatch')
                self.assertEqual(inventory(self.root), before)

    def test_older_successful_binding_without_intent_refreshes_without_reinitialization(self):
        first = self.setup()
        (self.state / 'setup-intent.json').unlink()
        before = digest(self.state / 'coordinator.sqlite3')
        result = self.setup()
        self.assertEqual(result['route'], 'existing_binding')
        self.assertEqual(result['project_id'], first['project_id'])
        self.assertEqual(digest(self.state / 'coordinator.sqlite3'), before)
        self.assertFalse((self.state / 'setup-intent.json').exists())

    def test_corrupt_intent_is_not_repaired_or_replaced(self):
        self.setup()
        path = self.state / 'setup-intent.json'
        value = json.loads(path.read_text()); value['token'] = 'x' * 48
        path.write_text(json.dumps(value))
        before = inventory(self.root)
        self.setup(expected=3)
        self.assertEqual(inventory(self.root), before)

    def test_legacy_marker_refused_without_state_or_migration(self):
        (self.project / 'Coordination').mkdir()
        before = inventory(self.root)
        result = self.setup(expected=4)
        self.assertEqual(result['code'], 'already_configured')
        self.assertFalse(self.state.exists())
        self.assertEqual(inventory(self.root), before)

    def test_join_evidence_on_unmarked_folder_never_falls_back_to_init(self):
        before = inventory(self.root)
        result = self.setup('--endpoint', 'https://example.invalid', expected=4)
        self.assertEqual(result['code'], 'setup_access_required')
        self.assertFalse(self.state.exists())
        self.assertEqual(inventory(self.root), before)

    def test_interrupted_setup_resumes_without_reentering_original_identity(self):
        arguments = ['setup', str(self.project), '--state-dir', str(self.state),
                     '--actor', 'interrupted-owner', '--person', 'Original Person']
        crashed = subprocess.run([sys.executable, str(REPO / 'product/tests/test_setup_recovery.py'),
                                  '--crash-worker', str(self.package), 'after-credential', json.dumps(arguments)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(crashed.returncode, 83, crashed.stdout + crashed.stderr)
        intent = (self.state / 'setup-intent.json').read_bytes()
        token = (self.state / 'member.token').read_bytes()
        result = self.setup()
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(result['project_id'], json.loads(intent)['project_id'])
        self.assertEqual((self.state / 'member.token').read_bytes(), token)
        self.assertEqual((self.state / 'setup-intent.json').read_bytes(), intent)
        self.assert_preserved()

    def test_existing_schema_two_normalized_configuration_and_history_preserved(self):
        config = self.root / 'coordination.json'
        config.write_text(json.dumps({'person_id': 'person-owner', 'agent_id': 'agent-owner', 'policy': {}}))
        self.cli('init', self.project, '--state-dir', self.state, '--actor', 'owner', '--person', 'Owner',
                 '--agent', 'Existing agent', '--purpose', 'Existing schema 2 project', '--coordination-file', config)
        intent = (self.state / 'setup-intent.json').read_bytes()
        before = digest(self.state / 'coordinator.sqlite3')
        config.unlink()  # Resume uses the durable normalized config, not this original input file.
        result = self.setup()
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(digest(self.state / 'coordinator.sqlite3'), before)
        self.assertEqual((self.state / 'setup-intent.json').read_bytes(), intent)
        policy = self.coord('policy', {})
        self.assertIn('policy', policy)

    def test_accepted_revision_and_events_survive_repeated_setup(self):
        self.setup('--actor', 'owner')
        self.coord('claim', {'assignment_id': 'work', 'targets': ['Result.md'], 'criteria': ['Exact bytes'],
                            'dependencies': [], 'resource_limits': {}, 'integration_owner': 'owner'})
        self.coord('propose', {'proposal_id': 'result', 'assignment_id': 'work', 'base_revision': 0,
                              'changes': {'Result.md': 'Accepted current history\r\n'}, 'evidence': 'Exact content'})
        self.coord('accept', {'proposal_id': 'result', 'validation': 'Exact content', 'reason': 'Accept output'})
        events = self.coord('events', {})
        snapshot = self.coord('snapshot', {})
        result = self.setup()
        self.assertEqual(result['receipt']['revision'], 1)
        self.assertEqual(result['receipt']['files_hash'], snapshot['files_hash'])
        self.assertEqual(self.coord('events', {}), events)
        self.assertEqual((self.project / 'Result.md').read_bytes(), b'Accepted current history\r\n')

    def test_owner_with_intended_provider_is_not_mislabeled_as_joined(self):
        result = self.setup('--provider', 'google-drive')
        self.assertEqual(result['workspace_scope'], 'local')
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(result['provider_delivery'], 'unverified')
        self.assertTrue(result['actor'].startswith('local-'))

    def test_preserved_modified_deletion_returns_actionable_partial_not_success(self):
        self.setup('--actor', 'owner')
        self.coord('claim', {'assignment_id': 'deletion', 'targets': ['Home.md'], 'criteria': ['Reviewed deletion'],
                            'dependencies': [], 'resource_limits': {}, 'integration_owner': 'owner'})
        self.coord('propose', {'proposal_id': 'delete-home', 'assignment_id': 'deletion', 'base_revision': 0,
                              'changes': {'Home.md': None}, 'evidence': 'Reviewed fixture deletion'})
        self.coord('accept', {'proposal_id': 'delete-home', 'validation': 'Reviewed fixture', 'reason': 'Bounded deletion'})
        edited = b'Keep offline edit after remote deletion\r\n'
        (self.project / 'Home.md').write_bytes(edited)
        result = self.setup(expected=4)
        self.assertEqual(result['code'], 'setup_incomplete')
        self.assertEqual(result['data']['readiness'], 'partial')
        self.assertTrue(result['data']['preserved_drafts'])
        self.assertEqual((self.project / 'Home.md').read_bytes(), edited)

    def private_project_fixture(self):
        files = {
            '.env': b'SYNTHETIC_ENV_SECRET_2cf78386=never_import\r\n',
            '.private.md': b'SYNTHETIC_ENV_SECRET_2cf78386 hidden Markdown\n',
            'member.token': b'SYNTHETIC_ENV_SECRET_2cf78386 own membership\n',
            'connection.json': b'{"private":"SYNTHETIC_ENV_SECRET_2cf78386"}\n',
            '.codex/history.jsonl': b'{"private":"SYNTHETIC_SESSION_81d9a5b4"}\n',
            'credentials/Account.md': b'# SYNTHETIC_CREDENTIAL_537ca0d7\r\n',
            'credentials/nested/session.json': b'{"private":"SYNTHETIC_NESTED_6162b68f"}',
        }
        for name, data in files.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        return files

    def assert_private_project_opaque(self, files):
        first = self.setup()
        second = self.setup()
        self.assertEqual(first['readiness'], 'ready')
        self.assertEqual(second['readiness'], 'ready')
        self.assertEqual(first['preserved_drafts'], [])
        self.assertEqual(second['preserved_drafts'], [])
        snapshot = self.coord('snapshot', {})
        for name, data in files.items():
            self.assertEqual((self.project / name).read_bytes(), data)
            self.assertNotIn(name, snapshot['files'])
        # Examine every generated state file, including authority, setup intent,
        # snapshot, drafts and backups. The synthetic private markers must never
        # be copied into any of them, even if the caller receives a ready receipt.
        markers = [b'SYNTHETIC_ENV_SECRET_2cf78386', b'SYNTHETIC_SESSION_81d9a5b4',
                   b'SYNTHETIC_CREDENTIAL_537ca0d7', b'SYNTHETIC_NESTED_6162b68f']
        for path in self.state.rglob('*'):
            if path.is_file():
                data = path.read_bytes()
                for marker in markers:
                    self.assertNotIn(marker, data, str(path.relative_to(self.state)))
        self.assert_preserved()

    def test_untracked_env_session_and_credentials_are_opaque_and_do_not_block_setup(self):
        self.assert_private_project_opaque(self.private_project_fixture())

    def test_untracked_venv_symlink_is_not_traversed_or_rejected_during_setup(self):
        files = self.private_project_fixture()
        outside = self.root / 'private-interpreter-fixture'
        outside.write_bytes(b'SYNTHETIC_OUTSIDE_EXECUTABLE_0be7d259')
        link = self.project / 'venv/bin/python'
        link.parent.mkdir(parents=True)
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Symlink creation unavailable on this host: ' + type(exc).__name__)
        before = digest(outside)
        target = os.readlink(link)
        self.assert_private_project_opaque(files)
        self.assertTrue(link.is_symlink())
        self.assertEqual(os.readlink(link), target)
        self.assertEqual(digest(outside), before)
        for path in self.state.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'SYNTHETIC_OUTSIDE_EXECUTABLE_0be7d259', path.read_bytes())


if __name__ == '__main__':
    unittest.main()
