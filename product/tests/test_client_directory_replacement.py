"""Real engine/client regressions for an empty directory becoming accepted text."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest import mock
import uuid

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace import client as module
from shared_workspace.client import Client
from shared_workspace.engine import Coordinator
from shared_workspace.errors import ProductError


class DirectoryReplacementTests(unittest.TestCase):
    def fixture(self, refresh_deletion=True, nested=False):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-directory-file-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / 'project'; self.project.mkdir()
        self.state = self.root / 'private-client'
        self.db = self.root / 'authority.sqlite'
        self.token = secrets.token_urlsafe(32)
        self.engine = Coordinator(self.db)
        self.project_id = str(uuid.uuid4())
        self.old_note = 'Previously accepted note: café\n'
        self.new_file = 'Accepted directory replacement: 世界\n'
        self.old_path = 'Folder/Level/Deep/Note.md' if nested else 'Folder/Note.md'
        self.engine.initialize(self.project_id, {'actor': 'owner', 'human': 'Synthetic owner',
            'agent': 'Independent test'}, self.token,
            {'Home.md': '# Fixture\n', self.old_path: self.old_note})
        self.client = Client(self.project, self.state, self.request)
        self.assertEqual(self.client.attach(self.project_id)['readiness'], 'ready')
        self.request('claim', {'assignment_id': 'work', 'targets': ['.'],
            'criteria': ['Verify accepted bytes and preserved local files'], 'dependencies': [],
            'resource_limits': {'max_proposals': 4}, 'integration_owner': 'owner'})
        self.accept('delete-note', {self.old_path: None})
        if refresh_deletion:
            self.assertEqual(self.client.refresh()['readiness'], 'ready')
        self.target = self.project / 'Folder'
        self.assertTrue(self.target.is_dir())
        if refresh_deletion and not nested:
            self.assertEqual(list(self.target.iterdir()), [])
        self.accept('replace-directory', {'Folder': self.new_file})

    def request(self, operation, payload):
        return self.engine.request(self.token, operation, payload)

    def accept(self, proposal, changes):
        self.request('propose', {'proposal_id': proposal, 'assignment_id': 'work',
            'base_revision': self.request('snapshot', {})['revision'], 'changes': changes,
            'claims': [], 'evidence': 'Synthetic exact-byte review'})
        result = self.request('accept', {'proposal_id': proposal,
            'validation': 'Verified synthetic content', 'reason': 'Accept bounded fixture change'})
        self.assertTrue(result['accepted'])

    def reopen(self):
        self.engine = Coordinator(self.db)
        self.client = Client(self.project, self.state, self.request)

    def assert_ready(self):
        result = self.client.refresh()
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(result['revision'], 2)
        self.assertEqual(result['files_hash'], self.request('snapshot', {})['files_hash'])
        self.assertEqual(self.target.read_bytes(), self.new_file.encode())
        self.assertFalse((self.state / 'journal.json').exists())
        backup = self.state / 'backups' / hashlib.sha256(self.old_note.encode()).hexdigest()
        self.assertEqual(backup.read_bytes(), self.old_note.encode())

    def interrupt(self, boundary):
        real_rmdir, real_link = os.rmdir, os.link
        def rmdir(path, *args, **kwargs):
            if Path(path) == self.target and boundary == 'before_rmdir':
                raise OSError(errno.EIO, 'Injected before directory removal')
            result = real_rmdir(path, *args, **kwargs)
            if Path(path) == self.target and boundary == 'after_rmdir':
                raise OSError(errno.EIO, 'Injected after directory removal')
            return result
        def link(source, destination, *args, **kwargs):
            if Path(destination) == self.target and boundary == 'before_link':
                raise OSError(errno.EIO, 'Injected before exclusive installation')
            result = real_link(source, destination, *args, **kwargs)
            if Path(destination) == self.target and boundary == 'after_link':
                raise OSError(errno.EIO, 'Injected after exclusive installation')
            return result
        with mock.patch.object(module.os, 'rmdir', rmdir), mock.patch.object(module.os, 'link', link):
            with self.assertRaises(ProductError) as error:
                self.client.refresh()
        self.assertEqual(error.exception.exit_code, 5)
        self.assertTrue((self.state / 'journal.json').is_file())
        self.assertEqual(self.client.receipt()['readiness'], 'partial')

    def test_deleted_child_empty_directory_becomes_accepted_file(self):
        self.fixture()
        unrelated = self.project / 'UnrelatedEmpty'; unrelated.mkdir()
        self.assert_ready()
        self.assertTrue(unrelated.is_dir(), 'No unrelated empty-directory cleanup')
        self.reopen(); self.assert_ready()

    def test_nonempty_untracked_descendants_block_replacement_and_survive_restart(self):
        for relative, content in [('private.bin', b'\x00\xffUNTRACKED'),
                                  ('.obsidian/settings.json', b'{"preserve":true}')]:
            with self.subTest(descendant=relative):
                self.fixture()
                descendant = self.target / relative
                descendant.parent.mkdir(parents=True, exist_ok=True)
                descendant.write_bytes(content)
                for _ in range(2):
                    with self.assertRaises(ProductError) as error:
                        self.client.refresh()
                    self.assertEqual(error.exception.code, 'unsafe_path')
                    self.assertEqual(descendant.read_bytes(), content)
                    self.assertTrue((self.state / 'journal.json').is_file())
                    self.assertEqual(self.client.receipt()['readiness'], 'partial')
                    self.reopen()

    def test_directory_conversion_recovers_four_interruption_boundaries(self):
        for boundary in ('before_rmdir', 'after_rmdir', 'before_link', 'after_link'):
            with self.subTest(boundary=boundary):
                self.fixture(); self.interrupt(boundary)
                self.reopen(); self.assert_ready()

    def test_post_interruption_file_edits_are_preserved_before_retry(self):
        for boundary in ('after_rmdir', 'after_link'):
            with self.subTest(boundary=boundary):
                self.fixture(); self.interrupt(boundary)
                local = 'New local edit after interruption: ' + boundary + '\n'
                self.target.write_bytes(local.encode())
                self.reopen(); self.assert_ready()
                drafts = [json.loads(path.read_text()) for path in (self.state / 'drafts').glob('*.json')]
                self.assertTrue(any(item.get('changes', {}).get('Folder') == local for item in drafts))
                backup = self.state / 'backups' / hashlib.sha256(local.encode()).hexdigest()
                self.assertEqual(backup.read_bytes(), local.encode())

    def test_post_interruption_new_descendant_is_not_removed(self):
        self.fixture(); self.interrupt('after_rmdir')
        self.target.mkdir()
        local = self.target / 'new-local.md'; local.write_bytes(b'NEW POST-CRASH CONTENT\n')
        self.reopen()
        with self.assertRaises(ProductError):
            self.client.refresh()
        self.assertEqual(local.read_bytes(), b'NEW POST-CRASH CONTENT\n')
        self.assertTrue((self.state / 'journal.json').is_file())

    def test_concurrent_descendant_at_rmdir_is_preserved(self):
        self.fixture()
        real_rmdir = os.rmdir
        descendant = self.target / 'concurrent.bin'
        def racing_rmdir(path, *args, **kwargs):
            if Path(path) == self.target:
                descendant.write_bytes(b'CONCURRENT PRIVATE BYTES')
            return real_rmdir(path, *args, **kwargs)
        with mock.patch.object(module.os, 'rmdir', racing_rmdir):
            with self.assertRaises(ProductError):
                self.client.refresh()
        self.assertEqual(descendant.read_bytes(), b'CONCURRENT PRIVATE BYTES')
        self.assertTrue((self.state / 'journal.json').is_file())

    def test_concurrent_file_at_installation_is_never_overwritten(self):
        self.fixture()
        real_link = os.link
        def racing_link(source, destination, *args, **kwargs):
            if Path(destination) == self.target:
                self.target.write_bytes(b'CONCURRENT FILE BYTES')
            return real_link(source, destination, *args, **kwargs)
        with mock.patch.object(module.os, 'link', racing_link):
            with self.assertRaises(ProductError):
                self.client.refresh()
        self.assertEqual(self.target.read_bytes(), b'CONCURRENT FILE BYTES')
        self.reopen(); self.assert_ready()
        backup = self.state / 'backups' / hashlib.sha256(b'CONCURRENT FILE BYTES').hexdigest()
        self.assertEqual(backup.read_bytes(), b'CONCURRENT FILE BYTES')

    def test_directory_symlink_is_rejected_without_touching_outside(self):
        self.fixture()
        outside = self.root / 'outside'; outside.mkdir()
        sentinel = outside / 'private.bin'; sentinel.write_bytes(b'OUTSIDE PRIVATE')
        self.target.rmdir()
        try:
            self.target.symlink_to(outside, target_is_directory=True)
        except OSError as error:
            if error.errno in {errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP} or getattr(error, 'winerror', None) == 1314:
                self.skipTest('Directory symlink creation unavailable on this runner')
            raise
        with self.assertRaises(ProductError) as error:
            self.client.refresh()
        self.assertEqual(error.exception.code, 'unsafe_path')
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b'OUTSIDE PRIVATE')

    def test_symlink_created_at_installation_is_not_followed(self):
        self.fixture()
        outside = self.root / 'outside'; outside.mkdir()
        sentinel = outside / 'private.bin'; sentinel.write_bytes(b'OUTSIDE PRIVATE')
        real_link = os.link
        def racing_link(source, destination, *args, **kwargs):
            if Path(destination) == self.target:
                try:
                    self.target.symlink_to(outside, target_is_directory=True)
                except OSError as error:
                    if error.errno in {errno.EPERM, errno.EACCES, errno.ENOSYS, errno.ENOTSUP} or getattr(error, 'winerror', None) == 1314:
                        self.skipTest('Directory symlink creation unavailable on this runner')
                    raise
            return real_link(source, destination, *args, **kwargs)
        with mock.patch.object(module.os, 'link', racing_link):
            with self.assertRaises(ProductError):
                self.client.refresh()
        self.assertTrue(self.target.is_symlink())
        self.assertEqual(sentinel.read_bytes(), b'OUTSIDE PRIVATE')
        self.assertTrue((self.state / 'journal.json').is_file())

    def test_offline_recipient_skips_deletion_revision_and_replaces_parent(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                self.fixture(refresh_deletion=False, nested=nested)
                self.assertEqual(self.client.receipt()['revision'], 0)
                self.assert_ready()
                self.reopen(); self.assert_ready()

    def test_skipped_revision_keeps_untracked_private_and_empty_sibling_paths(self):
        for relative, content in [('private.bin', b'\xffUNTRACKED'),
                                  ('Level/.obsidian/settings.json', b'{"private":true}'),
                                  ('UntrackedEmpty', None)]:
            with self.subTest(path=relative):
                self.fixture(refresh_deletion=False, nested=True)
                local = self.target / relative
                if content is None:
                    local.mkdir()
                else:
                    local.parent.mkdir(parents=True, exist_ok=True)
                    local.write_bytes(content)
                for _ in range(2):
                    with self.assertRaises(ProductError):
                        self.client.refresh()
                    self.assertTrue(local.is_dir() if content is None else local.read_bytes() == content)
                    self.assertTrue((self.state / 'journal.json').is_file())
                    self.assertEqual(self.client.receipt()['readiness'], 'partial')
                    self.reopen()
                backup = self.state / 'backups' / hashlib.sha256(self.old_note.encode()).hexdigest()
                self.assertEqual(backup.read_bytes(), self.old_note.encode())

    def test_skipped_revision_preserves_modified_tracked_child_and_blocks_conversion(self):
        self.fixture(refresh_deletion=False, nested=True)
        child = self.project / self.old_path
        local = 'User modified the accepted child while offline\n'
        child.write_bytes(local.encode())
        for _ in range(2):
            with self.assertRaises(ProductError):
                self.client.refresh()
            self.assertEqual(child.read_bytes(), local.encode())
            self.assertTrue((self.state / 'journal.json').is_file())
            self.assertEqual(self.client.receipt()['readiness'], 'partial')
            self.reopen()
        drafts = [json.loads(path.read_text()) for path in (self.state / 'drafts').glob('*.json')]
        self.assertTrue(any(item.get('changes', {}).get(self.old_path) == local for item in drafts))
        backup = self.state / 'backups' / hashlib.sha256(local.encode()).hexdigest()
        self.assertEqual(backup.read_bytes(), local.encode())

    def test_skipped_revision_recovers_child_delete_and_ancestor_prune_interruptions(self):
        for boundary in ('child_delete', 'ancestor_prune', 'after_rmdir', 'after_link'):
            with self.subTest(boundary=boundary):
                self.fixture(refresh_deletion=False, nested=True)
                if boundary in ('after_rmdir', 'after_link'):
                    self.interrupt(boundary)
                else:
                    method = 'unlink' if boundary == 'child_delete' else 'rmdir'
                    real = getattr(os, method)
                    target = self.project / self.old_path if boundary == 'child_delete' else self.target / 'Level' / 'Deep'
                    def failing(path, *args, **kwargs):
                        result = real(path, *args, **kwargs)
                        if Path(path) == target:
                            raise OSError(errno.EIO, 'Injected after tracked deletion/pruning')
                        return result
                    with mock.patch.object(module.os, method, failing):
                        with self.assertRaises(ProductError) as error:
                            self.client.refresh()
                    self.assertEqual(error.exception.exit_code, 5)
                    self.assertTrue((self.state / 'journal.json').is_file())
                plan = json.loads((self.state / 'journal.json').read_text())
                self.assertEqual(plan['paths'], sorted(plan['paths']), 'Stored journal format must remain canonical')
                self.reopen(); self.assert_ready()

    def test_new_descendant_after_prune_interruption_survives_restart(self):
        self.fixture(refresh_deletion=False, nested=True)
        real_rmdir = os.rmdir
        old_parent = self.target / 'Level' / 'Deep'
        def failing(path, *args, **kwargs):
            result = real_rmdir(path, *args, **kwargs)
            if Path(path) == old_parent:
                raise OSError(errno.EIO, 'Injected after ancestor pruning')
            return result
        with mock.patch.object(module.os, 'rmdir', failing):
            with self.assertRaises(ProductError):
                self.client.refresh()
        old_parent.mkdir()
        local = old_parent / 'new-private.bin'; local.write_bytes(b'POST-INTERRUPTION PRIVATE')
        self.reopen()
        with self.assertRaises(ProductError):
            self.client.refresh()
        self.assertEqual(local.read_bytes(), b'POST-INTERRUPTION PRIVATE')
        self.assertTrue((self.state / 'journal.json').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
