"""Real private authority upgrades, backup preservation and crash boundaries."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace import coordinator_migration as migration
from shared_workspace.engine import Coordinator, digest
from shared_workspace.errors import ProductError


def killed_upgrade(arguments, boundary, sender, stop):
    original = migration._connect

    def connect(engine, readonly=False):
        connection = original(engine, readonly)
        if not readonly:
            connection.execute("PRAGMA cache_size=1")
            connection.execute("PRAGMA cache_spill=ON")
        return connection

    def reached(name):
        if name == boundary:
            journal = Path(str(arguments['database']) + '-journal')
            data = journal.read_bytes() if journal.exists() else b''
            sender.send({'boundary': name, 'journal_bytes': len(data),
                         'hot_header': any(data[:8])})
            stop.wait(30)

    migration._connect = connect
    migration._boundary = reached
    try:
        migration.upgrade(**arguments)
    except BaseException as error:
        sender.send({'error': type(error).__name__, 'message': str(error)})
    finally:
        sender.close()


def contending_writer(database, token, sender):
    def connect(self, readonly=False):
        connection = sqlite3.connect(self.db_path.as_uri() + ('?mode=ro' if readonly else '?mode=rw'),
                                     uri=True, timeout=0.1, isolation_level=None)
        connection.row_factory = sqlite3.Row
        return connection

    Coordinator._connect = connect
    try:
        Coordinator(database).request(token, 'member', {
            'actor': 'racing-reader', 'human': 'Synthetic reader', 'agent': 'Test',
            'role': 'reader', 'token': 'racing-reader-secret-long-enough'})
        sender.send({'committed': True})
    except ProductError as error:
        sender.send({'committed': False, 'code': error.exit_code})
    finally:
        sender.close()


class CoordinatorMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-upgrade-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.db = self.root / 'authority.sqlite3'
        self.backup = self.root / 'before-upgrade.sqlite3'
        self.token = secrets.token_urlsafe(32)
        self.project = str(uuid.uuid4())
        self.config = {'person_id': 'person-owner', 'agent_id': 'agent-owner', 'policy': {}}
        self.engine = Coordinator(self.db)
        self.engine.initialize(self.project, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'},
                               self.token, {'Home.md': 'Initial bytes', 'Legacy.md': 'Old note'})

    def call(self, operation, payload):
        return self.engine.request(self.token, operation, payload)

    def claim(self, identity, targets):
        return self.call('claim', {'assignment_id': identity, 'targets': targets,
             'criteria': ['Exact fixture acceptance'], 'dependencies': [],
             'resource_limits': {}, 'integration_owner': 'owner'})

    def proposal(self, identity, content, revision=0):
        return self.call('propose', {'proposal_id': identity, 'assignment_id': 'work',
            'base_revision': revision, 'changes': {'Home.md': content},
            'evidence': 'Synthetic review'})

    def history(self):
        self.claim('work', ['Home.md', 'Legacy.md'])
        self.proposal('accepted', 'Accepted bytes')
        self.call('accept', {'proposal_id': 'accepted', 'validation': 'Compared exact bytes', 'reason': 'Fixture'})
        self.proposal('conflicting', 'Conflicting preserved bytes')
        self.call('accept', {'proposal_id': 'conflicting', 'validation': 'Compared stale version', 'reason': 'Fixture'})
        self.proposal('pending', 'Pending preserved bytes', 1)
        self.proposal('abandoned', 'Rejected preserved bytes', 1)
        self.call('reject', {'proposal_id': 'abandoned', 'reason': 'Explicit owner decision'})
        self.call('member', {'actor': 'receiver', 'human': 'Other fixture owner', 'agent': 'Test',
                  'role': 'contributor', 'token': 'receiver-secret-long-enough'})
        self.claim('handoff', ['Handoff.md'])
        self.call('handoff', {'assignment_id': 'handoff', 'to_actor': 'receiver',
                             'summary': 'Preserve unfinished receipt'})

    def plan(self):
        return migration.plan(self.db, self.token, expected_project_id=self.project,
                              coordination=self.config)

    def arguments(self):
        return {'database': self.db, 'token': self.token, 'expected_project_id': self.project,
                'expected_checkpoint': self.plan()['checkpoint'], 'coordination': self.config,
                'backup_destination': self.backup, 'migration_id': 'fixture-upgrade'}

    def raw(self, path=None):
        with closing(sqlite3.connect(path or self.db)) as connection:
            return {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY {order}').fetchall()
                    for name, order in migration.LEGACY.items()}

    def checkpoint(self, version=1, path=None):
        engine = Coordinator(path or self.db)
        with closing(engine._connect(readonly=True)) as connection:
            connection.execute('BEGIN')
            return migration.verify_checkpoint(connection, engine, expected_schema=version,
                                               expected_project_id=self.project)

    def test_plan_is_read_only_and_upgrade_preserves_all_legacy_bytes_and_verified_backup(self):
        self.history()
        before = self.raw()
        disk = self.db.read_bytes()
        planned = self.plan()
        self.assertEqual(disk, self.db.read_bytes())
        self.assertEqual(planned['assignments_requiring_rebind'], 2)
        self.assertEqual(planned['legacy_proposals_requiring_new_context'], 2)
        result = migration.upgrade(**self.arguments())
        self.assertFalse(result['idempotent'])
        self.assertEqual(self.raw(self.backup), before)
        after = self.raw()
        for table in set(migration.LEGACY) - {'meta', 'events', 'sqlite_sequence'}:
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(after['events'][:-1], before['events'])
        self.assertEqual(self.checkpoint(2)['revision'], planned['revision'])
        self.assertEqual(result['backup_sha256'], hashlib.sha256(self.backup.read_bytes()).hexdigest())
        self.assertEqual(self.checkpoint(path=self.backup)['checkpoint'], planned['checkpoint'])
        with self.assertRaises(ProductError):
            self.call('accept', {'proposal_id': 'pending', 'validation': 'No new context', 'reason': 'Must refuse'})
        self.assertEqual(self.raw()['proposals'], before['proposals'])

    def test_invalid_owner_identity_configuration_and_existing_backup_leave_authority_unchanged(self):
        self.call('member', {'actor': 'reader', 'human': 'Read only', 'agent': 'Test',
                  'role': 'reader', 'token': 'reader-secret-long-enough'})
        args = self.arguments()
        before = self.db.read_bytes()
        for changed in ({'token': 'reader-secret-long-enough'},
                        {'token': 'unknown-secret-long-enough'},
                        {'expected_project_id': str(uuid.uuid4())},
                        {'coordination': {'person_id': 'owner'}}):
            with self.subTest(changed=tuple(changed)):
                with self.assertRaises(ProductError):
                    migration.upgrade(**{**args, **changed})
                self.assertEqual(self.db.read_bytes(), before)
                self.assertFalse(self.backup.exists())
        self.backup.write_bytes(b'Existing unrelated backup must survive')
        with self.assertRaises(ProductError):
            migration.upgrade(**args)
        self.assertEqual(self.backup.read_bytes(), b'Existing unrelated backup must survive')
        self.assertEqual(self.db.read_bytes(), before)

    def test_historical_corruption_and_proposal_state_corruption_fail_before_backup(self):
        for statement in ("UPDATE snapshots SET files_json='{}' WHERE revision=0",
                          "UPDATE proposals SET status='rejected' WHERE id='pending'",
                          "UPDATE events SET event_hash='bad' WHERE seq=1",
                          "UPDATE assignments SET document_hash='bad' WHERE id='work'"):
            with self.subTest(statement=statement), tempfile.TemporaryDirectory(dir=self.root) as directory:
                original = self.db
                self.db = Path(directory) / 'case.sqlite3'
                self.engine = Coordinator(self.db)
                self.engine.initialize(self.project, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'},
                                       self.token, {'Home.md': 'Initial bytes'})
                self.history()
                args = self.arguments()
                with closing(sqlite3.connect(self.db)) as connection:
                    connection.execute(statement); connection.commit()
                before = self.db.read_bytes()
                with self.assertRaises(ProductError):
                    migration.upgrade(**args)
                self.assertEqual(self.db.read_bytes(), before)
                self.assertFalse(self.backup.exists())
                self.db = original

    def test_member_write_after_backup_invalidates_checkpoint_without_losing_writer(self):
        args = self.arguments()
        before = self.raw()

        def boundary(name):
            if name == 'after_backup':
                self.call('member', {'actor': 'new-reader', 'human': 'Fixture', 'agent': 'Test',
                          'role': 'reader', 'token': 'new-reader-secret-long-enough'})

        with patch.object(migration, '_boundary', boundary):
            with self.assertRaises(ProductError) as raised:
                migration.upgrade(**args)
        self.assertEqual(raised.exception.code, 'migration_changed')
        self.assertEqual(self.raw(self.backup), before)
        current = self.checkpoint()
        self.assertEqual(current['revision'], 0)
        self.assertNotEqual(current['checkpoint'], args['expected_checkpoint'])
        self.assertTrue(any(row[0] == 'new-reader' for row in self.raw()['members']))

    def test_real_writer_cannot_commit_while_upgrade_holds_exclusive_lock(self):
        context = multiprocessing.get_context('spawn')
        evidence = []

        def boundary(name):
            if name != 'after_exclusive':
                return
            receive, send = context.Pipe(duplex=False)
            worker = context.Process(target=contending_writer, args=(self.db, self.token, send))
            worker.start(); send.close()
            try:
                self.assertTrue(receive.poll(10))
                evidence.append(receive.recv())
                worker.join(10)
                self.assertFalse(worker.is_alive())
            finally:
                if worker.is_alive():
                    worker.kill(); worker.join(5)
                receive.close()

        with patch.object(migration, '_boundary', boundary):
            migration.upgrade(**self.arguments())
        self.assertEqual(evidence, [{'committed': False, 'code': 5}])
        self.assertFalse(any(row[0] == 'racing-reader' for row in self.raw()['members']))

    def test_lost_ack_retry_is_exact_read_only_and_detects_changed_backup_or_binding(self):
        self.history()
        args = self.arguments()
        migration.upgrade(**args)
        # A lost-response retry must not roll back later legitimate activity.
        self.call('member', {'actor': 'later-reader', 'human': 'Later fixture', 'agent': 'Test',
                  'role': 'reader', 'token': 'later-reader-secret-long-enough'})
        before, backup = self.db.read_bytes(), self.backup.read_bytes()
        result = migration.upgrade(**args)
        self.assertTrue(result['idempotent'])
        self.assertFalse(result['authority_changed'])
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.backup.read_bytes(), backup)
        for changed in ({'migration_id': 'different'}, {'expected_checkpoint': 'a' * 64},
                        {'coordination': {**self.config, 'person_id': 'another-person'}}):
            with self.assertRaises(ProductError):
                migration.upgrade(**{**args, **changed})
            self.assertEqual(self.db.read_bytes(), before)
        self.backup.write_bytes(backup + b'changed')
        with self.assertRaises(ProductError):
            migration.upgrade(**args)
        self.assertEqual(self.db.read_bytes(), before)

    def test_reader_event_hides_backup_path_while_local_receipt_and_exact_retry_remain_useful(self):
        reader_token = 'ordinary-reader-secret-long-enough'
        self.call('member', {'actor': 'ordinary-reader', 'human': 'Synthetic reader', 'agent': 'Test',
                            'role': 'reader', 'token': reader_token})
        args = self.arguments()
        result = migration.upgrade(**args)
        self.assertEqual(result['backup_destination'], str(self.backup))
        events = self.engine.request(reader_token, 'events', {})['events']
        upgrade_event = next(event for event in events if event['operation'] == 'upgrade-coordination')
        serialized = json.dumps(events)
        self.assertNotIn(str(self.backup), serialized)
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn('backup_destination', serialized)
        self.assertEqual(upgrade_event['data']['backup_sha256'], result['backup_sha256'])
        self.assertEqual(upgrade_event['data']['backup_binding_hash'],
                         digest({'kind': 'private_migration_backup_v1', 'destination': str(self.backup)}))
        with closing(sqlite3.connect(self.db)) as connection:
            private = json.loads(connection.execute('SELECT value FROM meta WHERE key=?',
                                                    (migration.RECEIPT_KEY,)).fetchone()[0])
        self.assertEqual(private['backup_destination'], str(self.backup))
        before = self.db.read_bytes()
        self.assertTrue(migration.upgrade(**args)['idempotent'])
        self.assertEqual(self.db.read_bytes(), before)
        relocated = self.root / 'other-private-backup.sqlite3'
        relocated.write_bytes(self.backup.read_bytes())
        with self.assertRaises(ProductError) as raised:
            migration.upgrade(**{**args, 'backup_destination': relocated})
        self.assertEqual(raised.exception.code, 'migration_mismatch')
        self.assertEqual(self.db.read_bytes(), before)

    def test_private_backup_binding_tamper_disagrees_with_public_event_commitment(self):
        args = self.arguments()
        migration.upgrade(**args)
        relocated = self.root / 'replacement-private-backup.sqlite3'
        relocated.write_bytes(self.backup.read_bytes())
        with closing(sqlite3.connect(self.db)) as connection:
            receipt = json.loads(connection.execute('SELECT value FROM meta WHERE key=?',
                                                    (migration.RECEIPT_KEY,)).fetchone()[0])
            receipt['backup_destination'] = str(relocated)
            connection.execute('UPDATE meta SET value=? WHERE key=?',
                               (migration.canonical(receipt), migration.RECEIPT_KEY))
            connection.commit()
        corrupted = self.db.read_bytes()
        with self.assertRaises(ProductError) as raised:
            migration.upgrade(**{**args, 'backup_destination': relocated})
        self.assertEqual(raised.exception.code, 'migration_invalid')
        self.assertEqual(self.db.read_bytes(), corrupted)

    def test_backup_deadline_and_fsync_failure_never_mutate_authority(self):
        args = self.arguments()
        before = self.db.read_bytes()
        with patch.object(migration, 'BACKUP_TIMEOUT_SECONDS', -1):
            with self.assertRaises(ProductError) as raised:
                migration.upgrade(**args)
        self.assertEqual(raised.exception.code, 'migration_timeout')
        self.assertEqual(self.db.read_bytes(), before)
        self.assertTrue(self.backup.exists())
        args['backup_destination'] = self.root / 'flush-failure.sqlite3'
        with patch.object(migration.os, 'fsync', side_effect=OSError('Synthetic durability failure')):
            with self.assertRaises(ProductError) as raised:
                migration.upgrade(**args)
        self.assertEqual(raised.exception.code, 'migration_environment')
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.raw(args['backup_destination']), self.raw())

    def test_journal_and_project_backup_destinations_reject_before_creation(self):
        args = self.arguments()
        before = self.db.read_bytes()
        project = self.root / 'selected-project'
        project.mkdir()
        (project / '.shared-memory.json').write_text('{}')
        for target in (Path(str(self.db) + '-journal'), Path(str(self.db) + '-wal'), project / 'backup.sqlite3'):
            with self.subTest(target=target.name):
                with self.assertRaises(ProductError):
                    migration.upgrade(**{**args, 'backup_destination': target})
                self.assertFalse(target.exists())
                self.assertEqual(self.db.read_bytes(), before)

    def test_explicit_rebind_resumes_work_with_new_proposal_and_preserves_legacy_requests(self):
        self.history()
        original_proposals = {row[0]: (row[4], row[5]) for row in self.raw()['proposals']}
        migration.upgrade(**self.arguments())
        session_token = 'new-session-secret-long-enough'
        self.call('session-open', {'session_id': 'resumed-session', 'token': session_token,
                  'ttl_seconds': 300, 'targets': ['.'],
                  'scopes': ['rebind', 'acquire', 'propose', 'accept', 'complete']})
        def session(operation, payload):
            return self.engine.request(session_token, operation, payload)
        legacy = self.call('assignment', {'assignment_id': 'work'})
        snapshot = self.call('snapshot', {})
        acceptance = {'proposal_id': 'pending', 'validation': 'Review after upgrade', 'reason': 'Must require new context'}
        with self.assertRaises(ProductError):
            session('accept', acceptance)
        rebound = session('rebind', {'assignment_id': 'work', 'expected_assignment_hash': digest(legacy),
            'outcome_key': 'resumed-outcome', 'summary': 'Explicitly resume legacy work',
            'dependencies': [], 'interface_paths': [], 'revision': snapshot['revision'],
            'files_hash': snapshot['files_hash'], 'policy_revision': 1,
            'evidence': 'Owner compared full preserved history and current snapshot'})
        acquired = session('acquire', {'assignment_id': 'work', 'expected_generation': rebound['generation'],
            'ttl_seconds': 120, 'revision': snapshot['revision'], 'files_hash': snapshot['files_hash'], 'policy_revision': 1})
        context = {'session_id': 'resumed-session', 'generation': acquired['generation'],
                   'policy_revision': 1, 'input_hash': acquired['input_hash']}
        with self.assertRaises(ProductError):
            session('accept', {**acceptance, 'coordination': context})
        session('propose', {'proposal_id': 'fresh-reviewed-proposal', 'assignment_id': 'work',
            'base_revision': snapshot['revision'], 'changes': {'Home.md': 'Freshly reviewed after upgrade'},
            'evidence': 'New session compared the latest accepted bytes', 'coordination': context})
        accepted = session('accept', {'proposal_id': 'fresh-reviewed-proposal', 'validation': 'Fresh byte comparison',
                                    'reason': 'Explicit new context', 'coordination': context})
        self.assertTrue(accepted['accepted'])
        final_snapshot = self.call('snapshot', {})
        session('complete', {'assignment_id': 'work', 'revision': final_snapshot['revision'],
                            'files_hash': final_snapshot['files_hash'], 'evidence': 'New output verified',
                            'coordination': context})
        after = {row[0]: (row[4], row[5]) for row in self.raw()['proposals']}
        for proposal_id, preserved in original_proposals.items():
            self.assertEqual(after[proposal_id], preserved)
        self.assertEqual(final_snapshot['files']['Home.md'], 'Freshly reviewed after upgrade')

    def test_checkpoint_covers_members_and_event_sequence_even_without_revision_change(self):
        for statement in ("UPDATE members SET human='Changed actor metadata' WHERE actor='owner'",
                          "UPDATE sqlite_sequence SET seq=900 WHERE name='events'"):
            with self.subTest(statement=statement), tempfile.TemporaryDirectory(dir=self.root) as directory:
                database = Path(directory) / 'authority.sqlite3'
                engine = Coordinator(database)
                engine.initialize(self.project, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'},
                                  self.token, {'Home.md': 'Initial bytes'})
                planned = migration.plan(database, self.token, expected_project_id=self.project,
                                         coordination=self.config)
                with closing(sqlite3.connect(database)) as connection:
                    connection.execute(statement); connection.commit()
                before = database.read_bytes()
                with self.assertRaises(ProductError):
                    migration.upgrade(database, self.token, expected_project_id=self.project,
                                      expected_checkpoint=planned['checkpoint'], coordination=self.config,
                                      backup_destination=self.backup, migration_id='checkpoint-test')
                self.assertEqual(database.read_bytes(), before)
                self.assertFalse(self.backup.exists())
    def test_process_kill_boundaries_preserve_v1_or_complete_v2_and_retained_backup(self):
        context = multiprocessing.get_context('spawn')
        for boundary in ('before_backup', 'during_backup', 'after_backup', 'after_schema', 'after_event', 'before_commit', 'after_commit'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(dir=self.root) as directory:
                self.db = Path(directory) / 'authority.sqlite3'
                self.backup = Path(directory) / 'backup.sqlite3'
                self.engine = Coordinator(self.db)
                self.engine.initialize(self.project, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'},
                                       self.token, {'Home.md': 'Initial bytes'})
                self.history()
                args, original = self.arguments(), self.raw()
                receive, send = context.Pipe(duplex=False)
                stop = context.Event()
                worker = context.Process(target=killed_upgrade, args=(args, boundary, send, stop))
                worker.start(); send.close()
                try:
                    self.assertTrue(receive.poll(20), 'Migration did not reach the selected real boundary')
                    result = receive.recv()
                    self.assertEqual(result.get('boundary'), boundary, result)
                    if boundary in ('after_schema', 'after_event', 'before_commit'):
                        self.assertTrue(result['hot_header'], result)
                        self.assertGreater(result['journal_bytes'], 512)
                    worker.kill(); worker.join(10)
                    self.assertFalse(worker.is_alive())
                    self.assertNotEqual(worker.exitcode, 0)
                finally:
                    if worker.is_alive():
                        worker.kill(); worker.join(5)
                    receive.close()
                Coordinator(self.db).recover()
                if boundary == 'after_commit':
                    self.checkpoint(2)
                    self.assertTrue(migration.upgrade(**args)['idempotent'])
                else:
                    self.assertEqual(self.raw(), original)
                    self.assertEqual(self.checkpoint()['checkpoint'], args['expected_checkpoint'])
                if boundary == 'before_backup':
                    self.assertFalse(self.backup.exists())
                elif boundary != 'during_backup':
                    self.assertEqual(self.raw(self.backup), original)


if __name__ == '__main__':
    unittest.main()
