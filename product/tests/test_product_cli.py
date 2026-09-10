"""Acceptance tests for the actual packaged product preview CLI.

Run with Python 3.11+: python -m unittest discover -s product/tests -v
All projects, archives, and intentionally damaged fixtures are disposable.
"""
from __future__ import annotations

import hashlib
import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix():
            ('symlink:' + os.readlink(p) if p.is_symlink() else
             'directory' if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob('*'))}


def objects(value):
    """Inspect typed JSON recursively without assuming unspecified data nesting."""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from objects(child)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


class ProductCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.version_info < (3, 11):
            raise unittest.SkipTest('Product acceptance requires Python 3.11+')
        cls.build_temp = tempfile.TemporaryDirectory(prefix='workspace-package-test-')
        cls.addClassCleanup(cls.build_temp.cleanup)
        cls.archive = Path(cls.build_temp.name) / 'shared-workspace.pyz'
        build = subprocess.run([
            sys.executable, str(REPO / 'scripts/build_product.py'), '--output', str(cls.archive)
        ], cwd=REPO, text=True, capture_output=True, timeout=60)
        if build.returncode != 0:
            raise AssertionError('Actual product build failed:\n' + build.stdout + build.stderr)
        if not cls.archive.is_file():
            raise AssertionError('Build did not produce the requested archive')
        with zipfile.ZipFile(cls.archive) as archive:
            cls.build = json.loads(archive.read('BUILD.json'))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='workspace-product-acceptance-')
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.project = self.parent / 'Selected project'
        self.project.mkdir()

    def invoke(self, *args, expected=0, archive=None):
        result = subprocess.run([
            sys.executable, str(archive or self.archive), *map(str, args)
        ], cwd=self.parent, text=True, capture_output=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        try:
            response = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail('Operational stdout is not exactly one JSON object:\n' + result.stdout + result.stderr)
        self.assertIsInstance(response, dict)
        self.assertEqual(response.get('schema_version'), 1)
        self.assertEqual(response.get('product_version'), '0.3.0')
        self.assertTrue({'command', 'ok', 'code', 'data', 'warnings'} <= response.keys(), response)
        self.assertIsInstance(response['warnings'], list)
        self.assertEqual(response['ok'], expected == 0, response)
        self.assertNotIn('Traceback', result.stdout)
        if expected:
            self.assertIsInstance(response.get('message'), str)
            self.assertTrue(response['message'])
        return response

    def create(self, mode='local-only'):
        return self.invoke('create', self.project, '--person', 'Owner Fictional',
                           '--actor', 'owner-demo', '--agent', 'Scripted test',
                           '--mode', mode, '--purpose', 'Disposable product acceptance fixture')

    def metadata(self):
        return json.loads((self.project / '.workspace-project.json').read_text())

    def join(self, *, project_id=None, bundle_id=None, expected=0):
        meta = self.metadata()
        return self.invoke('join', self.project, '--person', 'Recipient Fictional',
                           '--actor', 'recipient-demo', '--agent', 'Scripted recipient',
                           '--expected-project-id', project_id or meta['project_id'],
                           '--expected-bundle-id', bundle_id or meta['bundle_id'], expected=expected)

    def work(self, *args, expected=0):
        return self.invoke('work', self.project, '--', *args, expected=expected)

    def assert_unchanged_error(self, args, expected=3):
        before = snapshot(self.parent)
        response = self.invoke(*args, expected=expected)
        self.assertEqual(snapshot(self.parent), before)
        return response

    def alter_archive(self, filename, transform):
        target = self.parent / 'changed-package.pyz'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(target, 'w') as dest:
            for item in source.infolist():
                body = source.read(item.filename)
                dest.writestr(item, transform(body) if item.filename == filename else body)
        return target

    def test_build_identity_and_hashes_cover_actual_package_bytes(self):
        self.assertEqual(self.build['product_version'], '0.3.0')
        self.assertEqual(self.build['toolkit_version'], '1.3.0')
        self.assertIsInstance(self.build['source_revision'], str)
        self.assertIsInstance(self.build['source_dirty'], bool)
        mapping = self.build['files']
        self.assertTrue(mapping)
        canonical = json.dumps(mapping, sort_keys=True, separators=(',', ':')).encode()
        self.assertEqual(hashlib.sha256(canonical).hexdigest(), self.build['bundle_id'])
        with zipfile.ZipFile(self.archive) as archive:
            for name, digest in mapping.items():
                self.assertFalse(Path(name).is_absolute())
                self.assertNotIn('..', Path(name).parts)
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest, name)
            self.assertTrue(any(name.startswith('bundle/') for name in mapping))
            self.assertTrue(any(name.startswith('shared_workspace/') for name in mapping))
        version = self.invoke('version')
        self.assertIn(self.build['bundle_id'], set(strings(version['data'])))
        self.assertIn(self.build['source_revision'], set(strings(version['data'])))

    def test_usage_errors_are_json(self):
        for args in [(), ('not-a-command',), ('create',), ('join', str(self.project))]:
            with self.subTest(args=args):
                self.invoke(*args, expected=2)

    def test_unsupported_python_reports_json_when_available(self):
        candidates = [shutil.which('python3.9'), shutil.which('python3.10'), '/usr/bin/python3']
        for candidate in candidates:
            if not candidate or not Path(candidate).is_file():
                continue
            probe = subprocess.run([candidate, '-c', 'import sys; print(sys.version_info[:2])'],
                                   capture_output=True, text=True, timeout=15)
            if probe.returncode or probe.stdout.strip() not in {'(3, 9)', '(3, 10)'}:
                continue
            result = subprocess.run([candidate, str(self.archive), 'version'],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            response = json.loads(result.stdout)
            self.assertFalse(response['ok'])
            self.assertEqual(response['schema_version'], 1)
            self.assertTrue(response['message'])
            return
        self.skipTest('No installed unsupported Python 3.9/3.10 interpreter to exercise the runtime gate')

    def test_create_preserves_selected_folder_home_and_parent_private_state(self):
        (self.parent / 'Private.md').write_text('Private parent note, not shared.\n')
        (self.parent / 'AGENTS.md').write_text('Parent instructions must not change.\n')
        config = self.parent / '.obsidian'; config.mkdir()
        (config / 'sentinel.json').write_text('{"synthetic_fixture": true}\n')
        (self.project / 'Home.md').write_text('# Existing project\n\nKeep this history.\n')
        (self.project / 'AGENTS.md').write_text('# Existing scope\n\nNever publish.\n')
        before = snapshot(self.parent)
        response = self.create()
        after = snapshot(self.parent)
        for path, digest in before.items():
            if path not in {'Selected project', 'Selected project/AGENTS.md'}:
                self.assertEqual(after[path], digest, path)
        self.assertIn('Never publish.', (self.project / 'AGENTS.md').read_text())
        self.assertFalse((self.project / '.obsidian').exists())
        self.assertIn('ready', set(strings(response['data'])))
        meta = self.metadata()
        self.assertEqual(meta['format_version'], 1)
        uuid.UUID(meta['project_id'])
        self.assertEqual(meta['mode'], 'local-only')
        self.assertEqual(meta['product_version'], '0.3.0')
        self.assertEqual(meta['toolkit_version'], '1.3.0')
        self.assertEqual(meta['bundle_id'], self.build['bundle_id'])
        tracker = self.project / 'Coordination/project_tracker.py'
        self.assertEqual(meta['tracker_sha256'], hashlib.sha256(tracker.read_bytes()).hexdigest())
        encoded = json.dumps(meta)
        self.assertNotIn(str(self.parent), encoded)
        self.assertNotIn('Owner Fictional', encoded)
        self.assertNotIn('owner-demo', encoded)
        self.assert_unchanged_error(('create', self.project, '--person', 'Owner Fictional',
            '--actor', 'owner-demo', '--agent', 'Scripted test', '--mode', 'local-only',
            '--purpose', 'Must refuse an existing project'), expected=4)

    def test_missing_target_reports_io_error_without_creating_it(self):
        missing = self.parent / 'not-created'
        self.assert_unchanged_error(('create', missing, '--person', 'Owner', '--actor', 'owner',
            '--agent', 'Test', '--mode', 'local-only', '--purpose', 'Fixture'), expected=5)
        self.assertFalse(missing.exists())

    def test_generated_symlink_paths_refused_without_touching_outside_targets(self):
        outside_file = self.parent / 'Outside.md'
        outside_file.write_text('Outside bytes must remain untouched.\n')
        outside_dir = self.parent / 'Outside folder'
        outside_dir.mkdir()
        (outside_dir / 'Private.md').write_text('Outside private note.\n')
        cases = [('AGENTS.md', outside_file, 3), ('CLAUDE.md', outside_file, 3),
                 ('Home.md', outside_file, 3),
                 ('README.md', outside_file, 3), ('Coordination', outside_dir, 3),
                 ('Coordination/Workspace.base', outside_file, 3),
                 ('Coordination/project_tracker.py', outside_file, 4),
                 ('.workspace-project.json', outside_file, 4)]
        for index, (relative, destination, expected) in enumerate(cases):
            with self.subTest(relative=relative):
                self.project = self.parent / ('Link project ' + str(index))
                self.project.mkdir()
                link = self.project / relative
                link.parent.mkdir(parents=True, exist_ok=True)
                try:
                    link.symlink_to(destination, target_is_directory=destination.is_dir())
                except OSError as exc:
                    if (getattr(exc, 'winerror', None) == 1314 or
                            exc.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP, errno.ENOSYS}):
                        self.skipTest('Local environment does not permit symbolic links: ' + str(exc))
                    raise
                self.assert_unchanged_error(('create', self.project, '--person', 'Owner',
                    '--actor', 'owner', '--agent', 'Test', '--mode', 'local-only',
                    '--purpose', 'Must reject symlink fixture'), expected=expected)
                self.assertTrue(link.is_symlink())

    def test_generated_path_type_collisions_refused_before_any_setup_write(self):
        for index, (relative, directory) in enumerate([
                ('Coordination', False), ('AGENTS.md', True), ('README.md', True),
                ('Coordination/Workspace.base', True)]):
            with self.subTest(relative=relative):
                self.project = self.parent / ('Collision project ' + str(index))
                self.project.mkdir()
                path = self.project / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                if directory:
                    path.mkdir()
                    (path / 'Preserved.md').write_text('Keep existing folder contents.\n')
                else:
                    path.write_text('Existing regular file must not be replaced.\n')
                self.assert_unchanged_error(('create', self.project, '--person', 'Owner',
                    '--actor', 'owner', '--agent', 'Test', '--mode', 'local-only',
                    '--purpose', 'Must reject type collision before writing'), expected=3)

    def test_invalid_actor_refused_before_any_setup_write(self):
        (self.project / 'Keep.md').write_text('Existing project material.\n')
        for actor in ['@', '!!!']:
            with self.subTest(actor=actor):
                self.assert_unchanged_error(('create', self.project, '--person', 'Owner',
                    '--actor', actor, '--agent', 'Test', '--mode', 'local-only',
                    '--purpose', 'Must reject invalid actor before writing'), expected=2)

    def test_interrupted_create_is_not_silently_repaired(self):
        self.create()
        (self.project / '.workspace-project.json').unlink()
        self.assert_unchanged_error(('doctor', self.project))
        self.assert_unchanged_error(('create', self.project, '--person', 'Owner', '--actor', 'owner',
            '--agent', 'Test', '--mode', 'local-only', '--purpose', 'Fixture'), expected=4)

    def test_join_relocated_project_with_independent_actor(self):
        self.create()
        original_id = self.metadata()['project_id']
        destination = self.parent / 'Other person' / 'Private vault' / 'Elsewhere' / 'Shared'
        shutil.copytree(self.project, destination)
        self.project = destination
        self.join()
        self.assertEqual(self.metadata()['project_id'], original_id)
        records = list((self.project / 'Coordination/Items').glob('ACTOR-*.md'))
        self.assertTrue(any('OWNER-DEMO' in p.read_text() for p in records))
        self.assertTrue(any('RECIPIENT-DEMO' in p.read_text() for p in records))
        self.assertFalse(list((self.project / 'Coordination/Items').glob('WORK-*.md')))
        self.invoke('doctor', self.project)

    def test_join_wrong_expected_identities_does_not_write(self):
        self.create()
        for kwargs in [{'project_id': str(uuid.uuid4())}, {'bundle_id': '0' * 64}]:
            with self.subTest(kwargs=kwargs):
                before = snapshot(self.parent)
                self.join(expected=3, **kwargs)
                self.assertEqual(snapshot(self.parent), before)

    def test_missing_tracker_and_wrong_manifest_version_fail_closed(self):
        self.create()
        tracker = self.project / 'Coordination/project_tracker.py'
        saved = tracker.read_bytes(); tracker.unlink()
        before = snapshot(self.parent)
        self.join(expected=3)
        self.assertEqual(snapshot(self.parent), before)
        self.assert_unchanged_error(('doctor', self.project))
        tracker.write_bytes(saved)
        meta = self.metadata(); meta['product_version'] = '99.0.0'
        (self.project / '.workspace-project.json').write_text(json.dumps(meta))
        before = snapshot(self.parent)
        self.join(expected=3)
        self.assertEqual(snapshot(self.parent), before)

    def test_tampered_project_tracker_never_executes(self):
        self.create()
        sentinel = self.parent / 'TARGET-CODE-EXECUTED'
        (self.project / 'Coordination/project_tracker.py').write_text(
            'from pathlib import Path\nPath(' + repr(str(sentinel)) + ').write_text("unsafe")\n')
        for args in [('doctor', self.project), ('status', self.project), ('work', self.project, '--', 'status')]:
            with self.subTest(command=args[0]):
                self.assert_unchanged_error(args)
                self.assertFalse(sentinel.exists())

    def test_tampered_bundle_and_identity_rejected_before_toolkit_execution(self):
        target_name = next(name for name in self.build['files'] if name.endswith('/assets/project_tracker.py'))
        sentinel = self.parent / 'BUNDLE-CODE-EXECUTED'
        damaged = self.alter_archive(target_name, lambda body:
            body + ('\nfrom pathlib import Path\nPath(' + repr(str(sentinel)) + ').write_text("unsafe")\n').encode())
        self.invoke('version', archive=damaged, expected=3)
        self.assertFalse(sentinel.exists())
        damaged = self.alter_archive('BUILD.json', lambda body:
            json.dumps({**json.loads(body), 'bundle_id': '0' * 64}).encode())
        self.invoke('version', archive=damaged, expected=3)

    def test_missing_bundled_file_is_integrity_failure(self):
        target_name = next(name for name in self.build['files'] if name.endswith('/assets/project_tracker.py'))
        archive_path = self.parent / 'incomplete-package.pyz'
        with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(archive_path, 'w') as dest:
            for item in source.infolist():
                if item.filename != target_name:
                    dest.writestr(item, source.read(item.filename))
        self.invoke('version', archive=archive_path, expected=3)

    def test_consistent_manifest_cannot_authorize_unsafe_archive_paths(self):
        escaped = self.parent / 'ARCHIVE-ESCAPED'
        for index, name in enumerate([str(escaped), '../ARCHIVE-ESCAPED-' + str(uuid.uuid4())]):
            with self.subTest(member=name):
                payload = b'Unsafe path must never be extracted.\n'
                manifest = {**self.build, 'files': {**self.build['files'],
                            name: hashlib.sha256(payload).hexdigest()}}
                manifest['bundle_id'] = hashlib.sha256(json.dumps(manifest['files'],
                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                archive_path = self.parent / ('unsafe-path-' + str(index) + '.pyz')
                with zipfile.ZipFile(self.archive) as source, zipfile.ZipFile(archive_path, 'w') as dest:
                    for item in source.infolist():
                        dest.writestr(item, json.dumps(manifest).encode() if item.filename == 'BUILD.json'
                                      else source.read(item.filename))
                    dest.writestr(name, payload)
                before = snapshot(self.parent)
                self.invoke('version', archive=archive_path, expected=3)
                self.assertEqual(snapshot(self.parent), before)
                self.assertFalse(escaped.exists())
                if name.startswith('../'):
                    self.assertFalse((Path(tempfile.gettempdir()) / name[3:]).exists())

    def test_source_mode_requires_explicit_built_bundle(self):
        env = dict(os.environ, PYTHONPATH=str(REPO / 'product'), PYTHONDONTWRITEBYTECODE='1')
        result = subprocess.run([sys.executable, '-m', 'shared_workspace.cli', 'version'],
            cwd=self.parent, env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 5, result.stdout + result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response['ok'])
        self.assertEqual(response['schema_version'], 1)
        self.assertIn('bundle', response['message'].lower())

    def test_shared_mode_is_partial_and_diagnostics_read_only(self):
        self.create(mode='shared-folder')
        before = snapshot(self.parent)
        doctor = self.invoke('doctor', self.project)
        self.assertIn('partial', set(strings(doctor['data'])))
        self.assertIn('unverified', set(strings(doctor['data'])))
        self.invoke('status', self.project)
        self.assertEqual(snapshot(self.parent), before)

    def test_teammate_prompt_has_expected_identities_without_author_path(self):
        self.create(mode='shared-folder')
        before = snapshot(self.parent)
        response = self.invoke('teammate-prompt', self.project)
        self.assertIn('partial', set(strings(response['data'])))
        encoded = json.dumps(response['data'])
        self.assertNotIn(str(self.project), encoded)
        self.assertNotIn('Owner Fictional', encoded)
        self.assertIn(self.metadata()['project_id'], encoded)
        self.assertIn(self.metadata()['bundle_id'], encoded)
        response = self.invoke('teammate-prompt', self.project,
            '--package-locator', 'approved private transfer: package.pyz',
            '--access-locator', 'approved team folder invitation')
        encoded = json.dumps(response['data'])
        self.assertNotIn(str(self.project), encoded)
        self.assertNotIn('Owner Fictional', encoded)
        self.assertIn('approved private transfer: package.pyz', encoded)
        self.assertIn('approved team folder invitation', encoded)
        self.assertEqual(snapshot(self.parent), before)

    def test_literal_special_project_path(self):
        self.project = self.parent / "Spaces ' quotes $HOME ; (literal)"
        self.project.mkdir()
        self.create()
        self.invoke('doctor', self.project)
        self.assertEqual(self.metadata()['mode'], 'local-only')

    def test_real_claim_change_handoff_accept_and_complete(self):
        self.create(); self.join()
        self.work('claim', '--actor', 'owner-demo', '--owner', 'Owner Fictional', '--agent', 'Scripted test',
            '--initiated-by', 'Owner Fictional', '--work-id', 'DEMO', '--title', 'Tiny output',
            '--objective', 'Write and verify the fixture note', '--target', 'Deliverable.md',
            '--acceptance', 'Note equals the required fixture text', '--next-action', 'Write the note')
        self.work('check', '--actor', 'owner-demo', '--work-id', 'DEMO')
        text = '# Deliverable\n\nChecked fixture content.\n'
        (self.project / 'Deliverable.md').write_text(text)
        self.assertEqual((self.project / 'Deliverable.md').read_text(), text)
        self.work('change', '--actor', 'owner-demo', '--work-id', 'DEMO', '--summary', 'Wrote checked note',
            '--change-kind', 'validation', '--impact', 'none', '--pass-criterion', '1',
            '--evidence', 'Deliverable.md', '--validation', 'Test process compared exact note content.',
            '--next-action', 'Hand off for review')
        self.work('handoff', '--actor', 'owner-demo', '--work-id', 'DEMO',
            '--to-actor', 'recipient-demo', '--to-owner', 'Recipient Fictional', '--to-agent', 'Scripted recipient',
            '--last-verified', 'Exact content comparison passed', '--evidence', 'Deliverable.md',
            '--next-action', 'Accept and verify')
        before = snapshot(self.parent)
        self.work('check', '--actor', 'recipient-demo', '--work-id', 'DEMO', expected=4)
        self.assertEqual(snapshot(self.parent), before)
        self.work('accept-handoff', '--actor', 'recipient-demo', '--work-id', 'DEMO',
            '--summary', 'Read note and handoff', '--next-action', 'Check and complete')
        self.work('check', '--actor', 'recipient-demo', '--work-id', 'DEMO')
        self.assertEqual((self.project / 'Deliverable.md').read_text(), text)
        self.work('change', '--actor', 'recipient-demo', '--work-id', 'DEMO',
            '--summary', 'Recipient reran exact content comparison', '--change-kind', 'validation',
            '--impact', 'none', '--evidence', 'Deliverable.md', '--validation', 'Exact content matched.',
            '--next-action', 'Complete')
        self.work('complete', '--actor', 'recipient-demo', '--work-id', 'DEMO',
            '--summary', 'Verified tiny fixture', '--evidence', 'Deliverable.md',
            '--validation', 'Test process compared exact content after handoff.', '--impact', 'none')
        status = self.invoke('status', self.project)
        work = [o for o in objects(status['data']) if o.get('work_id') == 'DEMO' and 'status' in o]
        self.assertTrue(work, 'status must expose typed work records')
        self.assertTrue(any(o['status'] == 'verified' and o.get('actor_id') == 'RECIPIENT-DEMO'
                            and o.get('acceptance_passed') == 1 for o in work), work)

    def test_work_cannot_override_project_root(self):
        self.create()
        outside = self.parent / 'Outside'; outside.mkdir()
        before = snapshot(self.parent)
        result = subprocess.run([sys.executable, str(self.archive), 'work', str(self.project), '--',
            '--project-root', str(outside), 'sync', '--actor', 'intruder', '--human', 'Intruder', '--agent', 'Test'],
            cwd=self.parent, capture_output=True, text=True, timeout=60)
        self.assertIn(result.returncode, (2, 3, 4), result.stdout + result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response['ok'])
        self.assertEqual(snapshot(self.parent), before)

    def test_capabilities_do_not_claim_unsupported_team_gates_passed(self):
        response = self.invoke('capabilities')
        data = response['data']
        text = json.dumps(data).lower()
        for command in ['version', 'create', 'join', 'doctor', 'status', 'work', 'teammate-prompt']:
            self.assertIn(command, text)
        for gate in ['team-03', 'team-05', 'team-06', 'team-07', 'team-08', 'team-09', 'team-10', 'team-11']:
            self.assertIn(gate, text)
        self.assertTrue(any(word in text for word in ['unsupported', 'not_run', 'not run']))
        for item in objects(data):
            identity = str(item.get('id', item.get('gate', ''))).lower()
            if identity in {'team-03', 'team-05', 'team-06', 'team-07', 'team-08', 'team-09', 'team-10', 'team-11'}:
                self.assertNotIn(str(item.get('status', '')).lower(), ('passed', 'verified', 'complete'))


if __name__ == '__main__':
    unittest.main(verbosity=2)
