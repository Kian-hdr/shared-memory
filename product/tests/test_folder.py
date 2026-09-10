"""Actual independent folder roots and immutable-history transport fixtures."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared_workspace import folder as module
from shared_workspace.folder import Folder
from shared_workspace.errors import ProductError


def transport(source, target):
    """Synthetic file delivery only; no server or authority substitutes."""
    for path in (source.root / '.shared-memory').rglob('*'):
        if path.is_file():
            destination = target.root / path.relative_to(source.root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and not p.is_symlink()}


class FolderTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='direct-folder-')
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()

    def create(self, name='one', files=None, **kwargs):
        root = self.base / name; root.mkdir()
        for path, text in (files or {'Note.md': 'one\ntwo\nthree\n'}).items():
            destination = root / path; destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(text.encode())
        return Folder.initialize(root, self.base / (name + '-private'), name, 'Fixture person', name + ' agent', **kwargs)

    def attach(self, owner, name='two', readonly=False):
        root = self.base / name; root.mkdir()
        shutil.copyfile(owner.root / module.MANIFEST, root / module.MANIFEST)
        shutil.copytree(owner.root / module.HISTORY, root / module.HISTORY)
        return Folder.attach(root, self.base / (name + '-private'), name, 'Fixture person', name + ' agent', owner.project_id, readonly)

    def edit(self, folder, text, path='Note.md'):
        (folder.root / path).write_bytes(text.encode())

    def text(self, folder, path='Note.md'):
        path = folder.root / path
        return path.read_bytes().decode() if path.exists() else None

    def exchange(self, left, right):
        transport(left, right); transport(right, left)
        a = left.sync(); b = right.sync()
        transport(left, right); transport(right, left)
        return left.sync(), right.sync()

    def test_initialization_exact_bytes_private_state_and_idempotent_resume(self):
        one = self.create(files={'Note.md': '世界\r\nMixed\nlast\rno-newline'})
        before = inventory(one.root)
        again = Folder.initialize(one.root, one.state, 'one', 'Fixture person', 'one agent')
        self.assertEqual(again.project_id, one.project_id)
        self.assertEqual(again.status()['readiness'], 'ready')
        self.assertEqual(inventory(one.root), before)
        self.assertEqual(self.text(one), '世界\r\nMixed\nlast\rno-newline')
        self.assertFalse(any(p.suffix == '.sqlite3' for p in one.root.rglob('*')))

    def test_nextcloud_binding_and_unverified_delivery(self):
        one = self.create(provider='nextcloud')
        self.assertEqual(one.status()['provider'], 'nextcloud')
        self.assertEqual(one.status()['provider_delivery'], 'unverified')

    def test_offline_disjoint_edits_merge_and_converge_without_pingpong(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'ONE\ntwo\nthree\n'); self.edit(two, 'one\ntwo\nTHREE\n')
        one.sync(); two.sync()
        a, b = self.exchange(one, two)
        self.assertEqual(self.text(one), 'ONE\ntwo\nTHREE\n')
        self.assertEqual(self.text(two), self.text(one))
        self.assertEqual(a['history_hash'], b['history_hash'])
        count = a['event_count']
        self.assertEqual(one.sync()['event_count'], count)
        self.assertEqual(two.sync()['event_count'], count)
        self.assertEqual(a['readiness'], 'ready')

    def test_capture_precedes_incoming_history_and_keeps_offline_parent(self):
        one = self.create(); two = self.attach(one)
        initial = two.status()['heads']['Note.md']
        self.edit(two, 'offline\ntwo\nthree\n')
        self.edit(one, 'remote\ntwo\nthree\n'); one.sync(); transport(one, two)
        result = two.sync()
        observed = [e for e in two.history()['events'] if e['author']['actor'] == 'two']
        self.assertEqual(observed[0]['parents']['Note.md'], initial)
        self.assertTrue(result['conflicts'])
        self.assertEqual(self.text(two), 'offline\ntwo\nthree\n')

    def test_conflict_heads_and_reports_converge_then_any_editor_resolves(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'left\n'); self.edit(two, 'right\n')
        one.sync(); two.sync(); a, b = self.exchange(one, two)
        self.assertEqual(a['conflicts'], b['conflicts'])
        self.assertEqual(self.text(one), 'left\n'); self.assertEqual(self.text(two), 'right\n')
        report = one.root / a['conflicts'][0]['report']
        self.assertTrue(report.is_file())
        self.assertEqual(report.read_bytes(), (two.root / b['conflicts'][0]['report']).read_bytes())
        two.resolve('Note.md', 'Reviewed combined answer\n', 'Compared both original versions with the supplied source')
        a, b = self.exchange(one, two)
        self.assertEqual(a['conflicts'], []); self.assertEqual(b['conflicts'], [])
        self.assertEqual(self.text(one), 'Reviewed combined answer\n')
        versions = [e['changes']['Note.md'] for e in one.history('Note.md')['events']]
        self.assertIn('left\n', versions); self.assertIn('right\n', versions)
        with self.assertRaises(ProductError):
            two.resolve('Note.md', 'x', '')

    def test_missing_file_is_not_delete_and_explicit_delete_is_durable(self):
        one = self.create(); before = one.status()['event_count']
        (one.root / 'Note.md').unlink()
        result = one.sync()
        self.assertEqual(result['event_count'], before)
        self.assertEqual(result['missing_files'], ['Note.md'])
        self.assertIsNone(self.text(one))
        result = one.delete('Note.md', 'Deliberately remove the selected note')
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(one.delete('Note.md', 'Retry removal')['event_count'], result['event_count'])
        self.assertTrue(any(e['kind'] == 'delete' for e in one.history()['events']))

    def test_delete_edit_race_preserves_both_and_can_resolve(self):
        one = self.create(); two = self.attach(one)
        one.delete('Note.md', 'Remove explicitly')
        self.edit(two, 'offline edited version\n'); two.sync()
        a, b = self.exchange(one, two)
        self.assertTrue(a['conflicts']); self.assertEqual(a['conflicts'], b['conflicts'])
        self.assertIsNone(self.text(one)); self.assertEqual(self.text(two), 'offline edited version\n')
        one.resolve('Note.md', 'offline edited version\n', 'Keep the offline work after reviewing the deletion')
        a, b = self.exchange(one, two)
        self.assertEqual(self.text(one), self.text(two)); self.assertFalse(a['conflicts'])

    def test_rename_single_event_preserves_source_and_retries(self):
        one = self.create(); two = self.attach(one)
        original = self.text(one)
        result = one.rename('Note.md', 'Archive/Moved.md', 'Move the note explicitly')
        self.assertIsNone(self.text(one)); self.assertEqual(self.text(one, 'Archive/Moved.md'), original)
        self.assertEqual(one.rename('Note.md', 'Archive/Moved.md', 'Move the note explicitly')['event_count'], result['event_count'])
        a, b = self.exchange(one, two)
        self.assertIsNone(self.text(two)); self.assertEqual(self.text(two, 'Archive/Moved.md'), original)
        event = [e for e in one.history()['events'] if e['kind'] == 'rename'][0]
        self.assertEqual(event['changes'], {'Note.md': None, 'Archive/Moved.md': original})

    def test_rename_edit_race_is_visible_not_lost(self):
        one = self.create(); two = self.attach(one)
        one.rename('Note.md', 'Moved.md', 'Move note')
        self.edit(two, 'Offline work on old name\n'); two.sync()
        a, b = self.exchange(one, two)
        self.assertEqual(a['conflicts'][0]['path'], 'Note.md')
        self.assertEqual(self.text(two), 'Offline work on old name\n')
        self.assertTrue((two.root / 'Moved.md').exists())

    def test_missing_parent_defers_without_rolling_back_visible_file(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'version one\n'); one.sync()
        parent = one.status()['heads']['Note.md'][0]
        self.edit(one, 'version two\n'); one.sync()
        child = one.status()['heads']['Note.md'][0]
        shutil.copyfile(one.shared / 'events' / (child + '.json'), two.shared / 'events' / (child + '.json'))
        original = self.text(two)
        result = two.sync()
        self.assertTrue(result['deferred_events']); self.assertEqual(self.text(two), original)
        shutil.copyfile(one.shared / 'events' / (parent + '.json'), two.shared / 'events' / (parent + '.json'))
        result = two.sync()
        self.assertEqual(result['deferred_events'], [])
        self.assertEqual(self.text(two), 'version two\n')
        self.assertEqual(two.sync()['event_count'], result['event_count'])

    def test_incomplete_history_file_defers_and_retry_recovers(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'next\n'); one.sync(); newest = one.status()['heads']['Note.md'][0]
        destination = two.shared / 'events' / (newest + '.json')
        destination.write_bytes(b'{"partial":')
        result = two.sync()
        self.assertTrue(result['invalid_events']); self.assertEqual(self.text(two), 'one\ntwo\nthree\n')
        shutil.copyfile(one.shared / 'events' / (newest + '.json'), destination)
        self.assertEqual(two.sync()['readiness'], 'ready'); self.assertEqual(self.text(two), 'next\n')

    def test_partial_utf8_local_write_is_not_captured_or_replaced(self):
        one = self.create(); before = one.status()['event_count']
        (one.root / 'Note.md').write_bytes(b'\xf0\x9f')
        result = one.sync()
        self.assertEqual(result['event_count'], before)
        self.assertEqual(result['partial_files'], ['Note.md'])
        self.assertEqual((one.root / 'Note.md').read_bytes(), b'\xf0\x9f')

    def test_stable_read_checks_detect_changed_inode_stamp(self):
        path = self.base / 'text'; path.write_bytes(b'original')
        original = module.os.fstat; calls = []
        def changed(fd):
            result = original(fd); calls.append(1)
            if len(calls) == 2:
                class Different:
                    st_dev = result.st_dev; st_ino = result.st_ino; st_size = result.st_size
                    st_mtime_ns = result.st_mtime_ns + 1; st_ctime_ns = result.st_ctime_ns
                return Different()
            return result
        with patch.object(module.os, 'fstat', changed):
            with self.assertRaises(ProductError) as failure:
                module.read_bytes(path)
        self.assertEqual(failure.exception.code, 'folder_partial_file')

    def test_scope_private_trees_nested_coordination_and_binary_not_copied(self):
        root = self.base / 'one'; root.mkdir()
        originals = {'Note.md': b'# Note\n', '.env': b'PRIVATE_MARKER', '.codex/history.jsonl': b'PRIVATE_MARKER',
                     'Sub/Coordination/work.md': b'PRIVATE_MARKER', 'secrets/notes.md': b'PRIVATE_MARKER', 'image.png': b'\x00\xff'}
        for name, value in originals.items():
            path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(value)
        one = Folder.initialize(root, self.base / 'private', 'a', 'Person', 'Agent')
        self.assertEqual(one.status()['readiness'], 'ready')
        for name, value in originals.items(): self.assertEqual((root / name).read_bytes(), value)
        self.assertFalse(any(b'PRIVATE_MARKER' in p.read_bytes() for p in one.state.rglob('*') if p.is_file()))
        self.assertFalse(any(b'PRIVATE_MARKER' in p.read_bytes() for p in one.shared.rglob('*') if p.is_file()))

    def test_previously_imported_nonmarkdown_remains_managed(self):
        one = self.create(files={'Note.md': '# Note\n', 'data.txt': 'original'}, initial_files={'Note.md': '# Note\n', 'data.txt': 'original'})
        self.edit(one, 'updated', 'data.txt'); one.sync()
        self.assertEqual(one.history('data.txt')['events'][-1]['changes']['data.txt'], 'updated')

    def test_migration_initial_base_preserves_divergent_current_content(self):
        one = self.create(files={'Note.md': 'newer working content\r\n'}, initial_files={'Note.md': 'older accepted content\n'})
        self.assertEqual(self.text(one), 'newer working content\r\n')
        values = [e['changes']['Note.md'] for e in one.history()['events']]
        self.assertIn('older accepted content\n', values); self.assertIn('newer working content\r\n', values)

    def test_readonly_status_history_no_mutation_and_edit_operations_refused(self):
        one = self.create(); two = self.attach(one, readonly=True)
        before = inventory(self.base)
        two.status(); two.history()
        for call in (two.sync, lambda: two.resolve('Note.md', 'x', 'why'), lambda: two.delete('Note.md', 'why'), lambda: two.rename('Note.md', 'Other.md', 'why')):
            with self.assertRaises(ProductError) as failure: call()
            self.assertEqual(failure.exception.code, 'folder_readonly')
        self.assertEqual(inventory(self.base), before)

    def test_wrong_identity_private_inside_and_symlinks_refused(self):
        one = self.create(); root = self.base / 'other'; root.mkdir()
        shutil.copyfile(one.root / module.MANIFEST, root / module.MANIFEST)
        with self.assertRaises(ProductError): Folder.attach(root, self.base / 'private2', 'b', 'B', 'Agent', 'wrong')
        self.assertFalse((self.base / 'private2').exists())
        with self.assertRaises(ProductError): Folder(root, root / 'private')
        unsafe = self.base / 'unsafe'; unsafe.mkdir(); (unsafe / 'Note.md').symlink_to(one.root / 'Note.md')
        with self.assertRaises(ProductError): Folder.initialize(unsafe, self.base / 'unsafe-state', 'a', 'A', 'Agent')
        self.assertFalse((self.base / 'unsafe-state').exists())

    def test_provider_conflict_copy_is_distinct_preserved_note(self):
        one = self.create()
        self.edit(one, 'provider divergent copy\n', 'Note (conflicted copy).md')
        result = one.sync()
        self.assertEqual(result['provider_conflict_copies'], ['Note (conflicted copy).md'])
        self.assertIn('Note (conflicted copy).md', result['heads'])
        self.assertEqual(self.text(one), 'one\ntwo\nthree\n')

    def test_real_process_crash_initialization_and_attach_resume(self):
        for route in ('initialize', 'attach'):
            with self.subTest(route=route):
                root = self.base / ('crash-' + route); root.mkdir(); state = self.base / ('state-' + route)
                if route == 'initialize': (root / 'Note.md').write_bytes(b'Keep exact bytes\r\n')
                else:
                    owner = self.create('attach-owner')
                    shutil.copyfile(owner.root / module.MANIFEST, root / module.MANIFEST)
                    shutil.copytree(owner.shared, root / module.HISTORY)
                code = '''import os,sys\nfrom pathlib import Path\nfrom shared_workspace import folder as m\nold=m.atomic\ndef interrupted(path,data,immutable=False):\n old(path,data,immutable)\n if Path(path).name == sys.argv[4]: os._exit(81)\nm.atomic=interrupted\nroot,state=Path(sys.argv[1]),Path(sys.argv[2])\nif sys.argv[3]=='initialize': m.Folder.initialize(root,state,'crash','Person','Agent')\nelse: m.Folder.attach(root,state,'crash','Person','Agent',m.parse(m.read_bytes(root/m.MANIFEST))['project_id'])\n'''
                env = dict(os.environ, PYTHONPATH=str(Path(module.__file__).parents[1]))
                result = subprocess.run([sys.executable, '-c', code, str(root), str(state), route,
                                         module.MANIFEST if route == 'initialize' else 'folder.json'], env=env, capture_output=True)
                self.assertEqual(result.returncode, 81, result.stderr)
                if route == 'initialize': ready = Folder.initialize(root, state, 'crash', 'Person', 'Agent')
                else: ready = Folder.attach(root, state, 'crash', 'Person', 'Agent', owner.project_id)
                self.assertEqual(ready.status()['readiness'], 'ready')

    def test_crash_after_evacuating_file_preserves_post_crash_edit(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'remote revision\n'); one.sync(); transport(one, two)
        code = '''import os,sys\nfrom pathlib import Path\nfrom shared_workspace import folder as m\nold=m.os.rename\ndef stop(src,dst):\n old(src,dst)\n if Path(dst).name.startswith('.folder-old-'): os._exit(82)\nm.os.rename=stop\nm.Folder(sys.argv[1],sys.argv[2]).sync()\n'''
        env = dict(os.environ, PYTHONPATH=str(Path(module.__file__).parents[1]))
        result = subprocess.run([sys.executable, '-c', code, str(two.root), str(two.state)], env=env, capture_output=True)
        self.assertEqual(result.returncode, 82, result.stderr)
        self.assertTrue((two.state / 'journal.json').exists())
        self.edit(two, 'new local edit after crash\n')
        reopened = Folder(two.root, two.state); result = reopened.sync()
        self.assertEqual(self.text(two), 'new local edit after crash\n')
        self.assertTrue(result['conflicts'])
        values = [e['changes']['Note.md'] for e in reopened.history()['events']]
        self.assertIn('new local edit after crash\n', values); self.assertIn('remote revision\n', values)

    def test_new_file_race_never_overwrites_racing_editor(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'remote\n', 'New.md'); one.sync(); transport(one, two)
        original = module.os.link; injected = []
        def race(src, dst, *args, **kwargs):
            if Path(dst) == two.root / 'New.md' and not injected:
                injected.append(1); Path(dst).write_bytes(b'RACING EDITOR\n')
            return original(src, dst, *args, **kwargs)
        with patch.object(module.os, 'link', race): result = two.sync()
        self.assertEqual(self.text(two, 'New.md'), 'RACING EDITOR\n')
        self.assertEqual(result['readiness'], 'partial')
        again = two.sync()
        self.assertTrue(again['conflicts'])


    def test_valid_provider_event_copies_deduplicate_or_keep_distinct_content(self):
        one = self.create(); two = self.attach(one)
        self.edit(one, 'new provider text\n'); one.sync()
        head = one.status()['heads']['Note.md'][0]
        content = (one.shared / 'events' / (head + '.json')).read_bytes()
        copies = [two.shared / 'events' / ('history (conflicted copy).json'), two.shared / 'events' / 'second-copy.json']
        for path in copies: path.write_bytes(content)
        result = two.sync()
        self.assertEqual(result['readiness'], 'ready')
        self.assertEqual(result['event_count'], 2)
        self.assertEqual(len(result['history_copies']), 2)
        self.assertEqual(self.text(two), 'new provider text\n')
        self.assertEqual(two.sync()['event_count'], 2)
        for path in copies: self.assertEqual(path.read_bytes(), content)

    def test_required_private_subtree_does_not_import_siblings(self):
        files = {'Note.md': '# Public\n', 'Coordination/Kept.md': 'Imported existing record\n',
                 'Coordination/Private.md': 'PRIVATE_SIBLING', 'Coordination/Nested/Secret.md': 'PRIVATE_SIBLING'}
        one = self.create(files=files, initial_files={k: v for k, v in files.items() if 'PRIVATE_SIBLING' not in v})
        result = one.status()
        self.assertEqual(result['readiness'], 'ready')
        self.assertNotIn('Coordination/Private.md', result['heads'])
        self.assertNotIn('Coordination/Nested/Secret.md', result['heads'])
        self.assertFalse(any(b'PRIVATE_SIBLING' in p.read_bytes() for p in one.state.rglob('*') if p.is_file()))

    def test_file_readonly_blocks_explicit_changes_and_incoming_replacement(self):
        one = self.create(); two = self.attach(one)
        path = two.root / 'Note.md'; path.chmod(0o444)
        self.addCleanup(lambda: path.chmod(0o644) if path.exists() else None)
        before = inventory(two.root)
        for call in (lambda: two.delete('Note.md', 'remove'), lambda: two.rename('Note.md', 'Other.md', 'move'),
                     lambda: two.resolve('Note.md', 'replace', 'reason')):
            with self.assertRaises(ProductError) as failure: call()
            self.assertEqual(failure.exception.code, 'folder_readonly_file')
        self.assertEqual(inventory(two.root), before)
        self.edit(one, 'new remote text\n'); one.sync(); transport(one, two)
        result = two.sync()
        self.assertEqual(self.text(two), 'one\ntwo\nthree\n')
        self.assertEqual(result['readiness'], 'partial')
        self.assertEqual(path.stat().st_mode & 0o777, 0o444)
        path.chmod(0o640); two.sync()
        self.assertEqual(self.text(two), 'new remote text\n')
        if os.name != 'nt': self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_corrupt_baseline_or_journal_never_materializes(self):
        one = self.create()
        original = (one.state / 'baseline.json').read_bytes()
        value = json.loads(original); value['paths']['Note.md']['text'] = 'corruption'
        (one.state / 'baseline.json').write_text(json.dumps(value))
        before = inventory(one.root)
        with self.assertRaises(ProductError): one.sync()
        self.assertEqual(inventory(one.root), before)
        (one.state / 'baseline.json').write_bytes(original)
        (one.state / 'journal.json').write_text(json.dumps({'format': 1, 'project_id': one.project_id, 'operations': {}, 'checksum': 'bad'}))
        with self.assertRaises(ProductError) as failure: one.sync()
        self.assertEqual(failure.exception.code, 'folder_journal_invalid')
        self.assertEqual(inventory(one.root), before)

    def test_concurrent_portable_case_collision_preserves_local_path(self):
        one = self.create(files={'Home.md': '# Home\n'}); two = self.attach(one)
        self.edit(one, 'first\n', 'Note.md'); self.edit(two, 'second\n', 'note.md')
        one.sync(); two.sync(); transport(one, two); transport(two, one)
        before_one = self.text(one, 'Note.md'); before_two = self.text(two, 'note.md')
        a, b = one.sync(), two.sync()
        self.assertTrue(a['path_collisions']); self.assertTrue(b['path_collisions'])
        self.assertEqual(self.text(one, 'Note.md'), before_one); self.assertEqual(self.text(two, 'note.md'), before_two)
        self.assertEqual(a['readiness'], 'partial')

    def test_resolution_retry_has_no_extra_event(self):
        one = self.create(); one.resolve('Note.md', 'reviewed\n', 'Reviewed sources')
        count = one.status()['event_count']
        self.assertEqual(one.resolve('Note.md', 'reviewed\n', 'Reviewed sources')['event_count'], count)

    def test_compatible_merge_bound_retains_large_full_versions_as_conflict(self):
        text = ''.join(str(i) + '\n' for i in range(2100))
        one = self.create(files={'Note.md': text}); two = self.attach(one)
        self.edit(one, text.replace('0\n', 'FIRST\n', 1)); self.edit(two, text + 'LAST\n')
        one.sync(); two.sync(); a, b = self.exchange(one, two)
        self.assertTrue(a['conflicts'])
        self.assertTrue(self.text(one).startswith('FIRST\n'))
        self.assertTrue(self.text(two).endswith('LAST\n'))


    def test_concurrent_renames_report_intent_and_acknowledge_without_rewrites(self):
        for operation in ('resolve', 'delete'):
            with self.subTest(operation=operation):
                one = self.create('rename-one-' + operation)
                two = self.attach(one, 'rename-two-' + operation)
                original = self.text(one)
                one.rename('Note.md', 'DifferentA.md', 'Choose A')
                two.rename('Note.md', 'DifferentB.md', 'Choose B')
                a, b = self.exchange(one, two)
                self.assertEqual(a['readiness'], 'ready')
                self.assertEqual(a['conflicts'], [])
                self.assertEqual(a['rename_divergences'], b['rename_divergences'])
                divergence = a['rename_divergences'][0]
                self.assertEqual(divergence['source'], 'Note.md')
                self.assertEqual(divergence['destinations'], ['DifferentA.md', 'DifferentB.md'])
                self.assertEqual(len(divergence['event_ids']), 2)
                self.assertEqual(a['warnings'][0]['code'], 'rename_intent_divergence')
                for device in (one, two):
                    self.assertEqual(self.text(device, 'DifferentA.md'), original)
                    self.assertEqual(self.text(device, 'DifferentB.md'), original)
                    before = inventory(device.root)
                    count = device.status()['event_count']
                    self.assertEqual(device.sync()['event_count'], count)
                    self.assertEqual(inventory(device.root), before)
                if operation == 'resolve':
                    two.resolve('Note.md', None, 'Reviewed both destinations; deliberately retain both copies')
                else:
                    two.delete('Note.md', 'Reviewed both destinations; retain both and keep source removed')
                a, b = self.exchange(one, two)
                self.assertEqual(a['rename_divergences'], [])
                self.assertEqual(b['rename_divergences'], [])
                self.assertEqual(a['warnings'], [])
                self.assertEqual(self.text(one, 'DifferentA.md'), original)
                self.assertEqual(self.text(one, 'DifferentB.md'), original)


    def test_readonly_destination_keeps_journal_and_post_crash_old_inode(self):
        one = self.create('readonly-source'); two = self.attach(one, 'readonly-recipient')
        self.edit(one, 'incoming replacement\n'); one.sync(); transport(one, two)
        class Interrupted(Exception): pass
        original = module.os.rename
        def interrupt(source, destination):
            original(source, destination)
            if Path(destination).name.startswith('.folder-old-'):
                raise Interrupted()
        with patch.object(module.os, 'rename', interrupt):
            with self.assertRaises(Interrupted): two.sync()
        journal_path = two.state / 'journal.json'
        journal = json.loads(journal_path.read_bytes())
        evacuated = two.root / journal['operations']['Note.md']['evacuated']
        old_edit = b'UNIQUE POST-CRASH OLD-INODE EDIT\n'
        evacuated.write_bytes(old_edit)
        path = two.root / 'Note.md'
        visible = b'KEEP VISIBLE READONLY CONTENT\n'
        path.write_bytes(visible); path.chmod(0o444)
        self.addCleanup(lambda: path.chmod(0o644) if path.exists() else None)
        reopened = Folder(two.root, two.state)
        first = reopened.sync()
        self.assertTrue(first['recovery_pending'])
        self.assertEqual(first['readiness'], 'partial')
        self.assertTrue(journal_path.is_file()); self.assertTrue(evacuated.is_file())
        self.assertEqual(path.read_bytes(), visible)
        self.assertTrue(any(p.read_bytes() == old_edit for p in (two.state / 'backups').iterdir()))
        changes = [e['changes'].get('Note.md') for e in reopened.history()['events']]
        self.assertIn(old_edit.decode(), changes)
        self.assertIn(visible.decode(), changes)
        second = reopened.sync()
        self.assertEqual(second['event_count'], first['event_count'])
        self.assertEqual(path.read_bytes(), visible)
        self.assertTrue(journal_path.exists())
        path.chmod(0o644)
        finished = reopened.sync()
        self.assertFalse(journal_path.exists())
        self.assertFalse(evacuated.exists())
        self.assertEqual(path.read_bytes(), visible)
        self.assertTrue(finished['conflicts'])
        reopened.resolve('Note.md', visible.decode(), 'Reviewed all retained post-crash variants')
        self.assertEqual(reopened.status()['readiness'], 'ready')


    def test_known_nextcloud_state_directory_is_refused_before_writes(self):
        root = self.base / 'local-project'; root.mkdir()
        (root / 'Note.md').write_bytes(b'# Existing note\n')
        state = self.base / 'Nextcloud/private-state'
        with self.assertRaises(ProductError) as failure:
            Folder.initialize(root, state, 'owner', 'Person', 'Agent')
        self.assertEqual(failure.exception.code, 'folder_private_path')
        self.assertFalse(state.exists())
        self.assertFalse((root / module.MANIFEST).exists())


    def test_stable_read_accepts_stable_cross_api_timestamp_differences(self):
        from types import SimpleNamespace
        path = self.base / 'windows-stat.bin'
        content = b'CRLF\r\nMixed\nCtrlZ\x1aExact'
        path.write_bytes(content)
        original = module.os.fstat
        def descriptor_metadata(fd):
            info = original(fd)
            # Windows path stat may expose creation-time ctime while fstat
            # exposes metadata-change time. Compare each API with itself.
            return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino, st_mode=info.st_mode,
                                   st_size=info.st_size, st_mtime_ns=info.st_mtime_ns + 17,
                                   st_ctime_ns=info.st_ctime_ns + 10_000_000_000)
        with patch.object(module.os, 'fstat', descriptor_metadata):
            self.assertEqual(module.read_bytes(path), content)

    def test_stable_read_rejects_real_replacement_between_path_check_and_open(self):
        path = self.base / 'replace-during-read.txt'; path.write_bytes(b'original')
        replacement = self.base / 'replacement.txt'; replacement.write_bytes(b'replaced')
        before = path.stat()
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        original = module.os.open
        changed = []
        def replace_before_open(name, flags, *args, **kwargs):
            if Path(name) == path and not changed:
                changed.append(True); os.replace(replacement, path)
            return original(name, flags, *args, **kwargs)
        with patch.object(module.os, 'open', replace_before_open):
            with self.assertRaises(ProductError) as failure:
                module.read_bytes(path)
        self.assertEqual(failure.exception.code, 'folder_partial_file')
        self.assertEqual(path.read_bytes(), b'replaced')

    def test_stable_read_rejects_actual_inplace_write_during_read(self):
        path = self.base / 'inplace.txt'; path.write_bytes(b'original')
        before = path.stat(); original = module.os.fstat; calls = []
        def edit_before_after_stat(fd):
            calls.append(True)
            if len(calls) == 2:
                path.write_bytes(b'MODIFIED')
                os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 2_000_000_000))
            return original(fd)
        with patch.object(module.os, 'fstat', edit_before_after_stat):
            with self.assertRaises(ProductError) as failure:
                module.read_bytes(path)
        self.assertEqual(failure.exception.code, 'folder_partial_file')
        self.assertEqual(path.read_bytes(), b'MODIFIED')

    def test_stable_read_explicitly_requests_binary_descriptor(self):
        path = self.base / 'binary.txt'; content = b'one\r\ntwo\x1athree\r'
        path.write_bytes(content)
        original = module.os.open
        binary_flag = getattr(module.os, 'O_BINARY', 0x40000000)
        observed = []
        def capture_flags(name, flags, *args, **kwargs):
            observed.append(flags)
            forwarded = flags if os.name == 'nt' else flags & ~binary_flag
            return original(name, forwarded, *args, **kwargs)
        with patch.object(module.os, 'O_BINARY', binary_flag, create=True), patch.object(module.os, 'open', capture_flags):
            self.assertEqual(module.read_bytes(path), content)
        self.assertTrue(observed[0] & binary_flag)


if __name__ == '__main__': unittest.main()
