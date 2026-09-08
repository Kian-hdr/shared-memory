"""TEAM-07 reconciliation using actual local authority and private client state.

Transport loss is injected; there is no provider, network, or mixed-device proof.
Independent-file work uses distinct owner/contributor memberships. Same-file work
uses two local clients of the SAME owner, preserving exclusive assignment rules.
"""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
import uuid

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace.client import Client
from shared_workspace.engine import Coordinator
from shared_workspace.errors import ProductError


class InterruptibleLocalTransport:
    """Reopens the real persistent authority for every delivered request."""
    def __init__(self, database, token):
        self.database, self.token = database, token
        self.online = True
        self.lose_proposal_response = False

    def __call__(self, operation, payload):
        if not self.online:
            raise ConnectionError('Injected offline client; no request delivered')
        result = Coordinator(self.database).request(self.token, operation, payload)
        if operation == 'propose' and self.lose_proposal_response:
            self.lose_proposal_response = False
            raise TimeoutError('Injected response loss after durable proposal receipt')
        return result


class OfflineReconciliationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-offline-reconciliation-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.database = self.root / 'private-authority.sqlite3'
        self.project_id = str(uuid.uuid4())
        self.owner_token = secrets.token_urlsafe(48)
        self.contributor_token = secrets.token_urlsafe(48)
        self.initial = {'Notes/a.md': 'Original accepted A\n', 'Notes/b.md': 'Original accepted B\n'}
        Coordinator(self.database).initialize(self.project_id,
            {'actor': 'owner', 'human': 'Fictional Owner', 'agent': 'Local test'}, self.owner_token, self.initial)
        self.call('member', {'actor': 'contributor', 'human': 'Fictional Contributor',
            'agent': 'Local test', 'role': 'contributor', 'token': self.contributor_token})

    def call(self, operation, payload=None, token=None):
        return Coordinator(self.database).request(token or self.owner_token, operation, payload or {})

    def make_client(self, name, token):
        project = self.root / (name + '-selected-project'); project.mkdir()
        state = self.root / (name + '-private-state')
        transport = InterruptibleLocalTransport(self.database, token)
        client = Client(project, state, transport)
        receipt = client.attach(self.project_id)
        self.assertEqual(receipt['readiness'], 'ready')
        return client, project, state, transport

    def claim(self, identity, path, token=None):
        return self.call('claim', {'assignment_id': identity, 'targets': [path],
            'criteria': ['Verify exact synthetic accepted and draft bytes'], 'dependencies': [],
            'resource_limits': {'max_proposals': 8}, 'integration_owner': 'owner'}, token)

    def accept(self, proposal_id):
        return self.call('accept', {'proposal_id': proposal_id,
            'validation': 'Reviewed exact fixture changes against accepted revision',
            'reason': 'Explicit test integration after offline reconciliation'})

    def saved(self, state, identity):
        return state / 'drafts' / (identity + '.json')

    def assert_materialized(self, client, project, expected):
        receipt = client.refresh()
        self.assertEqual(receipt['readiness'], 'ready')
        self.assertEqual(receipt['revision'], expected['revision'])
        self.assertEqual(receipt['files_hash'], expected['files_hash'])
        actual = {p.relative_to(project).as_posix(): p.read_bytes()
                  for p in project.rglob('*') if p.is_file()}
        self.assertEqual(actual, {name: text.encode('utf-8') for name, text in expected['files'].items()})

    def test_distinct_members_offline_original_base_rebases_after_independent_accepted_change(self):
        offline, project, state, transport = self.make_client('contributor', self.contributor_token)
        online, online_project, _, _ = self.make_client('owner', self.owner_token)
        self.claim('contributor-a', 'Notes/a.md', self.contributor_token)
        self.claim('owner-b', 'Notes/b.md')
        original = self.call('snapshot')
        transport.online = False
        (project / 'Notes/a.md').write_bytes('OFFLINE-CONTRIBUTOR-A\n'.encode('utf-8'))
        proposal = offline.draft('offline-a', 'contributor-a', 'Offline contributor compared A with original accepted base')
        self.assertEqual(proposal['base_revision'], original['revision'])
        saved_bytes = self.saved(state, 'offline-a').read_bytes()
        with self.assertRaises((ProductError, ConnectionError)):
            offline.submit('offline-a')
        self.assertEqual(self.call('snapshot'), original)

        (online_project / 'Notes/b.md').write_bytes('ONLINE-OWNER-B\n'.encode('utf-8'))
        online.draft('online-b', 'owner-b', 'Owner verified independent B change')
        online.submit('online-b'); self.accept('online-b')
        advanced = self.call('snapshot')
        self.assertEqual(advanced['revision'], original['revision'] + 1)
        self.assertEqual(advanced['files'], {**self.initial, 'Notes/b.md': 'ONLINE-OWNER-B\n'})
        with self.assertRaises((ProductError, ConnectionError)):
            offline.refresh()
        self.assertEqual((project / 'Notes/a.md').read_bytes(), 'OFFLINE-CONTRIBUTOR-A\n'.encode('utf-8'))
        self.assertEqual(self.saved(state, 'offline-a').read_bytes(), saved_bytes)

        # Restart and refresh before submitting: queued proposal keeps ORIGINAL
        # base and bytes even though visible files now show newer accepted context.
        offline = Client(project, state, transport)
        transport.online = True
        self.assert_materialized(offline, project, advanced)
        self.assertEqual(self.saved(state, 'offline-a').read_bytes(), saved_bytes)
        transport.lose_proposal_response = True
        with self.assertRaises((ProductError, TimeoutError)):
            offline.submit('offline-a')
        self.assertEqual(self.call('snapshot'), advanced)
        offline = Client(project, state, transport)
        offline.submit('offline-a')
        stored = self.call('proposal', {'proposal_id': 'offline-a'})
        self.assertEqual(stored['actor'], 'contributor')
        self.assertEqual(stored['base_revision'], original['revision'])
        self.assertEqual(stored['changes'], {'Notes/a.md': 'OFFLINE-CONTRIBUTOR-A\n'})
        result = self.accept('offline-a')
        self.assertTrue(result['accepted']); self.assertTrue(result['rebased'])
        reconciled = self.call('snapshot')
        self.assertEqual(reconciled['revision'], advanced['revision'] + 1)
        self.assertEqual(reconciled['files'], {'Notes/a.md': 'OFFLINE-CONTRIBUTOR-A\n', 'Notes/b.md': 'ONLINE-OWNER-B\n'})
        self.assertFalse(self.call('status')['conflicts'])
        offline.submit('offline-a'); retried = self.accept('offline-a')
        self.assertTrue(retried['idempotent'])
        self.assertEqual(self.call('snapshot'), reconciled)
        self.assertEqual(self.call('snapshot', {'revision': original['revision']}), original)
        self.assert_materialized(offline, project, reconciled)
        self.assertEqual(self.saved(state, 'offline-a').read_bytes(), saved_bytes)

    def same_owner_reconciliation(self, offline_text, online_text):
        # Two clients of one authorized owner, not two competing actors. One
        # active assignment owns A; both proposals retain that same membership.
        offline, project, state, transport = self.make_client('owner-offline', self.owner_token)
        online, online_project, _, _ = self.make_client('owner-online', self.owner_token)
        self.claim('owner-a', 'Notes/a.md')
        original = self.call('snapshot')
        transport.online = False
        (project / 'Notes/a.md').write_bytes(offline_text.encode('utf-8'))
        offline.draft('queued-a', 'owner-a', 'Saved original owner draft while this local client was offline')
        immutable = self.saved(state, 'queued-a').read_bytes()
        (online_project / 'Notes/a.md').write_bytes(online_text.encode('utf-8'))
        online.draft('accepted-a', 'owner-a', 'Owner reviewed alternate local-client proposal')
        online.submit('accepted-a'); self.accept('accepted-a')
        advanced = self.call('snapshot')
        self.assertEqual(advanced['revision'], original['revision'] + 1)
        self.assertEqual(advanced['files']['Notes/a.md'], online_text)
        with self.assertRaises((ProductError, ConnectionError)):
            offline.submit('queued-a')
        self.assertEqual(self.saved(state, 'queued-a').read_bytes(), immutable)
        self.assertEqual((project / 'Notes/a.md').read_bytes(), offline_text.encode('utf-8'))
        transport.online = True
        offline = Client(project, state, transport)
        self.assert_materialized(offline, project, advanced)
        self.assertEqual(self.saved(state, 'queued-a').read_bytes(), immutable)
        offline.submit('queued-a')
        stored = self.call('proposal', {'proposal_id': 'queued-a'})
        self.assertEqual(stored['actor'], 'owner')
        self.assertEqual(stored['base_revision'], original['revision'])
        self.assertEqual(stored['changes'], {'Notes/a.md': offline_text})
        return offline, project, state, immutable, original, advanced

    def test_same_owner_two_clients_offline_conflict_retains_both_versions_and_retry(self):
        offline_text, online_text = 'OFFLINE-OWNER-PROPOSAL\n', 'ONLINE-OWNER-ACCEPTED\n'
        offline, project, state, immutable, original, advanced = self.same_owner_reconciliation(offline_text, online_text)
        result = self.accept('queued-a')
        self.assertEqual(result['status'], 'conflict'); self.assertFalse(result['accepted'])
        self.assertEqual(result['revision'], advanced['revision'])
        self.assertEqual(self.call('snapshot'), advanced)
        self.assertEqual(len(result['conflicts']), 1)
        detail = self.call('conflict', {'conflict_id': result['conflicts'][0]['conflict_id']})
        self.assertEqual(detail['base'], self.initial['Notes/a.md'])
        self.assertEqual(detail['accepted'], online_text)
        self.assertEqual(detail['proposed'], offline_text)
        self.assertEqual(detail['status'], 'unresolved')
        conflicts_before = self.call('status')['conflicts']
        offline.submit('queued-a'); retry = self.accept('queued-a')
        self.assertFalse(retry['accepted']); self.assertEqual(retry['status'], 'conflict')
        self.assertEqual(self.call('snapshot'), advanced)
        self.assertEqual(self.call('status')['conflicts'], conflicts_before)
        self.assertEqual(self.call('proposal', {'proposal_id': 'queued-a'})['changes'], {'Notes/a.md': offline_text})
        self.assertEqual(self.call('proposal', {'proposal_id': 'accepted-a'})['changes'], {'Notes/a.md': online_text})
        self.assertEqual(self.call('snapshot', {'revision': original['revision']}), original)
        self.assert_materialized(offline, project, advanced)
        self.assertEqual(self.saved(state, 'queued-a').read_bytes(), immutable)

    def test_crlf_and_mixed_line_endings_survive_offline_draft_acceptance_and_materialization(self):
        offline, project, state, transport = self.make_client('contributor-line-endings', self.contributor_token)
        recipient, recipient_project, _, _ = self.make_client('owner-line-endings', self.owner_token)
        self.claim('preserve-line-endings', 'Notes/', self.contributor_token)
        original = self.call('snapshot')
        # Explicit bytes avoid Windows text-mode newline conversion. Both CRLF
        # and mixed LF/CRLF/lone-CR content, UTF8 and missing final newline matter.
        payloads = {
            'Notes/a.md': 'CRLF first\r\nCRLF second\r\n'.encode('utf-8'),
            'Notes/b.md': 'LF α\nCRLF β\r\nCR γ\rno final newline'.encode('utf-8'),
        }
        transport.online = False
        for name, content in payloads.items():
            (project / name).write_bytes(content)
        proposal = offline.draft('exact-line-endings', 'preserve-line-endings',
                                 'Reviewed exact UTF8 bytes without newline normalization')
        self.assertEqual(proposal['base_revision'], original['revision'])
        self.assertEqual({name: text.encode('utf-8') for name, text in proposal['changes'].items()}, payloads)
        saved = self.saved(state, 'exact-line-endings')
        immutable = saved.read_bytes()
        persisted = json.loads(immutable)
        self.assertEqual({name: text.encode('utf-8') for name, text in persisted['changes'].items()}, payloads)
        with self.assertRaises((ProductError, ConnectionError)):
            offline.submit('exact-line-endings')
        for name, content in payloads.items():
            self.assertEqual((project / name).read_bytes(), content)

        # Restart and refresh restore accepted context, while original draft
        # bytes stay queued for an explicit submission and owner acceptance.
        offline = Client(project, state, transport)
        transport.online = True
        self.assert_materialized(offline, project, original)
        self.assertEqual(saved.read_bytes(), immutable)
        offline.submit('exact-line-endings')
        stored = self.call('proposal', {'proposal_id': 'exact-line-endings'})
        self.assertEqual({name: text.encode('utf-8') for name, text in stored['changes'].items()}, payloads)
        self.assertTrue(self.accept('exact-line-endings')['accepted'])
        accepted = self.call('snapshot')
        self.assertEqual(accepted['revision'], original['revision'] + 1)
        self.assertEqual({name: text.encode('utf-8') for name, text in accepted['files'].items()}, payloads)
        self.assert_materialized(offline, project, accepted)
        self.assert_materialized(recipient, recipient_project, accepted)
        self.assertEqual(saved.read_bytes(), immutable)
        self.assertEqual(self.call('snapshot', {'revision': original['revision']}), original)

    def test_same_owner_offline_identical_proposal_deduplicates_without_another_revision(self):
        text = 'IDENTICAL-OWNER-CONTENT\n'
        offline, project, state, immutable, _, advanced = self.same_owner_reconciliation(text, text)
        result = self.accept('queued-a')
        self.assertTrue(result['accepted']); self.assertEqual(result['status'], 'deduplicated')
        self.assertEqual(self.call('snapshot'), advanced)
        offline.submit('queued-a'); retry = self.accept('queued-a')
        self.assertTrue(retry['idempotent'])
        self.assertFalse(self.call('status')['conflicts'])
        self.assertEqual(self.call('snapshot'), advanced)
        self.assert_materialized(offline, project, advanced)
        self.assertEqual(self.saved(state, 'queued-a').read_bytes(), immutable)


if __name__ == '__main__':
    unittest.main(verbosity=2)
