"""Actual coordinator trust checks with separately stored download bytes.

These local fixtures do not assert cloud-provider or second-device delivery.
"""
from __future__ import annotations

import copy
import json
import secrets
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))

from shared_workspace.client import Client
from shared_workspace.engine import Coordinator, files_hash
from shared_workspace.errors import ProductError


def tree(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob('*') if path.is_file()}


class MetadataTransport:
    def __init__(self, coordinator, token):
        self.coordinator, self.token = coordinator, token
        self.calls = []
        self.online = True

    def __call__(self, operation, payload):
        self.calls.append((operation, payload))
        if operation != 'status':
            raise AssertionError('Downloaded application requested coordinator file bytes')
        if not self.online:
            raise ConnectionError('Disposable offline transport')
        return self.coordinator.request(self.token, operation, payload)


class ClientDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-downloaded-client-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = self.root / 'vault' / 'shared'
        self.project.mkdir(parents=True)
        (self.project.parent / 'Private.md').write_bytes(b'PRIVATE PARENT')
        self.state = self.root / 'private-state'
        self.coordinator = Coordinator(self.root / 'authority.sqlite')
        self.project_id = str(uuid.uuid4())
        self.token = secrets.token_urlsafe(32)
        self.initial = {'a.md': 'Original A\r\n', 'b.md': 'Original B\n',
                        'remove.md': 'Original removal candidate\n'}
        self.coordinator.initialize(self.project_id,
            {'actor': 'owner', 'human': 'Fixture owner', 'agent': 'Fixture'}, self.token, self.initial)
        self.client = Client(self.project, self.state, self.call)
        self.client.attach(self.project_id)
        self.transport = MetadataTransport(self.coordinator, self.token)
        self.client.request = self.transport
        self.call('claim', {'assignment_id': 'work', 'targets': ['.'],
            'criteria': ['Compare exact bytes'], 'dependencies': [],
            'resource_limits': {'max_proposals': 8}, 'integration_owner': 'owner'})
        self.download_dir = self.root / 'separate-byte-source'
        self.download_dir.mkdir()
        self.original = self.download()

    def call(self, operation, payload):
        return self.coordinator.request(self.token, operation, payload)

    def download(self):
        # Publisher-side fixture serializes authority bytes to a separate source.
        # The receiving Client transport cannot request the snapshot endpoint.
        snapshot = self.call('snapshot', {})
        path = self.download_dir / ('revision-' + str(snapshot['revision']) + '.json')
        path.write_bytes(json.dumps(snapshot, ensure_ascii=False).encode('utf-8'))
        return json.loads(path.read_bytes())

    def publish(self, identity, changes):
        revision = self.call('status', {'limit': 1})['revision']
        self.call('propose', {'proposal_id': identity, 'assignment_id': 'work',
            'base_revision': revision, 'changes': changes,
            'evidence': 'Compared disposable fixture bytes', 'claims': []})
        self.call('accept', {'proposal_id': identity, 'validation': 'Exact bytes reviewed',
                            'reason': 'Accept fixture'})
        return self.download()

    def preserved(self):
        return [json.loads(path.read_bytes()) for path in (self.state / 'drafts').glob('*.json')]

    def assert_rejected_unchanged(self, target, code=None, client=None):
        before = tree(self.state), tree(self.project.parent)
        with self.assertRaises(ProductError) as raised:
            (client or self.client).apply_downloaded(target)
        if code:
            self.assertEqual(raised.exception.code, code)
        self.assertEqual((tree(self.state), tree(self.project.parent)), before)

    def interrupt_application(self):
        target = self.publish('interrupted', {'a.md': 'Accepted A2', 'b.md': 'Accepted B2'})
        original_write = self.client._write_project
        calls = []

        def fail_second(name, content):
            calls.append(name)
            if len(calls) == 2:
                raise OSError('Disposable second-file interruption')
            return original_write(name, content)

        with patch.object(self.client, '_write_project', side_effect=fail_second):
            with self.assertRaises(ProductError) as raised:
                self.client.apply_downloaded(target)
        self.assertEqual(raised.exception.code, 'client_io')
        self.assertEqual(calls, ['a.md', 'b.md'])
        self.assertTrue((self.state / 'journal.json').exists())
        self.assertEqual(self.client.receipt()['readiness'], 'partial')
        return target

    def test_applies_distinct_download_source_with_metadata_only_authority(self):
        contents = 'Καλημέρα\r\nMixed\nLone\r終わり'
        target = self.publish('update', {'a.md': contents, 'new.md': 'NEW'})
        result = self.client.apply_downloaded(target)
        self.assertEqual(self.transport.calls, [('status', {'limit': 1})])
        self.assertEqual(result['byte_source'], 'provider_download')
        self.assertEqual(result['authority_check'], {k: target[k] for k in
                         ('project_id', 'revision', 'files_hash')})
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual((self.project / 'a.md').read_bytes(), contents.encode('utf-8'))
        self.assertEqual(self.client.accepted_snapshot(), target)
        self.assertEqual((self.project.parent / 'Private.md').read_bytes(), b'PRIVATE PARENT')
        self.assertEqual(self.client.apply_downloaded(target)['readiness'], 'ready')

    def test_missing_corrupt_wrong_project_and_forged_content_rejected(self):
        target = self.publish('update', {'a.md': 'Accepted A2'})
        bad_hash = copy.deepcopy(target)
        bad_hash['files']['a.md'] = 'CORRUPT'
        wrong_project = dict(target, project_id=str(uuid.uuid4()))
        forged = copy.deepcopy(target)
        forged['files']['a.md'] = 'Locally self-hashed content is not authority'
        forged['files_hash'] = files_hash(forged['files'])
        missing = {k: v for k, v in target.items() if k != 'files'}
        for candidate in (None, missing, bad_hash, wrong_project, forged):
            with self.subTest(candidate_type=type(candidate).__name__):
                self.assert_rejected_unchanged(candidate)
        self.assertEqual(self.client.accepted_snapshot(), self.original)

    def test_stale_download_cannot_apply_even_when_newer_than_saved_baseline(self):
        stale = self.publish('first', {'a.md': 'Accepted A2'})
        latest = self.publish('second', {'b.md': 'Accepted B3'})
        self.assert_rejected_unchanged(stale, 'download_not_current')
        self.assertEqual(self.client.apply_downloaded(latest)['readiness'], 'ready')
        self.assert_rejected_unchanged(stale, 'revision_rollback')

    def test_same_revision_disagreement_is_not_accepted_as_local_authority(self):
        forged = copy.deepcopy(self.original)
        forged['files']['a.md'] = 'Forged baseline'
        forged['files_hash'] = files_hash(forged['files'])
        self.assert_rejected_unchanged(forged, 'revision_integrity')
        self.assertFalse(self.transport.calls)

    def test_unattached_scope_does_not_create_state_or_project_files(self):
        fresh = self.root / 'unattached-state'
        client = Client(self.project, fresh, self.transport)
        self.assert_rejected_unchanged(self.original, 'not_attached', client)
        self.assertFalse(fresh.exists())
        self.assertFalse(self.transport.calls)

    def test_authority_unavailable_or_membership_revoked_cannot_apply(self):
        target = self.publish('update', {'a.md': 'Accepted A2'})
        self.transport.online = False
        before = tree(self.state), tree(self.project)
        with self.assertRaises(ProductError) as raised:
            self.client.apply_downloaded(target)
        self.assertEqual(raised.exception.code, 'client_io')
        self.assertEqual((tree(self.state), tree(self.project)), before)
        self.transport.online = True
        reader_token = secrets.token_urlsafe(32)
        self.call('member', {'actor': 'reader', 'human': 'Fixture reader', 'agent': 'Fixture',
                            'role': 'reader', 'token': reader_token})
        self.transport.token = reader_token
        self.call('revoke', {'actor': 'reader'})
        self.assert_rejected_unchanged(target)

    def test_local_edits_deletions_and_untracked_files_survive_as_drafts_or_artifacts(self):
        (self.project / 'a.md').write_bytes(b'LOCAL EDIT')
        (self.project / 'b.md').unlink()
        (self.project / 'remove.md').write_bytes(b'DIVERGENT DELETED FILE')
        (self.project / 'untracked.md').write_bytes(b'UNTRACKED NOTE')
        binary = b'\x89PNG\x00\xffATTACHMENT'
        (self.project / 'attachment.png').write_bytes(binary)
        target = self.publish('update', {'a.md': 'Accepted A2', 'b.md': 'Accepted B2', 'remove.md': None})
        result = self.client.apply_downloaded(target)
        self.assertEqual(result['readiness'], 'partial')
        self.assertTrue(result['drafts'])
        changes = self.preserved()[0]['changes']
        self.assertEqual(changes['a.md'], 'LOCAL EDIT')
        self.assertIsNone(changes['b.md'])
        self.assertEqual(changes['remove.md'], 'DIVERGENT DELETED FILE')
        self.assertEqual(changes['untracked.md'], 'UNTRACKED NOTE')
        self.assertEqual((self.project / 'a.md').read_bytes(), b'Accepted A2')
        self.assertEqual((self.project / 'b.md').read_bytes(), b'Accepted B2')
        self.assertEqual((self.project / 'remove.md').read_bytes(), b'DIVERGENT DELETED FILE')
        self.assertEqual((self.project / 'untracked.md').read_bytes(), b'UNTRACKED NOTE')
        self.assertEqual((self.project / 'attachment.png').read_bytes(), binary)
        self.assertIn('attachment.png', json.dumps(result['excluded_artifacts']))
        self.assertNotIn('remove.md', self.client.accepted_snapshot()['files'])

    def test_unchanged_accepted_file_is_removed(self):
        target = self.publish('delete', {'remove.md': None})
        self.assertEqual(self.client.apply_downloaded(target)['readiness'], 'ready')
        self.assertFalse((self.project / 'remove.md').exists())

    def test_reopen_recovers_download_journal_and_preserves_post_interruption_edits(self):
        target = self.interrupt_application()
        (self.project / 'a.md').write_bytes(b'POST INTERRUPTION EDIT')
        (self.project / 'b.md').unlink()
        self.client = Client(self.project, self.state, self.transport)
        result = self.client.apply_downloaded(target)
        self.assertEqual(result['readiness'], 'ready')
        self.assertFalse((self.state / 'journal.json').exists())
        self.assertEqual(self.client.accepted_snapshot(), target)
        drafts = self.preserved()
        self.assertTrue(any(item['changes'].get('a.md') == 'POST INTERRUPTION EDIT' for item in drafts))
        self.assertTrue(any('b.md' in item['changes'] and item['changes']['b.md'] is None for item in drafts))
        self.assertEqual((self.project / 'a.md').read_bytes(), b'Accepted A2')
        self.assertTrue(all(op == 'status' for op, _ in self.transport.calls))

    def test_recovery_can_advance_from_pending_target_to_new_current_download(self):
        self.interrupt_application()
        latest = self.publish('newer', {'remove.md': None, 'b.md': 'Newest B'})
        result = self.client.apply_downloaded(latest)
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(self.client.accepted_snapshot(), latest)
        self.assertFalse((self.project / 'remove.md').exists())

    def test_rejected_download_never_resumes_existing_journal(self):
        target = self.interrupt_application()
        self.assert_rejected_unchanged(self.original, 'revision_rollback')
        forged = copy.deepcopy(target)
        forged['files']['a.md'] = 'FORGED PENDING CONTENT'
        forged['files_hash'] = files_hash(forged['files'])
        self.assert_rejected_unchanged(forged, 'revision_integrity')
        self.publish('newer', {'b.md': 'Accepted B3'})
        self.assert_rejected_unchanged(target, 'download_not_current')
        self.assertTrue((self.state / 'journal.json').exists())

    def test_recovery_rejects_journal_target_ahead_of_authenticated_authority(self):
        target = self.interrupt_application()
        journal_path = self.state / 'journal.json'
        journal = json.loads(journal_path.read_bytes())
        journal['target']['revision'] = target['revision'] + 1
        journal_path.write_bytes(json.dumps(journal).encode('utf-8'))
        self.assert_rejected_unchanged(target, 'revision_rollback')

    def test_unrelated_journal_baseline_and_saved_state_corruption_are_rejected(self):
        target = self.interrupt_application()
        journal_path = self.state / 'journal.json'
        original_bytes = journal_path.read_bytes()
        journal = json.loads(original_bytes)
        journal['base']['files']['a.md'] = 'UNRELATED JOURNAL BASE'
        journal['base']['files_hash'] = files_hash(journal['base']['files'])
        journal_path.write_bytes(json.dumps(journal).encode('utf-8'))
        self.assert_rejected_unchanged(target, 'client_state')
        journal_path.write_bytes(original_bytes)
        saved_path = self.state / 'snapshot.json'
        saved = json.loads(saved_path.read_bytes())
        saved['files']['a.md'] = 'CORRUPTED SAVED BASELINE'
        saved_path.write_bytes(json.dumps(saved).encode('utf-8'))
        self.assert_rejected_unchanged(target, 'snapshot_integrity')

    def test_accepted_snapshot_is_fresh_saved_copy_without_requests_or_recovery(self):
        self.interrupt_application()
        (self.project / 'a.md').write_bytes(b'LOCAL POST CRASH BYTES')
        before = tree(self.state), tree(self.project)
        self.transport.calls.clear()
        baseline = self.client.accepted_snapshot()
        self.assertEqual(baseline, self.original)
        baseline['files']['a.md'] = 'Mutated caller copy'
        self.assertEqual(self.client.accepted_snapshot(), self.original)
        self.assertEqual((tree(self.state), tree(self.project)), before)
        self.assertFalse(self.transport.calls)
        self.assertTrue((self.state / 'journal.json').exists())

    def test_invalid_metadata_and_wrong_authority_identity_leave_journal_untouched(self):
        target = self.interrupt_application()
        actual_status = self.call('status', {'limit': 1})
        for changes, code in (({'revision': True}, 'invalid_authority'),
                              ({'files_hash': 'bad'}, 'invalid_authority'),
                              ({'project_id': str(uuid.uuid4())}, 'project_mismatch'),
                              ({'revision': 0}, 'download_not_current')):
            with self.subTest(changes=changes):
                malformed = dict(actual_status, **changes)
                with patch.object(self.client, 'request', return_value=malformed):
                    self.assert_rejected_unchanged(target, code)

    def test_newly_tracked_binary_target_is_rejected_before_pending_recovery(self):
        self.interrupt_application()
        (self.project / 'new.md').write_bytes(b'\xffUNTRACKED BINARY')
        target = self.publish('new-file', {'new.md': 'New accepted text'})
        self.assert_rejected_unchanged(target, 'unsupported_content')

    def test_recovery_after_snapshot_commit_before_journal_removal(self):
        target = self.interrupt_application()
        original_save = self.client._save

        def stop_after_commit(name, value):
            original_save(name, value)
            if name == 'snapshot.json':
                raise OSError('Disposable interruption after accepted state commit')

        with patch.object(self.client, '_save', side_effect=stop_after_commit):
            with self.assertRaises(ProductError):
                self.client.apply_downloaded(target)
        self.assertEqual(self.client.accepted_snapshot(), target)
        self.assertTrue((self.state / 'journal.json').exists())
        self.assertEqual(self.client.receipt()['readiness'], 'partial')
        (self.project / 'a.md').write_bytes(b'POST COMMIT LOCAL EDIT')
        reopened = Client(self.project, self.state, self.transport)
        self.assertEqual(reopened.apply_downloaded(target)['readiness'], 'ready')
        self.assertTrue(any(item['changes'].get('a.md') == 'POST COMMIT LOCAL EDIT'
                            for item in self.preserved()))


if __name__ == '__main__':
    unittest.main()
