"""Delivery protocol plus actual rclone LOCAL-backend evidence. No Drive IO.

No credentials, accounts, network provider or cross-device claims are exercised.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace import delivery
from shared_workspace.delivery import (Delivery, Entry, GoogleDriveBinding,
                                       LocalRcloneBackend, RcloneBackend)
from shared_workspace.engine import Coordinator, canonical, files_hash
from shared_workspace.errors import ProductError


class FixtureBackend:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.fail_after = None
        self.starts = 0
        self.extra_entries = []

    def start(self):
        self.starts += 1

    def info(self):
        return {'route': 'local_fixture'}

    def list(self, prefix):
        found = {p[len(prefix) + 1:]: data for p, data in self.objects.items() if p.startswith(prefix + '/')}
        return [Entry(name, len(data)) for name, data in found.items()] + list(self.extra_entries)

    def read(self, path, maximum):
        if path not in self.objects:
            raise ProductError(5, 'fixture_missing', 'Synthetic object is unavailable.')
        value = self.objects[path]
        if len(value) > maximum:
            raise ProductError(5, 'fixture_limit', 'Synthetic object exceeds the read bound.')
        return value

    def put_new(self, path, data):
        if self.fail_after is not None and len(self.writes) >= self.fail_after:
            raise ProductError(5, 'fixture_offline', 'Injected offline transfer.')
        if path in self.objects and self.objects[path] != data:
            raise ProductError(3, 'fixture_immutable', 'Synthetic immutable collision.')
        self.objects[path] = data
        self.writes.append(path)


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-delivery-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.coordinator = Coordinator(self.root / 'authority.sqlite3')
        self.token = secrets.token_urlsafe(32)
        self.project_id = str(uuid.uuid4())
        self.files = {'Home.md': '# Synthetic accepted project\n', 'Notes/Grüße.md': 'Accepted Unicode\n',
                      'Old.md': 'To be deleted\n'}
        self.coordinator.initialize(self.project_id, {'actor': 'owner', 'human': 'Fixture owner', 'agent': 'test'},
                                    self.token, self.files)
        self.snapshot = self.coordinator.request(self.token, 'snapshot', {})
        self.backend = FixtureBackend()
        self.delivery = Delivery(self.backend)

    def manifest_key(self, snapshot=None):
        value = snapshot or self.snapshot
        return f"{value['project_id']}/revisions/{value['revision']}-{value['files_hash']}/{delivery.MANIFEST_NAME}"

    def accept(self, changes):
        self.coordinator.request(self.token, 'claim', {'assignment_id': 'work', 'targets': ['.'],
            'criteria': ['Synthetic exact bytes'], 'dependencies': [], 'resource_limits': {}, 'integration_owner': 'owner'})
        self.coordinator.request(self.token, 'propose', {'proposal_id': 'change', 'assignment_id': 'work',
            'base_revision': self.snapshot['revision'], 'changes': changes, 'claims': [], 'evidence': 'Fixture edit'})
        self.coordinator.request(self.token, 'accept', {'proposal_id': 'change', 'validation': 'Exact fixture review',
                                                       'reason': 'Test delivery'})
        return self.coordinator.request(self.token, 'snapshot', {})

    def assert_failure(self, operation, code=None):
        with self.assertRaises(ProductError) as caught:
            operation()
        if code:
            self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_actual_coordinator_snapshot_manifest_last_fetch_and_retry(self):
        receipt = self.delivery.publish(self.snapshot)
        self.assertEqual(receipt['provider_receipt'], 'not_run')
        self.assertEqual(self.backend.writes[-1], self.manifest_key())
        original = dict(self.backend.objects)
        writes = list(self.backend.writes)
        self.delivery.publish(self.snapshot)
        self.assertEqual(self.backend.objects, original)
        self.assertEqual(self.backend.writes, writes)
        result = self.delivery.fetch(self.snapshot, self.root / 'download')
        self.assertEqual(result.snapshot, self.snapshot)
        self.assertEqual(result.receipt['route'], 'local_fixture')
        self.assertEqual(result.receipt['provider_receipt'], 'not_run')
        for name, text in self.files.items():
            self.assertEqual((result.staging / 'files' / name).read_bytes(), text.encode())

    def test_actual_accepted_deletion_reports_base_but_never_deletes_history(self):
        self.delivery.publish(self.snapshot)
        before = dict(self.backend.objects)
        current = self.accept({'Old.md': None, 'Notes/Grüße.md': 'Accepted revision one\n'})
        self.delivery.publish(current, previous=self.snapshot)
        self.assertTrue(all(self.backend.objects[k] == v for k, v in before.items()))
        result = self.delivery.fetch(current, self.root / 'next', previous=self.snapshot)
        self.assertEqual(result.receipt['deletion_base']['revision'], 0)
        self.assertEqual(result.receipt['deleted_paths'], ['Old.md'])
        self.assertEqual(result.receipt['local_deletions'], 'not_applied')
        self.assertEqual(result.receipt['remote_history'], 'retained')
        self.assertFalse((result.staging / 'files' / 'Old.md').exists())

    def test_partial_publication_has_no_manifest_and_resumes_exact_bytes(self):
        self.backend.fail_after = 1
        self.assert_failure(lambda: self.delivery.publish(self.snapshot))
        self.assertNotIn(self.manifest_key(), self.backend.objects)
        self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'partial'))
        self.assertFalse((self.root / 'partial').exists())
        partial = dict(self.backend.objects)
        self.backend.fail_after = None
        self.delivery.publish(self.snapshot)
        self.assertTrue(all(self.backend.objects[k] == v for k, v in partial.items()))
        self.assertEqual(self.delivery.fetch(self.snapshot, self.root / 'complete').snapshot, self.snapshot)

    def test_published_missing_content_cannot_be_repaired_by_overwriting_history(self):
        self.delivery.publish(self.snapshot)
        self.backend.objects.pop(self.manifest_key().rsplit('/', 1)[0] + '/files/Old.md')
        before = dict(self.backend.objects)
        self.assert_failure(lambda: self.delivery.publish(self.snapshot), 'delivery_incomplete')
        self.assertEqual(self.backend.objects, before)

    def test_existing_different_bytes_extra_files_and_directories_fail_without_writes(self):
        self.delivery.publish(self.snapshot)
        prefix = self.manifest_key().rsplit('/', 1)[0]
        good = dict(self.backend.objects)
        corruptions = [lambda: self.backend.objects.__setitem__(prefix + '/files/Old.md', b'X' * len(self.files['Old.md'].encode())),
                       lambda: self.backend.objects.__setitem__(prefix + '/unexpected', b'PRIVATE'),
                       lambda: self.backend.extra_entries.append(Entry('untracked-dir', 0, True))]
        for corrupt in corruptions:
            with self.subTest(corruption=corruptions.index(corrupt)):
                self.backend.objects = dict(good)
                self.backend.extra_entries = []
                corrupt()
                before = dict(self.backend.objects)
                self.assert_failure(lambda: self.delivery.publish(self.snapshot))
                self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'bad'))
                self.assertEqual(before, self.backend.objects)
                self.assertFalse((self.root / 'bad').exists())

    def test_duplicate_and_unsafe_inventory_entries_fail(self):
        self.delivery.publish(self.snapshot)
        for name in ('files/Home.md', 'FILES/home.md', '../escape.md', '/absolute', 'files/.obsidian/private'):
            with self.subTest(name=name):
                self.backend.extra_entries = [Entry(name, len(self.files['Home.md'].encode()))]
                self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'bad'))
                self.assertFalse((self.root / 'bad').exists())

    def test_manifest_identity_duplicate_keys_and_unsafe_names_rejected(self):
        self.delivery.publish(self.snapshot)
        key = self.manifest_key()
        valid = self.backend.objects[key]
        value = json.loads(valid)
        invalid_identity = dict(value, project_id=str(uuid.uuid4()))
        unsafe = dict(value, files={'../escape': {'size': 0, 'sha256': hashlib.sha256(b'').hexdigest()}})
        oversized = dict(value, files={'Home.md': {'size': delivery.MAX_FILE_BYTES + 1, 'sha256': '0' * 64}})
        for raw in [canonical(invalid_identity).encode(), canonical(unsafe).encode(), canonical(oversized).encode(),
                    b'{"schema_version":1,' + valid[1:], b' ' + valid]:
            with self.subTest(raw=raw[:40]):
                self.backend.objects[key] = raw
                self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'bad'))
                self.assertFalse((self.root / 'bad').exists())

    def test_trusted_snapshot_hash_catches_internally_consistent_provider_tamper(self):
        self.delivery.publish(self.snapshot)
        key = self.manifest_key()
        value = json.loads(self.backend.objects[key])
        tampered = b'Provider changed content\n'
        self.backend.objects[key.rsplit('/', 1)[0] + '/files/Home.md'] = tampered
        value['files']['Home.md'] = {'size': len(tampered), 'sha256': hashlib.sha256(tampered).hexdigest()}
        self.backend.objects[key] = canonical(value).encode()
        self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'bad'), 'delivery_integrity')
        self.assertFalse((self.root / 'bad').exists())

    def test_stale_wrong_project_and_existing_staging_fail_before_backend(self):
        older = dict(self.snapshot, revision=2)
        foreign = dict(self.snapshot, project_id=str(uuid.uuid4()))
        for previous in (older, foreign):
            self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'bad', previous=previous), 'delivery_base')
        target = self.root / 'existing'
        target.mkdir()
        sentinel = target / 'Private.md'
        sentinel.write_bytes(b'PRIVATE')
        self.assert_failure(lambda: self.delivery.fetch(self.snapshot, target), 'delivery_staging')
        self.assertEqual(sentinel.read_bytes(), b'PRIVATE')
        self.assertEqual(self.backend.starts, 0)

    def test_symlink_staging_boundary_preserves_outside(self):
        outside = self.root / 'outside'
        outside.mkdir()
        sentinel = outside / 'Private.md'
        sentinel.write_bytes(b'PRIVATE')
        link = self.root / 'link'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symlink capability unavailable: {exc.errno}')
        self.assert_failure(lambda: self.delivery.fetch(self.snapshot, link / 'bad'), 'delivery_path')
        self.assertEqual(list(outside.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'PRIVATE')

    def test_injected_fixture_cannot_claim_drive_receipt(self):
        self.backend.info = lambda: {'route': 'google_drive_rclone'}
        self.assert_failure(lambda: self.delivery.publish(self.snapshot), 'delivery_backend')
        self.assertEqual(self.backend.objects, {})

    def test_manifest_and_inventory_limits_fail_without_staging(self):
        self.delivery.publish(self.snapshot)
        with patch.object(delivery, 'MANIFEST_LIMIT', 32):
            self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'oversized'))
        with patch.object(delivery, 'ENTRY_LIMIT', 1):
            self.assert_failure(lambda: self.delivery.fetch(self.snapshot, self.root / 'too-many'), 'delivery_limit')
        self.assertFalse((self.root / 'oversized').exists())
        self.assertFalse((self.root / 'too-many').exists())

    def test_interrupted_staging_retains_partial_bytes_without_success_and_retries_fresh(self):
        self.delivery.publish(self.snapshot)
        original_open = Path.open
        target = self.root / 'interrupted'
        def interrupted_open(path, *args, **kwargs):
            if path == target / delivery.MANIFEST_NAME:
                raise OSError('Injected private-path disk failure')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', interrupted_open):
            self.assert_failure(lambda: self.delivery.fetch(self.snapshot, target), 'delivery_staging')
        self.assertEqual((target / 'files' / 'Home.md').read_bytes(), self.files['Home.md'].encode())
        self.assertFalse((target / delivery.MANIFEST_NAME).exists())
        self.assert_failure(lambda: self.delivery.fetch(self.snapshot, target), 'delivery_staging')
        result = self.delivery.fetch(self.snapshot, self.root / 'retried')
        self.assertEqual(result.snapshot, self.snapshot)

    def test_real_rclone_local_backend_preserves_private_files_and_immutable_history(self):
        executable = shutil.which('rclone')
        if not executable:
            self.skipTest('Installed rclone unavailable; no installation is attempted.')
        store = self.root / 'local-provider-fixture'
        store.mkdir()
        private = store / 'Private.md'
        private.write_bytes(b'UNRELATED PRIVATE FIXTURE')
        backend = LocalRcloneBackend(executable, store)
        self.addCleanup(backend.close)
        instance = Delivery(backend)
        receipt = instance.publish(self.snapshot)
        self.assertRegex(receipt['rclone_version'], r'^v\d+\.\d+\.\d+')
        self.assertEqual(receipt['provider_receipt'], 'not_run')
        first = instance.fetch(self.snapshot, self.root / 'real-first')
        instance.publish(self.snapshot)
        current = self.accept({'Old.md': None, 'Home.md': '# New accepted revision\n'})
        instance.publish(current, previous=self.snapshot)
        result = instance.fetch(current, self.root / 'real-second', previous=self.snapshot)
        self.assertEqual(first.snapshot, self.snapshot)
        self.assertEqual(result.snapshot, current)
        self.assertEqual(result.receipt['deleted_paths'], ['Old.md'])
        self.assertEqual(result.receipt['provider_receipt'], 'not_run')
        self.assertEqual(private.read_bytes(), b'UNRELATED PRIVATE FIXTURE')
        self.assertTrue((store / self.manifest_key()).is_file())


class DriverBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-driver-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config = self.root / 'private.conf'
        self.contents = ('[reviewed]\ntype = drive\nclient_id = fixture-owned-client\nclient_secret = SECRET\n'
                         'scope = drive\nroot_folder_id = fixture-folder-id\n'
                         'token = {"refresh_token":"PRIVATE-REFRESH-TOKEN"}\n')
        self.config.write_text(self.contents)
        self.config.chmod(0o600)
        self.binding = GoogleDriveBinding(self.config, 'reviewed', 'fixture-folder-id', 'personal', reviewed=True)

    def test_binding_preflight_is_local_and_does_not_expose_credentials(self):
        with patch('shared_workspace.delivery.subprocess.Popen') as process:
            backend = RcloneBackend(sys.executable, self.binding)
            process.assert_not_called()
        self.assertEqual(backend.info()['route'], 'google_drive_rclone')
        self.assertNotIn('SECRET', repr(self.binding))
        self.assertNotIn('fixture-folder-id', repr(self.binding))
        self.assertEqual(self.config.read_text(), self.contents)

    def test_invalid_type_root_scope_review_and_extra_config_rejected_without_process(self):
        with patch('shared_workspace.delivery.subprocess.Popen') as process:
            for binding in (replace(self.binding, reviewed=False), replace(self.binding, root_folder_id='other'),
                            replace(self.binding, remote=':local'), replace(self.binding, account_type='unspecified')):
                with self.subTest(binding=repr(binding)), self.assertRaises(ProductError):
                    RcloneBackend(sys.executable, binding)
            for contents in (self.contents.replace('type = drive', 'type = local'),
                             self.contents.replace('scope = drive', 'scope = drive.metadata.readonly'),
                             self.contents + 'token_url = https://attacker.invalid\n',
                             self.contents.replace('client_id = fixture-owned-client', 'client_id =')):
                self.config.write_text(contents)
                with self.subTest(contents=contents[:20]), self.assertRaises(ProductError) as caught:
                    RcloneBackend(sys.executable, self.binding)
                self.assertNotIn('SECRET', str(caught.exception))
            process.assert_not_called()

    def test_shared_drive_binding_and_private_config_permissions(self):
        self.config.write_text(self.contents + 'team_drive = shared-drive-id\n')
        shared = replace(self.binding, account_type='workspace_shared_drive', team_drive_id='shared-drive-id')
        RcloneBackend(sys.executable, shared)
        with self.assertRaises(ProductError):
            RcloneBackend(sys.executable, self.binding)
        if os.name != 'nt':
            self.config.chmod(0o644)
            with self.assertRaises(ProductError) as caught:
                RcloneBackend(sys.executable, shared)
            self.assertEqual(caught.exception.code, 'delivery_binding')

    def test_config_symlink_is_rejected_without_reading_target(self):
        link = self.root / 'config-link'
        try:
            link.symlink_to(self.config)
        except OSError as exc:
            self.skipTest(f'Symlink capability unavailable: {exc.errno}')
        with self.assertRaises(ProductError) as caught:
            RcloneBackend(sys.executable, replace(self.binding, config=link))
        self.assertEqual(caught.exception.code, 'delivery_path')
        self.assertEqual(self.config.read_text(), self.contents)

    def test_raw_drive_inventory_rejects_shortcuts_native_docs_duplicates_and_wrong_parent(self):
        backend = RcloneBackend(sys.executable, self.binding)
        regular = {'id': 'file-id', 'name': 'Note.md', 'mimeType': 'text/plain',
                   'parents': ['fixture-folder-id'], 'size': '4'}
        variants = [[dict(regular, mimeType='application/vnd.google-apps.shortcut')],
                    [dict(regular, mimeType='application/vnd.google-apps.document')],
                    [regular, dict(regular, id='second-id')],
                    [dict(regular, parents=['outside-folder'])], [dict(regular, name='../escape')]]
        for values in variants:
            with self.subTest(values=values), patch.object(backend, '_run', return_value=canonical(values).encode()):
                with self.assertRaises(ProductError):
                    backend._children('fixture-folder-id')
        with patch.object(backend, '_run', return_value=canonical([regular]).encode()) as run:
            self.assertEqual(backend._children('fixture-folder-id'), [regular])
            args = run.call_args.args[0]
            self.assertEqual(args[:2], ['backend', 'query'])
            self.assertEqual(args[-1], "'fixture-folder-id' in parents and trashed = false")
        with patch.object(backend, '_run', return_value=b'null'):
            self.assertEqual(backend._children('fixture-folder-id'), [])

    def subprocess_backend(self, timeout=2):
        backend = LocalRcloneBackend(sys.executable, self.root, timeout=timeout)
        self.addCleanup(backend.close)
        backend.deadline = delivery.time.monotonic() + 5
        return backend

    def test_actual_child_output_limit_timeout_failure_redaction_and_sanitized_environment(self):
        backend = self.subprocess_backend(timeout=0.25)
        real_popen = subprocess.Popen
        scripts = [('import sys; sys.stdout.write("x"*1000000)', 'delivery_limit'),
                   ('import time; time.sleep(3)', 'delivery_timeout'),
                   ('import sys; sys.stderr.write("PRIVATE-REFRESH-TOKEN secret-remote"); sys.exit(9)', 'delivery_unavailable'),
                   ('import sys; sys.stdout.write("[]"); sys.stderr.write("ERROR search result INCOMPLETE")', 'delivery_unavailable')]
        for script, expected_code in scripts:
            def spawn(command, **kwargs):
                self.assertFalse(kwargs['shell'])
                self.assertNotIn('RCLONE_CONFIG_ATTACKER_TYPE', kwargs['env'])
                self.assertNotIn('HTTPS_PROXY', kwargs['env'])
                self.assertIn('--config', command)
                return real_popen([sys.executable, '-c', script], **kwargs)
            with self.subTest(code=expected_code), patch.dict(os.environ, {'RCLONE_CONFIG_ATTACKER_TYPE': 'drive',
                    'HTTPS_PROXY': 'http://secret-proxy.invalid'}), patch('shared_workspace.delivery.subprocess.Popen', side_effect=spawn):
                with self.assertRaises(ProductError) as caught:
                    backend._run(['version'], maximum=128)
                self.assertEqual(caught.exception.code, expected_code)
                self.assertNotIn('PRIVATE-REFRESH-TOKEN', str(caught.exception))
                self.assertNotIn('secret-remote', str(caught.exception))
                self.assertEqual(caught.exception.data, {})


if __name__ == '__main__':
    unittest.main()
