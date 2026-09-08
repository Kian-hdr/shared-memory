"""Kill actual Coordinator acceptance at selected SQL/commit boundaries.

These tests exercise a real SQLite transaction in a spawned process. A connection
subclass pauses after the selected real SQL statement (or around real commit),
then the parent kills the process without allowing rollback/cleanup handlers.
This is local process-crash evidence, not every SQLite/filesystem internal boundary,
power-loss behavior, a remote transport result, or a production durability claim.
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import secrets
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))

from shared_workspace.engine import Coordinator


def acceptance_worker(database, token, payload, boundary, ready, release):
    """Interpose synchronization only; execute the actual coordinator and driver."""
    original_connect = sqlite3.connect
    statements = {
        'snapshot_insert': 'INSERT INTO snapshots ',
        'state_update': 'UPDATE meta SET value=',
        'proposal_state': 'UPDATE proposals SET status=',
        'conflict_cleanup': 'INSERT INTO conflicts(',
        'event_insert': 'INSERT INTO events(',
    }

    class PausedConnection(sqlite3.Connection):
        def stop_at_boundary(self):
            ready.send({'boundary': boundary, 'in_transaction': self.in_transaction,
                        'actual_changes': self.total_changes})
            if not release.wait(timeout=30):
                raise TimeoutError('Parent did not terminate the paused fixture process')

        def execute(self, statement, *args, **kwargs):
            result = super().execute(statement, *args, **kwargs)
            if boundary in statements and statement.startswith(statements[boundary]):
                self.stop_at_boundary()
            return result

        def commit(self):
            if boundary == 'before_commit':
                self.stop_at_boundary()
            super().commit()
            if boundary == 'after_commit':
                self.stop_at_boundary()

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=PausedConnection)
        # Exercise disk-backed dirty pages with the real DELETE journal instead
        # of relying on all modified data remaining in SQLite's page cache.
        connection.execute('PRAGMA cache_size=2')
        connection.execute('PRAGMA cache_spill=ON')
        return connection

    sqlite3.connect = connect
    try:
        result = Coordinator(database).request(token, 'accept', payload)
        ready.send({'unexpected_result': result})
    except Exception as error:
        ready.send({'unexpected_error': type(error).__name__, 'message': str(error)})
    finally:
        sqlite3.connect = original_connect
        ready.close()


class AcceptanceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = tempfile.TemporaryDirectory(prefix='shared-memory-accept-boundaries-')
        self.addCleanup(self.fixture.cleanup)
        self.db = Path(self.fixture.name) / 'authority.sqlite'
        self.engine = Coordinator(self.db)
        self.token = secrets.token_urlsafe(32)
        self.original_files = {'Home.md': '# Isolated boundary fixture\n',
                               'Notes/a.md': 'Original accepted fixture\n'}
        self.engine.initialize(str(uuid.uuid4()),
            {'actor': 'owner', 'human': 'Fictional Boundary Owner', 'agent': 'Independent test'},
            self.token, self.original_files)
        self.call('claim', {'assignment_id': 'work', 'targets': ['Notes/'],
            'criteria': ['Compare exact accepted bytes and retained history'],
            'dependencies': [], 'resource_limits': {'max_proposals': 4},
            'integration_owner': 'owner'})
        self.new_text = 'Accepted boundary fixture: café\n' * 8192
        self.accept_payload = {'proposal_id': 'candidate',
            'validation': 'Independent exact-byte review of synthetic fixture',
            'reason': 'Accept the bounded fixture update'}

    def call(self, operation, payload=None):
        return self.engine.request(self.token, operation, payload or {})

    def propose_candidate(self, claims=None):
        self.call('propose', {'proposal_id': 'candidate', 'assignment_id': 'work',
            'base_revision': self.call('snapshot')['revision'],
            'changes': {'Notes/a.md': self.new_text}, 'evidence': 'Original proposal evidence',
            'claims': claims or []})

    def durable_history(self):
        with closing(sqlite3.connect(self.db)) as connection:
            snapshots = connection.execute('SELECT * FROM snapshots ORDER BY revision').fetchall()
            events = connection.execute('SELECT * FROM events ORDER BY seq').fetchall()
            proposal_bytes = connection.execute(
                'SELECT id,request_json,request_hash FROM proposals ORDER BY id').fetchall()
        return {'snapshots': snapshots, 'events': events, 'proposal_bytes': proposal_bytes}

    def kill_acceptance(self, boundary):
        context = multiprocessing.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        release = context.Event()
        process = context.Process(target=acceptance_worker,
            args=(str(self.db), self.token, self.accept_payload, boundary, sender, release))
        try:
            process.start()
            sender.close()
            self.assertTrue(receiver.poll(20), 'Acceptance never reached ' + boundary)
            observed = receiver.recv()
            self.assertEqual(observed.get('boundary'), boundary, observed)
            self.assertEqual(observed['in_transaction'], boundary != 'after_commit')
            self.assertGreater(observed['actual_changes'], 0)
            self.assertTrue(process.is_alive(), 'Child must still be paused before response delivery')
            process.kill()
            process.join(timeout=10)
            self.assertFalse(process.is_alive(), 'Killed fixture process failed to exit')
            self.assertNotEqual(process.exitcode, 0)
        finally:
            if process.is_alive():
                process.kill(); process.join(timeout=5)
            receiver.close()
            sender.close()

    def assert_boundary(self, boundary, conflict_id=None):
        previous_snapshot = self.call('snapshot')
        previous_status = self.call('status')
        previous_proposal = self.call('proposal', {'proposal_id': 'candidate'})
        previous_history = self.durable_history()
        previous_conflict = self.call('conflict', {'conflict_id': conflict_id}) if conflict_id else None
        self.assertEqual(previous_proposal['status'], 'conflict' if conflict_id else 'pending')
        self.kill_acceptance(boundary)

        self.engine = Coordinator(self.db)
        recovery = self.engine.recover()
        self.assertFalse(recovery['logical_state_changed'])
        recovered_history = self.durable_history()
        self.assertEqual(recovered_history['proposal_bytes'], previous_history['proposal_bytes'])
        if boundary != 'after_commit':
            self.assertEqual(self.call('snapshot'), previous_snapshot)
            self.assertEqual(self.call('status'), previous_status)
            self.assertEqual(self.call('proposal', {'proposal_id': 'candidate'}), previous_proposal)
            self.assertEqual(recovered_history, previous_history)
            if conflict_id:
                self.assertEqual(self.call('conflict', {'conflict_id': conflict_id}), previous_conflict)
        else:
            self.assertEqual(self.call('snapshot')['revision'], previous_snapshot['revision'] + 1)
            self.assertEqual(self.call('snapshot')['files']['Notes/a.md'], self.new_text)
            self.assertEqual(self.call('proposal', {'proposal_id': 'candidate'})['status'], 'accepted')
            self.assertEqual(len(recovered_history['snapshots']), len(previous_history['snapshots']) + 1)
            self.assertEqual(len(recovered_history['events']), len(previous_history['events']) + 1)

        result = self.call('accept', self.accept_payload)
        self.assertTrue(result['accepted'])
        self.assertEqual(result['revision'], previous_snapshot['revision'] + 1)
        accepted = self.call('snapshot')
        expected_files = {**previous_snapshot['files'], 'Notes/a.md': self.new_text}
        self.assertEqual(accepted['files'], expected_files)
        expected_hash = hashlib.sha256(json.dumps(expected_files, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(accepted['files_hash'], expected_hash)
        final_history = self.durable_history()
        self.assertEqual(final_history['proposal_bytes'], previous_history['proposal_bytes'])
        self.assertEqual(final_history['snapshots'][:-1], previous_history['snapshots'])
        self.assertEqual(final_history['events'][:-1], previous_history['events'])
        accepted_events = [json.loads(row[1]) for row in final_history['events']
            if json.loads(row[1])['operation'] == 'accept'
            and json.loads(row[1])['data']['proposal_id'] == 'candidate']
        self.assertEqual(len(accepted_events), 1)
        if conflict_id:
            resolved = self.call('conflict', {'conflict_id': conflict_id})
            self.assertEqual(resolved['status'], 'resolved')
            for key in ('accepted', 'proposed', 'responsible_owner'):
                self.assertEqual(resolved[key], previous_conflict[key])
        if boundary == 'after_commit':
            self.assertTrue(result['idempotent'])
            self.assertEqual(final_history, recovered_history, 'Lost response must not create a second acceptance')

        self.engine = Coordinator(self.db)
        replay = self.call('accept', self.accept_payload)
        self.assertTrue(replay['idempotent'])
        self.assertEqual(self.call('snapshot'), accepted)
        self.assertEqual(self.durable_history(), final_history)

    def test_kill_after_snapshot_insert_rolls_back_before_retry(self):
        self.propose_candidate(); self.assert_boundary('snapshot_insert')

    def test_kill_after_current_revision_update_rolls_back_before_retry(self):
        self.propose_candidate(); self.assert_boundary('state_update')

    def test_kill_after_proposal_state_update_rolls_back_before_retry(self):
        self.propose_candidate(); self.assert_boundary('proposal_state')

    def test_kill_after_conflict_cleanup_preserves_dispute_before_retry(self):
        initial_claim = {'key': 'capacity', 'value': '10', 'source': 'fixture/source-a', 'authority': 'owner'}
        self.call('propose', {'proposal_id': 'baseline-fact', 'assignment_id': 'work', 'base_revision': 0,
            'changes': {}, 'claims': [initial_claim], 'evidence': 'Reviewed original synthetic fact'})
        self.call('accept', {**self.accept_payload, 'proposal_id': 'baseline-fact'})
        self.propose_candidate([{**initial_claim, 'value': '20', 'source': 'fixture/source-b'}])
        disputed = self.call('accept', self.accept_payload)
        self.assertFalse(disputed['accepted'])
        conflict_id = disputed['conflicts'][0]['conflict_id']
        self.call('resolve', {'proposal_id': 'candidate', 'resolutions': [
            {**initial_claim, 'value': '20', 'source': 'fixture/owner-resolution',
             'reason': 'Responsible owner reviewed both synthetic sources'}]})
        self.assert_boundary('conflict_cleanup', conflict_id)

    def test_kill_after_acceptance_event_insert_rolls_back_before_retry(self):
        self.propose_candidate(); self.assert_boundary('event_insert')

    def test_kill_before_commit_rolls_back_all_acceptance_writes(self):
        self.propose_candidate(); self.assert_boundary('before_commit')

    def test_kill_after_commit_loses_response_but_retry_accepts_exactly_once(self):
        self.propose_candidate(); self.assert_boundary('after_commit')


if __name__ == '__main__':
    unittest.main(verbosity=2)
