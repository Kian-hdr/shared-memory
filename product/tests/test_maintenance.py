"""Real-package maintenance tests, confined to isolated local fixtures."""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import shutil
import shlex
import subprocess
import sys
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / 'product') not in sys.path:
    sys.path.insert(0, str(ROOT / 'product'))
from shared_workspace import PRODUCT_VERSION
from shared_workspace.engine import Coordinator
from shared_workspace.errors import ProductError
from shared_workspace import maintenance, workflow
from shared_workspace.transport import HTTPTransport


def inventory(root):
    return {p.relative_to(root).as_posix(): ('symlink:' + os.readlink(p) if p.is_symlink()
            else 'directory' if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob('*'))}


class MaintenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory(prefix='shared-memory-maintenance-package-')
        cls.addClassCleanup(cls.build_temp.cleanup)
        cls.package = Path(cls.build_temp.name) / 'current.pyz'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build_product.py'), '--output', str(cls.package)],
                                capture_output=True, text=True, cwd=ROOT)
        if result.returncode:
            raise AssertionError('Real product package build failed: ' + result.stdout + result.stderr)
        cls.package_sha = maintenance.sha(cls.package)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-maintenance-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.tools = self.root / 'tools'

    def init_project(self, name):
        project = self.root / name
        project.mkdir()
        (project / 'Home.md').write_text('# Fixture ' + name + '\n', encoding='utf-8')
        state = self.root / (name + '-private')
        args = argparse.Namespace(command='init', project=str(project), state_dir=str(state),
                                  person='Fixture', actor=name, agent='Test', purpose='Synthetic test',
                                  include=None, mode='local', provider='local')
        return project, state, workflow.dispatch(None, args)

    def test_real_package_install_preserves_bytes_and_exact_idempotent_reinstall(self):
        result = maintenance.install(self.package, self.package_sha, self.tools)
        installed = self.tools / 'versions' / (self.package_sha + '.pyz')
        self.assertEqual(installed.read_bytes(), self.package.read_bytes())
        self.assertEqual(result['installed']['sha256'], self.package_sha)
        self.assertFalse(result['project_schemas_changed'])
        before = installed.read_bytes()
        maintenance.install(self.package, self.package_sha, self.tools)
        self.assertEqual(installed.read_bytes(), before)
        self.assertEqual(json.loads((self.tools / 'current.json').read_text())['sha256'], self.package_sha)
        self.assertTrue(list((self.tools / 'history').glob('*.json')))

    def test_external_hash_rejection_creates_no_install_state(self):
        with self.assertRaises(ProductError):
            maintenance.install(self.package, '0' * 64, self.tools)
        self.assertFalse(self.tools.exists())

    def test_interrupted_install_remains_unactivated_and_retry_can_complete(self):
        def interrupted(source, destination, *args, **kwargs):
            destination.write(source.read(64))
            destination.flush()
            raise OSError('Injected copy interruption')
        with patch.object(maintenance.shutil, 'copyfileobj', side_effect=interrupted):
            with self.assertRaises((OSError, ProductError)):
                maintenance.install(self.package, self.package_sha, self.tools)
        self.assertFalse((self.tools / 'current.json').exists())
        result = maintenance.install(self.package, self.package_sha, self.tools)
        self.assertEqual(result['installed']['sha256'], self.package_sha)
        self.assertEqual(maintenance.sha(self.tools / 'versions' / (self.package_sha + '.pyz')), self.package_sha)

    def test_modified_existing_immutable_version_is_never_overwritten(self):
        maintenance.install(self.package, self.package_sha, self.tools)
        installed = self.tools / 'versions' / (self.package_sha + '.pyz')
        installed.write_bytes(b'USER-PRESERVED-MODIFIED-FIXTURE')
        before = inventory(self.tools)
        with self.assertRaises(ProductError):
            maintenance.install(self.package, self.package_sha, self.tools)
        self.assertEqual(inventory(self.tools), before)

    def test_other_reviewed_version_is_checked_without_executing_and_can_be_reactivated(self):
        old = self.root / 'previous-reviewed.pyz'
        marker = self.root / 'UNEXPECTED-PACKAGE-EXECUTION'
        with zipfile.ZipFile(self.package) as archive:
            payload = {name: archive.read(name) for name in archive.namelist()}
        build = json.loads(payload.pop('BUILD.json'))
        older = '0.1.0' if PRODUCT_VERSION != '0.1.0' else '0.0.9'
        for name in ('__main__.py', 'shared_workspace/__init__.py'):
            payload[name] = payload[name].replace(PRODUCT_VERSION.encode(), older.encode())
        tracker = 'bundle/skills/setup-shared-project-workspace/assets/project_tracker.py'
        payload[tracker] += ('\nfrom pathlib import Path as _FixturePath\n_FixturePath(' + repr(str(marker)) + ').write_text("EXECUTED")\n').encode()
        build['product_version'] = older
        build['files'] = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
        build['bundle_id'] = hashlib.sha256(json.dumps(build['files'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        payload['BUILD.json'] = json.dumps(build).encode()
        with zipfile.ZipFile(old, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, data in payload.items():
                archive.writestr(name, data)
        old_sha = maintenance.sha(old)
        maintenance.install(old, old_sha, self.tools)
        self.assertFalse(marker.exists(), 'Installation executed package-supplied code')
        maintenance.install(self.package, self.package_sha, self.tools)
        result = maintenance.dispatch(None, argparse.Namespace(command='rollback-package', tools_dir=str(self.tools), sha256=old_sha))
        self.assertFalse(marker.exists(), 'Rollback executed package-supplied code')
        self.assertEqual(result['installed']['product_version'], older)
        self.assertEqual(json.loads((self.tools / 'current.json').read_text())['sha256'], old_sha)
        self.assertEqual((self.tools / 'versions' / (self.package_sha + '.pyz')).read_bytes(), self.package.read_bytes())

    def test_migration_plan_is_read_only_excludes_private_state_and_resolves_wikilinks(self):
        source = self.root / 'Source'; source.mkdir()
        (source / 'Notes').mkdir()
        (source / 'Notes' / 'Other.md').write_text('# Other\n')
        (source / 'Home.md').write_text('[[Notes/Other.md]] [[Other#Part|label]] [[Outside]]\n')
        (source / '.obsidian').mkdir(); (source / '.obsidian' / 'private.json').write_text('{"private":true}')
        for name in ('connection.json', 'client.json', 'snapshot.json', 'journal.json', 'state.json', 'setup-intent.json', '.setup.lock'):
            (source / name).write_text('{"private_fixture":"KEEP-OUT"}')
        (source / 'member.token').write_text('PRIVATE-CREDENTIAL-FIXTURE')
        (source / 'authority.sqlite').write_bytes(b'PRIVATE-DATABASE-FIXTURE')
        (source / 'Picture.png').write_bytes(b'\x89PNG\xff\x00')
        before = inventory(self.root)
        destination = self.root / 'Future project'
        result = maintenance.migration_plan(source, destination)
        self.assertEqual(inventory(self.root), before)
        self.assertFalse(destination.exists())
        self.assertFalse(result['apply_performed'])
        self.assertFalse(result['live_migration_authorized'])
        self.assertEqual(set(result['files']), {'Home.md', 'Notes/Other.md', 'Picture.png'})
        self.assertEqual(result['external_or_unresolved_wikilinks'], [{'path': 'Home.md', 'target': 'Outside'}])

    def test_migration_excludes_private_state_subtrees_and_preserves_missing_path_links(self):
        source = self.root / 'Source'; source.mkdir()
        (source / 'Notes').mkdir(); (source / 'Notes' / 'Other.md').write_text('# Other')
        (source / 'Home.md').write_text('[[Missing/Other.md]] [[Notes/Other.md]]')
        (source / 'client-state' / 'drafts').mkdir(parents=True)
        (source / 'client-state' / 'drafts' / 'proposal.json').write_text('{"private":"draft"}')
        (source / 'coordinator-state').mkdir()
        (source / 'coordinator-state' / 'history.json').write_text('{"private":"history"}')
        (source / 'authority.sqlite-wal').write_bytes(b'PRIVATE-WAL-FIXTURE')
        (source / 'setup-recovery').mkdir()
        (source / 'setup-recovery' / 'private.md').write_text('PRIVATE-SETUP-RECOVERY-FIXTURE')
        before = inventory(self.root)
        result = maintenance.migration_plan(source, self.root / 'Future')
        self.assertEqual(inventory(self.root), before)
        self.assertEqual(set(result['files']), {'Home.md', 'Notes/Other.md'})
        self.assertEqual(result['external_or_unresolved_wikilinks'], [{'path': 'Home.md', 'target': 'Missing/Other.md'}])

    def test_migration_graph_checks_markdown_aliases_anchors_and_ambiguity(self):
        source = self.root / 'Source'; source.mkdir()
        (source / 'A').mkdir(); (source / 'B').mkdir()
        (source / 'A' / 'Same.md').write_bytes(b'# Same\n')
        (source / 'B' / 'Same.md').write_bytes(b'# Same\n')
        (source / 'Canonical.md').write_bytes(b'---\naliases: [Shortcut]\n---\n# Present\n')
        (source / 'Home.md').write_bytes(
            b'[broken](Missing.md)\n[[Shortcut]]\n[[Same]]\n'
            b'[anchor](Canonical.md#absent)\n[[Canonical#Present]]\n'
            b'`[[CodeOnly]]`\n```md\n[ignored](Code.md)\n```\n')
        before = inventory(self.root)
        result = maintenance.migration_plan(source, self.root / 'Future')
        graph = result['link_analysis']
        by_line = {edge['line']: edge for edge in graph['edges']}
        self.assertEqual(by_line[1]['status'], 'missing')
        self.assertEqual(by_line[1]['requested_path'], 'Missing.md')
        self.assertEqual(by_line[2]['target'], 'Canonical.md')
        self.assertEqual(by_line[2]['resolution'], 'alias')
        self.assertEqual(by_line[3]['status'], 'ambiguous')
        self.assertEqual(by_line[3]['candidates'], ['A/Same.md', 'B/Same.md'])
        self.assertEqual(by_line[4]['anchor_status'], 'missing')
        self.assertEqual(by_line[5]['anchor_status'], 'resolved')
        self.assertEqual(len(by_line), 5)
        self.assertIn('alias_requires_canonical_link', {d['code'] for d in graph['diagnostics']})
        self.assertEqual(result['external_or_unresolved_wikilinks'], [{'path': 'Home.md', 'target': 'Same'}])
        self.assertEqual(inventory(self.root), before)
        self.assertFalse(result['apply_performed'])

    def test_migration_graph_reports_omitted_notes_without_exporting_private_links(self):
        source = self.root / 'Source'; source.mkdir()
        (source / 'Bad.md').write_bytes(b'\xff\xfe')
        (source / 'Home.md').write_bytes(
            b'[[https://user:private-fixture@example.invalid/key?q=secret]]\n'
            b'[[../Private.md]]\n[[credentials/Hidden]]\n[[Bad]]\n')
        (self.root / 'Private.md').write_bytes(b'PRIVATE-PARENT')
        (source / 'credentials').mkdir()
        (source / 'credentials' / 'Hidden.md').write_bytes(b'[[PRIVATE-GRAPH-MARKER]]')
        (source / 'secrets.md').write_bytes(b'PRIVATE-CREDENTIAL-NOTE')
        before = inventory(self.root)
        original_scan, original_sha = os.scandir, maintenance.sha
        def guarded_scan(path):
            self.assertNotEqual(Path(path), source / 'credentials', 'Private subtree was traversed')
            return original_scan(path)
        def guarded_sha(path):
            self.assertNotEqual(Path(path), source / 'secrets.md', 'Private note was read')
            return original_sha(path)
        with patch.object(os, 'scandir', side_effect=guarded_scan), patch.object(maintenance, 'sha', side_effect=guarded_sha):
            result = maintenance.migration_plan(source, self.root / 'Future')
        self.assertNotIn('credentials/Hidden.md', result['files'])
        self.assertNotIn('secrets.md', result['files'])
        graph = result['link_analysis']
        self.assertIn('non_utf8_note_omitted', {d['code'] for d in graph['diagnostics']})
        self.assertEqual([e['status'] for e in graph['edges']], ['external', 'outside_scope', 'excluded', 'excluded'])
        serialized = json.dumps(graph)
        for marker in ('private-fixture', 'example.invalid', 'PRIVATE-GRAPH-MARKER'):
            self.assertNotIn(marker, serialized)
        self.assertTrue(all(e['requested_path'] is None for e in graph['edges'][:3]))
        self.assertEqual(inventory(self.root), before)

    def test_migration_graph_limits_fail_without_creating_destination(self):
        from shared_workspace import knowledge
        source = self.root / 'Source'; source.mkdir()
        (source / 'Large.md').write_bytes(b'a' * (knowledge.MAX_NOTE_BYTES + 1))
        before = inventory(self.root)
        with self.assertRaises(ProductError) as raised:
            maintenance.migration_plan(source, self.root / 'Future')
        self.assertEqual(raised.exception.code, 'knowledge_limit')
        self.assertEqual(inventory(self.root), before)

    def test_migration_refuses_inventory_graph_disagreement(self):
        from shared_workspace import knowledge
        source = self.root / 'Source'; source.mkdir()
        note = source / 'Home.md'; note.write_bytes(b'# Before\n')
        original = knowledge.analyze
        def changed(**kwargs):
            note.write_bytes(b'# After\n')
            return original(**kwargs)
        with patch.object(knowledge, 'analyze', side_effect=changed):
            with self.assertRaises(ProductError) as raised:
                maintenance.migration_plan(source, self.root / 'Future')
        self.assertEqual(raised.exception.code, 'migration_source_changed')
        self.assertEqual(note.read_bytes(), b'# After\n')
        self.assertFalse((self.root / 'Future').exists())

    def test_migration_refuses_files_arriving_between_inventory_and_graph(self):
        from shared_workspace import knowledge
        for filename in ('new.png', 'unlinked.bin'):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory(dir=self.root) as directory:
                source = Path(directory) / 'Source'; source.mkdir()
                (source / 'Home.md').write_bytes(b'![image](new.png)\n')
                original = knowledge.analyze
                def changed(**kwargs):
                    (source / filename).write_bytes(b'new attachment')
                    return original(**kwargs)
                destination = Path(directory) / 'Future'
                with patch.object(knowledge, 'analyze', side_effect=changed):
                    with self.assertRaises(ProductError) as raised:
                        maintenance.migration_plan(source, destination)
                self.assertEqual(raised.exception.code, 'migration_source_changed')
                self.assertEqual((source / filename).read_bytes(), b'new attachment')
                self.assertFalse(destination.exists())

    def test_private_setup_records_cannot_enter_accepted_project_content(self):
        from shared_workspace.engine import validate_files
        for name in ('setup-intent.json', 'Nested/setup-intent.json',
                     'setup-recovery/private.md', '.setup.lock'):
            with self.subTest(path=name), self.assertRaises(ProductError):
                validate_files({name: 'PRIVATE-SETUP-FIXTURE'})

    def test_migration_rejects_existing_or_nested_destination_without_mutation(self):
        source = self.root / 'Source'; source.mkdir(); (source / 'Home.md').write_text('fixture')
        existing = self.root / 'Existing'; existing.mkdir()
        before = inventory(self.root)
        for target in (existing, source / 'Nested'):
            with self.subTest(target=target), self.assertRaises(ProductError):
                maintenance.migration_plan(source, target)
        self.assertEqual(inventory(self.root), before)

    @unittest.skipUnless(shutil.which('git'), 'Git unavailable')
    def test_git_worktree_plan_and_apply_preserve_original_dirty_checkout(self):
        repo = self.root / 'repository'; repo.mkdir()
        def git(*args):
            result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()
        git('init', '-q'); (repo / 'code.txt').write_text('committed fixture\n'); git('add', 'code.txt')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Synthetic base')
        (repo / 'code.txt').write_text('UNCOMMITTED-USER-FIXTURE\n')
        (repo / 'untracked.txt').write_text('UNTRACKED-USER-FIXTURE\n')
        status, head = git('status', '--porcelain'), git('rev-parse', 'HEAD')
        worktree = self.root / 'isolated-worktree'
        args = argparse.Namespace(repository=str(repo), worktree=str(worktree), branch='fixture-agent', base='HEAD', apply=False)
        planned = maintenance.git_isolate(args)
        self.assertFalse(planned['applied']); self.assertFalse(worktree.exists())
        args.apply = True; result = maintenance.git_isolate(args)
        self.assertTrue(result['applied']); self.assertFalse(result['uncommitted_changes_included'])
        self.assertEqual(git('status', '--porcelain'), status); self.assertEqual(git('rev-parse', 'HEAD'), head)
        self.assertEqual((repo / 'code.txt').read_text(), 'UNCOMMITTED-USER-FIXTURE\n')
        self.assertEqual((repo / 'untracked.txt').read_text(), 'UNTRACKED-USER-FIXTURE\n')
        self.assertEqual((worktree / 'code.txt').read_text(), 'committed fixture\n')
        self.assertFalse((worktree / 'untracked.txt').exists())

    @unittest.skipUnless(shutil.which('git') and os.name != 'nt', 'POSIX hook injection fixture requires Git and a shell')
    def test_git_worktree_does_not_execute_a_hook_that_changes_original_dirty_bytes(self):
        repo = self.root / 'repository'; repo.mkdir()
        def git(*args):
            result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.strip()
        git('init', '-q'); tracked = repo / 'code.txt'; tracked.write_text('base')
        git('add', 'code.txt')
        git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'Synthetic base')
        tracked.write_text('ORIGINAL-DIRTY-BYTES')
        hook = repo / '.git' / 'hooks' / 'post-checkout'
        program = 'from pathlib import Path; Path(' + repr(str(tracked)) + ').write_text("HOOK-CHANGED-DIRTY-BYTES")'
        hook.write_text('#!/bin/sh\nexec ' + shlex.quote(sys.executable) + ' -c ' + shlex.quote(program) + '\n')
        hook.chmod(0o700)
        args = argparse.Namespace(repository=str(repo), worktree=str(self.root / 'worktree'), branch='fixture-hook-test', base='HEAD', apply=True)
        maintenance.git_isolate(args)
        self.assertEqual(tracked.read_text(), 'ORIGINAL-DIRTY-BYTES')

    def test_http_transport_rejects_malformed_error_and_protocol_envelopes(self):
        token = self.root / 'private.token'; workflow.write_private(token, secrets.token_urlsafe(48))
        transport = HTTPTransport('http://127.0.0.1:1', token)
        envelopes = [
            {'protocol': True, 'ok': True, 'data': {}},
            {'protocol': 1, 'ok': False, 'exit_code': 0, 'code': 'bad', 'message': 'bad', 'data': {}},
            {'protocol': 1, 'ok': False, 'exit_code': '4', 'code': 'bad', 'message': 'bad', 'data': {}},
            {'protocol': 1, 'ok': False, 'exit_code': 4, 'code': ['bad'], 'message': 'bad', 'data': {}},
        ]
        class Response:
            def __init__(self, payload):
                self.payload = payload
                self.status = 200 if payload['ok'] else 403
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, limit): return json.dumps(self.payload).encode()
        for envelope in envelopes:
            with self.subTest(envelope=envelope), patch.object(transport.opener, 'open', return_value=Response(envelope)):
                with self.assertRaises(ProductError) as raised:
                    transport('status', {})
                self.assertEqual(raised.exception.exit_code, 3)
                self.assertEqual(raised.exception.code, 'protocol_invalid')

    def test_coordinator_backup_readback_preserves_project_snapshot_history_and_source(self):
        database = self.root / 'authority.sqlite3'; token = secrets.token_urlsafe(48)
        authority = Coordinator(database); project_id = str(uuid.uuid4())
        authority.initialize(project_id, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'}, token, {'Home.md': '# Test\n'})
        authority.request(token, 'claim', {'assignment_id': 'work', 'targets': ['Home.md'], 'criteria': ['review'],
            'dependencies': [], 'resource_limits': {'max_proposals': 2}, 'integration_owner': 'owner'})
        authority.request(token, 'propose', {'proposal_id': 'proposal', 'assignment_id': 'work', 'base_revision': 0,
            'changes': {'Home.md': '# Accepted revision\n'}, 'evidence': 'Fixture review'})
        authority.request(token, 'accept', {'proposal_id': 'proposal', 'validation': 'Verified synthetic bytes', 'reason': 'Fixture acceptance'})
        snapshot, events = authority.request(token, 'snapshot', {}), authority.request(token, 'events', {})
        destination = self.root / 'backup.sqlite3'
        result = maintenance.backup_coordinator(database, destination)
        restored = Coordinator(destination)
        self.assertEqual(restored.request(token, 'snapshot', {}), snapshot)
        self.assertEqual(restored.request(token, 'events', {}), events)
        self.assertEqual(authority.request(token, 'snapshot', {}), snapshot)
        self.assertEqual(result['backup_sha256'], maintenance.sha(destination))
        self.assertEqual(result['integrity_check'], 'ok')
        self.assertTrue(result['history_verified'])
        before = destination.read_bytes()
        with self.assertRaises(ProductError):
            maintenance.backup_coordinator(database, destination)
        self.assertEqual(destination.read_bytes(), before)

    def test_backup_rejects_wrong_identity_and_corrupt_old_history_before_creation(self):
        database = self.root / 'authority.sqlite3'; token = secrets.token_urlsafe(48)
        authority = Coordinator(database); identity = str(uuid.uuid4())
        authority.initialize(identity, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'}, token, {'Home.md': 'original'})
        target = self.root / 'backup.sqlite3'
        with self.assertRaises(ProductError):
            maintenance.backup_coordinator(database, target, str(uuid.uuid4()))
        self.assertFalse(target.exists())
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("UPDATE snapshots SET files_json=? WHERE revision=0", ('{"Home.md":"corrupt"}',))
            connection.commit()
        before = database.read_bytes()
        with self.assertRaises(ProductError):
            maintenance.backup_coordinator(database, target, identity)
        self.assertFalse(target.exists())
        self.assertEqual(database.read_bytes(), before)

    def test_backup_verifies_opt_in_coordination_history_and_private_sessions(self):
        database = self.root / 'v2.sqlite3'; token = secrets.token_urlsafe(48)
        authority = Coordinator(database); identity = str(uuid.uuid4())
        authority.initialize(identity, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'}, token, {'Home.md': 'original'},
                             coordination={'person_id': 'person', 'agent_id': 'agent', 'policy': {}})
        session_token = secrets.token_urlsafe(48)
        authority.request(token, 'session-open', {'session_id': 'run', 'token': session_token,
            'ttl_seconds': 300, 'scopes': ['policy'], 'targets': ['.']})
        before = database.read_bytes()
        target = self.root / 'v2-backup.sqlite3'
        result = maintenance.backup_coordinator(database, target, identity)
        self.assertEqual(result['schema_version'], 2)
        self.assertTrue(result['history_verified'])
        self.assertEqual(database.read_bytes(), before)
        self.assertEqual(Coordinator(target).request(session_token, 'policy', {}), authority.request(session_token, 'policy', {}))
        self.assertNotIn(session_token, json.dumps(result))

    def test_backup_never_uses_authority_sidecars_or_shared_project_directories(self):
        database = self.root / 'authority.sqlite3'; token = secrets.token_urlsafe(48)
        authority = Coordinator(database); identity = str(uuid.uuid4())
        authority.initialize(identity, {'actor': 'owner', 'human': 'Fixture', 'agent': 'Test'}, token, {'Home.md': 'original'})
        shared = self.root / 'shared'; shared.mkdir()
        (shared / '.shared-memory.json').write_text('{}')
        before = inventory(self.root)
        for target in [Path(str(database) + suffix) for suffix in ('-journal', '-wal', '-shm')] + [shared / 'backup.sqlite3']:
            with self.subTest(target=target.name), self.assertRaises(ProductError):
                maintenance.backup_coordinator(database, target, identity)
            self.assertFalse(target.exists())
        self.assertEqual(inventory(self.root), before)

    def test_selected_project_cannot_reuse_another_project_client_state(self):
        project_a, state_a, _ = self.init_project('alpha')
        project_b, state_b, _ = self.init_project('beta')
        before = inventory(project_b)
        args = argparse.Namespace(command='receipt', project=str(project_b), state_dir=str(state_a))
        with self.assertRaises(ProductError):
            workflow.dispatch(None, args)
        self.assertEqual(inventory(project_b), before)

    def test_connection_swap_cannot_mutate_a_different_authority(self):
        project_a, state_a, _ = self.init_project('alpha')
        project_b, state_b, _ = self.init_project('beta')
        (state_a / 'connection.json').write_bytes((state_b / 'connection.json').read_bytes())
        (state_a / 'member.token').write_bytes((state_b / 'member.token').read_bytes())
        token_b = (state_b / 'member.token').read_text().strip()
        authority_b = Coordinator(state_b / 'coordinator.sqlite3')
        before = authority_b.request(token_b, 'status', {})
        payload = self.root / 'claim.json'; payload.write_text(json.dumps({'assignment_id': 'wrong-authority',
            'targets': ['Home.md'], 'criteria': ['review'], 'dependencies': [], 'resource_limits': {}, 'integration_owner': 'beta'}))
        args = argparse.Namespace(command='coord', project=str(project_a), state_dir=str(state_a), operation='claim', payload_file=str(payload))
        with self.assertRaises(ProductError):
            workflow.dispatch(None, args)
        self.assertEqual(authority_b.request(token_b, 'status', {}), before)


if __name__ == '__main__':
    unittest.main(verbosity=2)
