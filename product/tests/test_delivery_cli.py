"""Packaged delivery workflow through real local rclone; no cloud evidence."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import test_team_cli as fixtures

file_bytes = fixtures.file_bytes
from shared_workspace import delivery_workflow
from shared_workspace.errors import ProductError


class DeliveryBindingTests(unittest.TestCase):
    def test_binding_cannot_select_another_provider_or_relative_executable(self):
        args = SimpleNamespace(rclone='rclone', fixture_root=None, binding_file='unused')
        with self.assertRaises(ProductError) as caught:
            delivery_workflow._backend(args, Path('/project'), Path('/state'), 'google-drive')
        self.assertEqual(caught.exception.code, 'usage_error')
        args.rclone = sys.executable
        with self.assertRaises(ProductError) as caught:
            delivery_workflow._backend(args, Path('/project'), Path('/state'), 'local')
        self.assertEqual(caught.exception.code, 'delivery_provider')

    def test_fixture_cannot_overlap_private_state_or_selected_project(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            project, state = base / 'project', base / 'state'
            project.mkdir(); state.mkdir()
            for fixture in (state, state / 'nested', project / 'nested', base):
                args = SimpleNamespace(rclone=sys.executable, fixture_root=str(fixture), binding_file=None)
                with self.assertRaises(ProductError):
                    delivery_workflow._backend(args, project, state, 'local')


@unittest.skipUnless(shutil.which('rclone'), 'Optional installed rclone local backend unavailable; no provider evidence')
class DeliveryCLITests(unittest.TestCase):
    # Reuse only packaged fixture helpers, not the other suite's test methods.
    setUpClass = classmethod(fixtures.TeamCLITests.setUpClass.__func__)
    setUp = fixtures.TeamCLITests.setUp
    cli = fixtures.TeamCLITests.cli
    initialize = fixtures.TeamCLITests.initialize
    coord = fixtures.TeamCLITests.coord

    def prepare(self):
        (self.project / 'Old.md').write_bytes(b'accepted old\r\n')
        initialized = self.initialize()
        recipient = self.root / 'Recipient vault' / 'Shared'; recipient.mkdir(parents=True)
        (recipient.parent / 'Private.md').write_bytes(b'never shared')
        state = self.root / 'recipient-state'
        self.cli('attach', recipient, state, '--database', self.state / 'coordinator.sqlite3',
                 '--token-file', self.state / 'member.token', '--expected-project-id', initialized['project_id'])
        fixture = self.root / 'local-transfer'; fixture.mkdir()
        return recipient, state, fixture

    def change(self):
        self.coord('claim', {'assignment_id': 'delivery-work', 'targets': ['.'],
            'criteria': ['Exact fixture'], 'dependencies': [], 'resource_limits': {}, 'integration_owner': 'alex'})
        self.coord('propose', {'proposal_id': 'delivery-change', 'assignment_id': 'delivery-work',
            'base_revision': 0, 'changes': {'Old.md': None, 'New.md': '世界\r\nGreek Ω\nlast'},
            'claims': [], 'evidence': 'Exact fixture'})
        return self.coord('accept', {'proposal_id': 'delivery-change', 'validation': 'Fixture review', 'reason': 'Delivery test'})

    def transfer(self, command, fixture, project=None, state=None, expected=0):
        return self.cli(command, project, state, '--rclone', shutil.which('rclone'),
                        '--fixture-root', fixture, expected=expected)

    def test_packaged_provider_bytes_apply_deletion_and_preserve_private_parent(self):
        recipient, state, fixture = self.prepare()
        accepted = self.change()
        published = self.transfer('delivery-publish', fixture)
        self.assertEqual(published['delivery']['route'], 'local_fixture')
        self.assertEqual(published['delivery']['provider_receipt'], 'not_run')
        result = self.transfer('delivery-fetch', fixture, recipient, state)
        self.assertEqual(result['local']['revision'], accepted['revision'])
        self.assertEqual(result['local']['byte_source'], 'provider_download')
        self.assertEqual(result['delivery']['deleted_paths'], ['Old.md'])
        self.assertEqual(result['delivery']['local_deletions'], 'not_applied')
        self.assertFalse((recipient / 'Old.md').exists())
        self.assertEqual((recipient / 'New.md').read_bytes(), '世界\r\nGreek Ω\nlast'.encode())
        self.assertEqual((recipient.parent / 'Private.md').read_bytes(), b'never shared')
        retry = self.transfer('delivery-fetch', fixture, recipient, state)
        self.assertEqual(retry['local']['revision'], accepted['revision'])
        self.assertFalse(list(state.glob('delivery-*')))

    def test_unpublished_revision_never_falls_back_to_coordinator_content(self):
        recipient, state, fixture = self.prepare()
        self.change()
        before = file_bytes(recipient)
        self.transfer('delivery-fetch', fixture, recipient, state, expected=5)
        self.assertEqual(file_bytes(recipient), before)
        self.assertEqual(json.loads((state / 'client/snapshot.json').read_text())['revision'], 0)

    def test_corrupt_provider_data_does_not_modify_recipient_or_saved_revision(self):
        recipient, state, fixture = self.prepare()
        self.change(); self.transfer('delivery-publish', fixture)
        remote = next(fixture.glob('*/revisions/*/files/New.md'))
        data = remote.read_bytes(); remote.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        before = file_bytes(recipient)
        self.transfer('delivery-fetch', fixture, recipient, state, expected=3)
        self.assertEqual(file_bytes(recipient), before)
        self.assertEqual(json.loads((state / 'client/snapshot.json').read_text())['revision'], 0)


if __name__ == '__main__':
    unittest.main()
