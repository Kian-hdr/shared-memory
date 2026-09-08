"""Core filesystem boundaries on disposable symlinks and real NTFS junctions."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import test_client as fixtures
from shared_workspace import client as client_module, engine, path_safety, workflow, transport
from shared_workspace.cli import parser
from shared_workspace.errors import ProductError


def inventory(root):
    """Fingerprint fixture entries without following the adversarial link."""
    if not root.exists():
        return None
    result, pending = {}, [root]
    while pending:
        folder = pending.pop()
        for path in folder.iterdir():
            name = path.relative_to(root).as_posix()
            if path_safety.is_link_or_reparse(path):
                result[name] = 'link-or-reparse'
            elif path.is_dir():
                result[name] = 'directory'
                pending.append(path)
            else:
                result[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class CorePathSafetyTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ClientTests.setUpClass.__func__)
    setUp = fixtures.ClientTests.setUp
    call = fixtures.ClientTests.call
    claim = fixtures.ClientTests.claim
    publish = fixtures.ClientTests.publish

    def alias(self, path, target):
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest('Directory symlink creation unavailable')
        self.addCleanup(lambda: path.unlink() if path.is_symlink() else None)
        return path

    def unchanged_refusal(self, operation):
        before = inventory(self.root)
        with self.assertRaises(ProductError):
            operation()
        self.assertEqual(inventory(self.root), before)

    def test_project_root_and_ancestor_alias_rejected_before_client_or_setup(self):
        alias = self.alias(self.root / 'project-alias', self.project)
        ancestor = self.alias(self.root / 'vault-alias', self.vault)
        for root in (alias, ancestor / self.project.relative_to(self.vault)):
            self.unchanged_refusal(lambda: self.Client(root, self.private, self.transport))
            self.unchanged_refusal(lambda: workflow.selected_root(root))
            args = parser().parse_args(['init', str(root), '--state-dir', str(self.private), '--person', 'Fixture',
                '--actor', 'fixture', '--agent', 'Test', '--purpose', 'Boundary'])
            self.unchanged_refusal(lambda: workflow.dispatch(None, args))

    def test_attached_draft_rejects_nested_alias_without_reading_or_drafting_private_bytes(self):
        self.client.attach(self.project_id)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'Private.md').write_bytes(b'PRIVATE-SIBLING-FIXTURE')
        self.alias(self.project / 'Linked', outside)
        self.unchanged_refusal(lambda: self.client.draft('unsafe', 'work', 'Review'))
        self.assertFalse((self.private / 'drafts/unsafe.json').exists())

    def test_fresh_attach_rejects_materialization_escape_before_creating_state(self):
        self.claim()
        self.publish('target', {'Linked/Target.md': 'Accepted target\n'})
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'Target.md').write_bytes(b'OUTSIDE-ORIGINAL')
        self.alias(self.project / 'Linked', outside)
        self.unchanged_refusal(lambda: self.client.attach(self.project_id))
        self.assertFalse(self.private.exists())

    def test_refresh_rejects_materialization_escape_without_project_state_or_authority_changes(self):
        self.client.attach(self.project_id)
        self.claim()
        self.publish('target', {'Linked/Target.md': 'Accepted target\n'})
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'Target.md').write_bytes(b'OUTSIDE-ORIGINAL')
        self.alias(self.project / 'Linked', outside)
        self.unchanged_refusal(self.client.refresh)

    def test_pending_journal_recovery_refuses_later_alias_without_advancing_state(self):
        self.client.attach(self.project_id)
        self.claim()
        self.publish('target', {'Linked/Target.md': 'Accepted target\n'})
        with patch.object(self.Client, '_write_project', side_effect=OSError('Disposable pre-write interruption')):
            with self.assertRaises(ProductError):
                self.client.refresh()
        self.assertTrue((self.private / 'journal.json').exists())
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'Target.md').write_bytes(b'OUTSIDE-ORIGINAL')
        self.alias(self.project / 'Linked', outside)
        self.unchanged_refusal(self.client.refresh)

    def test_client_private_state_and_private_record_parent_aliases_rejected(self):
        destination = self.project / 'would-be-private-state'
        destination.mkdir()
        alias = self.alias(self.root / 'state-alias', destination)
        self.unchanged_refusal(lambda: self.Client(self.project, alias, self.transport))
        self.unchanged_refusal(lambda: workflow.private_path(alias, self.project))
        self.client.attach(self.project_id)
        outside = self.root / 'outside-records'
        outside.mkdir()
        self.alias(self.private / 'drafts', outside)
        (self.project / 'Home.md').write_bytes(b'Local proposal\n')
        self.unchanged_refusal(lambda: self.client.draft('unsafe', 'work', 'Review'))

    def test_database_parent_and_sqlite_journal_aliases_rejected(self):
        outside = self.root / 'outside-database'
        outside.mkdir()
        (outside / 'authority.sqlite').write_bytes((self.root / 'authority.sqlite').read_bytes())
        alias = self.alias(self.root / 'database-alias', outside)
        self.unchanged_refusal(lambda: self.Coordinator(alias / 'authority.sqlite'))
        self.alias(self.root / 'authority.sqlite-journal', outside)
        self.unchanged_refusal(lambda: self.coordinator.request(self.token, 'status', {}))

    def test_existing_database_object_rechecks_parent_before_opening(self):
        original = self.root / 'database-holder'
        original.mkdir()
        (original / 'authority.sqlite').write_bytes((self.root / 'authority.sqlite').read_bytes())
        coordinator = self.Coordinator(original / 'authority.sqlite')
        moved = self.root / 'relocated-database-holder'
        original.rename(moved)
        self.alias(original, moved)
        self.unchanged_refusal(lambda: coordinator.request(self.token, 'status', {}))

    def test_workflow_json_and_private_setup_writes_guard_aliased_parent(self):
        outside = self.root / 'outside-input'
        outside.mkdir()
        (outside / 'input.json').write_bytes(b'{"fixture":true}')
        alias = self.alias(self.root / 'input-alias', outside)
        self.unchanged_refusal(lambda: workflow.json_file(alias / 'input.json'))
        self.unchanged_refusal(lambda: workflow.write_private(alias / 'new.token', 'fixture'))
        self.unchanged_refusal(lambda: workflow._publish_setup_bytes(alias / 'intent.json', b'{}'))
        self.unchanged_refusal(lambda: workflow.private_path(alias / 'new-state'))

    def test_lexical_parent_traversal_cannot_hide_alias_before_guard(self):
        outside = self.root / 'outside'
        nested = outside / 'nested'
        nested.mkdir(parents=True)
        (outside / 'secret.json').write_bytes(b'{"private_fixture":true}')
        alias = self.alias(self.project / 'alias', nested)
        target = alias / '..' / 'secret.json'
        self.assertEqual(path_safety.unsafe_ancestor(target), path_safety.absolute_path(alias))
        self.unchanged_refusal(lambda: workflow.json_file(target))
        self.unchanged_refusal(lambda: workflow.write_private(target, 'overwrite', exclusive=False))
        self.unchanged_refusal(lambda: workflow._publish_setup_bytes(alias / '..' / 'new.json', b'{}'))
        self.unchanged_refusal(lambda: self.Coordinator(alias / '..' / 'authority.sqlite'))
        self.unchanged_refusal(lambda: self.Client(alias / '..', self.private, self.transport))

    def test_direct_transport_token_parent_alias_is_refused_before_requests(self):
        outside = self.root / 'outside-token'
        outside.mkdir()
        token_file = outside / 'member.token'
        token_file.write_bytes(self.token.encode())
        token_file.chmod(0o600)
        alias = self.alias(self.root / 'credential-alias', outside)
        credential = alias / 'member.token'
        self.unchanged_refusal(lambda: transport.read_token(credential))
        self.unchanged_refusal(lambda: transport.LocalTransport(self.root / 'authority.sqlite', credential)('status', {}))
        # If HTTPTransport reaches network I/O, this assertion fails immediately.
        with patch.object(transport.urllib.request, 'urlopen', side_effect=AssertionError('Credential refusal must precede network')):
            self.unchanged_refusal(lambda: transport.HTTPTransport('http://127.0.0.1:1', credential)('status', {}))

    def test_init_nested_alias_refuses_before_setup_lock_intent_or_manifest(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'Private.md').write_bytes(b'OUTSIDE-INITIAL-NOTE')
        self.alias(self.project / 'Linked', outside)
        self.unchanged_refusal(lambda: workflow.initial_files(self.project, None))
        args = parser().parse_args(['init', str(self.project), '--state-dir', str(self.private), '--person', 'Fixture',
            '--actor', 'fixture', '--agent', 'Test', '--purpose', 'Boundary'])
        self.unchanged_refusal(lambda: workflow.dispatch(None, args))
        self.assertFalse(self.private.exists())

    def test_protected_configuration_alias_is_opaque_while_genuine_paths_work(self):
        outside = self.root / 'private-config'
        outside.mkdir()
        (outside / 'Private.md').write_bytes(b'PRIVATE-CONFIG-FIXTURE')
        self.alias(self.project / '.obsidian', outside)
        before = inventory(outside)
        self.assertEqual(self.client.attach(self.project_id)['readiness'], 'ready')
        (self.project / 'Home.md').write_bytes(b'Genuine changed home\r\n')
        draft = self.client.draft('genuine', 'work', 'Reviewed fixture')
        self.assertEqual(draft['changes'], {'Home.md': 'Genuine changed home\r\n'})
        self.assertEqual(inventory(outside), before)
        self.assertEqual(workflow.selected_root(self.project), self.project.resolve())
        self.assertEqual(workflow.private_path(self.private), self.private.resolve())
        self.assertEqual(self.coordinator.request(self.token, 'snapshot', {})['files'], self.initial)


@unittest.skipUnless(os.name == 'nt', 'Actual Windows directory junction fixtures')
class WindowsJunctionSafetyTests(CorePathSafetyTests):
    def alias(self, path, target):
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(path), str(target)], capture_output=True)
        self.assertEqual(result.returncode, 0, 'Disposable directory junction creation failed')
        self.assertFalse(path.is_symlink(), 'Fixture must exercise the non-symlink junction case')
        self.assertTrue(path_safety.is_link_or_reparse(path))
        self.addCleanup(lambda: os.rmdir(path) if path_safety.is_link_or_reparse(path) else None)
        return path


class SharedPathPrimitiveTests(unittest.TestCase):
    def test_reparse_attribute_without_symlink_mode_is_rejected(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(path_safety.os, 'lstat', return_value=info):
            self.assertTrue(path_safety.is_link_or_reparse(Path('fixture')))

    def test_initial_import_preserves_markdown_bytes_and_prunes_protected_trees(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='shared-memory-initial-paths-') as temporary:
            root = Path(temporary).resolve()
            (root / 'Notes').mkdir()
            (root / 'Home.md').write_bytes(b'# Home\r\nNo final newline')
            (root / 'Notes/Note.md').write_bytes('Mixed Δ\r\nLF\nCR\r'.encode())
            (root / 'Attachment.txt').write_bytes(b'Not imported')
            (root / 'Upper.MD').write_bytes(b'Platform glob case fixture')
            for folder in ('.obsidian', '.hidden', 'Coordination', 'credentials'):
                (root / folder).mkdir()
                (root / folder / 'Private.md').write_bytes(b'PRIVATE-EXCLUDED')
            actual = workflow.initial_files(root, None)
            # credentials is not in the authority's reserved set: preserve its
            # existing import semantics rather than adopting graph-only exclusions.
            expected = {'Home.md': '# Home\r\nNo final newline', 'Notes/Note.md': 'Mixed Δ\r\nLF\nCR\r'}
            if 'credentials' not in engine.PROTECTED:
                expected['credentials/Private.md'] = 'PRIVATE-EXCLUDED'
            if os.name == 'nt':
                expected['Upper.MD'] = 'Platform glob case fixture'
            self.assertEqual(actual, expected)
            self.assertEqual(workflow.initial_files(root, ['Notes/Note.md']), {'Notes/Note.md': expected['Notes/Note.md']})

    def test_ancestor_check_stops_before_descendants_of_detected_reparse(self):
        path = Path.cwd() / 'alias' / 'private' / 'note.md'
        alias = path.parent.parent
        seen = []
        def check(candidate):
            seen.append(candidate)
            return candidate == alias
        with patch.object(path_safety, 'is_link_or_reparse', side_effect=check):
            self.assertEqual(path_safety.unsafe_ancestor(path), alias)
        self.assertNotIn(path, seen)
        self.assertNotIn(path.parent, seen)

    @unittest.skipUnless(sys.platform == 'darwin', 'Known macOS system temporary aliases')
    def test_known_macos_system_aliases_remain_supported(self):
        for alias in ('/tmp', '/var', '/etc'):
            path = Path(alias)
            self.assertEqual(path_safety.absolute_path(path), Path('/private' + alias))
            self.assertIsNone(path_safety.unsafe_ancestor(path))
