"""Actual packaged session/coordination/migration CLI acceptance.

Fixtures are synthetic, local and private. The lost-response test uses the real
ASGI app over loopback; it does not establish provider or mixed-device delivery.
"""
from __future__ import annotations

from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer

import test_team_cli as helpers


class LostSessionAck(helpers.ASGIBridge):
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        request = json.loads(raw)
        self.rfile = io.BytesIO(raw)
        lose = self.server.lose_ack and request.get('operation') == 'session-open'
        if not lose:
            return super().do_POST()
        self.server.lose_ack = False
        self.server.lost_responses += 1
        original = self.wfile
        self.wfile = io.BytesIO()
        try:
            super().do_POST()  # Real authority commits before its response is discarded.
        finally:
            self.wfile = original
            self.close_connection = True


class CoordinationCLITests(unittest.TestCase):
    # Reuse the existing actual-package builder and selected-folder fixtures
    # without inheriting and rerunning its unrelated tests.
    setUpClass = classmethod(helpers.TeamCLITests.setUpClass.__func__)
    setUp = helpers.TeamCLITests.setUp
    cli = helpers.TeamCLITests.cli

    def json_input(self, value, name=None):
        path = self.root / (name or ('input-' + str(uuid.uuid4()) + '.json'))
        path.write_bytes(json.dumps(value).encode('utf-8'))
        return path

    def initialize(self, enhanced=True):
        self.config = {'person_id': 'person-alex', 'agent_id': 'agent-alex', 'policy': {}}
        self.config_file = self.json_input(self.config, 'coordination.json')
        extra = ['--coordination-file', self.config_file] if enhanced else []
        result = self.cli('init', None, None, '--person', 'Alex Fictional', '--actor', 'alex',
                          '--agent', 'Packaged coordination fixture', '--purpose', 'Bounded session acceptance', *extra)
        self.project_id = result['project_id']
        self.db = self.state / 'coordinator.sqlite3'
        return result

    def coord(self, operation, payload=None, *, session=None, expected=0):
        options = ['--payload-file', self.json_input(payload or {})]
        if session:
            options += ['--session-token-file', session]
        return self.cli('coord', None, None, operation, *options, expected=expected)

    def raw_cli(self, command, *args, expected=0):
        result = subprocess.run([sys.executable, str(self.archive), command, *map(str, args)],
                                cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['ok'], expected == 0)
        self.outputs.append(output)
        return output['data']

    def sessions(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return connection.execute('SELECT * FROM coord_sessions ORDER BY id').fetchall()

    def event_rows(self):
        with closing(sqlite3.connect(self.db)) as connection:
            return connection.execute('SELECT * FROM events ORDER BY seq').fetchall()

    def create_session(self, identity, scopes=None, targets=None, *, parent=None, to_actor=None, expected=0):
        scopes = scopes or self.coord('policy')['policy']['session_scopes']['owner']
        grants = {'ttl_seconds': 300 if parent else 1800, 'scopes': scopes, 'targets': targets or ['.']}
        path = self.json_input(grants)
        options = ['--session-id', identity, '--grants-file', path]
        if parent:
            options += ['--session-token-file', parent, '--delegate-to', to_actor]
        result = self.cli('session-create', None, None, *options, expected=expected)
        if expected:
            return result
        token = Path(result['credential_file'])
        self.assertEqual(token.read_bytes().strip(), (self.state / 'sessions' / identity / 'session.token').read_bytes().strip())
        self.assertTrue(result['credential_saved'])
        self.assertFalse(result['automatic_renewal'])
        self.assertNotIn(token.read_text().strip(), json.dumps(self.outputs))
        return token, result, path

    def plan_and_acquire(self, session, identity='work', targets=None):
        policy = self.coord('policy')['policy_revision']
        self.coord('plan', {'assignment_id': identity, 'outcome_key': 'outcome-' + identity,
            'summary': 'Deliver synthetic ' + identity, 'targets': targets or ['Result.md'],
            'criteria': ['Compare exact fixture bytes'], 'dependencies': [], 'interface_paths': [],
            'resource_limits': {}, 'integration_owner': 'alex', 'policy_revision': policy}, session=session)
        return self.acquire(session, identity)

    def acquire(self, session, identity='work'):
        item = self.coord('assignment', {'assignment_id': identity})
        snapshot = self.coord('snapshot')
        return self.coord('acquire', {'assignment_id': identity, 'expected_generation': item['generation'],
            'ttl_seconds': 120, 'revision': snapshot['revision'], 'files_hash': snapshot['files_hash'],
            'policy_revision': self.coord('policy')['policy_revision']}, session=session)

    def context(self, identity='work', session_id='owner-run'):
        item = self.coord('assignment', {'assignment_id': identity})
        return {'session_id': session_id, 'generation': item['generation'], 'input_hash': item['input_hash'],
                'policy_revision': self.coord('policy')['policy_revision']}

    def draft(self, proposal, context, *, assignment='work', expected=0):
        return self.cli('draft', None, None, '--proposal-id', proposal, '--assignment-id', assignment,
                        '--evidence', 'Exact fixture edit', '--coordination-file', self.json_input(context), expected=expected)

    def submit(self, proposal, session=None, expected=0):
        options = ['--proposal-id', proposal]
        if session:
            options += ['--session-token-file', session]
        return self.cli('submit', None, None, *options, expected=expected)

    def test_opt_in_init_and_default_legacy_schema_preserve_private_parent(self):
        self.initialize(False)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
        before = self.db.read_bytes()
        grants = self.json_input({'ttl_seconds': 300, 'scopes': ['status'], 'targets': ['.']})
        self.cli('session-create', None, None, '--session-id', 'unsupported', '--grants-file', grants, expected=3)
        self.assertFalse((self.state / 'sessions').exists())
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual((self.project.parent / 'Private.md').read_text(), 'PRIVATE-PARENT')

    def test_session_credential_retry_changed_grants_and_actual_session_authorization(self):
        self.initialize()
        token, first, grants = self.create_session('limited', scopes=['status', 'policy'])
        intent = self.state / 'sessions/limited/intent.json'
        original = (token.read_bytes(), intent.read_bytes(), self.sessions(), self.event_rows())
        retry = self.cli('session-create', None, None, '--session-id', 'limited', '--grants-file', grants)
        self.assertEqual(retry['session'], first['session'])
        self.assertEqual((token.read_bytes(), intent.read_bytes(), self.sessions(), self.event_rows()), original)
        if os.name != 'nt':
            self.assertEqual(token.stat().st_mode & 0o077, 0)
            self.assertEqual(intent.stat().st_mode & 0o077, 0)
        changed = self.json_input({'ttl_seconds': 301, 'scopes': ['status', 'policy'], 'targets': ['.']})
        self.cli('session-create', None, None, '--session-id', 'limited', '--grants-file', changed, expected=3)
        self.assertEqual((token.read_bytes(), intent.read_bytes(), self.sessions(), self.event_rows()), original)
        self.coord('policy', session=token)
        # The owner member token could update policy, but this limited session cannot.
        self.coord('policy-update', {'expected_revision': 1, 'policy': {}, 'reason': 'Must respect actual token'},
                   session=token, expected=4)
        self.assertEqual(self.coord('policy')['policy_revision'], 1)
        self.coord('session-open', {'session_id': 'unsafe'}, expected=2)

    def test_empty_explicit_credentials_never_fall_back_to_owner(self):
        initial_files = helpers.file_bytes(self.project)
        self.cli('init', None, None, '--person', 'Alex Fictional', '--actor', 'alex',
                 '--agent', 'Fixture', '--purpose', 'Must retain explicit schema choice',
                 '--coordination-file', '', expected=2)
        self.assertEqual(helpers.file_bytes(self.project), initial_files)
        self.assertFalse(self.state.exists())
        self.initialize()
        self.cli('draft', None, None, '--proposal-id', 'empty-context', '--assignment-id', 'work',
                 '--evidence', 'Must retain explicit context', '--coordination-file', '', expected=2)
        self.assertFalse((self.state / 'client/drafts/empty-context.json').exists())
        payload = self.json_input({'expected_revision': 1, 'policy': {}, 'reason': 'Must not use owner fallback'})
        before = self.db.read_bytes()
        for value in ('', '   '):
            self.cli('coord', None, None, 'policy-update', '--payload-file', payload,
                     '--session-token-file', value, expected=2)
            self.assertEqual(self.db.read_bytes(), before)
        grants = self.json_input({'ttl_seconds': 300, 'scopes': ['policy'], 'targets': ['.']})
        for options in (['--delegate-to', '', '--session-token-file', ''],
                        ['--delegate-to', 'alex', '--session-token-file', ''],
                        ['--delegate-to', 'alex', '--session-token-file', '   '],
                        ['--session-token-file', ''], ['--delegate-to', '']):
            self.cli('session-create', None, None, '--session-id', 'empty-parent',
                     '--grants-file', grants, *options, expected=2)
            self.assertEqual(self.db.read_bytes(), before)
            self.assertFalse((self.state / 'sessions').exists())
        from shared_workspace.workflow import connect
        from shared_workspace.errors import ProductError
        with self.assertRaises(ProductError):
            connect(self.state, '')
        self.assertEqual(self.db.read_bytes(), before)

    def test_lost_response_preserves_session_credential_and_retries_same_actual_session(self):
        self.initialize()
        from shared_workspace.transport import CoordinatorApp
        server = ThreadingHTTPServer(('127.0.0.1', 0), LostSessionAck)
        server.application = CoordinatorApp(self.db)
        server.requests_seen = 0
        server.redirect = None
        server.lose_ack = True
        server.lost_responses = 0
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
        thread.start()
        def close():
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        self.addCleanup(close)
        connection = {'protocol': 1, 'transport': 'https', 'endpoint': 'http://127.0.0.1:' + str(server.server_port),
                      'ca_file': None, 'mode': 'team'}
        (self.state / 'connection.json').write_bytes(json.dumps(connection).encode())
        grants = self.json_input({'ttl_seconds': 1800, 'scopes': ['status', 'policy'], 'targets': ['.']})
        args = ['--session-id', 'lost-ack', '--grants-file', grants]
        self.cli('session-create', None, None, *args, expected=5)
        token = self.state / 'sessions/lost-ack/session.token'
        saved = token.read_bytes()
        records = self.sessions()
        self.assertEqual(len(records), 1)
        retry = self.cli('session-create', None, None, *args)
        self.assertEqual(retry['session']['session_id'], 'lost-ack')
        self.assertEqual(token.read_bytes(), saved)
        self.assertEqual(self.sessions(), records)
        self.assertEqual(server.lost_responses, 1)
        self.coord('policy', session=token)

    def test_delegation_scope_targets_and_parent_revocation_enforced_by_package(self):
        self.initialize()
        member_file = self.root / 'sam.token'
        self.cli('member-add', None, None, '--actor', 'sam', '--person', 'Sam Fictional', '--agent', 'Test',
                 '--token-output', member_file)
        self.coord('member-binding', {'actor': 'sam', 'person_id': 'person-sam', 'agent_id': 'agent-sam'})
        parent, _, _ = self.create_session('parent', scopes=['status', 'policy', 'plan', 'assignment', 'session-delegate'],
                                          targets=['Notes/'])
        before = (self.sessions(), self.event_rows())
        self.create_session('other-actor', scopes=['status', 'policy', 'plan', 'assignment'],
            targets=['Notes/sub/'], parent=parent, to_actor='sam', expected=4)
        self.assertEqual((self.sessions(), self.event_rows()), before)
        child, result, _ = self.create_session('child', scopes=['status', 'policy', 'plan', 'assignment'],
            targets=['Notes/sub/'], parent=parent, to_actor='alex')
        self.assertEqual(result['session']['actor'], 'alex')
        self.assertEqual(result['session']['parent_session_id'], 'parent')
        self.assertEqual(self.coord('policy', session=child)['policy_revision'], 1)
        # The preflight may use membership identity, but the requested global
        # operation must still be denied to this narrower session.
        self.coord('status', session=child, expected=4)
        self.create_session('expanded-scope', scopes=['status', 'accept'], targets=['Notes/sub/'],
                            parent=parent, to_actor='alex', expected=4)
        self.create_session('expanded-target', scopes=['status', 'policy'], targets=['.'],
                            parent=parent, to_actor='alex', expected=4)
        payload = {'assignment_id': 'outside', 'outcome_key': 'outside-outcome', 'summary': 'Synthetic denied target',
                   'targets': ['Private.md'], 'criteria': ['Must reject'], 'dependencies': [], 'interface_paths': [],
                   'resource_limits': {}, 'integration_owner': 'alex', 'policy_revision': 1}
        self.coord('plan', payload, session=child, expected=4)
        self.coord('plan', dict(payload, assignment_id='inside', outcome_key='inside-outcome', targets=['Notes/sub/Result.md']), session=child)
        self.coord('session-revoke', {'session_id': 'parent', 'reason': 'End synthetic delegation'})
        self.coord('policy', session=child, expected=4)

    def test_immutable_drafts_reject_stale_generation_policy_and_wrong_session_then_complete_fresh(self):
        self.initialize()
        session, _, _ = self.create_session('owner-run')
        self.plan_and_acquire(session)
        original_context = self.context()
        (self.project / 'Result.md').write_bytes('SYNTHETIC ACCEPTED 終わり\r\n'.encode())
        draft = self.draft('old-generation', original_context)
        stored = self.state / 'client/drafts/old-generation.json'
        original_bytes = stored.read_bytes()
        self.assertEqual(draft['coordination'], original_context)
        self.draft('old-generation', dict(original_context, generation=original_context['generation'] + 1), expected=4)
        self.assertEqual(stored.read_bytes(), original_bytes)
        self.submit('old-generation', expected=4)  # Member credential cannot substitute a session.
        other, _, _ = self.create_session('other-run')
        self.submit('old-generation', other, expected=4)
        self.coord('release', {'assignment_id': 'work', 'generation': original_context['generation'],
                              'policy_revision': 1, 'reason': 'Move to a fresh generation'}, session=session)
        acquired = self.acquire(session)
        self.assertGreater(acquired['generation'], original_context['generation'])
        self.submit('old-generation', session, expected=4)
        policy_context = self.context()
        self.draft('old-policy', policy_context)
        policy_bytes = (self.state / 'client/drafts/old-policy.json').read_bytes()
        self.coord('policy-update', {'expected_revision': 1, 'policy': {'max_session_seconds': 3599},
                                    'reason': 'Change a relevant session constraint'})
        self.submit('old-policy', session, expected=4)
        self.assertEqual(stored.read_bytes(), original_bytes)
        self.assertEqual((self.state / 'client/drafts/old-policy.json').read_bytes(), policy_bytes)
        current = self.context()
        self.draft('fresh', current)
        self.submit('fresh', session)
        accepted = self.coord('accept', {'proposal_id': 'fresh', 'validation': 'Exact fixture bytes reviewed',
            'reason': 'Fresh session context accepted', 'coordination': current}, session=session)
        self.assertTrue(accepted['accepted'])
        self.cli('refresh')
        snapshot = self.coord('snapshot')
        completed = self.coord('complete', {'assignment_id': 'work', 'revision': snapshot['revision'],
            'files_hash': snapshot['files_hash'], 'evidence': 'Actual refreshed bytes match', 'coordination': current}, session=session)
        self.assertEqual(completed['status'], 'completed')
        self.assertEqual(snapshot['files']['Result.md'].encode(), (self.project / 'Result.md').read_bytes())

    def test_promoted_preserved_edit_keeps_original_bytes_and_immutable_coordination(self):
        self.initialize()
        session, _, _ = self.create_session('owner-run')
        self.plan_and_acquire(session, targets=['Home.md'])
        context = self.context()
        snapshot = self.coord('snapshot')
        (self.project / 'Home.md').write_bytes(b'PRIVATE LOCAL EDIT TO PRESERVE\r\n')
        self.coord('propose', {'proposal_id': 'remote', 'assignment_id': 'work', 'base_revision': snapshot['revision'],
            'changes': {'Home.md': 'Remote accepted bytes'}, 'evidence': 'Synthetic remote change', 'coordination': context}, session=session)
        self.coord('accept', {'proposal_id': 'remote', 'validation': 'Compare exact remote bytes',
                             'reason': 'Exercise real preservation', 'coordination': context}, session=session)
        refreshed = self.cli('refresh')
        preserved = next(identity for identity in refreshed['drafts'] if identity.startswith('preserved-'))
        preserved_path = self.state / 'client/drafts' / (preserved + '.json')
        original = preserved_path.read_bytes()
        args = ['--preserved-id', preserved, '--proposal-id', 'promoted', '--assignment-id', 'work',
                '--evidence', 'Owner reviewed preserved original', '--coordination-file', self.json_input(context)]
        promoted = self.cli('promote-draft', None, None, *args)
        self.assertEqual(promoted['coordination'], context)
        self.assertEqual(promoted['changes']['Home.md'].encode(), b'PRIVATE LOCAL EDIT TO PRESERVE\r\n')
        self.assertEqual(promoted['base_revision'], snapshot['revision'])
        path = self.state / 'client/drafts/promoted.json'
        immutable = path.read_bytes()
        self.cli('promote-draft', None, None, *args[:-1], self.json_input(dict(context, generation=context['generation'] + 1)), expected=4)
        self.assertEqual(path.read_bytes(), immutable)
        self.assertEqual(preserved_path.read_bytes(), original)
        self.submit('promoted', session)
        self.assertEqual(self.coord('proposal', {'proposal_id': 'promoted'})['changes'], promoted['changes'])

    def test_packaged_migration_is_explicit_preserves_history_and_hides_private_backup_from_reader(self):
        self.initialize(False)
        reader = self.root / 'reader.token'
        self.cli('member-add', None, None, '--actor', 'reader', '--person', 'Synthetic reader', '--agent', 'Test',
                 '--role', 'reader', '--token-output', reader)
        self.coord('claim', {'assignment_id': 'legacy', 'targets': ['Legacy.md'], 'criteria': ['Keep request'],
                            'dependencies': [], 'resource_limits': {}, 'integration_owner': 'alex'})
        self.coord('propose', {'proposal_id': 'legacy-pending', 'assignment_id': 'legacy', 'base_revision': 0,
                              'changes': {'Legacy.md': 'Pending original'}, 'evidence': 'Immutable legacy request'})
        original_events = self.event_rows()
        with closing(sqlite3.connect(self.db)) as connection:
            original_proposals = connection.execute('SELECT * FROM proposals ORDER BY id').fetchall()
        common = ['--database', self.db, '--token-file', self.state / 'member.token',
                  '--expected-project-id', self.project_id, '--coordination-file', self.config_file]
        before = self.db.read_bytes()
        plan = self.raw_cli('coordination-plan-upgrade', *common)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(plan['schema_version'], 1)
        self.assertEqual(plan['legacy_proposals_requiring_new_context'], 1)
        backup = self.root / 'private-before-upgrade.sqlite3'
        options = [*common, '--expected-checkpoint', plan['checkpoint'], '--backup-destination', backup,
                   '--migration-id', 'packaged-upgrade']
        upgraded = self.raw_cli('coordination-upgrade', *options)
        self.assertEqual(upgraded['backup_destination'], str(backup.resolve()))
        with closing(sqlite3.connect(backup)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
            self.assertEqual(connection.execute('SELECT * FROM events ORDER BY seq').fetchall(), original_events)
        with closing(sqlite3.connect(self.db)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 2)
            self.assertEqual(connection.execute('SELECT * FROM proposals ORDER BY id').fetchall(), original_proposals)
        self.assertEqual(self.event_rows()[:-1], original_events)
        self.assertNotIn(str(backup.resolve()), json.dumps(self.coord('events', session=reader)))
        before_retry = self.db.read_bytes()
        self.assertTrue(self.raw_cli('coordination-upgrade', *options)['idempotent'])
        self.assertEqual(self.db.read_bytes(), before_retry)
        self.coord('accept', {'proposal_id': 'legacy-pending', 'validation': 'Must require rebind', 'reason': 'No automatic migration'}, expected=4)
        session, _, _ = self.create_session('post-upgrade')
        self.assertEqual(self.coord('policy', session=session)['policy_revision'], 1)

    def test_revoked_session_cannot_submit_and_fresh_owner_reacquires_without_changing_old_draft(self):
        self.initialize()
        old, _, _ = self.create_session('owner-run')
        first = self.plan_and_acquire(old)
        (self.project / 'Result.md').write_bytes(b'Original offline proposal bytes')
        self.draft('revoked-session-draft', self.context())
        path = self.state / 'client/drafts/revoked-session-draft.json'
        original = path.read_bytes()
        self.coord('session-revoke', {'session_id': 'owner-run', 'reason': 'End stale running session'})
        events = self.event_rows()
        self.submit('revoked-session-draft', old, expected=4)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.event_rows(), events)
        fresh, _, _ = self.create_session('new-run')
        reacquired = self.acquire(fresh)
        self.assertGreater(reacquired['generation'], first['generation'])
        self.submit('revoked-session-draft', fresh, expected=4)
        self.draft('new-session-draft', self.context(session_id='new-run'))
        self.submit('new-session-draft', fresh)
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.coord('proposal', {'proposal_id': 'new-session-draft'})['changes'],
                         {'Result.md': 'Original offline proposal bytes'})


if __name__ == '__main__':
    unittest.main()
