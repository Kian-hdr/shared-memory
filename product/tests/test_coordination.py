"""Actual schema2 coordinator behavior in disposable local SQLite fixtures."""
from __future__ import annotations

import json
from contextlib import closing, nullcontext
import multiprocessing
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))

from shared_workspace import coordination
from shared_workspace import engine as engine_module
from shared_workspace.engine import Coordinator, digest
from shared_workspace.errors import ProductError


def raced_request(database, token, operation, payload, barrier, results, now_ms=None):
    try:
        barrier.wait(timeout=15)
        with patch.object(coordination.time, 'time_ns', return_value=now_ms * 1000000) if now_ms else nullcontext():
            result = Coordinator(database).request(token, operation, payload)
        results.put({'ok': True, 'result': result})
    except ProductError as exc:
        results.put({'ok': False, 'code': exc.code})
    except Exception as exc:
        results.put({'unexpected': type(exc).__name__})


def consume_inbox_page(database, token, checkpoint_path, results):
    """One real consumer process: reopen authority, acknowledge, persist cursor, exit."""
    try:
        checkpoint = Path(checkpoint_path)
        saved = json.loads(checkpoint.read_text()) if checkpoint.exists() else {'cursor': 0, 'message_ids': []}
        authority = Coordinator(database)
        page = authority.request(token, 'inbox', {'after_seq': saved['cursor'], 'limit': 2})
        ids = [message['message_id'] for message in page['messages']]
        if set(ids) & set(saved['message_ids']):
            raise AssertionError('Previously consumed logical message returned after persisted cursor')
        for message_id in ids:
            result = authority.request(token, 'ack', {'message_id': message_id})
            if not result['acknowledged']:
                raise AssertionError('Acknowledgement was not durable')
            with closing(sqlite3.connect(database)) as connection:
                before = connection.execute('SELECT * FROM events ORDER BY seq').fetchall()
            authority.request(token, 'ack', {'message_id': message_id})
            with closing(sqlite3.connect(database)) as connection:
                if connection.execute('SELECT * FROM events ORDER BY seq').fetchall() != before:
                    raise AssertionError('Repeated acknowledgement appended an event')
        saved = {'cursor': page['next_after_seq'], 'message_ids': saved['message_ids'] + ids}
        checkpoint.write_text(json.dumps(saved), encoding='utf-8')
        results.put({'ids': ids, 'has_more': page['has_more']})
    except Exception as exc:
        results.put({'unexpected': type(exc).__name__, 'message': str(exc)})


