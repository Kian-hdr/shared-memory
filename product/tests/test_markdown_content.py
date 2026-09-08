"""Packaged opt-in Markdown discovery; existing accepted paths remain managed."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

import test_onboarding as helpers


class MarkdownContentTests(unittest.TestCase):
    setUpClass = classmethod(helpers.OnboardingTests.setUpClass.__func__)
    setUp = helpers.OnboardingTests.setUp
    cli = helpers.OnboardingTests.cli
    setup = helpers.OnboardingTests.setup
    coord = helpers.OnboardingTests.coord
    assert_preserved = helpers.OnboardingTests.assert_preserved

    def fixture(self):
        originals = {
            'Nested/Coordination/Items/legacy.md': b'LEGACY_TRACKER_730282\r\n',
            'Nested/Coordination/project_tracker.py': b'LEGACY_CODE_730282\n',
            'Data/settings.json': b'{"preserve":"UNTRACKED_TEXT_730282"}',
            'photo.pdf': b'\x00\xffBINARY_730282',
        }
        for name, data in originals.items():
            path = self.project / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (self.project / 'Long.markdown').write_bytes(b'# Imported long extension\r\n')
        (self.project / 'Upper.MD').write_bytes(b'# Imported uppercase extension\n')
        return originals

    def assert_originals(self, originals):
        for name, data in originals.items():
            self.assertEqual((self.project / name).read_bytes(), data)
        self.assert_preserved()

    def test_markdown_setup_and_resume_preserve_nonmanaged_bytes_and_version_the_manifest(self):
        originals = self.fixture()
        first = self.setup('--content-mode', 'markdown', '--actor', 'owner')
        second = self.setup()
        self.assertEqual(first['readiness'], 'ready')
        self.assertEqual(second['readiness'], 'ready')
        self.assertEqual(first['content_mode'], 'markdown')
        self.assertEqual(second['project_id'], first['project_id'])
        self.assertEqual(first['preserved_drafts'], [])
        self.assertEqual(second['preserved_drafts'], [])
        metadata = json.loads((self.project / '.shared-memory.json').read_text())
        self.assertEqual(metadata['format_version'], 2)
        self.assertEqual(metadata['content_mode'], 'markdown')
        self.assertEqual(json.loads((self.state / 'client/client.json').read_text())['schema_version'], 2)
        self.assertEqual(json.loads((self.state / 'setup-intent.json').read_text())['binding']['content_mode'], 'markdown')
        snapshot = self.coord('snapshot', {})
        self.assertIn('Long.markdown', snapshot['files'])
        self.assertIn('Upper.MD', snapshot['files'])
        self.assertFalse(set(originals) & set(snapshot['files']))
        for path in self.state.rglob('*'):
            if path.is_file():
                for marker in (b'LEGACY_TRACKER_730282', b'LEGACY_CODE_730282', b'UNTRACKED_TEXT_730282', b'BINARY_730282'):
                    self.assertNotIn(marker, path.read_bytes())
        self.assert_originals(originals)

    def test_default_format_one_and_existing_intent_are_unchanged(self):
        self.setup()
        metadata = json.loads((self.project / '.shared-memory.json').read_text())
        intent = (self.state / 'setup-intent.json').read_bytes()
        self.assertEqual(metadata['format_version'], 1)
        self.assertNotIn('content_mode', metadata)
        self.assertNotIn('content_mode', json.loads(intent)['binding'])
        self.assertEqual(self.setup('--content-mode', 'legacy')['content_mode'], 'legacy')
        self.assertEqual((self.state / 'setup-intent.json').read_bytes(), intent)
        before = helpers.inventory(self.root)
        self.setup('--content-mode', 'markdown', expected=3)
        self.assertEqual(helpers.inventory(self.root), before)

    def test_markdown_mode_cannot_be_overridden_by_setup_or_init(self):
        self.setup('--content-mode', 'markdown', '--actor', 'owner', '--person', 'Owner',
                   '--agent', 'Test', '--purpose', 'Fixture')
        before = helpers.inventory(self.root)
        self.setup('--content-mode', 'legacy', expected=3)
        self.cli('init', self.project, '--state-dir', self.state, '--actor', 'owner', '--person', 'Owner',
                 '--agent', 'Test', '--purpose', 'Fixture', '--content-mode', 'legacy', expected=3)
        self.assertEqual(helpers.inventory(self.root), before)

    def test_advanced_init_accepts_markdown_and_resumes_without_resupplying_mode(self):
        self.fixture()
        self.cli('init', self.project, '--state-dir', self.state, '--actor', 'owner', '--person', 'Owner',
                 '--agent', 'Test', '--purpose', 'Fixture', '--content-mode', 'markdown')
        intent = (self.state / 'setup-intent.json').read_bytes()
        (self.project / '.shared-memory.json').unlink()
        self.cli('init', self.project, '--state-dir', self.state, '--actor', 'owner', '--person', 'Owner',
                 '--agent', 'Test', '--purpose', 'Fixture')
        self.assertEqual((self.state / 'setup-intent.json').read_bytes(), intent)
        self.assertEqual(json.loads((self.project / '.shared-memory.json').read_text())['format_version'], 2)

    def test_new_markdown_is_drafted_while_new_untracked_text_is_ignored(self):
        self.setup('--content-mode', 'markdown', '--actor', 'owner')
        self.coord('claim', {'assignment_id': 'new-note', 'targets': ['Fresh.markdown'], 'criteria': ['Exact note'],
                            'dependencies': [], 'resource_limits': {}, 'integration_owner': 'owner'})
        (self.project / 'Fresh.markdown').write_bytes(b'# New note\r\n')
        (self.project / 'ignore.json').write_bytes(b'{"private":"not a note"}')
        result = self.cli('draft', self.project, '--state-dir', self.state, '--assignment-id', 'new-note',
                          '--proposal-id', 'fresh-note', '--evidence', 'Exact new note')
        self.assertEqual(result['changes'], {'Fresh.markdown': '# New note\r\n'})

    def accept_changes(self, name, changes, revision):
        self.coord('claim', {'assignment_id': name, 'targets': list(changes), 'criteria': ['Reviewed accepted paths'],
                            'dependencies': [], 'resource_limits': {}, 'integration_owner': 'owner'})
        self.coord('propose', {'proposal_id': name, 'assignment_id': name, 'base_revision': revision,
                              'changes': changes, 'evidence': 'Reviewed fixture accepted paths'})
        self.coord('accept', {'proposal_id': name, 'validation': 'Exact fixture bytes', 'reason': 'Accepted paths remain managed'})

    def test_required_accepted_nonmarkdown_and_nested_coordination_remain_managed(self):
        originals = self.fixture()
        self.setup('--content-mode', 'markdown', '--actor', 'owner')
        changes = {'Accepted.txt': 'REQUIRED_TEXT\r\n', 'Nested/Coordination/Accepted.md': '# Required history\n'}
        self.accept_changes('required', changes, 0)
        self.cli('refresh', self.project, '--state-dir', self.state)
        self.assertEqual(self.cli('receipt', self.project, '--state-dir', self.state)['readiness'], 'ready')
        self.assert_originals(originals)
        for path in self.state.rglob('*'):
            if path.is_file():
                self.assertNotIn(b'LEGACY_TRACKER_730282', path.read_bytes())
        for name, text in changes.items():
            self.assertEqual((self.project / name).read_bytes(), text.encode())
        (self.project / 'Accepted.txt').write_bytes(b'MODIFIED_REQUIRED_TEXT\r\n')
        result = self.cli('draft', self.project, '--state-dir', self.state, '--assignment-id', 'required',
                          '--proposal-id', 'edit-required', '--evidence', 'Existing accepted text changed')
        self.assertEqual(result['changes'], {'Accepted.txt': 'MODIFIED_REQUIRED_TEXT\r\n'})
        receipt = self.cli('receipt', self.project, '--state-dir', self.state)
        self.assertEqual(receipt['readiness'], 'partial')

    def test_copied_manifest_joins_with_same_mode_without_flag(self):
        self.fixture()
        owner = self.setup('--content-mode', 'markdown', '--actor', 'owner')
        token = self.root / 'recipient.token'
        self.cli('member-add', self.project, '--state-dir', self.state, '--actor', 'recipient',
                 '--person', 'Recipient', '--agent', 'Own agent', '--token-output', token)
        project = self.root / 'Recipient'; project.mkdir()
        private = self.root / 'recipient-state'
        shutil.copyfile(self.project / '.shared-memory.json', project / '.shared-memory.json')
        (project / 'ignore.txt').write_bytes(b'LOCAL_UNTRACKED_TEXT')
        joined = self.setup('--database', self.state / 'coordinator.sqlite3', '--token-file', token,
                            project=project, state=private)
        self.assertEqual(joined['project_id'], owner['project_id'])
        self.assertEqual(joined['content_mode'], 'markdown')
        self.assertEqual(joined['readiness'], 'ready')
        self.assertEqual((project / 'ignore.txt').read_bytes(), b'LOCAL_UNTRACKED_TEXT')
        before = helpers.inventory(self.root)
        self.setup('--content-mode', 'legacy', project=project, state=private, expected=3)
        self.assertEqual(helpers.inventory(self.root), before)

    def test_unsupported_or_downgraded_mode_manifest_refused_without_writes(self):
        self.setup('--content-mode', 'markdown')
        path = self.project / '.shared-memory.json'
        original = json.loads(path.read_text())
        for change in ({'content_mode': 'unknown'}, {'format_version': 1}, {'format_version': 3}):
            path.write_text(json.dumps(dict(original, **change)))
            before = helpers.inventory(self.root)
            self.setup(expected=3)
            self.assertEqual(helpers.inventory(self.root), before)

    def test_markdown_still_refuses_root_legacy_coordination_without_touching_it(self):
        path = self.project / 'Coordination'; path.mkdir()
        (path / 'legacy.md').write_bytes(b'ROOT_LEGACY')
        before = helpers.inventory(self.root)
        self.setup('--content-mode', 'markdown', expected=4)
        self.assertEqual(helpers.inventory(self.root), before)
        self.assertFalse(self.state.exists())

    def test_nonmarkdown_symlink_is_skipped_but_required_markdown_symlink_is_rejected(self):
        link = self.project / 'untracked.txt'
        try:
            link.symlink_to(self.root / 'absent-outside-target')
        except (OSError, NotImplementedError) as exc:
            self.skipTest('Symlink fixture unavailable: ' + type(exc).__name__)
        self.assertEqual(self.setup('--content-mode', 'markdown')['readiness'], 'ready')
        self.assertTrue(link.is_symlink())
        (self.project / 'Bad.md').symlink_to(self.root / 'absent-outside-target')
        self.setup(expected=3)

    @unittest.skipIf(os.name == 'nt', 'Windows cannot create the nonportable filename fixture')
    def test_nonportable_binary_name_is_skipped_before_path_validation(self):
        path = self.project / 'private:asset?.pdf'
        path.write_bytes(b'\x00\xffNONPORTABLE_BINARY')
        self.assertEqual(self.setup('--content-mode', 'markdown')['readiness'], 'ready')
        self.assertEqual(path.read_bytes(), b'\x00\xffNONPORTABLE_BINARY')

    def test_graph_rename_uses_mode_and_preserves_ignored_nested_tracker(self):
        originals = self.fixture()
        self.setup('--content-mode', 'markdown', '--actor', 'owner')
        self.coord('claim', {'assignment_id': 'rename', 'targets': ['Long.markdown', 'Moved.md'],
                            'criteria': ['Preserve original content'], 'dependencies': [],
                            'resource_limits': {}, 'integration_owner': 'owner'})
        planned = self.cli('graph-rename-plan', self.project, '--state-dir', self.state,
                           '--source', 'Long.markdown', '--destination', 'Moved.md')
        self.cli('graph-rename-draft', self.project, '--state-dir', self.state, '--plan-id', planned['plan_id'],
                 '--proposal-id', 'rename', '--assignment-id', 'rename', '--evidence', 'Exact fixture bytes')
        self.cli('submit', self.project, '--state-dir', self.state, '--proposal-id', 'rename')
        self.coord('accept', {'proposal_id': 'rename', 'validation': 'Exact bytes', 'reason': 'Reviewed note move'})
        self.cli('graph-rename-apply', self.project, '--state-dir', self.state, '--plan-id', planned['plan_id'])
        self.assertEqual((self.project / 'Moved.md').read_bytes(), b'# Imported long extension\r\n')
        self.assertFalse((self.project / 'Long.markdown').exists())
        self.assert_originals(originals)

    def test_unmarked_recipient_explicitly_selects_markdown_mode(self):
        owner = self.setup('--content-mode', 'markdown', '--actor', 'owner')
        token = self.root / 'recipient.token'
        self.cli('member-add', self.project, '--state-dir', self.state, '--actor', 'recipient',
                 '--person', 'Recipient', '--agent', 'Own agent', '--token-output', token)
        recipient = self.root / 'Unmarked recipient'; recipient.mkdir()
        (recipient / 'untracked.json').write_bytes(b'UNTRACKED_RECIPIENT_BYTES')
        private = self.root / 'recipient-private-state'
        joined = self.setup('--content-mode', 'markdown', '--database', self.state / 'coordinator.sqlite3',
                            '--token-file', token, '--expected-project-id', owner['project_id'],
                            project=recipient, state=private)
        self.assertEqual(joined['content_mode'], 'markdown')
        self.assertEqual(joined['readiness'], 'ready')
        self.assertEqual((recipient / 'untracked.json').read_bytes(), b'UNTRACKED_RECIPIENT_BYTES')
        self.assertEqual(json.loads((recipient / '.shared-memory.json').read_text())['format_version'], 2)

    def test_interrupted_markdown_materialization_resumes_same_mode_and_private_bytes(self):
        originals = self.fixture()
        self.setup('--content-mode', 'markdown', '--actor', 'owner')
        self.accept_changes('interrupted', {'Accepted.txt': 'Required accepted text\r\n',
                                           'Fresh.md': '# New accepted note\n'}, 0)
        arguments = ['refresh', str(self.project), '--state-dir', str(self.state)]
        crashed = subprocess.run([sys.executable, str(helpers.REPO / 'product/tests/test_setup_recovery.py'),
                                  '--crash-worker', str(self.package), 'after-project-write', json.dumps(arguments)],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(crashed.returncode, 83, crashed.stdout + crashed.stderr)
        intent = (self.state / 'setup-intent.json').read_bytes()
        self.assertTrue((self.state / 'client/journal.json').exists())
        edited = b'POST-INTERRUPTION ACCEPTED TXT EDIT\r\n'
        (self.project / 'Accepted.txt').write_bytes(edited)
        result = self.setup()
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(result['content_mode'], 'markdown')
        self.assertEqual((self.state / 'setup-intent.json').read_bytes(), intent)
        self.assertTrue(result['preserved_drafts'])
        self.assertEqual((self.project / 'Accepted.txt').read_bytes(), b'Required accepted text\r\n')
        self.assertEqual((self.project / 'Fresh.md').read_bytes(), b'# New accepted note\n')
        self.assertTrue(any(path.read_bytes() == edited for path in (self.state / 'client/backups').iterdir()))
        self.assertFalse((self.state / 'client/journal.json').exists())
        self.assert_originals(originals)

    def test_malformed_intent_direct_init_refuses_without_writes(self):
        self.setup('--content-mode', 'markdown', '--actor', 'owner')
        path = self.state / 'setup-intent.json'
        for value in ([], {'binding': None}):
            path.write_text(json.dumps(value))
            before = helpers.inventory(self.root)
            error = self.cli('init', self.project, '--state-dir', self.state, '--actor', 'owner',
                             '--person', 'Owner', '--agent', 'Test', '--purpose', 'Fixture', expected=3)
            self.assertEqual(error['code'], 'setup_invalid')
            self.assertEqual(helpers.inventory(self.root), before)

    @unittest.skipUnless(shutil.which('rclone'), 'Local rclone fixture requires an installed executable')
    def test_delivery_fetch_applies_with_markdown_mode_and_keeps_untracked_text(self):
        self.setup('--content-mode', 'markdown', '--actor', 'owner')
        fixture = self.root / 'local-transfer'; fixture.mkdir()
        self.accept_changes('delivery', {'Delivered.md': '# Delivered fixture\r\n'}, 0)
        args = [self.project, '--state-dir', self.state, '--rclone', shutil.which('rclone'), '--fixture-root', fixture]
        self.cli('delivery-publish', *args)
        (self.project / 'untracked.json').write_bytes(b'PRESERVED_OUTSIDE_DELIVERY')
        result = self.cli('delivery-fetch', *args)
        self.assertEqual(result['local']['byte_source'], 'provider_download')
        self.assertEqual(result['local']['readiness'], 'ready')
        self.assertEqual(result['delivery']['route'], 'local_fixture')
        self.assertEqual((self.project / 'untracked.json').read_bytes(), b'PRESERVED_OUTSIDE_DELIVERY')
        self.assertEqual((self.project / 'Delivered.md').read_bytes(), b'# Delivered fixture\r\n')


if __name__ == '__main__':
    unittest.main()
