"""Local actual-client recovery tests; no provider or second-device claims."""
from __future__ import annotations

import errno
import hashlib
import importlib
import json
import os
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
from shared_workspace.errors import ProductError


def filesystem(root):
    return {p.relative_to(root).as_posix(): ('symlink:' + os.readlink(p) if p.is_symlink()
            else 'directory' if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob('*'))}


class LocalTransport:
    """Transport failure injection around the actual authenticated coordinator."""
    def __init__(self, coordinator, token):
        self.coordinator = coordinator
        self.token = token
        self.online = True
        self.fail_after_propose = False

    def __call__(self, operation, payload):
        if not self.online:
            raise ConnectionError('Injected unavailable transport; no request delivered')
        result = self.coordinator.request(self.token, operation, payload)
        if operation == 'propose' and self.fail_after_propose:
            self.fail_after_propose = False
            raise TimeoutError('Injected lost response after durable proposal receipt')
        return result


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_module = importlib.import_module('shared_workspace.client')
        cls.Client = cls.client_module.Client
        cls.Coordinator = importlib.import_module('shared_workspace.engine').Coordinator

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='shared-memory-client-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'Private vault' / 'Projects' / 'Shared project'
        self.project.mkdir(parents=True)
        self.vault = self.root / 'Private vault'
        (self.vault / '.obsidian').mkdir()
        (self.vault / '.obsidian' / 'private.json').write_text('{"fixture":true}')
        (self.vault / 'Private.md').write_text('PRIVATE-PARENT-NOTE')
        self.private = self.root / 'private-client-state'
        self.token = secrets.token_urlsafe(32)
        self.project_id = str(uuid.uuid4())
        self.coordinator = self.Coordinator(self.root / 'authority.sqlite')
        self.initial = {'Notes/a.md': 'Accepted A\n', 'Notes/b.md': 'Accepted B\n', 'Home.md': '# Accepted fixture\n'}
        self.coordinator.initialize(self.project_id, {'actor': 'owner', 'human': 'Owner', 'agent': 'Test'},
                                    self.token, self.initial)
        self.transport = LocalTransport(self.coordinator, self.token)
        self.client = self.Client(self.project, self.private, self.transport)

    def call(self, operation, payload):
        return self.coordinator.request(self.token, operation, payload)

    def claim(self):
        return self.call('claim', {'assignment_id': 'work', 'targets': ['.'], 'criteria': ['Verify fixture bytes'],
            'dependencies': [], 'resource_limits': {'max_proposals': 8}, 'integration_owner': 'owner'})

    def publish(self, identity, changes):
        snapshot = self.call('snapshot', {})
        self.call('propose', {'proposal_id': identity, 'assignment_id': 'work',
            'base_revision': snapshot['revision'], 'changes': changes, 'evidence': 'Remote fixture review', 'claims': []})
        return self.call('accept', {'proposal_id': identity, 'validation': 'Reviewed exact fixture',
                                    'reason': 'Accept synthetic change'})

    def private_contains(self, text):
        return any(text.encode() in p.read_bytes() for p in self.private.rglob('*') if p.is_file())

    def test_constructor_no_mutation_and_attach_preserves_private_parent(self):
        before = filesystem(self.root)
        self.Client(self.project, self.private, self.transport)
        self.assertEqual(filesystem(self.root), before)
        receipt = self.client.attach(self.project_id)
        self.assertEqual(receipt['project_id'], self.project_id)
        self.assertEqual(receipt['readiness'], 'ready')
        self.assertEqual((self.vault / 'Private.md').read_text(), 'PRIVATE-PARENT-NOTE')
        self.assertEqual((self.vault / '.obsidian/private.json').read_text(), '{"fixture":true}')
        for name, contents in self.initial.items():
            self.assertEqual((self.project / name).read_text(), contents)
        self.assertFalse((self.project / '.obsidian').exists())
        self.assertFalse(any(p.suffix in {'.db', '.sqlite'} for p in self.project.rglob('*')))

    def test_wrong_project_identity_and_private_state_inside_project_refused_without_writes(self):
        before = filesystem(self.root)
        with self.assertRaises(ProductError):
            self.client.attach(str(uuid.uuid4()))
        self.assertEqual(filesystem(self.root), before)
        with self.assertRaises(ProductError):
            invalid = self.Client(self.project, self.project / 'unsafe-state', self.transport)
            invalid.attach(self.project_id)
        self.assertEqual(filesystem(self.root), before)

    def test_attach_preserves_conflicting_local_content_before_materialization(self):
        (self.project / 'Notes').mkdir()
        (self.project / 'Notes/a.md').write_text('PREEXISTING-LOCAL-DRAFT')
        (self.project / 'Untracked.md').write_text('UNTRACKED-LOCAL-NOTE')
        self.client.attach(self.project_id)
        self.assertTrue(self.private_contains('PREEXISTING-LOCAL-DRAFT'))
        self.assertEqual((self.project / 'Untracked.md').read_text(), 'UNTRACKED-LOCAL-NOTE')
        self.assertEqual((self.project / 'Notes/a.md').read_text(), self.initial['Notes/a.md'])

    def test_offline_draft_persists_reopen_and_submit_then_accept(self):
        self.client.attach(self.project_id); self.claim()
        accepted = self.call('snapshot', {})
        (self.project / 'Notes/a.md').write_text('OFFLINE-PROPOSAL-BYTES')
        self.transport.online = False
        self.client.draft('offline-draft', 'work', 'Locally compared exact draft content')
        self.assertTrue(self.private_contains('OFFLINE-PROPOSAL-BYTES'))
        before_project = filesystem(self.project)
        try:
            self.client.submit('offline-draft')
        except (ConnectionError, TimeoutError, ProductError):
            pass
        self.assertEqual(filesystem(self.project), before_project)
        self.assertTrue(self.private_contains('OFFLINE-PROPOSAL-BYTES'))
        self.assertEqual(self.call('snapshot', {}), accepted)
        self.client = self.Client(self.project, self.private, self.transport)
        self.transport.online = True
        self.client.submit('offline-draft')
        self.call('accept', {'proposal_id': 'offline-draft', 'validation': 'Explicit review after reconnect',
                            'reason': 'Accept preserved offline proposal'})
        self.client.refresh()
        self.assertEqual(self.client.receipt()['readiness'], 'ready')
        self.assertEqual((self.project / 'Notes/a.md').read_text(), 'OFFLINE-PROPOSAL-BYTES')

    def test_lost_submission_response_retries_same_id_without_duplicate_proposal(self):
        self.client.attach(self.project_id); self.claim()
        (self.project / 'Notes/a.md').write_text('RETRY-PROPOSAL')
        self.client.draft('lost-response', 'work', 'Exact content checked')
        self.transport.fail_after_propose = True
        try:
            self.client.submit('lost-response')
        except (TimeoutError, ProductError):
            pass
        proposals_before = self.call('status', {})['proposals']
        self.client = self.Client(self.project, self.private, self.transport)
        self.client.submit('lost-response')
        self.assertEqual(self.call('status', {})['proposals'], proposals_before)
        self.assertTrue(self.private_contains('RETRY-PROPOSAL'))

    def test_external_edits_never_silently_become_accepted_and_both_versions_survive(self):
        self.client.attach(self.project_id); self.claim()
        (self.project / 'Notes/a.md').write_text('EXTERNAL-EDITOR-DRAFT')
        self.assertEqual(self.client.receipt()['readiness'], 'partial')
        self.assertEqual(self.call('snapshot', {})['files']['Notes/a.md'], 'Accepted A\n')
        self.publish('remote-update', {'Notes/a.md': 'REMOTE-ACCEPTED-CONTENT'})
        self.client.refresh()
        self.assertTrue(self.private_contains('EXTERNAL-EDITOR-DRAFT'))
        self.assertEqual((self.project / 'Notes/a.md').read_text(), 'REMOTE-ACCEPTED-CONTENT')
        self.assertEqual(self.client.receipt()['readiness'], 'ready')

    def test_preserved_external_draft_can_be_promoted_without_rewriting_original(self):
        self.client.attach(self.project_id); self.claim()
        (self.project / 'Notes/a.md').write_text('PRESERVED-FOR-PROMOTION')
        result = self.client.refresh()
        self.assertTrue(result['drafts'])
        preserved_id = result['drafts'][0]
        original_path = self.private / 'drafts' / (preserved_id + '.json')
        original = original_path.read_bytes()
        self.client.promote_preserved(preserved_id, 'promoted-draft', 'work', 'Reviewed external edit')
        self.assertEqual(original_path.read_bytes(), original)
        self.client.submit('promoted-draft')
        self.call('accept', {'proposal_id': 'promoted-draft', 'validation': 'Reviewed preserved draft',
                            'reason': 'Explicit acceptance after promotion'})
        self.client.refresh()
        self.assertEqual((self.project / 'Notes/a.md').read_text(), 'PRESERVED-FOR-PROMOTION')
        self.assertEqual(original_path.read_bytes(), original)

    def test_untracked_binary_attachment_is_preserved_and_explicitly_excluded(self):
        binary = b'\x89PNG\x00\xff\x01SYNTHETIC-BINARY-ATTACHMENT'
        (self.project / 'attachment.png').write_bytes(binary)
        result = self.client.attach(self.project_id)
        self.assertEqual((self.project / 'attachment.png').read_bytes(), binary)
        self.assertIn('attachment.png', json.dumps(result['excluded_artifacts']))
        self.assertNotIn('attachment.png', self.call('snapshot', {})['files'])
        self.client.refresh()
        self.assertEqual((self.project / 'attachment.png').read_bytes(), binary)

    def test_accepted_deletion_preserves_a_divergent_local_file(self):
        self.client.attach(self.project_id); self.claim()
        (self.project / 'Notes/a.md').write_text('LOCAL-AFTER-ACCEPTED-BASE')
        self.publish('delete-remote', {'Notes/a.md': None})
        self.client.refresh()
        self.assertEqual((self.project / 'Notes/a.md').read_text(), 'LOCAL-AFTER-ACCEPTED-BASE')
        self.assertEqual(self.client.receipt()['readiness'], 'partial')
        self.assertTrue(self.private_contains('LOCAL-AFTER-ACCEPTED-BASE'))

    def test_unavailable_transport_keeps_materialized_files_and_drafts(self):
        self.client.attach(self.project_id)
        (self.project / 'Notes/a.md').write_text('OFFLINE-EXTERNAL-EDIT')
        self.transport.online = False
        before = filesystem(self.project)
        try:
            result = self.client.refresh()
        except (ConnectionError, TimeoutError, ProductError):
            result = None
        self.assertEqual(filesystem(self.project), before)
        if result is not None:
            self.assertNotEqual(result['readiness'], 'ready')
        self.assertEqual(self.client.receipt()['readiness'], 'partial')

    def test_tampered_snapshot_hash_does_not_materialize(self):
        snapshot = self.call('snapshot', {})
        snapshot['files'] = {'Notes/a.md': 'TAMPERED-TRANSPORT-BYTES'}
        client = self.Client(self.project, self.private, lambda operation, payload: snapshot)
        before = filesystem(self.root)
        with self.assertRaises(ProductError):
            client.attach(self.project_id)
        self.assertEqual(filesystem(self.root), before)

    def test_symlink_target_is_never_followed_or_overwritten(self):
        outside = self.root / 'Outside.md'; outside.write_text('OUTSIDE-PRESERVED')
        (self.project / 'Notes').mkdir()
        link = self.project / 'Notes/a.md'
        try:
            link.symlink_to(outside)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314 or exc.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS}:
                self.skipTest('Symlinks unavailable in this test environment')
            raise
        before = filesystem(self.root)
        with self.assertRaises(ProductError):
            self.client.attach(self.project_id)
        self.assertEqual(filesystem(self.root), before)
        self.assertTrue(link.is_symlink())
        self.assertEqual(outside.read_text(), 'OUTSIDE-PRESERVED')

    def test_materialization_failure_reopen_preserves_new_interruption_edits(self):
        self.client.attach(self.project_id); self.claim()
        self.publish('two-files', {'Notes/a.md': 'REMOTE-A', 'Notes/b.md': 'REMOTE-B'})
        original = self.client._write_project
        calls = 0
        def fail_second(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError('Injected interruption after first project materialization write')
            return original(*args, **kwargs)
        with patch.object(self.client, '_write_project', side_effect=fail_second):
            with self.assertRaises((OSError, ProductError)):
                self.client.refresh()
        self.assertGreaterEqual(calls, 2)
        self.assertNotEqual(self.client.receipt()['readiness'], 'ready')
        (self.project / 'Notes/a.md').write_text('NEW-EDIT-AFTER-INTERRUPTION')
        self.client = self.Client(self.project, self.private, self.transport)
        self.client.refresh()
        self.assertTrue(self.private_contains('NEW-EDIT-AFTER-INTERRUPTION'))
        self.assertEqual((self.project / 'Notes/a.md').read_text(), 'REMOTE-A')
        self.assertEqual((self.project / 'Notes/b.md').read_text(), 'REMOTE-B')
        self.assertEqual(self.client.receipt()['readiness'], 'ready')

    def test_each_replace_boundary_before_and_after_recovers_with_post_crash_edits(self):
        clients = []
        for boundary in ['journal', 'first-file', 'second-file', 'snapshot']:
            for timing in ['before', 'after']:
                label = boundary + '-' + timing
                project = self.root / ('fixture-' + label); project.mkdir()
                state = self.root / ('state-' + label)
                client = self.Client(project, state, self.transport)
                client.attach(self.project_id)
                clients.append((boundary, timing, project, state, client))
        self.claim()
        self.publish('boundary-update', {'Notes/a.md': 'REMOTE-A', 'Notes/b.md': 'REMOTE-B'})
        expected = self.call('snapshot', {})
        replace = self.client_module.os.replace
        for boundary, timing, project, state, client in clients:
            with self.subTest(boundary=boundary, timing=timing):
                target = {'journal': state / 'journal.json', 'first-file': project / 'Notes/a.md',
                          'second-file': project / 'Notes/b.md', 'snapshot': state / 'snapshot.json'}[boundary]
                injected = False
                def fail_replace(source, destination, *args, **kwargs):
                    nonlocal injected
                    if Path(destination).resolve() == target.resolve() and not injected:
                        injected = True
                        if timing == 'before':
                            raise OSError('Injected pre-replace interruption')
                        replace(source, destination, *args, **kwargs)
                        raise OSError('Injected post-replace interruption')
                    return replace(source, destination, *args, **kwargs)
                with patch.object(self.client_module.os, 'replace', side_effect=fail_replace):
                    with self.assertRaises((OSError, ProductError)):
                        client.refresh()
                self.assertTrue(injected)
                receipt = client.receipt()
                self.assertFalse(receipt['readiness'] == 'ready' and receipt['revision'] == expected['revision'])
                marker = 'INTERRUPTION-EDIT-' + boundary + '-' + timing
                (project / 'Notes/a.md').write_text(marker)
                recovered = self.Client(project, state, self.transport)
                recovered.refresh()
                self.assertTrue(any(marker.encode() in p.read_bytes() for p in state.rglob('*') if p.is_file()))
                self.assertEqual((project / 'Notes/a.md').read_text(), 'REMOTE-A')
                self.assertEqual((project / 'Notes/b.md').read_text(), 'REMOTE-B')
                self.assertEqual(recovered.receipt()['readiness'], 'ready')


if __name__ == '__main__':
    unittest.main(verbosity=2)
