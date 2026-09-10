"""Packaged direct-folder onboarding and historical-authority migration."""
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]


class FolderCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='shared-memory-folder-cli-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.package = Path(cls.temp.name).resolve() / 'product.pyz'
        result = subprocess.run([sys.executable, str(REPO / 'scripts/build_product.py'), '--output', str(cls.package)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def setUp(self):
        self.temp_root = tempfile.TemporaryDirectory(prefix='shared-memory-folder-case-')
        self.addCleanup(self.temp_root.cleanup)
        self.base = Path(self.temp_root.name).resolve()
        self.project = self.base / 'Private vault/Shared project'
        self.project.mkdir(parents=True)
        self.state = self.base / 'private-state'
        (self.project / 'Note.md').write_bytes(b'# Note\r\nInitial\r\n')
        (self.project.parent / 'Private.md').write_text('Parent stays private')
        (self.project / 'image.bin').write_bytes(b'\x00\xff')

    def cli(self, command, *args, expected=0):
        result = subprocess.run([sys.executable, str(self.package), command, *map(str, args)], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        response = json.loads(result.stdout)
        self.assertEqual(response['ok'], expected == 0)
        return response['data'] if expected == 0 else response

    def setup(self, *args, expected=0, project=None, state=None):
        return self.cli('setup', project or self.project, '--state-dir', state or self.state, *args, expected=expected)

    def test_default_is_direct_editing_and_repeated_setup_preserves_identity(self):
        original = (self.project / 'Note.md').read_bytes()
        first = self.setup('--actor', 'editor-a', '--person', 'Editor', '--agent', 'Normal agent')
        self.assertFalse(first['coordinator_required'])
        self.assertFalse(first['approval_queue'])
        self.assertEqual(json.loads((self.project / '.shared-memory.json').read_text())['format_version'], 3)
        self.assertEqual((self.project / 'Note.md').read_bytes(), original)
        second = self.setup('--actor', 'editor-a')
        self.assertEqual(first['project_id'], second['project_id'])
        (self.project / 'Note.md').write_text('Direct edit, no claim or proposal.\n')
        self.cli('sync', self.project, '--state-dir', self.state)
        self.assertEqual((self.project / 'Note.md').read_text(), 'Direct edit, no claim or proposal.\n')
        self.assertFalse(list(self.project.rglob('*.sqlite3')))
        self.assertEqual((self.project.parent / 'Private.md').read_text(), 'Parent stays private')
        self.assertEqual((self.project / 'image.bin').read_bytes(), b'\x00\xff')
        self.setup('--provider', 'onedrive', expected=3)

    def test_another_device_joins_without_member_token_or_coordinator(self):
        first = self.setup('--actor', 'a', '--provider', 'nextcloud')
        remote = self.base / 'Another vault/Selected folder'
        shutil.copytree(self.project, remote)
        joined = self.setup('--actor', 'b', '--expected-project-id', first['project_id'], project=remote, state=self.base / 'state-b')
        self.assertEqual(joined['route'], 'join_folder')
        (remote / 'Note.md').write_text('Offline second device edit\n')
        self.cli('sync', remote, '--state-dir', self.base / 'state-b')
        self.assertEqual((remote / 'Note.md').read_text(), 'Offline second device edit\n')

    def test_readonly_join_cannot_silently_become_an_editor(self):
        self.setup('--actor', 'a')
        remote = self.base / 'Reader copy'; shutil.copytree(self.project, remote)
        private = self.base / 'reader-state'
        self.setup('--actor', 'reader', '--read-only', project=remote, state=private)
        self.setup('--actor', 'reader', project=remote, state=private)
        self.cli('sync', remote, '--state-dir', private, expected=4)
        self.setup('--read-only', expected=3)

    def test_setup_refuses_implicit_coordinator_replacement(self):
        self.setup('--workflow', 'coordinator', '--actor', 'legacy')
        old = (self.project / '.shared-memory.json').read_bytes()
        self.setup(expected=4)
        self.assertEqual((self.project / '.shared-memory.json').read_bytes(), old)

    def legacy(self):
        self.setup('--workflow', 'coordinator', '--actor', 'legacy', '--person', 'Legacy editor')
        return self.state / 'coordinator.sqlite3'

    def test_migration_preserves_newer_notes_uuid_and_complete_private_history(self):
        db = self.legacy()
        old = hashlib.sha256(db.read_bytes()).hexdigest()
        meta = json.loads((self.project / '.shared-memory.json').read_text())
        newer = b'# Note\r\nNewer direct edit\r\n'
        (self.project / 'Note.md').write_bytes(newer)
        backup = self.base / 'migration-backup'
        plan = self.cli('migrate-folder', self.project, '--state-dir', self.state, '--backup-dir', backup)
        self.assertFalse(plan['applied']); self.assertFalse(backup.exists())
        report = self.cli('migrate-folder', self.project, '--state-dir', self.state, '--backup-dir', backup, '--apply')
        self.assertTrue(report['history_preserved'])
        self.assertEqual(report['project_id'], meta['project_id'])
        self.assertEqual((self.project / 'Note.md').read_bytes(), newer)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), old)
        with sqlite3.connect(backup / 'coordinator.sqlite3') as connection:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertFalse(list(self.project.rglob('*.sqlite3')))
        self.assertTrue((self.state / 'member.token').exists())
        self.setup('--actor', 'legacy')
        again = self.cli('migrate-folder', self.project, '--state-dir', self.state, '--backup-dir', backup, '--apply')
        self.assertTrue(again['resumed'])

    def test_migration_does_not_infer_missing_provider_file_as_delete(self):
        self.legacy()
        # Disposable fixture deletion simulates a delayed provider file.
        (self.project / 'Note.md').unlink()
        result = self.cli('migrate-folder', self.project, '--state-dir', self.state,
                          '--backup-dir', self.base / 'backup', '--apply', expected=4)
        self.assertEqual(result['code'], 'migration_missing_files')
        self.assertFalse((self.base / 'backup').exists())
        self.assertEqual(json.loads((self.project / '.shared-memory.json').read_text())['format_version'], 1)

    def test_migration_retry_rejects_altered_verified_recovery_archive(self):
        db = self.legacy()
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        backup = self.base / 'backup'
        self.cli('migrate-folder', self.project, '--state-dir', self.state, '--backup-dir', backup, '--apply')
        manifest = (self.project / '.shared-memory.json').read_bytes()
        (backup / 'coordinator.sqlite3').write_bytes(b'Disposable tampered backup fixture')
        result = self.cli('migrate-folder', self.project, '--state-dir', self.state,
                          '--backup-dir', backup, '--apply', expected=4)
        self.assertEqual(result['code'], 'migration_backup_invalid')
        self.assertEqual((self.project / '.shared-memory.json').read_bytes(), manifest)
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