def interrupted_accept(database, token, payload, boundary, ready, wait):
    authority = Coordinator(database)
    if boundary == 'before_commit':
        original = coordination.Coordination.publish_notice

        def stop_in_transaction(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.db.execute('PRAGMA cache_size=2')
            self.db.execute('PRAGMA cache_spill=ON')
            # Force real uncommitted pages out under the real SQLite journal.
            for number in range(40):
                coordination._put(self.db, 'coord_inbox', 'crash-' + str(number),
                                  {'fixture': 'X' * 65536, 'number': number})
            ready.send('inside_uncommitted_transaction')
            wait.wait(timeout=30)

        with patch.object(coordination.Coordination, 'publish_notice', stop_in_transaction):
            authority.request(token, 'accept', payload)
    else:
        authority.request(token, 'accept', payload)
        ready.send('after_commit_before_response')
        wait.wait(timeout=30)


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-coordination-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.database = self.root / 'authority.sqlite'
        self.engine = Coordinator(self.database)
        self.project_id = str(uuid.uuid4())
        self.owner_token, self.worker_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.tokens = {}
        self.engine.initialize(self.project_id, {'actor': 'owner', 'human': 'Fixture person', 'agent': 'Fixture agent'},
            self.owner_token, {'a.md': 'BASE\r\n', 'b.md': 'BASE B'},
            coordination={'person_id': 'person-owner', 'agent_id': 'agent-owner', 'policy': {}})
        self.call('member', {'actor': 'worker', 'human': 'Another fixture person', 'agent': 'Worker agent',
                            'role': 'contributor', 'token': self.worker_token}, root=True)
        self.call('member-binding', {'actor': 'worker', 'person_id': 'person-worker', 'agent_id': 'agent-worker'}, root=True)
        self.open_session('owner-run', self.owner_token, 'owner')
        self.open_session('worker-run', self.worker_token, 'contributor')

    def call(self, operation, payload=None, *, session='owner-run', root=False):
        return self.engine.request(self.owner_token if root else self.tokens[session], operation, payload or {})

    def open_session(self, identity, credential, role, scopes=None, targets=None, ttl=3600):
        token = secrets.token_urlsafe(32)
        policy = self.engine.request(credential, 'policy', {})
        result = self.engine.request(credential, 'session-open', {'session_id': identity, 'token': token,
            'ttl_seconds': ttl, 'scopes': scopes or policy['policy']['session_scopes'][role], 'targets': targets or ['.']})
        self.tokens[identity] = token
        return result

    def policy_revision(self):
        return self.call('policy', root=True)['policy_revision']

    def snapshot(self):
        return self.call('snapshot', root=True)

    def plan_payload(self, identity, targets=None, dependencies=None, integration='owner', interfaces=None):
        return {'assignment_id': identity, 'outcome_key': 'outcome-' + identity, 'summary': 'Deliver ' + identity,
                'targets': targets or [identity + '.md'], 'criteria': ['Verify fixture bytes'],
                'dependencies': dependencies or [], 'interface_paths': interfaces or [],
                'resource_limits': {}, 'integration_owner': integration, 'policy_revision': self.policy_revision()}

    def plan(self, identity, **kwargs):
        return self.call('plan', self.plan_payload(identity, **kwargs))

    def assignment(self, identity):
        return self.call('assignment', {'assignment_id': identity}, root=True)

    def acquire_payload(self, identity):
        snapshot = self.snapshot()
        return {'assignment_id': identity, 'expected_generation': self.assignment(identity)['generation'],
                'ttl_seconds': 300, 'revision': snapshot['revision'], 'files_hash': snapshot['files_hash'],
                'policy_revision': self.policy_revision()}

    def acquire(self, identity, session='worker-run'):
        return self.call('acquire', self.acquire_payload(identity), session=session)

    def context(self, identity, session='worker-run'):
        assignment = self.assignment(identity)
        return {'session_id': session, 'generation': assignment['generation'],
                'input_hash': assignment['input_hash'], 'policy_revision': self.policy_revision()}

    def propose_payload(self, identity, proposal='proposal', changes=None, session='worker-run'):
        return {'assignment_id': identity, 'proposal_id': proposal, 'base_revision': self.snapshot()['revision'],
                'changes': changes or {identity + '.md': 'PROPOSED\r\n終わり'}, 'claims': [],
                'evidence': 'Compared exact disposable bytes', 'coordination': self.context(identity, session)}

    def accept_payload(self, identity, proposal='proposal', session='owner-run'):
        return {'proposal_id': proposal, 'validation': 'Automated authorized fixture validation',
                'reason': 'Integrate fixture', 'coordination': self.context(identity, session)}

    def complete(self, identity, session='worker-run'):
        snapshot = self.snapshot()
        return self.call('complete', {'assignment_id': identity, 'revision': snapshot['revision'],
            'files_hash': snapshot['files_hash'], 'evidence': 'Verified fixture output',
            'coordination': self.context(identity, session)}, session=session)

    def publish_interface(self, identity, contract='API contract v1', revision=1, session='worker-run'):
        return self.call('interface-publish', {'assignment_id': identity, 'interface_revision': revision,
            'contract': contract, 'evidence': 'Reviewed explicit API contract',
            'coordination': self.context(identity, session)}, session=session)

    def edge(self, identity, kind='interface', revision=1, contract='API contract v1'):
        return {'assignment_id': identity, 'kind': kind, kind + '_revision': revision,
                'interface_hash': digest(contract if kind == 'interface' else {})}

    def checkpoint(self):
        with closing(sqlite3.connect(self.database)) as connection:
            tables = sorted(row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'"))
            return digest({table: connection.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall() for table in tables})

    def reject_unchanged(self, operation, payload, **kwargs):
        before = self.checkpoint()
        with self.assertRaises(ProductError):
            self.call(operation, payload, **kwargs)
        self.assertEqual(self.checkpoint(), before)

    def test_opt_in_schema_identity_and_snapshot_contract_preserved(self):
        self.assertEqual(self.snapshot()['files']['a.md'].encode(), b'BASE\r\n')
        status = self.call('status', root=True)
        self.assertEqual(status['coordination']['schema_version'], 2)
        session = self.call('session', {'session_id': 'worker-run'}, session='worker-run')
        self.assertEqual((session['person_id'], session['agent_id'], session['actor']),
                         ('person-worker', 'agent-worker', 'worker'))
        text = json.dumps(self.call('events', root=True)) + json.dumps(status) + json.dumps(session)
        for token in [self.owner_token, self.worker_token, *self.tokens.values()]:
            self.assertNotIn(token, text)
        self.assertEqual(self.engine.recover()['logical_state_changed'], False)

    def test_membership_token_or_claimed_session_id_cannot_bypass_publication_auth(self):
        self.plan('work'); self.acquire('work')
        payload = self.propose_payload('work')
        self.reject_unchanged('propose', payload, root=True)
        other = self.open_session('other-worker', self.worker_token, 'contributor')
        self.reject_unchanged('propose', payload, session=other['session_id'])
        del payload['coordination']
        self.reject_unchanged('propose', payload, session='worker-run')

    def test_bound_delegation_restricts_scope_lifetime_and_revocation_lineage(self):
        parent = self.open_session('parent', self.owner_token, 'owner',
            scopes=['session-delegate', 'session-revoke', 'plan', 'policy', 'assignment'], targets=['Notes/'])
        child_token = secrets.token_urlsafe(32)
        payload = {'session_id': 'child', 'token': child_token, 'to_actor': 'owner', 'ttl_seconds': 100,
                   'scopes': ['plan', 'policy', 'assignment'], 'targets': ['Notes/sub/']}
        child = self.call('session-delegate', payload, session='parent')
        self.tokens['child'] = child_token
        self.assertEqual(child['parent_session_id'], parent['session_id'])
        self.assertEqual(child['person_id'], 'person-owner')
        self.reject_unchanged('session-delegate', dict(payload, session_id='escaped', scopes=['accept']), session='parent')
        self.reject_unchanged('session-delegate', dict(payload, session_id='escaped', targets=['.']), session='parent')
        self.reject_unchanged('plan', self.plan_payload('outside', targets=['Private.md']), session='child')
        self.call('plan', self.plan_payload('inside', targets=['Notes/sub/a.md']), session='child')
        self.call('session-revoke', {'session_id': 'parent', 'reason': 'End delegated run'}, root=True)
        self.reject_unchanged('policy', {}, session='child')

    def test_owner_session_operation_and_global_target_scope_gate_administration(self):
        self.open_session('limited-owner', self.owner_token, 'owner', scopes=['policy'], targets=['.'])
        update = {'expected_revision': 1, 'policy': {}, 'reason': 'Policy fixture'}
        self.reject_unchanged('policy-update', update, session='limited-owner')
        self.open_session('path-owner', self.owner_token, 'owner', scopes=['policy-update'], targets=['Notes/'])
        self.reject_unchanged('policy-update', update, session='path-owner')

    def test_session_credentials_cannot_be_reused_as_member_credentials(self):
        self.reject_unchanged('member', {'actor': 'spoof', 'human': 'Fixture', 'agent': 'Fixture',
            'role': 'owner', 'token': self.tokens['worker-run']}, root=True)

    def test_policy_revision_checked_before_both_propose_and_accept(self):
        self.plan('work'); self.acquire('work')
        proposal = self.propose_payload('work')
        self.call('propose', proposal, session='worker-run')
        acceptance = self.accept_payload('work')
        before_files = self.snapshot()
        changed = self.call('policy-update', {'expected_revision': 1, 'policy': {'max_lease_seconds': 299}, 'reason': 'Reviewed new lease constraint'}, root=True)
        self.assertEqual(changed['policy_revision'], 2)
        self.reject_unchanged('propose', dict(proposal, proposal_id='stale'), session='worker-run')
        self.reject_unchanged('accept', acceptance)
        self.reject_unchanged('accept', self.accept_payload('work'))
        self.assertEqual(self.snapshot(), before_files)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM coord_policies').fetchone()[0], 2)

    def test_same_actor_different_session_cannot_publish_after_reassignment_or_handoff(self):
        self.plan('work'); first = self.acquire('work')
        proposal = self.propose_payload('work')
        self.call('propose', proposal, session='worker-run')
        self.open_session('new-worker', self.worker_token, 'contributor')
        self.call('handoff', {'assignment_id': 'work', 'to_actor': 'worker', 'summary': 'Replace running session',
            'coordination': self.context('work')}, session='worker-run')
        second = self.acquire('work', 'new-worker')
        self.assertGreater(second['generation'], first['generation'])
        self.reject_unchanged('propose', dict(proposal, proposal_id='old-new-id'), session='worker-run')
        self.reject_unchanged('accept', self.accept_payload('work'))
        self.call('reject', {'proposal_id': 'proposal', 'reason': 'Retire stale generation explicitly',
                            'coordination': self.context('work', 'owner-run')})
        self.assertEqual(self.call('proposal', {'proposal_id': 'proposal'}, root=True)['status'], 'rejected')

    def test_authorized_contributor_integrates_without_mandatory_human_gate(self):
        self.plan('work', integration='worker'); self.acquire('work')
        self.call('propose', self.propose_payload('work'), session='worker-run')
        result = self.call('accept', self.accept_payload('work', session='worker-run'), session='worker-run')
        self.assertTrue(result['accepted'])
        self.assertEqual(self.snapshot()['files']['work.md'], 'PROPOSED\r\n終わり')
        self.assertTrue(self.call('accept', self.accept_payload('work', session='worker-run'), session='worker-run')['idempotent'])

    def test_interface_consumers_run_before_producer_complete_then_defect_fences_descendants(self):
        self.plan('producer'); producer = self.acquire('producer')
        self.plan('consumer', dependencies=[self.edge('producer')])
        self.plan('output-waiter', dependencies=[self.edge('producer', kind='output')])
        self.plan('grandchild', dependencies=[self.edge('consumer', kind='output')])
        self.plan('unrelated'); unrelated = self.acquire('unrelated')
        self.assertEqual(self.assignment('consumer')['status'], 'queued')
        self.publish_interface('producer')
        self.assertEqual(self.assignment('producer')['status'], 'active')
        self.assertEqual(self.assignment('output-waiter')['status'], 'queued')
        self.acquire('consumer')
        self.call('propose', self.propose_payload('consumer'), session='worker-run')
        old_context = self.context('consumer')
        defect = self.call('defect-report', {'defect_id': 'bad-api', 'assignment_id': 'producer', 'kind': 'interface',
            'interface_revision': 1, 'summary': 'Fixture contract omits field',
            'evidence': 'Reproduction: compare contract with declared required field', 'policy_revision': 1})
        self.assertEqual(set(defect['affected_assignments']), {'producer', 'consumer', 'grandchild', 'output-waiter'})
        self.assertEqual(self.assignment('unrelated')['lease'], unrelated['lease'])
        self.assertEqual(self.assignment('unrelated')['generation'], unrelated['generation'])
        self.assertGreater(self.assignment('producer')['generation'], producer['generation'])
        self.reject_unchanged('propose', dict(self.propose_payload('consumer', 'late'), coordination=old_context), session='worker-run')
        self.reject_unchanged('accept', self.accept_payload('consumer'))
        self.assertFalse(self.call('interface', {'assignment_id': 'producer', 'interface_revision': 1}, root=True)['valid'])
        self.assertEqual(self.snapshot()['revision'], 0)

    def test_output_dependency_released_by_completion_and_original_versions_retained_on_replan(self):
        self.plan('producer'); self.acquire('producer')
        self.plan('consumer', dependencies=[self.edge('producer', kind='output')])
        finished = self.complete('producer')
        self.assertEqual(finished['output']['output_revision'], 1)
        self.assertEqual(self.assignment('consumer')['status'], 'ready')
        self.acquire('consumer')
        old_output = self.call('outputs', {'assignment_id': 'producer'}, root=True)['outputs'][0]
        self.call('replan', {'assignment_id': 'producer', 'expected_plan_revision': 1, 'dependencies': [],
                           'reason': 'Explicit second output revision', 'policy_revision': 1})
        self.acquire('producer'); self.complete('producer')
        outputs = self.call('outputs', {'assignment_id': 'producer'}, root=True)['outputs']
        self.assertEqual(outputs[0], old_output)
        self.assertEqual([item['output_revision'] for item in outputs], [1, 2])

    def test_dependency_cycle_missing_reference_wrong_hash_and_outcome_reservations(self):
        self.plan('first')
        self.plan('second', dependencies=[self.edge('first')])
        self.reject_unchanged('replan', {'assignment_id': 'first', 'expected_plan_revision': 1,
            'dependencies': [self.edge('second')], 'reason': 'Cycle fixture', 'policy_revision': 1})
        payload = self.plan_payload('missing', dependencies=[self.edge('unknown')])
        self.reject_unchanged('plan', payload)
        self.reject_unchanged('plan', dict(self.plan_payload('duplicate'), outcome_key='OUTCOME-FIRST'))
        self.acquire('first'); self.publish_interface('first')
        wrong = self.edge('first'); wrong['interface_hash'] = '0' * 64
        self.plan('wrong', dependencies=[wrong])
        self.reject_unchanged('acquire', self.acquire_payload('wrong'), session='worker-run')

    def test_interface_publication_is_immutable_and_independent_of_file_revision(self):
        self.plan('work'); self.acquire('work')
        original = self.publish_interface('work')
        self.assertEqual(self.publish_interface('work'), original)
        before = self.checkpoint()
        with self.assertRaises(ProductError):
            self.publish_interface('work', contract='Different contract')
        self.assertEqual(self.checkpoint(), before)
        self.assertEqual(self.snapshot()['revision'], 0)

    def test_inbox_targets_ack_idempotency_and_atomic_failure(self):
        self.plan('work'); self.acquire('work')
        messages = self.call('inbox', session='worker-run')['messages']
        self.assertTrue(messages)
        message = messages[0]
        self.assertEqual(message['to_actor'], 'worker')
        self.reject_unchanged('ack', {'message_id': message['message_id']})
        result = self.call('ack', {'message_id': message['message_id']}, session='worker-run')
        self.assertTrue(result['acknowledged'])
        events = self.call('events', root=True)
        self.call('ack', {'message_id': message['message_id']}, session='worker-run')
        self.assertEqual(self.call('events', root=True), events)
        before = self.checkpoint()
        with patch.object(coordination.Coordination, 'notify', side_effect=OSError('Injected durable inbox failure')):
            with self.assertRaises(ProductError):
                self.call('plan', self.plan_payload('interrupted'))
        self.assertEqual(self.checkpoint(), before)

    def test_inbox_consumer_restart_paged_catchup_preserves_cursor_ack_and_recipient_isolation(self):
        # Generate independently identifiable work events through the real API.
        # Expected IDs come from persisted records, not the inbox paging code or
        # an assumption about its sequence/ID allocation algorithm.
        work = ['catchup-' + str(number) for number in range(7)]
        for identity in work:
            self.plan(identity)
            self.acquire(identity)

        def expected_messages():
            with closing(sqlite3.connect(self.database)) as connection:
                records = [json.loads(row[0]) for row in connection.execute('SELECT document FROM coord_inbox')]
            return sorted((record for record in records if record['to_actor'] == 'worker'),
                          key=lambda record: record['sequence'])

        initial = expected_messages()
        self.assertEqual([(item['assignment_id'], item['kind']) for item in initial],
                         [(identity, 'ownership-acquired') for identity in work])
        cursor_file = self.root / 'private-consumer-cursor.json'
        context = multiprocessing.get_context('spawn')

        def one_process_page():
            results = context.Queue()
            process = context.Process(target=consume_inbox_page,
                args=(str(self.database), self.tokens['worker-run'], str(cursor_file), results))
            process.start()
            try:
                result = results.get(timeout=15)
                process.join(timeout=15)
                self.assertFalse(process.is_alive(), 'Consumer did not shut down')
                self.assertEqual(process.exitcode, 0)
                self.assertNotIn('unexpected', result, result)
                return result
            finally:
                if process.is_alive():
                    process.terminate(); process.join(timeout=5)
                results.close(); results.join_thread()

        first = one_process_page()
        self.assertTrue(first['has_more'])
        self.assertEqual(first['ids'], [item['message_id'] for item in initial[:2]])
        # The consumer is stopped. New work arrives, and the authority is reopened
        # before fresh consumer processes resume from the on-disk checkpoint.
        self.engine = Coordinator(self.database)
        self.plan('while-stopped'); self.acquire('while-stopped')
        expected = expected_messages()
        self.assertEqual(len(expected), 8)
        for _ in range(10):
            page = one_process_page()
            if not page['has_more']:
                break
        else:
            self.fail('Bounded inbox catch-up did not terminate')
        saved = json.loads(cursor_file.read_text())
        self.assertEqual(saved['message_ids'], [item['message_id'] for item in expected])
        self.assertEqual(len(saved['message_ids']), len(set(saved['message_ids'])))
        self.assertEqual(saved['cursor'], expected[-1]['sequence'])
        self.assertTrue(all(item['acknowledged'] and item['acknowledged_by'] == 'worker-run'
                            for item in expected_messages()))
        self.assertEqual(one_process_page()['ids'], [])
        self.plan('after-catchup'); self.acquire('after-catchup')
        newest = expected_messages()[-1]
        self.assertEqual(newest['assignment_id'], 'after-catchup')
        self.assertEqual(one_process_page()['ids'], [newest['message_id']])
        self.assertEqual(one_process_page()['ids'], [])
        # The owner has its own independently addressed notices, never the
        # worker's message IDs, and cannot acknowledge any worker message.
        owner_ids = {item['message_id'] for item in self.call('inbox', {'limit': 1000})['messages']}
        self.assertFalse(owner_ids & {item['message_id'] for item in expected_messages()})
        for item in expected_messages():
            self.reject_unchanged('ack', {'message_id': item['message_id']})

    def test_clock_backwards_expiration_renewal_and_revoked_lease_reassignment(self):
        self.plan('work'); item = self.acquire('work')
        renewed = self.call('renew', {'assignment_id': 'work', 'generation': item['generation'],
            'ttl_seconds': 300, 'policy_revision': 1}, session='worker-run')
        self.assertEqual(renewed['generation'], item['generation'])
        with patch.object(coordination.time, 'time_ns', return_value=1):
            self.reject_unchanged('renew', {'assignment_id': 'work', 'generation': item['generation'],
                'ttl_seconds': 300, 'policy_revision': 1}, session='worker-run')
        self.call('session-revoke', {'session_id': 'worker-run', 'reason': 'Reassign vanished worker'}, root=True)
        self.open_session('replacement', self.worker_token, 'contributor')
        replacement = self.acquire('work', 'replacement')
        self.assertGreater(replacement['generation'], item['generation'])
        with patch.object(coordination.time, 'time_ns', return_value=(replacement['lease']['expires_ms'] + 1) * 1000000):
            self.reject_unchanged('propose', self.propose_payload('work', session='replacement'), session='replacement')

    def test_real_process_races_allow_one_outcome_and_one_lease_holder(self):
        ctx = multiprocessing.get_context('spawn')
        def race(operation, pairs):
            barrier, results = ctx.Barrier(len(pairs)), ctx.Queue()
            processes = [ctx.Process(target=raced_request, args=(str(self.database), token, operation, payload, barrier, results))
                         for token, payload in pairs]
            for process in processes:
                process.start()
            values = [results.get(timeout=20) for _ in processes]
            for process in processes:
                process.join(timeout=20)
                self.assertEqual(process.exitcode, 0)
            self.assertFalse(any('unexpected' in value for value in values), values)
            return values
        first = self.plan_payload('first')
        second = dict(self.plan_payload('second'), outcome_key=first['outcome_key'])
        outcomes = race('plan', [(self.tokens['owner-run'], first), (self.tokens['worker-run'], second)])
        self.assertEqual(sum(value['ok'] for value in outcomes), 1)
        identity = next(value['result']['assignment_id'] for value in outcomes if value['ok'])
        self.open_session('other-worker', self.worker_token, 'contributor')
        request = self.acquire_payload(identity)
        leases = race('acquire', [(self.tokens['worker-run'], request), (self.tokens['other-worker'], request)])
        self.assertEqual(sum(value['ok'] for value in leases), 1)

    def test_plan_acquire_and_proposal_lost_response_retries_preserve_identity(self):
        payload = self.plan_payload('work')
        self.call('plan', payload)
        self.call('plan', payload)
        request = self.acquire_payload('work')
        first = self.call('acquire', request, session='worker-run')
        second = self.call('acquire', request, session='worker-run')
        self.assertEqual(first, second)
        proposal = self.propose_payload('work')
        first_proposal = self.call('propose', proposal, session='worker-run')
        messages = self.call('inbox')['messages']
        second_proposal = self.call('propose', proposal, session='worker-run')
        self.assertEqual(first_proposal, second_proposal)
        self.assertEqual(self.call('inbox')['messages'], messages)
        self.reject_unchanged('propose', dict(proposal, evidence='Changed evidence'), session='worker-run')

    def test_actual_killed_acceptance_preserves_atomic_snapshot_and_targeted_inbox(self):
        self.plan('work'); self.acquire('work')
        self.call('propose', self.propose_payload('work'), session='worker-run')
        payload = self.accept_payload('work')
        ctx = multiprocessing.get_context('spawn')
        before = self.checkpoint()
        for boundary in ('before_commit', 'after_commit'):
            with self.subTest(boundary=boundary):
                read, write = ctx.Pipe(duplex=False)
                wait = ctx.Event()
                process = ctx.Process(target=interrupted_accept,
                    args=(str(self.database), self.tokens['owner-run'], payload, boundary, write, wait))
                process.start()
                self.assertTrue(read.poll(20), 'Worker failed to reach interruption boundary')
                read.recv()
                process.terminate(); process.join(timeout=20)
                self.engine = Coordinator(self.database)
                self.engine.recover()
                if boundary == 'before_commit':
                    self.assertEqual(self.checkpoint(), before)
                    self.assertEqual(self.snapshot()['revision'], 0)
                else:
                    self.assertEqual(self.snapshot()['revision'], 1)
                    self.assertEqual(self.call('proposal', {'proposal_id': 'proposal'}, root=True)['status'], 'accepted')
                    self.assertTrue(any(message['kind'] == 'proposal-accept' for message in self.call('inbox')['messages']))
                    self.assertTrue(self.call('accept', payload)['idempotent'])
                read.close(); write.close()

    def test_real_expiry_race_renewal_loses_to_generation_reassignment(self):
        self.plan('work'); original = self.acquire('work')
        proposal = self.propose_payload('work')
        self.call('propose', proposal, session='worker-run')
        self.open_session('replacement', self.worker_token, 'contributor')
        acquisition = self.acquire_payload('work')
        renewal = {'assignment_id': 'work', 'generation': original['generation'], 'ttl_seconds': 300, 'policy_revision': 1}
        now_ms = original['lease']['expires_ms'] + 1
        ctx = multiprocessing.get_context('spawn')
        barrier, results = ctx.Barrier(2), ctx.Queue()
        processes = [ctx.Process(target=raced_request, args=(str(self.database), token, operation, payload,
                      barrier, results, now_ms)) for token, operation, payload in
                     [(self.tokens['worker-run'], 'renew', renewal), (self.tokens['replacement'], 'acquire', acquisition)]]
        for process in processes:
            process.start()
        values = [results.get(timeout=20) for _ in processes]
        for process in processes:
            process.join(timeout=20)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sum(value.get('ok', False) for value in values), 1)
        winner = next(value['result'] for value in values if value.get('ok'))
        self.assertEqual(winner['lease']['session_id'], 'replacement')
        with patch.object(coordination.time, 'time_ns', return_value=now_ms * 1000000):
            self.reject_unchanged('accept', self.accept_payload('work'))

    def test_defect_replan_replacement_output_resolves_without_rewriting_contract_history(self):
        self.plan('producer'); self.acquire('producer')
        first = self.publish_interface('producer')
        self.complete('producer')
        self.call('defect-report', {'defect_id': 'broken', 'assignment_id': 'producer', 'kind': 'interface',
            'interface_revision': 1, 'summary': 'Reproduced contract defect', 'evidence': 'Expected field is absent',
            'policy_revision': 1})
        self.assertFalse(self.call('outputs', {'assignment_id': 'producer'}, root=True)['outputs'][0]['valid'])
        self.call('replan', {'assignment_id': 'producer', 'expected_plan_revision': 1, 'dependencies': [],
                           'reason': 'Replace defective contract', 'policy_revision': 1})
        self.acquire('producer')
        self.publish_interface('producer', 'Corrected contract', 2)
        replacement = self.complete('producer')['output']
        result = self.call('defect-resolve', {'defect_id': 'broken', 'replacement_assignment_id': 'producer',
            'replacement_output_revision': replacement['output_revision'], 'evidence': 'Reproduction now passes', 'policy_revision': 1})
        self.assertEqual(result['status'], 'resolved')
        original = self.call('interface', {'assignment_id': 'producer', 'interface_revision': 1}, root=True)
        self.assertFalse(original.pop('valid'))
        self.assertEqual(original, first)
        self.assertEqual(self.snapshot()['revision'], 0)

    def test_interface_version_invalidation_preserves_consumer_of_different_valid_version(self):
        self.plan('producer'); self.acquire('producer')
        self.publish_interface('producer', 'Old contract', 1)
        self.publish_interface('producer', 'New contract', 2)
        self.plan('new-consumer', dependencies=[self.edge('producer', revision=2, contract='New contract')])
        consumer = self.acquire('new-consumer')
        self.call('defect-report', {'defect_id': 'old-bug', 'assignment_id': 'producer', 'kind': 'interface',
            'interface_revision': 1, 'summary': 'Defect limited to old contract', 'evidence': 'Compare old version only',
            'policy_revision': 1})
        current = self.assignment('new-consumer')
        self.assertEqual(current['lease'], consumer['lease'])
        self.assertEqual(current['generation'], consumer['generation'])
        self.assertTrue(self.call('interface', {'assignment_id': 'producer', 'interface_revision': 2}, root=True)['valid'])

    def test_owner_session_cannot_mint_unbounded_membership_credentials(self):
        self.reject_unchanged('member', {'actor': 'escalated', 'human': 'Fixture', 'agent': 'Fixture',
            'role': 'owner', 'token': secrets.token_urlsafe(32)})

    def test_changed_parent_role_policy_restricts_preexisting_delegated_session(self):
        self.open_session('parent', self.worker_token, 'contributor', scopes=['session-delegate', 'policy'])
        child_token = secrets.token_urlsafe(32)
        self.call('session-delegate', {'session_id': 'child-worker', 'token': child_token, 'to_actor': 'worker',
            'ttl_seconds': 100, 'scopes': ['policy'], 'targets': ['.']}, session='parent')
        self.tokens['child-worker'] = child_token
        policy = self.call('policy', root=True)['policy']
        policy['session_scopes']['contributor'].remove('policy')
        self.call('policy-update', {'expected_revision': 1, 'policy': policy, 'reason': 'Withdraw parent capability'}, root=True)
        self.reject_unchanged('policy', {}, session='child-worker')

    def test_session_delegation_lifetime_is_bounded(self):
        child_token = secrets.token_urlsafe(32)
        parent = self.call('session', {'session_id': 'owner-run'}, root=True)
        near_expiry = parent['expires_ms'] - 1000
        with patch.object(coordination.time, 'time_ns', return_value=near_expiry * 1000000):
            self.reject_unchanged('session-delegate', {'session_id': 'outlives-parent', 'token': child_token,
                'to_actor': 'owner', 'ttl_seconds': 2, 'scopes': ['policy'], 'targets': ['.']})

    def test_delegation_depth_is_bounded_with_real_session_lineage(self):
        parent = 'owner-run'
        for number in range(1, coordination.MAX_DEPTH + 1):
            identity = 'depth-' + str(number)
            token = secrets.token_urlsafe(32)
            child = self.call('session-delegate', {'session_id': identity, 'token': token, 'to_actor': 'owner',
                'ttl_seconds': 1000 - number * 10, 'scopes': ['session-delegate', 'policy'], 'targets': ['.']}, session=parent)
            self.tokens[identity] = token
            self.assertEqual(child['depth'], number)
            parent = identity
        self.reject_unchanged('session-delegate', {'session_id': 'too-deep', 'token': secrets.token_urlsafe(32),
            'to_actor': 'owner', 'ttl_seconds': 100, 'scopes': ['policy'], 'targets': ['.']}, session=parent)

    def test_no_implicit_schema_upgrade_or_partial_configuration_creation(self):
        database = self.root / 'legacy.sqlite'
        legacy = Coordinator(database)
        legacy.initialize(str(uuid.uuid4()), {'actor': 'owner', 'human': 'Fixture', 'agent': 'Fixture'},
                          self.owner_token, {'a.md': 'LEGACY'})
        with self.assertRaises(ProductError):
            legacy.request(self.owner_token, 'policy', {})
        with closing(sqlite3.connect(database)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
        invalid = self.root / 'invalid.sqlite'
        with self.assertRaises(ProductError):
            Coordinator(invalid).initialize(str(uuid.uuid4()), {'actor': 'owner', 'human': 'Fixture', 'agent': 'Fixture'},
                self.owner_token, {}, coordination={'person_id': 'bad identity', 'agent_id': 'agent', 'policy': {}})
        self.assertFalse(invalid.exists())

    def semantic_conflict(self):
        self.plan('semantic', integration='worker')
        self.acquire('semantic')
        for identity, value in [('initial-fact', 'one'), ('disputed-fact', 'two')]:
            proposal = self.propose_payload('semantic', identity)
            proposal['claims'] = [{'key': 'fixture-policy', 'value': value,
                'source': 'Explicit fixture evidence', 'authority': 'owner'}]
            self.call('propose', proposal, session='worker-run')
            result = self.call('accept', self.accept_payload('semantic', identity, session='worker-run'), session='worker-run')
        self.assertFalse(result['accepted'])
        self.assertEqual([item['kind'] for item in result['conflicts']], ['semantic'])
        return {'proposal_id': 'disputed-fact', 'resolutions': [{'key': 'fixture-policy', 'value': 'two',
            'source': 'Reviewed corrected fixture', 'reason': 'Responsible owner verified correction', 'authority': 'owner'}],
            'coordination': self.context('semantic', 'owner-run')}

    def request_bytes(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute('SELECT id,request_json,request_hash FROM proposals ORDER BY id').fetchall()

    def test_scoped_responsible_owner_resolves_then_contributor_integrates_semantic_conflict(self):
        resolution = self.semantic_conflict()
        original = self.request_bytes()
        self.open_session('fact-reviewer', self.owner_token, 'owner', scopes=['resolve'], targets=['semantic.md'])
        resolution['coordination'] = self.context('semantic', 'fact-reviewer')
        decision = self.call('resolve', resolution, session='fact-reviewer')
        self.assertEqual(decision['decisions'][0]['authority'], 'owner')
        accepted = self.call('accept', self.accept_payload('semantic', 'disputed-fact', session='worker-run'), session='worker-run')
        self.assertTrue(accepted['accepted'])
        self.assertEqual(self.call('facts', root=True)['facts'][0]['value'], 'two')
        self.assertEqual(self.request_bytes(), original)
        self.assertEqual(self.complete('semantic')['status'], 'completed')

    def test_resolution_rejects_scope_identity_stale_context_and_retired_proposal_generation(self):
        resolution = self.semantic_conflict()
        self.open_session('wrong-target', self.owner_token, 'owner', scopes=['resolve'], targets=['other.md'])
        self.reject_unchanged('resolve', dict(resolution, coordination=self.context('semantic', 'wrong-target')), session='wrong-target')
        self.reject_unchanged('resolve', {key: value for key, value in resolution.items() if key != 'coordination'})
        self.reject_unchanged('resolve', dict(resolution, coordination=dict(resolution['coordination'], input_hash='0' * 64)))
        self.reject_unchanged('resolve', dict(resolution, coordination=self.context('semantic', 'worker-run')), session='worker-run')
        self.call('handoff', {'assignment_id': 'semantic', 'to_actor': 'worker', 'summary': 'Replace producer generation',
            'coordination': self.context('semantic')}, session='worker-run')
        self.acquire('semantic')
        self.reject_unchanged('resolve', dict(resolution, coordination=self.context('semantic', 'owner-run')))
        self.assertEqual(self.call('proposal', {'proposal_id': 'disputed-fact'}, root=True)['status'], 'conflict')

    def test_resolution_checks_current_policy_on_both_review_context_and_original_proposal(self):
        resolution = self.semantic_conflict()
        self.call('policy-update', {'expected_revision': 1, 'policy': {'max_lease_seconds': 299}, 'reason': 'New review constraint'}, root=True)
        self.reject_unchanged('resolve', resolution)
        self.reject_unchanged('resolve', dict(resolution, coordination=self.context('semantic', 'owner-run')))

    def test_fenced_supersession_preserves_original_requests_and_requires_integrator(self):
        self.plan('work', integration='worker'); self.acquire('work')
        for identity, contents in [('first', 'FIRST'), ('conflicted', 'SECOND')]:
            self.call('propose', self.propose_payload('work', identity, {'work.md': contents}), session='worker-run')
        self.call('accept', self.accept_payload('work', 'first', session='worker-run'), session='worker-run')
        conflict = self.call('accept', self.accept_payload('work', 'conflicted', session='worker-run'), session='worker-run')
        self.assertFalse(conflict['accepted'])
        self.call('propose', self.propose_payload('work', 'replacement', {'work.md': 'REVIEWED REPLACEMENT'}), session='worker-run')
        self.call('accept', self.accept_payload('work', 'replacement', session='worker-run'), session='worker-run')
        original = self.request_bytes()
        payload = {'proposal_id': 'conflicted', 'replacement_id': 'replacement', 'reason': 'Reviewed accepted replacement',
                   'coordination': self.context('work', 'worker-run')}
        self.reject_unchanged('supersede', dict(payload, coordination=self.context('work', 'owner-run')))
        self.reject_unchanged('supersede', dict(payload, coordination=dict(payload['coordination'], generation=0)), session='worker-run')
        result = self.call('supersede', payload, session='worker-run')
        self.assertEqual(result['status'], 'superseded')
        self.assertEqual(self.request_bytes(), original)
        self.assertEqual(self.snapshot()['files']['work.md'], 'REVIEWED REPLACEMENT')
        self.assertEqual(self.complete('work')['status'], 'completed')

    def test_fact_and_integration_transfer_allow_owner_departure_without_orphaning_work(self):
        next_owner_token = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'next-owner', 'human': 'Next fixture owner', 'agent': 'Fixture',
                            'role': 'owner', 'token': next_owner_token}, root=True)
        self.call('member-binding', {'actor': 'next-owner', 'person_id': 'next-person', 'agent_id': 'next-agent'}, root=True)
        self.open_session('next-owner-run', next_owner_token, 'owner')
        self.plan('work'); producer = self.acquire('work')
        initial = self.propose_payload('work', 'initial')
        initial['claims'] = [{'key': 'fixture-fact', 'value': 'Preserved value', 'source': 'Preserved source', 'authority': 'owner'}]
        self.call('propose', initial, session='worker-run')
        self.call('accept', self.accept_payload('work', 'initial'))
        self.call('propose', self.propose_payload('work', 'pending', {'work.md': 'NEW WORK'}), session='worker-run')
        before = self.snapshot()
        transfer = {'key': 'fixture-fact', 'to_actor': 'next-owner', 'evidence': 'Next owner accepted responsibility',
                    'reason': 'Original owner is leaving', 'policy_revision': 1,
                    'revision': before['revision'], 'files_hash': before['files_hash']}
        self.reject_unchanged('revoke', {'actor': 'owner'}, session='next-owner-run')
        moved = self.call('transfer-authority', transfer)
        self.assertEqual(moved['revision'], before['revision'] + 1)
        self.assertEqual(moved['files_hash'], before['files_hash'])
        self.assertEqual(moved['fact']['value'], 'Preserved value')
        self.assertEqual(moved['fact']['source'], 'Preserved source')
        integration = self.call('transfer-integration', {'assignment_id': 'work', 'to_actor': 'worker',
            'reason': 'Authorized contributor will integrate', 'coordination': self.context('work', 'owner-run')})
        self.assertEqual(integration['integration_owner'], 'worker')
        self.assertEqual(integration['generation'], producer['generation'])
        self.reject_unchanged('accept', self.accept_payload('work', 'pending'))
        self.call('revoke', {'actor': 'owner'}, session='next-owner-run')
        self.owner_token = next_owner_token
        self.reject_unchanged('accept', self.accept_payload('work', 'pending'))
        accepted = self.call('accept', self.accept_payload('work', 'pending', session='worker-run'), session='worker-run')
        self.assertTrue(accepted['accepted'])
        self.assertEqual(self.complete('work')['status'], 'completed')

    def test_transfer_routes_require_scopes_reviewed_policy_receipt_and_responsible_actor(self):
        self.plan('work'); self.acquire('work')
        transfer = {'assignment_id': 'work', 'to_actor': 'worker', 'reason': 'Fixture',
                    'coordination': self.context('work', 'worker-run')}
        self.reject_unchanged('transfer-integration', transfer, session='worker-run')
        self.reject_unchanged('transfer-integration', dict(transfer, coordination=dict(self.context('work', 'owner-run'), generation=0)))
        self.open_session('scoped-fact-owner', self.owner_token, 'owner', scopes=['transfer-authority'], targets=['work.md'])
        snapshot = self.snapshot()
        fact = {'key': 'not-present', 'to_actor': 'worker', 'evidence': 'Fixture', 'reason': 'Fixture',
                'policy_revision': 1, 'revision': snapshot['revision'], 'files_hash': snapshot['files_hash']}
        self.reject_unchanged('transfer-authority', fact, session='scoped-fact-owner')
        self.reject_unchanged('transfer-authority', dict(fact, policy_revision=2))
        self.reject_unchanged('transfer-authority', dict(fact, files_hash='0' * 64))

    def test_requester_identity_survives_different_worker_acquisition_and_replanning(self):
        planned = self.plan('work')
        expected = {'actor': 'owner', 'person_id': 'person-owner', 'agent_id': 'agent-owner', 'session_id': 'owner-run'}
        self.assertEqual(planned['requester'], expected)
        acquired = self.acquire('work')
        self.assertEqual(acquired['actor'], 'worker')
        self.assertEqual(acquired['person_id'], 'person-worker')
        self.assertEqual(acquired['requester'], expected)
        revised = self.call('replan', {'assignment_id': 'work', 'expected_plan_revision': 1, 'dependencies': [],
            'reason': 'Reviewed replan', 'policy_revision': 1})
        self.assertEqual(revised['requester'], expected)

    def test_output_history_pages_summaries_and_exports_exact_individual_version(self):
        # Lower only the protocol envelope to exercise the real aggregation limit
        # with disposable modest fixtures; production remains at 128 MiB.
        with patch.object(engine_module, 'MAX_RESPONSE_BYTES', 1024 * 1024):
            content = 'X' * (768 * 1024)
            self.plan('work', interfaces=['work.md']); self.acquire('work')
            self.call('propose', self.propose_payload('work', changes={'work.md': content}), session='worker-run')
            self.call('accept', self.accept_payload('work'))
            first = self.complete('work')['output']
            self.call('replan', {'assignment_id': 'work', 'expected_plan_revision': 1, 'dependencies': [],
                'reason': 'Publish a second immutable output version', 'policy_revision': 1})
            self.acquire('work'); second = self.complete('work')['output']
            self.assertGreater(len(json.dumps([first, second]).encode()), engine_module.MAX_RESPONSE_BYTES)
            page = self.call('outputs', {'assignment_id': 'work', 'limit': 1}, root=True)
            self.assertEqual(page['next_offset'], 1)
            self.assertEqual(page['total'], 2)
            self.assertNotIn('interfaces', page['outputs'][0])
            following = self.call('outputs', {'assignment_id': 'work', 'offset': page['next_offset'], 'limit': 1}, root=True)
            self.assertIsNone(following['next_offset'])
            self.assertEqual(following['outputs'][0]['output_revision'], 2)
            for expected in (first, second):
                detail = self.call('output', {'assignment_id': 'work', 'output_revision': expected['output_revision']}, root=True)
                self.assertTrue(detail.pop('valid'))
                self.assertEqual(detail, expected)
                self.assertEqual(detail['interfaces']['work.md'], content)
            self.reject_unchanged('outputs', {'assignment_id': 'work', 'limit': True}, root=True)

    def test_reader_only_policy_change_preserves_writer_proposal_and_targets_notifications(self):
        reader_token = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'reader', 'human': 'Reader fixture', 'agent': 'Reader agent',
                            'role': 'reader', 'token': reader_token}, root=True)
        self.call('member-binding', {'actor': 'reader', 'person_id': 'reader-person', 'agent_id': 'reader-agent'}, root=True)
        self.open_session('reader-run', reader_token, 'reader')
        self.plan('work'); self.acquire('work')
        proposed = self.propose_payload('work')
        self.call('propose', proposed, session='worker-run')
        acceptance = self.accept_payload('work')
        original = self.request_bytes()
        worker_inbox = self.call('inbox', session='worker-run')
        policy = self.call('policy', root=True)['policy']
        policy['session_scopes']['reader'].remove('inbox')
        self.call('policy-update', {'expected_revision': 1, 'policy': policy, 'reason': 'Change reader access only'}, root=True)
        self.assertEqual(self.call('inbox', session='worker-run'), worker_inbox)
        self.reject_unchanged('inbox', {}, session='reader-run')
        reader_notices = self.engine.request(reader_token, 'inbox', {})['messages']
        self.assertTrue(any(message['kind'] == 'policy-updated' for message in reader_notices))
        self.assertTrue(self.call('accept', acceptance)['accepted'])
        self.assertEqual(self.request_bytes(), original)
        self.reject_unchanged('policy-update', {'expected_revision': 1, 'policy': policy, 'reason': 'Stale compare-and-swap'}, root=True)

    def restrict_and_restore_role(self, role, operation):
        original = self.call('policy', root=True)['policy']
        restricted = json.loads(json.dumps(original))
        restricted['session_scopes'][role].remove(operation)
        self.call('policy-update', {'expected_revision': 1, 'policy': restricted, 'reason': 'Temporarily restrict authority'}, root=True)
        self.call('policy-update', {'expected_revision': 2, 'policy': original, 'reason': 'Explicitly restore authority'}, root=True)

    def test_restrict_restore_cannot_resurrect_original_producer_policy_context(self):
        self.plan('work'); self.acquire('work')
        original = self.propose_payload('work', 'old')
        self.call('propose', original, session='worker-run')
        original_bytes = self.request_bytes()[0]
        self.restrict_and_restore_role('contributor', 'propose')
        # Integrator explicitly reads the latest policy, but producer bytes still
        # carry their original now-invalidated policy history.
        self.reject_unchanged('accept', self.accept_payload('work', 'old'))
        self.reject_unchanged('propose', dict(original, proposal_id='old-context-new-id'), session='worker-run')
        self.call('propose', self.propose_payload('work', 'reviewed'), session='worker-run')
        self.assertTrue(self.call('accept', self.accept_payload('work', 'reviewed'))['accepted'])
        self.assertIn(original_bytes, self.request_bytes())

    def test_integrator_policy_context_is_checked_separately_from_unchanged_producer(self):
        self.plan('work'); self.acquire('work')
        self.call('propose', self.propose_payload('work'), session='worker-run')
        stale_acceptance = self.accept_payload('work')
        self.restrict_and_restore_role('owner', 'accept')
        self.reject_unchanged('accept', stale_acceptance)
        # Only the integrator role changed. The unchanged producer's immutable
        # old context remains usable after a fresh integration review.
        self.assertTrue(self.call('accept', self.accept_payload('work'))['accepted'])

    def delegated_owner(self, identity, scopes):
        token = secrets.token_urlsafe(32)
        self.call('session-delegate', {'session_id': identity, 'token': token, 'to_actor': 'owner',
            'ttl_seconds': 100, 'scopes': scopes, 'targets': ['work.md']}, session='owner-run')
        self.tokens[identity] = token

    def test_delegated_producer_policy_history_fences_even_with_fresh_integrator_context(self):
        self.plan('work')
        self.delegated_owner('delegated-producer', ['acquire', 'propose'])
        self.acquire('work', 'delegated-producer')
        self.call('propose', self.propose_payload('work', session='delegated-producer'), session='delegated-producer')
        self.restrict_and_restore_role('owner', 'propose')
        self.reject_unchanged('accept', self.accept_payload('work'))

    def test_delegated_integrator_policy_history_rejects_old_context_but_allows_fresh_review(self):
        self.plan('work'); self.acquire('work', 'worker-run')
        self.call('propose', self.propose_payload('work', session='worker-run'), session='worker-run')
        self.delegated_owner('delegated-integrator', ['accept'])
        stale = self.accept_payload('work', session='delegated-integrator')
        self.restrict_and_restore_role('owner', 'accept')
        self.reject_unchanged('accept', stale, session='delegated-integrator')
        self.assertTrue(self.call('accept', self.accept_payload('work', session='delegated-integrator'), session='delegated-integrator')['accepted'])

    def test_policy_notification_excludes_unrelated_independently_authenticated_owner(self):
        token = secrets.token_urlsafe(32)
        self.call('session-delegate', {'session_id': 'delegated-reader', 'token': token, 'to_actor': 'worker',
            'ttl_seconds': 100, 'scopes': ['policy'], 'targets': ['work.md']}, session='worker-run')
        administrator_token = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'administrator', 'human': 'Fixture administrator', 'agent': 'Fixture',
                            'role': 'owner', 'token': administrator_token}, root=True)
        policy = self.call('policy', root=True)['policy']
        policy['session_scopes']['contributor'].remove('policy')
        self.engine.request(administrator_token, 'policy-update', {'expected_revision': 1, 'policy': policy,
                                                                 'reason': 'Change delegating role only'})
        notices = [message for message in self.call('inbox')['messages'] if message['kind'] == 'policy-updated']
        self.assertFalse(notices)
        worker_notices = [message for message in self.call('inbox', session='worker-run')['messages'] if message['kind'] == 'policy-updated']
        self.assertTrue(worker_notices)
        self.assertEqual(worker_notices[-1]['data']['changed_roles'], ['contributor'])

    def test_custom_policy_cannot_delegate_past_ancestor_membership_role(self):
        policy = self.call('policy', root=True)['policy']
        policy['session_scopes']['contributor'].append('policy-update')
        self.call('policy-update', {'expected_revision': 1, 'policy': policy, 'reason': 'Explicit custom operation grants'}, root=True)
        self.open_session('custom-parent', self.worker_token, 'contributor', scopes=['session-delegate', 'policy-update'])
        token = secrets.token_urlsafe(32)
        self.call('session-delegate', {'session_id': 'custom-worker-child', 'token': token, 'to_actor': 'worker',
            'ttl_seconds': 100, 'scopes': ['policy-update'], 'targets': ['.']}, session='custom-parent')
        self.tokens['custom-worker-child'] = token
        self.reject_unchanged('policy-update', {'expected_revision': 2, 'policy': {}, 'reason': 'Attempt inherited-role elevation'}, session='custom-worker-child')

    def test_cross_actor_delegation_never_mints_supplied_token_or_integration_authority(self):
        for actor, role in [('fact-owner', 'owner'), ('other-worker', 'contributor')]:
            token = secrets.token_urlsafe(32)
            self.call('member', {'actor': actor, 'human': actor, 'agent': actor, 'role': role, 'token': token}, root=True)
            self.call('member-binding', {'actor': actor, 'person_id': actor + '-person', 'agent_id': actor + '-agent'}, root=True)
        self.plan('work'); self.acquire('work')
        initial = self.propose_payload('work', 'initial-fact')
        initial['claims'] = [{'key': 'separate-authority', 'value': 'Fixture fact', 'source': 'Reviewed fixture', 'authority': 'fact-owner'}]
        self.call('propose', initial, session='worker-run')
        self.call('accept', self.accept_payload('work', 'initial-fact'))
        self.assertEqual(self.call('facts', root=True)['facts'][0]['authority'], 'fact-owner')
        self.call('propose', self.propose_payload('work', changes={'work.md': 'NEXT REVIEWED WORK'}), session='worker-run')
        self.reject_unchanged('accept', self.accept_payload('work', session='worker-run'), session='worker-run')
        for number, (parent, recipient) in enumerate([
                ('worker-run', 'owner'), ('owner-run', 'fact-owner'),
                ('owner-run', 'worker'), ('worker-run', 'other-worker'), ('owner-run', 'other-worker')]):
            with self.subTest(parent=parent, recipient=recipient):
                child = 'forbidden-child-' + str(number)
                token = secrets.token_urlsafe(32)
                self.reject_unchanged('session-delegate', {'session_id': child, 'token': token, 'to_actor': recipient,
                    'ttl_seconds': 100, 'scopes': ['accept'], 'targets': ['work.md']}, session=parent)
                self.tokens[child] = token
                self.reject_unchanged('accept', self.accept_payload('work', session=child), session=child)
        self.assertTrue(self.call('accept', self.accept_payload('work'))['accepted'])

    def test_preserved_pre_fix_cross_actor_session_history_fails_authentication_without_rewriting(self):
        self.plan('work'); self.acquire('work')
        self.call('propose', self.propose_payload('work'), session='worker-run')
        token = secrets.token_urlsafe(32)
        session_id = 'retained-child'
        self.call('session-delegate', {'session_id': session_id, 'token': token, 'to_actor': 'worker',
            'ttl_seconds': 100, 'scopes': ['accept'], 'targets': ['work.md']}, session='worker-run')
        self.tokens[session_id] = token
        # Recreate exactly the cross-actor document shape accepted by the earlier
        # development runtime. The supplied secret remains in its real token row;
        # do not bypass current authentication or replace it with a mock authority.
        with closing(sqlite3.connect(self.database)) as connection:
            with connection:
                row = connection.execute('SELECT document FROM coord_sessions WHERE id=?', (session_id,)).fetchone()
                document = json.loads(row[0])
                document.update(actor='owner', person_id='person-owner', agent_id='agent-owner')
                connection.execute('UPDATE coord_sessions SET document=?,document_hash=? WHERE id=?',
                    (engine_module.canonical(document), digest(document), session_id))
        retained = self.checkpoint()
        self.reject_unchanged('accept', self.accept_payload('work', session=session_id), session=session_id)
        self.reject_unchanged('policy', {}, session=session_id)
        self.assertEqual(self.checkpoint(), retained)
        self.assertEqual(self.snapshot()['revision'], 0)

    def test_completed_outcome_stays_reserved_until_explicit_replan_or_new_versioned_key(self):
        self.plan('work'); self.acquire('work'); self.complete('work')
        self.reject_unchanged('plan', dict(self.plan_payload('duplicate'), outcome_key='OUTCOME-WORK'))
        reviewed = self.call('replan', {'assignment_id': 'work', 'expected_plan_revision': 1, 'dependencies': [],
            'reason': 'Explicit next version of existing outcome', 'policy_revision': 1})
        self.assertEqual(reviewed['outcome_key'], 'outcome-work')
        distinct = self.call('plan', dict(self.plan_payload('versioned'), outcome_key='outcome-work-v2'))
        self.assertEqual(distinct['outcome_key'], 'outcome-work-v2')


if __name__ == '__main__':
    unittest.main()
