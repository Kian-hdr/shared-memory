"""Actual coordinator acceptance on isolated local SQLite, not provider evidence."""
from __future__ import annotations

import hashlib
import importlib
import json
import multiprocessing
import secrets
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace.errors import ProductError


@contextmanager
def database(path):
    connection = sqlite3.connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def canonical_hash(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False).encode()).hexdigest()


def request_worker(db, token, operation, payload, barrier, results):
    """Real separate process; no coordinator state model or fake lock."""
    try:
        Coordinator = importlib.import_module('shared_workspace.engine').Coordinator
        coordinator = Coordinator(db)
        barrier.wait(timeout=15)
        result = coordinator.request(token, operation, payload)
        results.put({'ok': True, 'result': result})
    except ProductError as exc:
        results.put({'ok': False, 'exit_code': exc.exit_code, 'message': str(exc)})
    except Exception as exc:
        results.put({'ok': False, 'unexpected': type(exc).__name__ + ': ' + str(exc)})


def hot_journal_worker(db, ready, stop):
    """Spill real SQLite dirty pages while leaving an uncommitted transaction alive."""
    connection = sqlite3.connect(db)
    connection.execute('PRAGMA journal_mode=DELETE')
    connection.execute('PRAGMA cache_size=2')
    connection.execute('PRAGMA cache_spill=ON')
    connection.execute('BEGIN IMMEDIATE')
    connection.execute('UPDATE snapshots SET files_json=? WHERE revision=0',
                       (json.dumps({'Home.md': 'UNCOMMITTED-' + ('x' * (4 * 1024 * 1024))}),))
    journal = Path(str(db) + '-journal')
    header = journal.read_bytes()[:8] if journal.is_file() else b''
    ready.send({'hot_header': bool(header and header != b'\x00' * 8),
                'journal_bytes': journal.stat().st_size if journal.is_file() else 0})
    ready.close()
    stop.wait(timeout=30)
    connection.rollback()
    connection.close()


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = importlib.import_module('shared_workspace.engine')
        cls.Coordinator = cls.module.Coordinator

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='shared-memory-engine-')
        self.addCleanup(self.temporary.cleanup)
        self.db = Path(self.temporary.name) / 'private-coordinator.sqlite'
        self.engine = self.Coordinator(self.db)
        self.project_id = str(uuid.uuid4())
        self.owner = secrets.token_urlsafe(32)
        self.bob = secrets.token_urlsafe(32)
        self.reader = secrets.token_urlsafe(32)
        self.files = {'Notes/a.md': 'Original A\n', 'Notes/b.md': 'Original B\n', 'Home.md': '# Shared fixture\n'}
        self.engine.initialize(self.project_id, {'actor': 'owner', 'human': 'Owner Fictional',
            'agent': 'Independent test'}, self.owner, self.files)
        self.call('member', {'actor': 'bob', 'human': 'Bob Fictional', 'agent': 'Independent test',
            'role': 'contributor', 'token': self.bob})
        self.call('member', {'actor': 'reader', 'human': 'Reader Fictional', 'agent': 'Independent test',
            'role': 'reader', 'token': self.reader})

    def call(self, operation, payload=None, token=None):
        result = self.engine.request(token or self.owner, operation, payload or {})
        json.dumps(result)
        return result

    def snapshot(self):
        return self.call('snapshot')

    def stored_proposal(self, identity):
        with database(self.db) as connection:
            row = connection.execute('SELECT request_json FROM proposals WHERE id=?', (identity,)).fetchone()
        self.assertIsNotNone(row)
        return json.loads(row[0])

    def claim(self, identity='assignment-a', targets=None, token=None, dependencies=None):
        return self.call('claim', {'assignment_id': identity, 'targets': targets or ['Notes/a.md'],
            'criteria': ['Exact fixture content reviewed'], 'dependencies': dependencies or [],
            'resource_limits': {'max_proposals': 4}, 'integration_owner': 'owner'}, token)

    def proposal(self, identity, assignment='assignment-a', changes=None, base=None, token=None, claims=None):
        return self.call('propose', {'proposal_id': identity, 'assignment_id': assignment,
            'base_revision': self.snapshot()['revision'] if base is None else base,
            'changes': changes or {'Notes/a.md': 'Updated A\n'},
            'evidence': 'Independent test compared fixture bytes.', 'claims': claims or []}, token)

    def accept(self, identity, token=None, resolutions=None):
        payload = {'proposal_id': identity, 'validation': 'Fixture content and source reviewed.',
                   'reason': 'Accept the bounded reviewed proposal.'}
        if resolutions is not None:
            payload['resolutions'] = resolutions
        return self.call('accept', payload, token)

    def rejected(self, operation, payload, token=None, code=4):
        with self.assertRaises(ProductError) as error:
            self.call(operation, payload, token)
        self.assertEqual(error.exception.exit_code, code)

    def parallel(self, calls):
        context = multiprocessing.get_context('spawn')
        barrier = context.Barrier(len(calls) + 1)
        results = context.Queue()
        processes = [context.Process(target=request_worker,
            args=(self.db, token, operation, payload, barrier, results))
            for token, operation, payload in calls]
        try:
            for process in processes:
                process.start()
            barrier.wait(timeout=15)
            outcomes = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertFalse(process.is_alive(), 'Concurrent process did not finish')
                self.assertEqual(process.exitcode, 0)
            for outcome in outcomes:
                self.assertNotIn('unexpected', outcome, outcome)
            return outcomes
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate(); process.join(timeout=5)
            results.close()
            results.join_thread()

    def test_initialize_snapshot_history_and_secret_redaction(self):
        initial = self.snapshot()
        self.assertEqual(initial['project_id'], self.project_id)
        self.assertEqual(initial['files'], self.files)
        self.assertEqual(initial['files_hash'], canonical_hash(self.files))
        status = self.call('status')
        before_events = self.call('events')
        self.call('status'); self.call('snapshot')
        self.assertEqual(self.call('events'), before_events)
        exported = json.dumps([initial, status, before_events])
        for token in [self.owner, self.bob, self.reader]:
            self.assertNotIn(token, exported)
            self.assertNotIn(hashlib.sha256(token.encode()).hexdigest(), exported)
            self.assertNotIn(token.encode(), self.db.read_bytes())
        with self.assertRaises(ProductError):
            self.engine.initialize(self.project_id, {'actor': 'other', 'human': 'Other', 'agent': 'Test'},
                                   secrets.token_urlsafe(32), self.files)
        self.assertEqual(self.snapshot(), initial)

    def test_authentication_roles_and_revocation(self):
        initial = self.snapshot()
        with self.assertRaises(ProductError):
            self.call('status', token=secrets.token_urlsafe(32))
        with self.assertRaises(ProductError):
            self.claim(token=self.reader)
        self.claim(token=self.bob)
        self.proposal('proposal-bob', token=self.bob)
        self.rejected('accept', {'proposal_id': 'proposal-bob', 'validation': 'reviewed', 'reason': 'try'}, token=self.bob)
        self.call('revoke', {'actor': 'bob'})
        for operation, payload in [('status', {}), ('snapshot', {}), ('propose', {
            'proposal_id': 'after-revoke', 'assignment_id': 'assignment-a', 'base_revision': initial['revision'],
            'changes': {'Notes/a.md': 'Unauthorised'}, 'evidence': 'fixture'})]:
            with self.subTest(operation=operation), self.assertRaises(ProductError):
                self.call(operation, payload, self.bob)
        self.rejected('revoke', {'actor': 'owner'})
        self.assertEqual(self.snapshot(), initial)

    def test_barrier_concurrent_claims_only_one_owner(self):
        payload = {'targets': ['Notes/'], 'criteria': ['Review note'], 'dependencies': [],
                   'resource_limits': {'max_proposals': 4}, 'integration_owner': 'owner'}
        outcomes = self.parallel([
            (self.owner, 'claim', {**payload, 'assignment_id': 'owner-claim'}),
            (self.bob, 'claim', {**payload, 'assignment_id': 'bob-claim'})])
        self.assertEqual(sum(o['ok'] for o in outcomes), 1, outcomes)
        self.assertEqual([o['exit_code'] for o in outcomes if not o['ok']], [4])
        self.assertEqual(len(self.call('status')['assignments']), 1)

    def test_barrier_same_base_conflict_preserves_both_proposals(self):
        self.claim()
        initial = self.snapshot()
        self.proposal('left', changes={'Notes/a.md': 'LEFT\n'}, base=initial['revision'])
        self.proposal('right', changes={'Notes/a.md': 'RIGHT\n'}, base=initial['revision'])
        outcomes = self.parallel([(self.owner, 'accept', {'proposal_id': identity,
            'validation': 'Independent explicit review.', 'reason': 'Concurrent acceptance fixture'})
            for identity in ['left', 'right']])
        self.assertTrue(all(o['ok'] for o in outcomes), outcomes)
        accepted = self.snapshot()
        self.assertEqual(accepted['revision'], initial['revision'] + 1)
        self.assertIn(accepted['files']['Notes/a.md'], ['LEFT\n', 'RIGHT\n'])
        self.assertEqual(sum(o['result'].get('status') == 'conflict' for o in outcomes), 1)
        status = self.call('status')
        self.assertTrue(status['conflicts'])
        serialized = json.dumps([self.stored_proposal('left'), self.stored_proposal('right')])
        self.assertIn('LEFT', serialized); self.assertIn('RIGHT', serialized)
        self.assertEqual(self.call('snapshot', {'revision': initial['revision']}), initial)

    def test_independent_stale_changes_rebase_with_validation(self):
        self.claim('a', ['Notes/a.md']); self.claim('b', ['Notes/b.md'], self.bob)
        base = self.snapshot()['revision']
        self.proposal('proposal-a', 'a', {'Notes/a.md': 'New A\n'}, base)
        self.proposal('proposal-b', 'b', {'Notes/b.md': 'New B\n'}, base, self.bob)
        self.accept('proposal-a'); self.accept('proposal-b')
        snapshot = self.snapshot()
        self.assertEqual(snapshot['revision'], base + 2)
        self.assertEqual(snapshot['files']['Notes/a.md'], 'New A\n')
        self.assertEqual(snapshot['files']['Notes/b.md'], 'New B\n')
        self.assertFalse(self.call('status')['conflicts'])

    def test_identical_results_and_stable_proposal_retries_deduplicate(self):
        self.claim()
        base = self.snapshot()['revision']
        self.proposal('first', base=base)
        before_retry = self.call('status')
        self.proposal('first', base=base)
        self.assertEqual(self.call('status'), before_retry)
        self.proposal('same-result', base=base)
        self.accept('first')
        accepted = self.snapshot()
        self.accept('first'); self.accept('same-result')
        self.assertEqual(self.snapshot(), accepted)
        with self.assertRaises(ProductError):
            self.proposal('first', changes={'Notes/a.md': 'Altered retry'}, base=base)
        self.assertEqual(self.snapshot(), accepted)

    def test_semantic_contradiction_requires_responsible_owner_decision(self):
        self.claim('a', ['Notes/a.md']); self.claim('b', ['Notes/b.md'], self.bob)
        base = self.snapshot()['revision']
        self.proposal('fact-a', 'a', {'Notes/a.md': 'Capacity is 10.'}, base,
            claims=[{'key': 'capacity', 'value': '10', 'source': 'fixture/source-a', 'authority': 'owner'}])
        self.accept('fact-a')
        accepted = self.snapshot()
        self.proposal('fact-b', 'b', {'Notes/b.md': 'Capacity is 20.'}, base, self.bob,
            claims=[{'key': 'capacity', 'value': '20', 'source': 'fixture/source-b', 'authority': 'owner'}])
        conflict = self.accept('fact-b')
        self.assertEqual(conflict['status'], 'conflict')
        self.assertEqual(self.snapshot(), accepted)
        self.assertTrue(self.call('status')['conflicts'])
        resolution = {'key': 'capacity', 'value': '20', 'source': 'fixture/owner-reviewed-evidence',
                      'reason': 'Owner explicitly reviewed conflicting synthetic sources.', 'authority': 'owner'}
        with self.assertRaises(ProductError):
            self.accept('fact-b', self.bob, [resolution])
        self.assertEqual(self.snapshot(), accepted)
        self.accept('fact-b', resolutions=[resolution])
        self.assertEqual(self.snapshot()['files']['Notes/b.md'], 'Capacity is 20.')
        self.assertIn('fixture/owner-reviewed-evidence', json.dumps(self.call('events')))

    def test_cross_owner_fact_authority_resolves_before_integrator_accepts(self):
        responsible = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'responsible', 'human': 'Responsible Owner', 'agent': 'Test',
                            'role': 'owner', 'token': responsible})
        self.claim('a', ['Notes/a.md']); self.claim('b', ['Notes/b.md'], self.bob)
        self.proposal('initial-fact', 'a', {'Notes/a.md': 'Initial evidence'}, claims=[{
            'key': 'capacity', 'value': '10', 'source': 'source-initial', 'authority': 'responsible'}])
        self.accept('initial-fact')
        self.proposal('contested-fact', 'b', {'Notes/b.md': 'Contested evidence'}, token=self.bob, claims=[{
            'key': 'capacity', 'value': '20', 'source': 'source-contested', 'authority': 'responsible'}])
        self.assertEqual(self.accept('contested-fact')['status'], 'conflict')
        accepted = self.snapshot()
        payload = {'proposal_id': 'contested-fact', 'resolutions': [{'key': 'capacity', 'value': '20',
            'source': 'responsible-reviewed-source', 'reason': 'Responsible owner reviewed both sources.',
            'authority': 'responsible'}]}
        self.rejected('resolve', payload)
        self.assertEqual(self.snapshot(), accepted)
        self.call('resolve', payload, responsible)
        self.assertEqual(self.snapshot(), accepted, 'Recording a decision is not accepting file changes')
        self.accept('contested-fact')
        self.assertEqual(self.snapshot()['files']['Notes/b.md'], 'Contested evidence')
        self.assertIn('responsible-reviewed-source', json.dumps(self.call('events')))

    def test_only_integrator_rejects_proposal_and_completion_preserves_rejected_bytes(self):
        self.claim(token=self.bob)
        self.proposal('rejected-draft', token=self.bob)
        original = self.stored_proposal('rejected-draft')
        self.rejected('reject', {'proposal_id': 'rejected-draft', 'reason': 'Contributor cannot decide'}, self.bob)
        self.call('reject', {'proposal_id': 'rejected-draft', 'reason': 'Integrator reviewed and rejected'})
        current = self.snapshot()
        self.call('complete', {'assignment_id': 'assignment-a', 'revision': current['revision'],
            'files_hash': current['files_hash'], 'evidence': 'No file changes accepted; disposition reviewed'}, self.bob)
        self.assertEqual(self.stored_proposal('rejected-draft'), original)
        self.assertIn('reject', json.dumps(self.call('events')).lower())

    def test_explicit_integration_transfer_allows_revocation_and_recovery_handoff(self):
        successor = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'successor', 'human': 'Successor', 'agent': 'Test',
                            'role': 'owner', 'token': successor})
        self.claim()
        self.rejected('revoke', {'actor': 'owner'}, successor)
        self.call('transfer-integration', {'assignment_id': 'assignment-a', 'to_actor': 'successor',
                                          'reason': 'Explicit reviewed integration responsibility transfer'})
        self.call('revoke', {'actor': 'owner'}, successor)
        with self.assertRaises(ProductError):
            self.call('status')
        self.call('handoff', {'assignment_id': 'assignment-a', 'to_actor': 'bob',
                             'summary': 'Successor recovers assignment from revoked actor'}, successor)
        current = self.call('snapshot', token=successor)
        self.call('receive', {'assignment_id': 'assignment-a', 'revision': current['revision'],
                             'files_hash': current['files_hash']}, self.bob)
        self.call('complete', {'assignment_id': 'assignment-a', 'revision': current['revision'],
            'files_hash': current['files_hash'], 'evidence': 'Received current content; no proposed edits remain'}, self.bob)

    def test_fact_authority_transfer_preserves_files_and_prevents_orphaning(self):
        successor = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'successor', 'human': 'Successor', 'agent': 'Test',
                            'role': 'owner', 'token': successor})
        self.claim()
        self.proposal('owned-fact', claims=[{'key': 'capacity', 'value': '10',
            'source': 'fixture-reviewed', 'authority': 'owner'}])
        self.accept('owned-fact')
        current = self.snapshot()
        self.call('complete', {'assignment_id': 'assignment-a', 'revision': current['revision'],
            'files_hash': current['files_hash'], 'evidence': 'Reviewed accepted content'})
        self.rejected('revoke', {'actor': 'owner'}, successor)
        self.call('transfer-authority', {'key': 'capacity', 'to_actor': 'successor',
            'evidence': 'Reviewed responsibility record', 'reason': 'Explicit accountable owner handoff'})
        transferred = self.snapshot()
        self.assertEqual(transferred['revision'], current['revision'] + 1)
        self.assertEqual(transferred['files'], current['files'])
        self.assertEqual(transferred['files_hash'], current['files_hash'])
        self.call('revoke', {'actor': 'owner'}, successor)
        self.assertIn('transfer', json.dumps(self.call('events', token=successor)).lower())

    def test_handoff_requires_current_exact_receipt_and_retains_history(self):
        self.claim()
        snapshot = self.snapshot()
        self.call('handoff', {'assignment_id': 'assignment-a', 'to_actor': 'bob', 'summary': 'Review fixture'})
        for token in [self.owner, self.bob]:
            with self.assertRaises(ProductError):
                self.proposal('premature', token=token)
        self.rejected('receive', {'assignment_id': 'assignment-a', 'revision': snapshot['revision'],
            'files_hash': '0' * 64}, self.bob)
        self.call('receive', {'assignment_id': 'assignment-a', 'revision': snapshot['revision'],
            'files_hash': snapshot['files_hash']}, self.bob)
        self.proposal('received', token=self.bob)
        self.accept('received')
        current = self.snapshot()
        self.rejected('complete', {'assignment_id': 'assignment-a', 'revision': snapshot['revision'],
            'files_hash': snapshot['files_hash'], 'evidence': 'Old receipt is insufficient.'}, self.bob)
        self.call('complete', {'assignment_id': 'assignment-a', 'revision': current['revision'],
            'files_hash': current['files_hash'], 'evidence': 'Exact accepted content checked.'}, self.bob)
        self.assertIn('handoff', json.dumps(self.call('events')).lower())
        self.assertIn('complete', json.dumps(self.call('status')['assignments']).lower())

    def test_invalid_portable_paths_and_case_collisions_never_change_accepted_state(self):
        initial = self.snapshot()
        for path in ['/absolute', '../parent', 'C:/drive', 'a\\b', 'CON', 'note.', 'note ',
                     '.git/config', '.obsidian/settings.json', '.workspace-project.json', '.shared-memory.json']:
            with self.subTest(path=path), self.assertRaises(ProductError):
                self.claim('invalid', [path])
            self.assertEqual(self.snapshot(), initial)
        with self.assertRaises(ProductError):
            self.claim('case', ['notes/A.md'])
            self.proposal('case-proposal', 'case', {'notes/A.md': 'Case collision'})
        self.assertEqual(self.snapshot(), initial)

    def test_conflict_can_be_superseded_after_explicit_current_base_review(self):
        self.claim()
        base = self.snapshot()['revision']
        self.proposal('winner', changes={'Notes/a.md': 'Accepted first'}, base=base)
        self.proposal('stale', changes={'Notes/a.md': 'Preserved stale version'}, base=base)
        self.accept('winner')
        self.assertEqual(self.accept('stale')['status'], 'conflict')
        self.proposal('replacement', changes={'Notes/a.md': 'Explicitly reconciled current version'})
        self.accept('replacement')
        self.call('supersede', {'proposal_id': 'stale', 'replacement_id': 'replacement',
                               'reason': 'Reviewed both versions against current accepted content.'})
        current = self.snapshot()
        self.call('complete', {'assignment_id': 'assignment-a', 'revision': current['revision'],
            'files_hash': current['files_hash'], 'evidence': 'Reconciled output reviewed.'})
        self.assertIn('Preserved stale version', json.dumps(self.stored_proposal('stale')))
        self.assertIn('supersed', json.dumps(self.call('events')).lower())

    def test_acceptance_event_fault_rolls_back_snapshot_and_reopens_cleanly(self):
        self.claim(); self.proposal('fault-proposal')
        before_snapshot = self.snapshot()
        before_status = self.call('status')
        before_events = self.call('events')
        with database(self.db) as connection:
            connection.execute("CREATE TRIGGER acceptance_fault BEFORE INSERT ON events "
                               "BEGIN SELECT RAISE(ABORT, 'injected durable event failure'); END")
        with self.assertRaises(ProductError):
            self.accept('fault-proposal')
        self.engine = self.Coordinator(self.db)
        self.assertEqual(self.snapshot(), before_snapshot)
        self.assertEqual(self.call('status'), before_status)
        self.assertEqual(self.call('events'), before_events)
        with database(self.db) as connection:
            connection.execute('DROP TRIGGER acceptance_fault')
        self.engine = self.Coordinator(self.db)
        self.accept('fault-proposal')
        accepted = self.snapshot()
        self.assertEqual(accepted['revision'], before_snapshot['revision'] + 1)
        self.engine = self.Coordinator(self.db)
        self.accept('fault-proposal')
        self.assertEqual(self.snapshot(), accepted)

    def test_killed_writer_hot_journal_recovers_without_losing_accepted_history(self):
        before_snapshot = self.snapshot()
        before_status = self.call('status')
        before_events = self.call('events')
        context = multiprocessing.get_context('spawn')
        receive, send = context.Pipe(duplex=False)
        stop = context.Event()
        worker = context.Process(target=hot_journal_worker, args=(self.db, send, stop))
        worker.start()
        send.close()
        try:
            self.assertTrue(receive.poll(20), 'Writer did not reach the injected transaction boundary')
            evidence = receive.recv()
            self.assertTrue(evidence['hot_header'], evidence)
            self.assertGreater(evidence['journal_bytes'], 512)
            worker.kill()
            worker.join(timeout=10)
            self.assertFalse(worker.is_alive())
            self.assertNotEqual(worker.exitcode, 0)
            self.engine = self.Coordinator(self.db)
            json.dumps(self.engine.recover())
            self.assertEqual(self.snapshot(), before_snapshot)
            self.assertEqual(self.call('status'), before_status)
            self.assertEqual(self.call('events'), before_events)
        finally:
            if worker.is_alive():
                worker.kill(); worker.join(timeout=5)
            receive.close()

    def test_snapshot_tampering_fails_hash_verification(self):
        with database(self.db) as connection:
            connection.execute("UPDATE snapshots SET files_json='{}' WHERE revision=(SELECT MAX(revision) FROM snapshots)")
        with self.assertRaises(ProductError):
            self.snapshot()

    def test_event_tampering_fails_hash_verification(self):
        with database(self.db) as connection:
            connection.execute("UPDATE events SET event_json='{}' WHERE seq=(SELECT MIN(seq) FROM events)")
        with self.assertRaises(ProductError):
            self.call('events')

    def test_unknown_schema_is_refused(self):
        with database(self.db) as connection:
            connection.execute('PRAGMA user_version=999')
        with self.assertRaises(ProductError):
            reopened = self.Coordinator(self.db)
            reopened.request(self.owner, 'status', {})

    def test_large_proposals_have_bounded_status_and_lossless_detail_readers(self):
        self.claim()
        originals = {}
        for index in range(4):
            identity = 'large-' + str(index)
            content = ('Version %d: café 漢字\n' % index) * 32768
            originals[identity] = content
            self.proposal(identity, changes={'Notes/a.md': content}, base=0)
        self.accept('large-0')
        accepted = self.snapshot()
        conflict_ids = []
        for identity in list(originals)[1:]:
            outcome = self.accept(identity)
            self.assertFalse(outcome['accepted'])
            self.assertLess(len(json.dumps(outcome).encode()), 16384)
            conflict_ids.extend(item['conflict_id'] for item in outcome['conflicts'])
        status = self.call('status', token=self.reader)
        self.assertLess(len(json.dumps(status).encode()), 65536)
        self.assertEqual(len(status['proposals']), 4)
        self.assertEqual(len(status['conflicts']), 3)
        self.assertLess(len(json.dumps(self.call('events')).encode()), 65536)
        before_reads = self.db.read_bytes()
        self.engine = self.Coordinator(self.db)
        for identity, content in originals.items():
            record = self.call('proposal', {'proposal_id': identity}, self.reader)
            original_request = self.stored_proposal(identity)
            self.assertEqual(record['changes'], {'Notes/a.md': content})
            for key, value in original_request.items():
                self.assertEqual(record[key], value)
            self.assertEqual(record['request_hash'], canonical_hash(original_request))
        for identity in conflict_ids:
            conflict = self.call('conflict', {'conflict_id': identity}, self.reader)
            self.assertEqual(conflict['base'], self.files['Notes/a.md'])
            self.assertEqual(conflict['accepted'], originals['large-0'])
            self.assertEqual(conflict['proposed'], originals[conflict['proposal_id']])
        self.assertEqual(self.snapshot(), accepted)
        self.assertEqual(self.db.read_bytes(), before_reads, 'Detail reads must not mutate storage')

    def test_status_pages_exhaust_each_collection_without_duplicates(self):
        self.claim()
        for index in range(3):
            self.proposal('page-' + str(index), changes={'Notes/a.md': str(index)}, base=0)
        self.accept('page-0')
        self.accept('page-1'); self.accept('page-2')
        expected = self.call('status')
        before_reads = self.db.read_bytes()
        for collection in ('members', 'assignments', 'proposals', 'conflicts'):
            offset = 0
            observed = []
            for _ in range(10):
                page = self.call('status', {'offset': offset, 'limit': 1}, self.reader)
                self.assertEqual(page['paging']['totals'][collection], len(expected[collection]))
                self.assertLessEqual(len(page[collection]), 1)
                observed.extend(page[collection])
                next_offset = page['paging']['next_offsets'][collection]
                if next_offset is None:
                    break
                self.assertGreater(next_offset, offset)
                offset = next_offset
            else:
                self.fail('Status paging did not terminate')
            self.assertEqual(observed, expected[collection])
        self.assertEqual(self.db.read_bytes(), before_reads)

    def test_events_pages_preserve_exact_ordered_history_and_replay(self):
        for index in range(102):
            self.call('member', {'actor': 'page-reader-' + str(index), 'human': 'Fixture',
                'agent': 'Independent test', 'role': 'reader', 'token': secrets.token_urlsafe(32)})
        with database(self.db) as connection:
            originals = [{'sequence': sequence, **json.loads(value)} for sequence, value
                in connection.execute('SELECT seq,event_json FROM events ORDER BY seq')]
        self.assertGreater(len(originals), 100)
        default_page = self.call('events', token=self.reader)
        self.assertEqual(default_page['events'], originals[:100])
        self.assertTrue(default_page['has_more'])
        before_reads = self.db.read_bytes()
        cursor = 0
        observed = []
        for _ in range(30):
            payload = {'after_seq': cursor, 'limit': 7}
            page = self.call('events', payload, self.reader)
            self.assertEqual(self.call('events', payload, self.reader), page)
            self.assertEqual(page['project_id'], self.project_id)
            self.assertLessEqual(len(page['events']), 7)
            observed.extend(page['events'])
            if not page['has_more']:
                break
            self.assertEqual(page['next_after_seq'], page['events'][-1]['sequence'])
            self.assertGreater(page['next_after_seq'], cursor)
            cursor = page['next_after_seq']
        else:
            self.fail('Events paging did not terminate')
        self.assertEqual(observed, originals)
        tail = self.call('events', {'after_seq': originals[-1]['sequence'], 'limit': 7})
        self.assertEqual(tail['events'], [])
        self.assertFalse(tail['has_more'])
        self.assertEqual(self.db.read_bytes(), before_reads)

    def test_paged_history_verifies_events_before_requested_cursor(self):
        self.claim()
        self.proposal('later-event')
        with database(self.db) as connection:
            connection.execute("UPDATE events SET event_json='{}' WHERE seq=1")
        self.rejected('events', {'after_seq': 3, 'limit': 1}, code=3)

    def test_event_byte_budget_returns_contiguous_pages_without_losing_evidence(self):
        criteria = [('Detailed criterion %d: ' % index).ljust(16384, 'x') for index in range(100)]
        for index in range(3):
            self.call('claim', {'assignment_id': 'detailed-' + str(index),
                'targets': ['Future-' + str(index) + '.md'], 'criteria': criteria,
                'dependencies': [], 'resource_limits': {}, 'integration_owner': 'owner'})
        self.assertLess(len(json.dumps(self.call('status')).encode()), 65536)
        full_assignment = self.call('assignment', {'assignment_id': 'detailed-2'}, self.reader)
        self.assertEqual(full_assignment['criteria'], criteria)
        with database(self.db) as connection:
            originals = [{'sequence': sequence, **json.loads(value)} for sequence, value
                in connection.execute('SELECT seq,event_json FROM events ORDER BY seq')]
        first = self.call('events', {'limit': 100}, self.reader)
        self.assertTrue(first['has_more'], 'Byte budget must apply before the count limit')
        self.assertLess(len(json.dumps(first, ensure_ascii=False).encode()), 4 * 1024 * 1024 + 4096)
        second = self.call('events', {'after_seq': first['next_after_seq'], 'limit': 100}, self.reader)
        self.assertFalse(second['has_more'])
        self.assertEqual(first['events'] + second['events'], originals)

    def test_detail_readers_require_active_membership_and_exact_identity(self):
        self.claim()
        self.proposal('first', base=0)
        self.proposal('second', base=0, changes={'Notes/a.md': 'Other version\n'})
        self.accept('first')
        conflict_id = self.accept('second')['conflicts'][0]['conflict_id']
        requests = [('proposal', {'proposal_id': 'second'}),
                    ('conflict', {'conflict_id': conflict_id})]
        for operation, payload in requests:
            self.call(operation, payload, self.reader)
            self.rejected(operation, payload, secrets.token_urlsafe(32))
        self.call('revoke', {'actor': 'reader'})
        before_reads = self.db.read_bytes()
        for operation, payload in requests:
            self.rejected(operation, payload, self.reader)
            self.rejected(operation, {next(iter(payload)): 'missing-identity'})
        self.assertEqual(self.db.read_bytes(), before_reads)

    def test_malformed_paging_arguments_reject_without_writes(self):
        before_reads = self.db.read_bytes()
        for operation, field in [('status', 'offset'), ('facts', 'offset'), ('events', 'after_seq')]:
            for value in (-1, True, '0', 1.5):
                with self.subTest(operation=operation, field=field, value=value):
                    self.rejected(operation, {field: value}, code=3)
            for value in (0, -1, 1001, True, '1', 1.5):
                with self.subTest(operation=operation, field='limit', value=value):
                    self.rejected(operation, {'limit': value}, code=3)
        self.assertEqual(self.db.read_bytes(), before_reads)

    def test_assignment_detail_and_fact_pages_preserve_authority_evidence(self):
        assignment = self.claim()
        claims = [{'key': key, 'value': value, 'source': 'fixture/source-' + key,
                   'authority': 'owner'} for key, value in [('capacity', '10'), ('stage', 'reviewed')]]
        self.proposal('facts-visible', claims=claims)
        self.accept('facts-visible')
        before_reads = self.db.read_bytes()
        self.assertEqual(self.call('assignment', {'assignment_id': 'assignment-a'}, self.reader), assignment)
        first = self.call('facts', {'offset': 0, 'limit': 1}, self.reader)
        second = self.call('facts', {'offset': first['next_offset'], 'limit': 1}, self.reader)
        self.assertEqual(first['project_id'], self.project_id)
        self.assertEqual(first['revision'], self.snapshot()['revision'])
        self.assertEqual(first['total'], 2)
        self.assertIsNone(second['next_offset'])
        self.assertEqual(sorted(first['facts'] + second['facts'], key=lambda value: value['key']), claims)
        self.assertEqual(self.db.read_bytes(), before_reads)
        self.call('revoke', {'actor': 'reader'})
        self.rejected('facts', {}, self.reader)
        self.rejected('assignment', {'assignment_id': 'assignment-a'}, self.reader)

    def test_full_proposal_reader_detects_stored_byte_tampering(self):
        self.claim(); self.proposal('tampered-detail')
        with database(self.db) as connection:
            connection.execute("UPDATE proposals SET request_json='{}' WHERE id='tampered-detail'")
        self.rejected('proposal', {'proposal_id': 'tampered-detail'}, self.reader, code=3)

    def test_full_conflict_reader_detects_stored_byte_tampering(self):
        self.claim(); self.proposal('first', base=0)
        self.proposal('second', base=0, changes={'Notes/a.md': 'Conflicting bytes'})
        self.accept('first')
        conflict_id = self.accept('second')['conflicts'][0]['conflict_id']
        with database(self.db) as connection:
            connection.execute("UPDATE conflicts SET document='{}' WHERE id=?", (conflict_id,))
        self.rejected('conflict', {'conflict_id': conflict_id}, self.reader, code=3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
