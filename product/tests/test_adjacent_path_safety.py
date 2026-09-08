"""Private-path boundaries for delivery and maintenance, without provider IO."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace import coordinator_migration as migration
from shared_workspace import delivery, maintenance
from shared_workspace.engine import Coordinator
from shared_workspace.errors import ProductError
from test_delivery import FixtureBackend


class AdjacentPathSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-adjacent-paths-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.outside = self.root / 'private-outside'
        self.outside.mkdir()
        self.secret = self.outside / 'Private.md'
        self.secret.write_bytes(b'PRIVATE OUTSIDE NOTE\r\n')
        self.project = self.root / 'selected'
        self.project.mkdir()
        (self.project / 'Home.md').write_bytes(b'# Selected\n')

    def link(self, path, destination):
        if os.name == 'nt':
            result = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(path), str(destination)],
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.addCleanup(lambda: os.rmdir(path) if os.path.lexists(path) else None)
        else:
            path.symlink_to(destination, target_is_directory=True)
            self.addCleanup(lambda: path.unlink() if path.is_symlink() else None)
        return path

    def failure(self, operation, code):
        with self.assertRaises(ProductError) as caught:
            operation()
        self.assertEqual(caught.exception.exit_code, 3)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.secret.read_bytes(), b'PRIVATE OUTSIDE NOTE\r\n')

    def authority(self):
        token, project_id = secrets.token_urlsafe(32), str(uuid.uuid4())
        engine = Coordinator(self.root / 'authority.sqlite3')
        engine.initialize(project_id, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'},
                          token, {'Home.md': '# Accepted\r\n'})
        return engine, token, project_id

    def test_normal_delivery_fetch_and_ordinary_parent_spelling_use_same_guarded_path(self):
        engine, token, _ = self.authority()
        snapshot = engine.request(token, 'snapshot', {})
        backend = FixtureBackend()
        route = delivery.Delivery(backend)
        route.publish(snapshot)
        nested = self.root / 'ordinary'; nested.mkdir()
        downloaded = route.fetch(snapshot, nested / '..' / 'fresh-stage')
        self.assertEqual(downloaded.staging, self.root / 'fresh-stage')
        self.assertEqual((downloaded.staging / 'files/Home.md').read_bytes(), b'# Accepted\r\n')
        self.assertEqual(downloaded.receipt['provider_receipt'], 'not_run')

    def test_normal_migration_prunes_hidden_and_protected_directories_before_enumeration(self):
        excluded = [self.project / '.obsidian', self.project / 'client-state', self.project / 'setup-recovery']
        for folder in excluded:
            folder.mkdir()
            (folder / 'private.md').write_bytes(b'PRIVATE SUBTREE CONTENT')
        normal = self.project / 'Notes'; normal.mkdir()
        (normal / 'Other.md').write_bytes(b'# Other\n')
        (self.project / 'Home.md').write_bytes(b'[[Notes/Other]] [[Missing]]\n')
        original = os.scandir
        visited = []

        def scandir(path):
            visited.append(Path(path))
            self.assertFalse(any(Path(path) == folder or Path(path).is_relative_to(folder) for folder in excluded))
            return original(path)

        with patch.object(maintenance.os, 'scandir', side_effect=scandir):
            result = maintenance.migration_plan(normal / '..', self.root / 'future')
        self.assertEqual(set(result['files']), {'Home.md', 'Notes/Other.md'})
        self.assertEqual(result['external_or_unresolved_wikilinks'], [{'path': 'Home.md', 'target': 'Missing'}])
        self.assertEqual({item['path'] for item in result['warnings']}, {'.obsidian', 'client-state', 'setup-recovery'})
        self.assertNotIn('PRIVATE SUBTREE CONTENT', json.dumps(result))
        self.assertFalse((self.root / 'future').exists())
        self.assertIn(normal, visited)

    def test_normal_verified_backup_preserves_authority_and_checkpoint(self):
        engine, token, project_id = self.authority()
        before = engine.db_path.read_bytes()
        backup = self.root / 'backup.sqlite3'
        result = maintenance.backup_coordinator(engine.db_path, backup, project_id)
        nested = self.root / 'ordinary'; nested.mkdir()
        self.assertEqual(migration._verify_backup(nested / '..' / backup.name, project_id,
                         result['checkpoint'], result['backup_sha256']), hashlib.sha256(backup.read_bytes()).hexdigest())
        self.assertEqual(engine.db_path.read_bytes(), before)
        self.assertEqual(engine.request(token, 'snapshot', {})['revision'], 0)

    def test_delivery_link_parent_and_dotdot_refused_before_transport_or_stage_creation(self):
        alias = self.link(self.root / 'alias', self.outside)
        expected = {'project_id': str(uuid.uuid4()), 'revision': 0, 'files_hash': '0' * 64}
        for path in (alias / 'stage', alias / '..' / 'stage'):
            backend = FixtureBackend()
            self.failure(lambda: delivery.Delivery(backend).fetch(expected, path), 'delivery_path')
            self.assertEqual(backend.starts, 0)
            self.assertFalse((self.outside / 'stage').exists())
            self.assertFalse((self.root / 'stage').exists())

    def test_backup_link_parent_and_dotdot_refused_before_any_file_hash(self):
        alias = self.link(self.root / 'alias', self.outside)
        for path in (alias / 'Private.md', alias / '..' / 'backup.sqlite3'):
            with patch.object(migration, '_file_hash', side_effect=AssertionError('Outside hash attempted')) as hashed:
                self.failure(lambda: migration._verify_backup(path, str(uuid.uuid4()), '0' * 64), 'migration_invalid')
            hashed.assert_not_called()

    def test_install_package_link_parent_and_dotdot_refuse_before_hash_or_inspection(self):
        alias = self.link(self.root / 'alias', self.outside)
        for candidate in (alias / 'candidate.pyz', alias / '..' / 'candidate.pyz'):
            with patch.object(maintenance, 'sha', side_effect=AssertionError('Outside package hash attempted')):
                self.failure(lambda: maintenance.install(candidate, '0' * 64, self.root / 'tools'), 'package_mismatch')
            self.assertFalse((self.root / 'tools').exists())

    def test_rollback_versions_link_refuses_before_hash_or_activation(self):
        tools = self.root / 'tools'; tools.mkdir()
        self.link(tools / 'versions', self.outside)
        args = argparse.Namespace(command='rollback-package', tools_dir=tools, sha256='0' * 64)
        with patch.object(maintenance, 'sha', side_effect=AssertionError('Outside rollback hash attempted')):
            self.failure(lambda: maintenance.dispatch(None, args), 'rollback_invalid')
        self.assertFalse((tools / 'current.json').exists())

    def test_migration_link_source_and_destination_dotdot_refuse_before_inventory(self):
        alias = self.link(self.root / 'alias', self.outside)
        with patch.object(maintenance.os, 'scandir', side_effect=AssertionError('Outside inventory attempted')):
            for source in (alias, alias / '..' / 'selected'):
                self.failure(lambda: maintenance.migration_plan(source, self.root / 'future'), 'project_path_unsafe')
            for destination in (alias / 'future', alias / '..' / 'future'):
                self.failure(lambda: maintenance.migration_plan(self.project, destination), 'migration_target_invalid')
        self.assertFalse((self.outside / 'future').exists())

    @unittest.skipUnless(os.name == 'nt', 'Windows NTFS junction fixture')
    def test_windows_delivery_backend_root_junction_rejected_before_config_creation(self):
        alias = self.link(self.root / 'alias', self.outside)
        with patch.object(delivery.tempfile, 'TemporaryDirectory', side_effect=AssertionError('Private config created')):
            self.failure(lambda: delivery.LocalRcloneBackend(sys.executable, alias), 'delivery_path')

    @unittest.skipUnless(os.name == 'nt', 'Windows NTFS junction fixture')
    def test_windows_delivery_backend_child_junction_refused_before_enumeration_or_rclone(self):
        prefix = self.project / 'revision'; prefix.mkdir()
        alias = self.link(prefix / 'junction', self.outside)
        backend = delivery.LocalRcloneBackend(sys.executable, self.project)
        self.addCleanup(backend.close)
        original = os.scandir

        def scandir(path):
            self.assertNotEqual(Path(path), alias, 'Enumerated junction target')
            self.assertNotEqual(Path(path), self.outside, 'Enumerated private directory')
            return original(path)

        with patch.object(delivery.os, 'scandir', side_effect=scandir), patch.object(
                backend, '_run', side_effect=AssertionError('Rclone invoked on unsafe route')) as run:
            self.failure(lambda: backend.list('revision'), 'delivery_path')
        run.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows NTFS junction fixture')
    def test_windows_migration_child_junction_warns_without_outside_hash_read_or_enumeration(self):
        alias = self.link(self.project / 'junction', self.outside)
        original_scan, original_hash, original_read = os.scandir, maintenance.sha, Path.read_text

        def check_path(path):
            value = Path(path)
            self.assertFalse(value == alias or value.is_relative_to(alias)
                             or value == self.outside or value.is_relative_to(self.outside))

        def scandir(path):
            check_path(path)
            return original_scan(path)

        def hashed(path):
            check_path(path)
            return original_hash(path)

        def read(path, *args, **kwargs):
            check_path(path)
            return original_read(path, *args, **kwargs)

        with patch.object(maintenance.os, 'scandir', side_effect=scandir), patch.object(
                maintenance, 'sha', side_effect=hashed), patch.object(Path, 'read_text', new=read):
            result = maintenance.migration_plan(self.project, self.root / 'future')
        self.assertEqual(set(result['files']), {'Home.md'})
        self.assertIn({'path': 'junction', 'issue': 'symlink_requires_manual_review'}, result['warnings'])
        self.assertNotIn('PRIVATE OUTSIDE NOTE', json.dumps(result))
        self.assertNotIn('Private.md', json.dumps(result))
        self.assertEqual(self.secret.read_bytes(), b'PRIVATE OUTSIDE NOTE\r\n')


if __name__ == '__main__':
    unittest.main()
