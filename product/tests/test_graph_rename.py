"""Actual authority/client rename proposals and recovery, disposable folders only."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, call, patch

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))
import test_client as fixtures
import test_team_cli as cli_fixtures
from shared_workspace import graph_rename as rename
from shared_workspace.errors import ProductError


class RenameTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.ClientTests.setUpClass.__func__)
    setUp = fixtures.ClientTests.setUp
    call = fixtures.ClientTests.call
    claim = fixtures.ClientTests.claim
    publish = fixtures.ClientTests.publish

    def test_original_root_is_guarded_before_canonicalization_and_canonical_root_is_rechecked(self):
        # Model Windows lexical/8.3 expansion without pretending macOS is NTFS.
        # Native package tests below exercise actual equivalent Windows paths.
        observed = Mock()
        lexical = Mock()
        canonical = self.project.resolve()
        lexical.resolve.side_effect = lambda: (observed.resolve(), canonical)[1]
        def guard(path):
            observed.guard(path)
            return canonical if path == canonical else lexical
        supplied = Path('LEXICAL~1') / 'Selected folder'
        with patch.object(rename.knowledge, '_absolute', side_effect=guard):
            self.assertEqual(rename._selected_root(supplied), canonical)
        self.assertEqual(observed.mock_calls, [call.guard(supplied), call.resolve(), call.guard(canonical)])
        lexical.reset_mock()
        with patch.object(rename.knowledge, '_absolute', side_effect=ProductError(3, 'knowledge_root', 'Refused reparse')):
            with self.assertRaises(ProductError):
                rename._selected_root(supplied)
        lexical.resolve.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'Windows junction spelling is exercised in packaged tests')
    def test_link_parent_spelling_cannot_disappear_before_root_guard(self):
        alias = self.root / 'Alias'
        alias.symlink_to(self.project, target_is_directory=True)
        try:
            supplied = alias / '..' / self.project.relative_to(self.root)
            self.assertEqual(Path(os.path.abspath(supplied)), self.project)
            with self.assertRaises(ProductError) as caught:
                rename._selected_root(supplied)
            self.assertEqual(caught.exception.code, 'knowledge_root')
        finally:
            alias.unlink()

    def setup_notes(self):
        self.claim()
        self.publish('notes', {'Home.md': '---\r\nrelated: "[[Notes/Old#Heading|Label]]"\r\n---\r\n'
            '# Home\n![[Notes/Old#^block|embed]] [display](Notes/Old.md#heading "title")\r'
            '`[[Notes/Old]]`\n<!-- [[Notes/Old]] -->\n',
            'Notes/Old.md': '# Heading\r\nText ^block\n[other](b.md) [[#Heading]]\rno final newline',
            'Notes/b.md': '# Other\n', 'Notes/a.md': None})
        self.client.attach(self.project_id)

    def prepare(self):
        result = rename.plan(self.client, 'Notes/Old.md', 'Archive/New name.md')
        saved = rename.draft(self.client, result['plan_id'], 'rename-note', 'work', 'Reviewed exact rename and backlink diff')
        return result, saved

    def accept(self):
        self.client.submit('rename-note')
        self.call('accept', {'proposal_id': 'rename-note', 'validation': 'Exact reviewed rename bytes', 'reason': 'Fixture acceptance'})

    def test_plan_draft_accept_apply_preserves_exact_links_and_line_endings(self):
        self.setup_notes()
        before = fixtures.filesystem(self.project)
        parent = (self.vault / 'Private.md').read_bytes()
        plan, draft = self.prepare()
        self.assertEqual(fixtures.filesystem(self.project), before)
        self.assertEqual(plan['source_hashes']['Notes/Old.md'], hashlib.sha256((self.project / 'Notes/Old.md').read_bytes()).hexdigest())
        self.assertEqual(draft['proposal']['changes'], plan['changes'])
        self.assertEqual(plan['originals']['Archive/New name.md'], None)
        with self.assertRaisesRegex(ProductError, 'Submit and accept'):
            rename.apply(self.client, plan['plan_id'])
        self.assertEqual(fixtures.filesystem(self.project), before)
        self.accept()
        result = rename.apply(self.client, plan['plan_id'])
        self.assertEqual(result['readiness'], 'ready')
        self.assertFalse((self.project / 'Notes/Old.md').exists())
        home = (self.project / 'Home.md').read_bytes()
        self.assertIn(b'related: "[[Archive/New name.md#Heading|Label]]"\r\n', home)
        self.assertIn(b'![[Archive/New name.md#^block|embed]]', home)
        self.assertIn(b'[display](Archive/New%20name.md#heading "title")\r', home)
        self.assertIn(b'`[[Notes/Old]]`', home)
        self.assertIn(b'<!-- [[Notes/Old]] -->', home)
        self.assertEqual((self.project / 'Archive/New name.md').read_bytes(),
            b'# Heading\r\nText ^block\n[other](../Notes/b.md) [[#Heading]]\rno final newline')
        self.assertEqual((self.vault / 'Private.md').read_bytes(), parent)
        self.assertEqual(rename.apply(self.client, plan['plan_id'])['readiness'], 'ready')
        for original in plan['originals'].values():
            if original is not None:
                self.assertEqual((self.private / 'backups' / rename.digest(original)).read_bytes(), original.encode())

    def test_local_edit_new_link_and_deleted_note_reject_stale_plan_without_mutation(self):
        self.setup_notes()
        for mutation in ('edit', 'new', 'delete'):
            with self.subTest(mutation=mutation):
                plan = rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
                path = self.project / ('New.md' if mutation == 'new' else 'Home.md')
                original = path.read_bytes() if path.exists() else None
                if mutation == 'delete':
                    path.unlink()
                else:
                    path.write_bytes(b'[[Notes/Old]]\n')
                before = fixtures.filesystem(self.root)
                with self.assertRaises(ProductError) as error:
                    rename.draft(self.client, plan['plan_id'], 'stale', 'work', 'Review')
                self.assertEqual(error.exception.code, 'rename_stale')
                self.assertEqual(fixtures.filesystem(self.root), before)
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)

    def test_remote_advance_and_tampered_plan_refuse_before_draft(self):
        self.setup_notes()
        plan = rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
        self.publish('advance', {'Notes/b.md': '# New accepted other\n'})
        before = fixtures.filesystem(self.root)
        with self.assertRaises(ProductError) as error:
            rename.draft(self.client, plan['plan_id'], 'stale', 'work', 'Review')
        self.assertEqual(error.exception.code, 'rename_stale')
        self.assertEqual(fixtures.filesystem(self.root), before)
        path = self.private / 'rename-plans' / (plan['plan_id'] + '.json')
        value = json.loads(path.read_bytes())
        value['changes']['Home.md'] = 'Corrupted plan'
        path.write_bytes(json.dumps(value).encode())
        before = fixtures.filesystem(self.root)
        with self.assertRaises(ProductError) as error:
            rename.apply(self.client, plan['plan_id'])
        self.assertEqual(error.exception.code, 'rename_plan')
        self.assertEqual(fixtures.filesystem(self.root), before)

    def test_case_prefix_private_escape_and_existing_destination_refuse(self):
        self.setup_notes()
        (self.project / 'Empty').mkdir()
        (self.project / 'Untracked.txt').write_bytes(b'Keep')
        for source, destination in [('Notes/Old.md', '../Escape.md'), ('Notes/Old.md', '.obsidian/New.md'),
                ('Notes/Old.md', 'notes/old.md'), ('Notes/Old.md', 'Notes/b.md/Child.md'),
                ('Notes/Old.md', 'notes/New.md'), ('Notes/Old.md', 'Untracked.txt/Child.md'),
                ('.obsidian/private.md', 'New.md')]:
            with self.subTest(source=source, destination=destination):
                before = fixtures.filesystem(self.root)
                with self.assertRaises(ProductError):
                    rename.plan(self.client, source, destination)
                self.assertEqual(fixtures.filesystem(self.root), before)

    def test_reference_and_ambiguous_links_refuse_without_draft(self):
        self.setup_notes()
        for content in ('[label][old]\n\n[old]: Notes/Old.md\n', '[[b]]\n'):
            changes = {'Home.md': content}
            if content.startswith('[['):
                changes['Extra/b.md'] = '# Duplicate basename\n'
            self.publish('refs' if content.startswith('[label]') else 'ambiguous', changes)
            self.client.refresh()
            before = fixtures.filesystem(self.root)
            with self.assertRaises(ProductError) as error:
                rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
            self.assertEqual(error.exception.code, 'rename_unsupported')
            self.assertEqual(fixtures.filesystem(self.root), before)

    def test_rename_cannot_make_unaffected_existing_basename_link_ambiguous(self):
        self.setup_notes()
        self.publish('basename', {'Home.md': '# Home\n[[b]]\n'})
        self.client.refresh()
        before = fixtures.filesystem(self.root)
        with self.assertRaises(ProductError) as error:
            rename.plan(self.client, 'Notes/Old.md', 'Archive/b.md')
        self.assertEqual(error.exception.code, 'rename_unsupported')
        self.assertEqual(fixtures.filesystem(self.root), before)

    def test_unparsed_frontmatter_and_html_refuse_precisely(self):
        self.setup_notes()
        for identity, content in [('yaml', '---\ncustom: "[[Notes/Old]]"\n---\n# Home\n'),
                                  ('html', '<a href="Notes/Old.md">Old</a>\n')]:
            self.publish(identity, {'Home.md': content})
            self.client.refresh()
            before = fixtures.filesystem(self.root)
            with self.assertRaises(ProductError) as error:
                rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
            self.assertEqual(error.exception.code, 'rename_unsupported')
            self.assertEqual(fixtures.filesystem(self.root), before)

    def test_private_recovery_symlink_refused_and_source_bytes_unchanged(self):
        self.setup_notes()
        link = self.private / 'rename-plans'
        try:
            link.symlink_to(self.vault, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        before = fixtures.filesystem(self.project)
        with self.assertRaises(ProductError) as error:
            rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
        self.assertEqual(error.exception.code, 'rename_unsafe')
        self.assertEqual(fixtures.filesystem(self.project), before)

    def test_static_symlink_and_reparse_detection_never_read_parent(self):
        self.setup_notes()
        link = self.project / 'outside'
        try:
            link.symlink_to(self.vault, target_is_directory=True)
        except OSError:
            self.skipTest('Symlink creation unavailable')
        before = (self.vault / 'Private.md').read_bytes()
        with self.assertRaises(ProductError) as error:
            rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
        self.assertEqual(error.exception.code, 'rename_unsafe')
        self.assertEqual((self.vault / 'Private.md').read_bytes(), before)

    def test_partial_failure_reopen_preserves_post_crash_source_edit(self):
        self.setup_notes()
        plan, _ = self.prepare()
        self.accept()
        original = rename.RenameClient._write_project
        calls = []
        def interrupted(client, name, text):
            calls.append(name)
            if len(calls) == 2:
                raise OSError('Injected interruption after first planned write')
            return original(client, name, text)
        with patch.object(rename.RenameClient, '_write_project', interrupted):
            with self.assertRaises(ProductError):
                rename.apply(self.client, plan['plan_id'])
        self.assertTrue((self.private / 'journal.json').exists())
        (self.project / 'Notes/Old.md').write_bytes(b'Human post-interruption source edit\r\n')
        reopened = self.Client(self.project, self.private, self.transport)
        result = rename.apply(reopened, plan['plan_id'])
        self.assertEqual(result['readiness'], 'partial')
        self.assertEqual((self.project / 'Notes/Old.md').read_bytes(), b'Human post-interruption source edit\r\n')
        self.assertEqual((self.project / 'Archive/New name.md').read_bytes(), plan['changes']['Archive/New name.md'].encode())
        self.assertFalse((self.private / 'journal.json').exists())
        self.assertTrue(result['drafts'])
        self.assertTrue(any(b'Human post-interruption' in path.read_bytes() for path in (self.private / 'drafts').glob('*.json')))

    def test_rejected_apply_never_recovers_existing_pending_journal(self):
        self.setup_notes()
        plan, _ = self.prepare()
        self.accept()
        with patch.object(rename.RenameClient, '_write_project', side_effect=OSError('Before first write')):
            with self.assertRaises(ProductError):
                rename.apply(self.client, plan['plan_id'])
        self.publish('later', {'Notes/b.md': '# Later unrelated acceptance\n'})
        before = fixtures.filesystem(self.root)
        with self.assertRaises(ProductError) as error:
            rename.apply(self.client, plan['plan_id'])
        self.assertEqual(error.exception.code, 'rename_not_accepted')
        self.assertEqual(fixtures.filesystem(self.root), before)

    def test_process_exit_after_first_write_then_real_reopen_recovers(self):
        self.setup_notes()
        plan, _ = self.prepare()
        self.accept()
        credential = self.root / 'process.token'
        credential.write_bytes(self.token.encode())
        program = r'''
import os, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from shared_workspace.client import Client
from shared_workspace.engine import Coordinator
from shared_workspace import graph_rename
engine = Coordinator(Path(sys.argv[4]))
token = Path(sys.argv[5]).read_bytes().decode()
client = Client(Path(sys.argv[2]), Path(sys.argv[3]), lambda op, payload: engine.request(token, op, payload))
original = graph_rename.RenameClient._write_project
def interrupted(self, name, text):
    original(self, name, text)
    os._exit(73)
graph_rename.RenameClient._write_project = interrupted
graph_rename.apply(client, sys.argv[6])
'''
        result = subprocess.run([sys.executable, '-c', program, str(TESTS.parent), str(self.project),
            str(self.private), str(self.root / 'authority.sqlite'), str(credential), plan['plan_id']],
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 73, result.stderr.decode())
        self.assertEqual(result.stdout, b'')
        self.assertTrue((self.private / 'journal.json').exists())
        receipt = rename.apply(self.Client(self.project, self.private, self.transport), plan['plan_id'])
        self.assertEqual(receipt['readiness'], 'ready')
        self.assertFalse((self.project / 'Notes/Old.md').exists())
        self.assertEqual((self.project / 'Archive/New name.md').read_bytes(), plan['changes']['Archive/New name.md'].encode())

    @unittest.skipUnless(os.name == 'nt', 'Actual NTFS junction check runs on Windows')
    def test_windows_junction_directory_and_root_are_refused(self):
        self.setup_notes()
        link = self.project / 'outside'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(self.vault)], capture_output=True)
        self.assertEqual(result.returncode, 0)
        try:
            with self.assertRaises(ProductError):
                rename.plan(self.client, 'Notes/Old.md', 'Archive/New.md')
            with self.assertRaises(ProductError):
                rename.plan(self.Client(link, self.private, self.transport), 'Notes/Old.md', 'Archive/New.md')
        finally:
            os.rmdir(link)


class RenameCLITests(unittest.TestCase):
    setUpClass = classmethod(cli_fixtures.TeamCLITests.setUpClass.__func__)
    setUp = cli_fixtures.TeamCLITests.setUp
    cli = cli_fixtures.TeamCLITests.cli
    initialize = cli_fixtures.TeamCLITests.initialize
    coord = cli_fixtures.TeamCLITests.coord

    def test_genuinely_different_root_with_same_project_metadata_remains_rejected(self):
        self.initialize()
        other = self.root / 'Different selected root'
        other.mkdir()
        for name in ('Home.md', '.shared-memory.json'):
            (other / name).write_bytes((self.project / name).read_bytes())
        before = fixtures.filesystem(self.root)
        self.cli('graph-rename-plan', other, self.state, '--source', 'Home.md', '--destination', 'Moved.md', expected=4)
        self.assertEqual(fixtures.filesystem(self.root), before)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows canonical case and 8.3 spelling')
    def test_windows_equivalent_lexical_roots_bind_same_saved_client(self):
        import ctypes
        from ctypes import wintypes
        self.initialize()
        saved = json.loads((self.state / 'client/client.json').read_bytes())['project_root']
        differently_cased = str(self.project).swapcase()
        self.assertNotEqual(differently_cased, saved)
        self.assertEqual(str(Path(differently_cased).resolve()), saved)
        variants = [differently_cased]
        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
        get_short.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = get_short(str(self.project), buffer, len(buffer))
        self.assertGreater(length, 0)
        self.assertLess(length, len(buffer))
        if buffer.value != saved:
            self.assertEqual(str(Path(buffer.value).resolve()), saved)
            variants.append(buffer.value)
        initial = self.cli('graph-rename-plan', self.project, self.state, '--source', 'Home.md', '--destination', 'Moved.md')
        for variant in variants:
            with self.subTest(spelling=variant):
                before = fixtures.filesystem(self.root)
                result = self.cli('graph-rename-plan', variant, self.state, '--source', 'Home.md', '--destination', 'Moved.md')
                self.assertEqual(result, initial)
                self.assertEqual(fixtures.filesystem(self.root), before)

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows junction must be rejected before normalization')
    def test_windows_package_junction_root_not_normalized_into_authorized_root(self):
        self.initialize()
        junction = self.root / 'Junction alias'
        made = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(self.project)], capture_output=True)
        self.assertEqual(made.returncode, 0)
        try:
            before = fixtures.filesystem(self.project)
            state_before = fixtures.filesystem(self.state)
            for supplied in (junction, junction / '..' / self.project.relative_to(self.root)):
                self.cli('graph-rename-plan', supplied, self.state, '--source', 'Home.md', '--destination', 'Moved.md', expected=3)
            self.assertEqual(fixtures.filesystem(self.project), before)
            self.assertEqual(fixtures.filesystem(self.state), state_before)
        finally:
            os.rmdir(junction)

    def test_packaged_plan_draft_submit_accept_apply_exact_bytes(self):
        (self.project / 'Old.md').write_bytes('# Résumé\r\nNo final newline'.encode())
        (self.project / 'Home.md').write_bytes(b'# Home\r\n[[Old|label]]\n')
        self.initialize()
        self.coord('claim', {'assignment_id': 'rename', 'targets': ['.'], 'criteria': ['Verify renamed graph'],
            'dependencies': [], 'resource_limits': {}, 'integration_owner': 'alex'})
        before = fixtures.filesystem(self.project)
        plan = self.cli('graph-rename-plan', None, None,
            '--source', 'Old.md', '--destination', 'New.md')
        result = self.cli('graph-rename-draft', None, None,
            '--plan-id', plan['plan_id'], '--proposal-id', 'rename-note', '--assignment-id', 'rename',
            '--evidence', 'Reviewed packaged fixture')
        self.assertFalse(result['project_files_changed'])
        self.assertEqual(fixtures.filesystem(self.project), before)
        self.cli('submit', None, None, '--proposal-id', 'rename-note')
        self.coord('accept', {'proposal_id': 'rename-note', 'validation': 'Reviewed links', 'reason': 'Accept fixture'})
        receipt = self.cli('graph-rename-apply', None, None, '--plan-id', plan['plan_id'])
        self.assertEqual(receipt['readiness'], 'ready')
        self.assertEqual((self.project / 'New.md').read_bytes(), '# Résumé\r\nNo final newline'.encode())
        self.assertEqual((self.project / 'Home.md').read_bytes(), b'# Home\r\n[[New.md|label]]\n')
        self.assertFalse((self.project / 'Old.md').exists())

    def test_explicit_empty_private_inputs_are_usage_errors_without_writes(self):
        self.initialize()
        for field in ('--coordination-file', '--session-token-file'):
            before = fixtures.filesystem(self.root)
            self.cli('graph-rename-draft', None, None, '--plan-id', 'rename-' + '0' * 64,
                '--proposal-id', 'draft', '--assignment-id', 'work', '--evidence', 'Review', field, '  ', expected=2)
            self.assertEqual(fixtures.filesystem(self.root), before)

    def test_explicit_null_and_malformed_context_never_save_unfenced_draft(self):
        self.initialize()
        plan = self.cli('graph-rename-plan', None, None, '--source', 'Home.md', '--destination', 'Moved.md')
        context = self.root / 'malformed-context.json'
        for value in (None, [], 'context', 1, {}, {'policy_revision': 1}):
            with self.subTest(value=value):
                context.write_bytes(json.dumps(value).encode())
                before = fixtures.filesystem(self.root)
                self.cli('graph-rename-draft', None, None, '--plan-id', plan['plan_id'],
                    '--proposal-id', 'draft', '--assignment-id', 'work', '--evidence', 'Review',
                    '--coordination-file', context, expected=3)
                self.assertEqual(fixtures.filesystem(self.root), before)
