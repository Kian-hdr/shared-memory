"""Release provenance/privacy checks in disposable committed Git repositories."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
VERSION = '0.2.0-alpha.1'


class ReleaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        # Include distribution prerequisites when exercising an uncommitted
        # working change to the release tooling or assets.
        names += ['scripts/build_release.py', 'scripts/build_product.py', '.gitattributes',
                  'assets/README.md', 'assets/shared-memory.svg', 'assets/shared-memory.png',
                  'assets/shared-memory.icns']
        cls.sources = {name: (ROOT / name).read_bytes() for name in set(names)
                       if name and (ROOT / name).is_file() and not (ROOT / name).is_symlink()}

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-release-build-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.repo = self.root / 'checkout'
        self.repo.mkdir()
        for name, content in self.sources.items():
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        # Windows Git defaults and global hooks must not change fixture bytes.
        self.git('init', '-q')
        self.git('config', 'user.name', 'Synthetic Release Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        self.git('config', 'core.autocrlf', 'false')
        self.git('config', 'core.hooksPath', str(self.root / 'no-hooks'))
        self.git('config', 'commit.gpgsign', 'false')
        ignore = self.repo / '.gitignore'
        ignore.write_bytes(ignore.read_bytes() + b'\n.env\n.DS_Store\nignored-module.py\n')
        self.git('add', '.')
        self.git('commit', '-qm', 'Synthetic reviewed release inputs')
        self.revision = self.git('rev-parse', 'HEAD').decode().strip()
        self.output = self.root / 'release'

    def git(self, *args):
        return subprocess.check_output(['git', *args], cwd=self.repo, stderr=subprocess.PIPE)

    def invoke(self, output=None, *, expected=0):
        result = subprocess.run([sys.executable, str(self.repo / 'scripts/build_release.py'),
            '--output', str(output or self.output), '--release-version', VERSION],
            cwd=self.root, capture_output=True, timeout=60)
        if expected == 0:
            self.assertEqual(result.returncode, 0, (result.stdout + result.stderr).decode(errors='replace'))
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def files(self, root):
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file()}

    def assert_secret_absent(self, content, secret):
        self.assertNotIn(secret, content)
        if zipfile.is_zipfile(io.BytesIO(content)):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                for name in archive.namelist():
                    self.assertNotIn('.env', name.split('/'))
                    self.assertNotIn('.DS_Store', name.split('/'))
                    self.assert_secret_absent(archive.read(name), secret)

    def test_ignored_skill_and_runtime_extras_never_enter_any_release_asset(self):
        # The complete source kit includes this test itself. A fresh marker
        # distinguishes ignored fixture data from the test's committed source.
        secret = ('SYNTHETIC_IGNORED_SECRET_' + secrets.token_hex(16)).encode()
        for name in ('skills/setup-shared-project-workspace/.env',
                     'skills/setup-shared-project-workspace/.DS_Store',
                     'product/shared_workspace/ignored-module.py'):
            (self.repo / name).write_bytes(secret)
        self.assertEqual(self.git('status', '--porcelain'), b'')
        self.invoke()
        for content in self.files(self.output).values():
            self.assert_secret_absent(content, secret)
        with zipfile.ZipFile(self.output / f'shared-memory-{VERSION}.pyz') as archive:
            build = json.loads(archive.read('BUILD.json'))
            self.assertFalse(build['source_dirty'])
            self.assertEqual(build['source_revision'], self.revision)
            self.assertNotIn('shared_workspace/ignored-module.py', archive.namelist())

    def test_hidden_changed_tracked_bytes_refused_before_artifact_creation(self):
        for flag, undo in [('--assume-unchanged', '--no-assume-unchanged'),
                           ('--skip-worktree', '--no-skip-worktree')]:
            for name in ('product/shared_workspace/cli.py', 'skills/setup-shared-project-workspace/SKILL.md',
                         'assets/shared-memory.svg', 'SETUP-PROMPT.md'):
                with self.subTest(flag=flag, name=name):
                    path = self.repo / name
                    original = path.read_bytes()
                    self.git('update-index', flag, name)
                    path.write_bytes(original + b'\nHIDDEN UNREVIEWED CHANGE\n')
                    self.assertEqual(self.git('status', '--porcelain'), b'')
                    result = self.invoke(expected=1)
                    self.assertIn(b'Tracked working bytes differ', result.stderr)
                    self.assertFalse(self.output.exists())
                    path.write_bytes(original)
                    self.git('update-index', undo, name)

    def test_complete_committed_source_bundle_hashes_provenance_and_repeatability(self):
        self.invoke()
        assets = self.files(self.output)
        package_name = f'shared-memory-{VERSION}.pyz'
        with zipfile.ZipFile(io.BytesIO(assets[f'shared-memory-{VERSION}.zip'])) as kit:
            committed = self.git('ls-tree', '-r', '--name-only', '-z', 'HEAD').decode().split('\0')
            for name in filter(None, committed):
                self.assertEqual(kit.read(name), self.git('show', 'HEAD:' + name), name)
            self.assertEqual(set(kit.namelist()), set(filter(None, committed)) |
                             {package_name, 'RELEASE-MANIFEST.json', 'SHA256SUMS'})
            self.assertEqual(kit.read(package_name), assets[package_name])
            self.assertTrue(all(entry.create_system == 3 for entry in kit.infolist()))
        manifest = json.loads(assets['RELEASE-MANIFEST.json'])
        self.assertEqual(manifest['source_revision'], self.revision)
        self.assertFalse(manifest['source_dirty'])
        self.assertEqual(manifest['runtime_sha256'], hashlib.sha256(assets[package_name]).hexdigest())
        for line in assets['SHA256SUMS'].decode().splitlines():
            checksum, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256(assets[name]).hexdigest(), checksum)
        with zipfile.ZipFile(io.BytesIO(assets[package_name])) as package:
            build = json.loads(package.read('BUILD.json'))
            self.assertEqual(set(package.namelist()), set(build['files']) | {'BUILD.json'})
            self.assertTrue(all(entry.create_system == 3 for entry in package.infolist()))
            for name, checksum in build['files'].items():
                self.assertEqual(hashlib.sha256(package.read(name)).hexdigest(), checksum)
        result = subprocess.run([sys.executable, str(self.output / package_name), 'version'],
                                capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['ok'])
        second = self.root / 'repeat'
        self.invoke(second)
        self.assertEqual(self.files(second), assets)

    def test_existing_output_and_checkout_output_refused_without_overwrite(self):
        self.output.mkdir()
        sentinel = self.output / 'keep.bin'
        sentinel.write_bytes(b'EXISTING ARTIFACT')
        self.invoke(expected=1)
        self.assertEqual(self.files(self.output), {'keep.bin': b'EXISTING ARTIFACT'})
        inside = self.repo / 'release'
        self.invoke(inside, expected=1)
        self.assertFalse(inside.exists())

    def test_development_builder_excludes_ignored_and_labels_new_or_hidden_inputs_dirty(self):
        secret = b'SYNTHETIC DEVELOPMENT ONLY INPUT'
        (self.repo / 'skills/setup-shared-project-workspace/.env').write_bytes(secret)
        self.assertEqual(self.git('status', '--porcelain'), b'')
        output = self.root / 'development.pyz'
        result = subprocess.run([sys.executable, str(self.repo / 'scripts/build_product.py'),
                                 '--output', str(output)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['source_dirty'])
        with zipfile.ZipFile(output) as archive:
            self.assertNotIn('bundle/skills/setup-shared-project-workspace/.env', archive.namelist())
            for name in archive.namelist():
                self.assertNotIn(secret, archive.read(name))
        new_source = self.repo / 'product/shared_workspace/new_feature.py'
        new_source.write_bytes(b'# Legitimate untracked development work\n')
        new_output = self.root / 'new-development.pyz'
        result = subprocess.run([sys.executable, str(self.repo / 'scripts/build_product.py'),
            '--output', str(new_output)], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['source_dirty'])
        with zipfile.ZipFile(new_output) as archive:
            self.assertEqual(archive.read('shared_workspace/new_feature.py'), new_source.read_bytes())
        new_source.unlink()
        path = self.repo / 'product/shared_workspace/cli.py'
        self.git('update-index', '--assume-unchanged', 'product/shared_workspace/cli.py')
        path.write_bytes(path.read_bytes() + b'\n# Hidden development change\n')
        result = subprocess.run([sys.executable, str(self.repo / 'scripts/build_product.py'),
            '--output', str(self.root / 'hidden-development.pyz')], capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['source_dirty'])


if __name__ == '__main__':
    unittest.main()
