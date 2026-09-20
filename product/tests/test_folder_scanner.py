"""Archive directory links are excluded without weakening managed-path boundaries."""
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_folder as fixtures
from shared_workspace import folder as module
from shared_workspace.errors import ProductError


class ScannerTests(unittest.TestCase):
    setUp = fixtures.FolderTests.setUp
    create = fixtures.FolderTests.create
    edit = fixtures.FolderTests.edit
    def test_archived_directory_links_excluded_external_target_untouched(self):
        one = self.create()
        external = self.base / 'external'; external.mkdir()
        (external / 'Secret.md').write_text('EXTERNAL PRIVATE CONTENT')
        archive = one.root / 'Raw' / 'archive'; archive.mkdir(parents=True)
        (archive / 'outside').symlink_to(external, target_is_directory=True)
        (archive / 'inside').symlink_to(one.root, target_is_directory=True)
        before = fixtures.inventory(external)
        self.edit(one, 'ordinary updated note')
        result = one.sync()
        self.assertEqual(result['readiness'], 'ready')
        self.assertIn('Raw/archive/outside', result['excluded'])
        self.assertIn('Raw/archive/inside', result['excluded'])
        self.assertEqual(fixtures.inventory(external), before)
        self.assertFalse(any(b'EXTERNAL PRIVATE CONTENT' in p.read_bytes()
                             for p in one.shared.rglob('*') if p.is_file()))
        self.assertEqual(one.history('Note.md')['events'][-1]['changes']['Note.md'], 'ordinary updated note')

    def test_initial_scan_excludes_archive_link(self):
        root = self.base / 'new'; root.mkdir()
        external = self.base / 'external'; external.mkdir()
        (external / 'Secret.md').write_text('outside')
        (root / 'archive').symlink_to(external, target_is_directory=True)
        (root / 'Note.md').write_text('inside')
        one = module.Folder.initialize(root, self.base / 'private', 'a', 'A', 'Agent')
        self.assertEqual(set(one.status()['heads']), {'Note.md'})

    def test_link_replacing_tracked_subtree_rejected_without_mutation(self):
        one = self.create(files={'Notes/Tracked.md': 'tracked'})
        original = one.root / 'Notes'
        original.rename(self.base / 'saved-notes')
        external = self.base / 'external'; external.mkdir()
        (external / 'Tracked.md').write_text('external replacement')
        original.symlink_to(external, target_is_directory=True)
        before = fixtures.inventory(external); history = fixtures.inventory(one.shared)
        with self.assertRaises(ProductError) as caught:
            one.sync()
        self.assertEqual(caught.exception.code, 'folder_unsafe_path')
        self.assertEqual(fixtures.inventory(external), before)
        self.assertEqual(fixtures.inventory(one.shared), history)

    def test_root_and_state_aliases_and_history_links_still_rejected(self):
        one = self.create()
        alias = self.base / 'alias'; alias.symlink_to(one.root, target_is_directory=True)
        with self.assertRaises(ProductError) as caught:
            module.Folder(alias, one.state)
        self.assertEqual(caught.exception.code, 'folder_unsafe_path')
        state_alias = self.base / 'state-alias'; state_alias.symlink_to(one.state, target_is_directory=True)
        with self.assertRaises(ProductError): module.Folder(one.root, state_alias)
        history = one.shared; saved = self.base / 'saved-history'; history.rename(saved)
        history.symlink_to(saved, target_is_directory=True)
        with self.assertRaises(ProductError): module.Folder(one.root, one.state)

    def test_untracked_markdown_file_link_excluded(self):
        one = self.create()
        external = self.base / 'outside.md'; external.write_text('outside')
        (one.root / 'Linked.md').symlink_to(external)
        result = one.sync()
        self.assertEqual(result['readiness'], 'ready')
        self.assertIn('Linked.md', result['excluded'])
        self.assertNotIn('Linked.md', result['heads'])
        self.assertEqual(external.read_text(), 'outside')

    def test_link_replacing_tracked_markdown_file_still_rejected(self):
        one = self.create()
        external = self.base / 'outside.md'; external.write_text('outside')
        (one.root / 'Note.md').rename(self.base / 'saved-note.md')
        (one.root / 'Note.md').symlink_to(external)
        before = fixtures.inventory(one.shared)
        with self.assertRaises(ProductError) as caught: one.sync()
        self.assertEqual(caught.exception.code, 'folder_unsafe_path')
        self.assertEqual(fixtures.inventory(one.shared), before)
        self.assertEqual(external.read_text(), 'outside')

    def test_reparse_directory_detection_prunes_before_descent(self):
        one = self.create()
        directory = one.root / 'archive'; directory.mkdir()
        (directory / 'Hidden.md').write_text('must not scan')
        original = module.is_link_or_reparse
        with patch.object(module, 'is_link_or_reparse', side_effect=lambda p: p == directory or original(p)):
            files = one._scan(set())
        self.assertNotIn('archive/Hidden.md', files)
        self.assertIn('archive', one._excluded)

    @unittest.skipIf(os.name == "nt", "Fixture requires filenames Windows cannot create")
    def test_untracked_nonportable_files_skipped_with_bounded_warning(self):
        one = self.create()
        names = ['Bad <> name.md', 'CON.md', 'Trailing ./Note.md', 'Other?.md']
        for name in names:
            path = one.root / 'Raw' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('untracked original')
        result = one.sync()
        self.assertEqual(result['skipped_paths']['count'], 4)
        self.assertEqual(len(result['skipped_paths']['samples']), 3)
        self.assertTrue(any(w['code'] == 'untracked_nonportable_paths' for w in result['warnings']))
        self.assertEqual(set(result['heads']), {'Note.md'})
        for name in names:
            self.assertEqual((one.root / 'Raw' / name).read_text(), 'untracked original')
        with self.assertRaises(ProductError) as caught:
            one._scan({'Raw/Bad <> name.md'})
        self.assertEqual(caught.exception.code, 'engine_invalid')

    @unittest.skipIf(os.name == "nt", "Fixture uses a colon filename, which is an ADS on Windows")
    def test_unrecognized_path_failure_not_suppressed(self):
        one = self.create()
        (one.root / 'Unsafe:name.md').write_text('untouched')
        with self.assertRaises(ProductError) as caught:
            one.sync()
        self.assertEqual(caught.exception.code, 'engine_invalid')
