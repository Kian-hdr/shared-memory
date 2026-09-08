"""Actual coordinator dependency and resource-budget boundaries; disposable state only."""
from __future__ import annotations

import hashlib
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
from shared_workspace.engine import Coordinator
from shared_workspace.errors import ProductError


class AssignmentLimitsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-assignment-limits-')
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'authority.sqlite3'
        self.coordinator = Coordinator(self.db)
        self.token = secrets.token_urlsafe(32)
        self.coordinator.initialize(str(uuid.uuid4()),
            {'actor': 'owner', 'human': 'Synthetic owner', 'agent': 'Independent test'},
            self.token, {'Home.md': '# Fixture\n', 'Notes/old.md': 'Preserved original'})

    def call(self, operation, payload=None):
        result = self.coordinator.request(self.token, operation, payload or {})
        json.dumps(result)
        return result

    def claim_payload(self, identity, targets=None, dependencies=None, limits=None):
        return {'assignment_id': identity, 'targets': targets or ['Notes/'],
                'criteria': ['Review exact bounded fixture bytes'],
                'dependencies': dependencies or [], 'resource_limits': limits or {},
                'integration_owner': 'owner'}

    def proposal_payload(self, identity, changes, assignment='work'):
        return {'proposal_id': identity, 'assignment_id': assignment, 'base_revision': 0,
                'changes': changes, 'evidence': 'Explicit fixture byte comparison'}

    def record(self):
        return {'snapshot': self.call('snapshot'), 'status': self.call('status'),
                'events': self.call('events'), 'database_sha256': hashlib.sha256(self.db.read_bytes()).hexdigest()}

    def unchanged_rejection(self, operation, payload, code=4):
        before = self.record()
        with self.assertRaises(ProductError) as raised:
            self.call(operation, payload)
        self.assertEqual(raised.exception.exit_code, code)
        self.coordinator = Coordinator(self.db)
        self.assertEqual(self.record(), before, 'Rejected operation changed durable state, history or database bytes')

    def finish(self, identity):
        current = self.call('snapshot')
        return self.call('complete', {'assignment_id': identity, 'revision': current['revision'],
            'files_hash': current['files_hash'], 'evidence': 'No pending changes; dependency reviewed'})

    def test_unknown_dependency_rejects_without_state_or_history_changes(self):
        self.unchanged_rejection('claim', self.claim_payload('dependent', dependencies=['missing']))

    def test_active_dependency_rejects_then_completed_dependency_allows_claim(self):
        self.call('claim', self.claim_payload('upstream', targets=['Upstream.md']))
        payload = self.claim_payload('dependent', dependencies=['upstream'])
        self.unchanged_rejection('claim', payload)
        self.finish('upstream')
        accepted = self.call('claim', payload)
        self.assertEqual(accepted['dependencies'], ['upstream'])
        self.assertEqual(accepted['status'], 'active')
        self.assertEqual(self.call('assignment', {'assignment_id': 'dependent'}), accepted)

    def test_every_dependency_must_be_completed_without_partial_claim(self):
        self.call('claim', self.claim_payload('done', targets=['Done.md']))
        self.finish('done')
        self.call('claim', self.claim_payload('active', targets=['Active.md']))
        self.unchanged_rejection('claim', self.claim_payload('dependent', dependencies=['done', 'active']))
        self.unchanged_rejection('claim', self.claim_payload('dependent', dependencies=['done', 'unknown']))
        self.finish('active')
        result = self.call('claim', self.claim_payload('dependent', dependencies=['done', 'active']))
        self.assertEqual(result['dependencies'], ['done', 'active'])

    def test_proposal_budget_exact_limit_rejects_next_identity_and_allows_exact_retry(self):
        self.call('claim', self.claim_payload('work', limits={'max_proposals': 2}))
        first = self.proposal_payload('first', {'Notes/a.md': 'one'})
        second = self.proposal_payload('second', {'Notes/a.md': 'two'})
        self.call('propose', first); self.call('propose', second)
        self.unchanged_rejection('propose', self.proposal_payload('excess', {'Notes/a.md': 'three'}))
        before = self.record()
        self.call('propose', first)
        self.assertEqual(self.record(), before, 'Exact retry consumed budget or created a second event')
        self.unchanged_rejection('propose', {**first, 'changes': {'Notes/a.md': 'changed retry'}})

    def test_file_budget_counts_creations_and_deletions_at_exact_boundary(self):
        self.call('claim', self.claim_payload('work', limits={'max_files': 1}))
        self.unchanged_rejection('propose', self.proposal_payload('too-many',
            {'Notes/new.md': 'new', 'Notes/old.md': None}))
        create = self.call('propose', self.proposal_payload('one-create', {'Notes/new.md': 'new'}))
        delete = self.call('propose', self.proposal_payload('one-delete', {'Notes/old.md': None}))
        self.assertEqual(create['changes'], {'Notes/new.md': 'new'})
        self.assertEqual(delete['changes'], {'Notes/old.md': None})
        self.assertEqual(self.call('snapshot')['files']['Notes/old.md'], 'Preserved original')

    def test_byte_budget_uses_utf8_aggregate_with_exact_boundary(self):
        self.call('claim', self.claim_payload('work', limits={'max_bytes': 4}))
        self.unchanged_rejection('propose', self.proposal_payload('five-bytes',
            {'Notes/a.md': '🌍', 'Notes/b.md': 'a'}))
        result = self.call('propose', self.proposal_payload('four-bytes', {'Notes/a.md': '🌍'}))
        self.assertEqual(result['changes'], {'Notes/a.md': '🌍'})
        empty = self.call('propose', self.proposal_payload('zero-bytes', {'Notes/a.md': ''}))
        self.assertEqual(empty['changes'], {'Notes/a.md': ''})
        self.assertNotIn('Notes/a.md', self.call('snapshot')['files'])

    def test_resource_limit_minimum_maximum_and_invalid_values(self):
        ceilings = {'max_proposals': 1000, 'max_files': 10000, 'max_bytes': 100 * 1024 * 1024}
        for key, maximum in ceilings.items():
            for value in (1, maximum):
                with self.subTest(key=key, valid=value):
                    identity = key + '-' + str(value)
                    result = self.call('claim', self.claim_payload(identity,
                        targets=[identity + '.md'], limits={key: value}))
                    self.assertEqual(result['resource_limits'][key], value)
            for value in (0, -1, maximum + 1, True, False, 1.5, '1', None):
                with self.subTest(key=key, invalid=value):
                    self.unchanged_rejection('claim', self.claim_payload('invalid',
                        targets=['Invalid.md'], limits={key: value}), code=3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
