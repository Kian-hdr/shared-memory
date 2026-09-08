"""Packaged init/join restart tests with real subprocess death and private state.

Faults are installed only inside these disposable test subprocesses. The runtime
has no environment-controlled crash hooks. No live project or provider is used.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch
import time
import unittest

REPO = Path(__file__).resolve().parents[2]


def crash_worker(package, boundary, arguments):
    sys.path.insert(0, package)
    from shared_workspace import workflow, cli
    from shared_workspace.client import Client
    from shared_workspace.engine import Coordinator
    original_json = workflow._publish_setup_json
    original_bytes = workflow._publish_setup_bytes
    original_initialize = Coordinator.initialize
    original_event = Coordinator._event
    original_write = Client._write_project
    original_link = os.link

    def stop():
        os._exit(83)

    def publish_json(path, value):
        name = Path(path).name
        if boundary == 'before-intent' and name == workflow.SETUP_INTENT:
            stop()
        if boundary == 'before-manifest' and name == workflow.MANIFEST:
            stop()
        if boundary == 'hold-manifest' and name == workflow.MANIFEST:
            state = Path(arguments[arguments.index('--state-dir') + 1])
            (state / '.setup-write-root-reservation-waiting').write_bytes(b'waiting')
            deadline = time.monotonic() + 20
            while not (state / '.setup-write-root-reservation-release').exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError('Fixture root reservation release did not arrive')
                time.sleep(0.02)
        if boundary == 'hold-intent' and name == workflow.SETUP_INTENT:
            # Parent observes this private marker, then tries a competing setup.
            (Path(path).parent / '.setup-write-test-holder').write_bytes(b'lock held')
            time.sleep(30)
        result = original_json(path, value)
        if boundary == 'after-intent' and name == workflow.SETUP_INTENT:
            stop()
        if boundary == 'after-manifest' and name == workflow.MANIFEST:
            stop()
        return result

    def publish_bytes(path, value):
        result = original_bytes(path, value)
        if boundary == 'after-credential' and Path(path).name == 'member.token':
            stop()
        return result

    def initialize(self, *args, **kwargs):
        result = original_initialize(self, *args, **kwargs)
        if boundary == 'after-authority':
            stop()
        return result

    def event(self, connection, actor, operation, payload, revision):
        result = original_event(self, connection, actor, operation, payload, revision)
        if boundary == 'inside-authority' and operation == 'initialize':
            stop()
        return result

    def write(self, *args, **kwargs):
        result = original_write(self, *args, **kwargs)
        if boundary == 'after-project-write':
            stop()
        return result

    def link(source, destination, *args, **kwargs):
        result = original_link(source, destination, *args, **kwargs)
        if boundary == 'after-authority-publish' and Path(destination).name == 'coordinator.sqlite3':
            stop()
        return result

    workflow._publish_setup_json = publish_json
    workflow._publish_setup_bytes = publish_bytes
    Coordinator.initialize = initialize
    Coordinator._event = event
    Client._write_project = write
    os.link = link
    raise SystemExit(cli.main(['--bundle', package, *arguments]))


class SetupRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory(prefix='shared-memory-setup-package-')
        cls.addClassCleanup(cls.build_temp.cleanup)
        cls.package = Path(cls.build_temp.name).resolve() / 'reviewed.pyz'
        built = subprocess.run([sys.executable, str(REPO / 'scripts/build_product.py'), '--output', str(cls.package)],
                               cwd=REPO, capture_output=True, text=True)
        if built.returncode:
            raise AssertionError('Package build failed: ' + built.stdout + built.stderr)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='shared-memory-setup-recovery-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def fixture(self, name):
        vault = self.root / name; vault.mkdir()
        (vault / 'Private.md').write_bytes(b'PRIVATE-PARENT-PRESERVED\n')
        project = vault / 'Selected'; project.mkdir()
        (project / 'Home.md').write_bytes(b'# Original accepted source\n')
        return project, self.root / (name + '-private-state')

    def init_args(self, project, state):
        return ['init', str(project), '--state-dir', str(state), '--person', 'Fixture Owner', '--actor', 'owner',
                '--agent', 'Test', '--purpose', 'Preserve exact original source', '--provider', 'local']

    def run_cli(self, arguments, expected=0):
        result = subprocess.run([sys.executable, str(self.package), *arguments], cwd=REPO,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(len(result.stdout.splitlines()), 1, result.stdout)
        value = json.loads(result.stdout)
        self.assertEqual(value['ok'], expected == 0)
        return value

    def crash(self, boundary, arguments):
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--crash-worker', str(self.package),
                                 boundary, json.dumps(arguments)], cwd=REPO, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 83, result.stdout + result.stderr)
        self.assertEqual(result.stdout, '')

    def coordinator(self, project, state, operation, payload=None):
        args = ['coord', str(project), '--state-dir', str(state), operation]
        if payload is not None:
            path = self.root / ('payload-' + str(time.time_ns()) + '.json')
            path.write_bytes(json.dumps(payload).encode('utf-8'))
            args += ['--payload-file', str(path)]
        return self.run_cli(args)['data']

    def assert_private(self, project, state):
        token = (state / 'member.token').read_bytes().strip()
        for path in project.rglob('*'):
            if path.is_file():
                self.assertNotIn(token, path.read_bytes(), path.name)
        self.assertEqual((project.parent / 'Private.md').read_bytes(), b'PRIVATE-PARENT-PRESERVED\n')

    def test_init_hard_exit_boundaries_resume_exact_identity_token_and_source_snapshot(self):
        boundaries = ['before-intent', 'after-intent', 'after-credential', 'inside-authority',
                      'after-authority', 'after-authority-publish', 'after-project-write', 'before-manifest', 'after-manifest']
        for boundary in boundaries:
            with self.subTest(boundary=boundary):
                project, state = self.fixture(boundary)
                args = self.init_args(project, state)
                self.crash(boundary, args)
                intent_path = state / 'setup-intent.json'
                original_intent = intent_path.read_bytes() if intent_path.exists() else None
                existing_token = (state / 'member.token').read_bytes() if (state / 'member.token').exists() else None
                if original_intent:
                    (project / 'Home.md').write_bytes(b'POST-INTERRUPTION-USER-EDIT\r\n')
                finished = self.run_cli(args)['data']
                self.assertEqual(finished['receipt']['readiness'], 'ready')
                self.assertEqual(finished['receipt']['revision'], 0)
                snapshot = self.coordinator(project, state, 'snapshot')
                self.assertEqual(snapshot['files']['Home.md'].encode('utf-8'), b'# Original accepted source\n')
                if original_intent:
                    intent = json.loads(original_intent)
                    self.assertEqual(finished['project_id'], intent['project_id'])
                    self.assertEqual(intent_path.read_bytes(), original_intent)
                    self.assertTrue(any(b'POST-INTERRUPTION-USER-EDIT' in p.read_bytes()
                                        for p in (state / 'client' / 'drafts').glob('*.json')))
                if existing_token:
                    self.assertEqual((state / 'member.token').read_bytes(), existing_token)
                self.assertEqual((project / 'Home.md').read_bytes(), b'# Original accepted source\n')
                self.assert_private(project, state)

    def test_attach_hard_exit_boundaries_resume_same_membership_and_preserve_edits(self):
        owner, owner_state = self.fixture('owner')
        initialized = self.run_cli(self.init_args(owner, owner_state))['data']
        incoming = self.root / 'recipient.token'
        self.run_cli(['member-add', str(owner), '--state-dir', str(owner_state), '--actor', 'recipient',
                      '--person', 'Fixture Recipient', '--agent', 'Test', '--token-output', str(incoming)])
        original_snapshot = self.coordinator(owner, owner_state, 'snapshot')
        for boundary in ('before-intent', 'after-intent', 'after-credential', 'after-project-write', 'before-manifest', 'after-manifest'):
            with self.subTest(boundary=boundary):
                project, state = self.fixture('recipient-' + boundary)
                args = ['attach', str(project), '--state-dir', str(state), '--expected-project-id', initialized['project_id'],
                        '--database', str(owner_state / 'coordinator.sqlite3'), '--token-file', str(incoming), '--provider', 'local']
                self.crash(boundary, args)
                intent_path = state / 'setup-intent.json'
                original_intent = intent_path.read_bytes() if intent_path.exists() else None
                if original_intent:
                    (project / 'Home.md').write_bytes(b'RECIPIENT-POST-CRASH-EDIT\n')
                finished = self.run_cli(args)['data']
                self.assertEqual(finished['receipt']['readiness'], 'ready')
                self.assertEqual(finished['receipt']['project_id'], initialized['project_id'])
                self.assertEqual((state / 'member.token').read_bytes(), incoming.read_bytes())
                if original_intent:
                    self.assertEqual(intent_path.read_bytes(), original_intent)
                    self.assertTrue(any(b'RECIPIENT-POST-CRASH-EDIT' in p.read_bytes()
                                        for p in (state / 'client' / 'drafts').glob('*.json')))
                self.assertEqual(self.coordinator(owner, owner_state, 'snapshot'), original_snapshot)
                self.assert_private(project, state)

    def test_init_preserves_existing_mixed_line_endings_utf8_and_missing_final_newline(self):
        project, state = self.fixture('exact-bytes')
        content = '# Existing α\r\nMixed β\nLast γ\rno final newline'.encode('utf-8')
        (project / 'Home.md').write_bytes(content)
        result = self.run_cli(self.init_args(project, state))['data']
        self.assertEqual(result['receipt']['readiness'], 'ready')
        self.assertEqual((project / 'Home.md').read_bytes(), content)
        self.assertEqual(self.coordinator(project, state, 'snapshot')['files']['Home.md'].encode('utf-8'), content)

    def test_changed_owner_provider_root_and_credentials_never_take_over_pending_state(self):
        project, state = self.fixture('binding')
        args = self.init_args(project, state)
        self.crash('after-credential', args)
        intent_before = (state / 'setup-intent.json').read_bytes()
        token_before = (state / 'member.token').read_bytes()
        for flag, value in (('--actor', 'different-owner'), ('--person', 'Different Person'),
                            ('--agent', 'Other Agent'), ('--purpose', 'Different source intent'), ('--provider', 'google-drive')):
            with self.subTest(flag=flag):
                changed = list(args); changed[changed.index(flag) + 1] = value
                self.run_cli(changed, expected=3)
                self.assertEqual((state / 'setup-intent.json').read_bytes(), intent_before)
                self.assertEqual((state / 'member.token').read_bytes(), token_before)
                self.assertFalse((state / 'coordinator.sqlite3').exists())
        other, _ = self.fixture('other-root'); changed = list(args); changed[1] = str(other)
        self.run_cli(changed, expected=3)
        (state / 'member.token').write_bytes(b'x' * 48 + b'\n')
        self.run_cli(args, expected=3)
        self.assertEqual((state / 'member.token').read_bytes(), b'x' * 48 + b'\n')
        self.assertFalse((state / 'coordinator.sqlite3').exists())

    def test_partial_intent_unrelated_state_and_legacy_project_are_preserved(self):
        project, state = self.fixture('partial-intent')
        args = self.init_args(project, state); self.crash('after-intent', args)
        (state / 'setup-intent.json').write_bytes(b'{"schema_version":')
        self.run_cli(args, expected=3)
        self.assertEqual((state / 'setup-intent.json').read_bytes(), b'{"schema_version":')
        self.assertFalse((state / 'member.token').exists())
        unrelated, unrelated_state = self.fixture('unrelated')
        unrelated_state.mkdir(); (unrelated_state / 'user.json').write_bytes(b'USER-STATE')
        self.run_cli(self.init_args(unrelated, unrelated_state), expected=4)
        self.assertEqual({p.name for p in unrelated_state.iterdir()}, {'user.json'})
        legacy, legacy_state = self.fixture('legacy'); (legacy / 'Coordination').mkdir()
        self.run_cli(self.init_args(legacy, legacy_state), expected=4)
        self.assertFalse(legacy_state.exists())

    def test_completed_retry_preserves_advanced_history_and_legacy_successful_refresh(self):
        project, state = self.fixture('advanced-history'); args = self.init_args(project, state)
        self.run_cli(args)
        self.coordinator(project, state, 'claim', {'assignment_id': 'edit', 'targets': ['Home.md'], 'criteria': ['verify'],
            'dependencies': [], 'resource_limits': {'max_proposals': 2}, 'integration_owner': 'owner'})
        self.coordinator(project, state, 'propose', {'proposal_id': 'change', 'base_revision': 0,
            'changes': {'Home.md': 'ACCEPTED-LATER-REVISION\r\n'}, 'evidence': 'Verified synthetic bytes', 'assignment_id': 'edit'})
        self.coordinator(project, state, 'accept', {'proposal_id': 'change', 'validation': 'Reviewed fixture', 'reason': 'Synthetic acceptance'})
        before = self.coordinator(project, state, 'snapshot')
        events = self.coordinator(project, state, 'events')
        self.run_cli(args)
        self.assertEqual(self.coordinator(project, state, 'snapshot'), before)
        self.assertEqual(self.coordinator(project, state, 'events'), events)
        self.assertEqual((project / 'Home.md').read_bytes(), b'ACCEPTED-LATER-REVISION\r\n')
        # Simulate a successful pre-journal installation. Ordinary refresh stays
        # usable; init must refuse adoption rather than fabricating a new intent.
        (state / 'setup-intent.json').unlink()
        self.run_cli(['refresh', str(project), '--state-dir', str(state)])
        self.run_cli(args, expected=4)
        self.assertEqual(self.coordinator(project, state, 'snapshot'), before)

    def test_invalid_actor_can_be_corrected_without_poisoning_private_state(self):
        project, state = self.fixture('invalid-owner'); args = self.init_args(project, state)
        args[args.index('--actor') + 1] = 'invalid actor'
        self.run_cli(args, expected=3)
        self.assertFalse(state.exists())
        self.assertFalse((project / '.shared-memory.json').exists())
        self.assertEqual((project / 'Home.md').read_bytes(), b'# Original accepted source\n')
        args[args.index('--actor') + 1] = 'corrected-owner'
        self.assertEqual(self.run_cli(args)['data']['receipt']['readiness'], 'ready')

    def test_virgin_lock_never_rewrites_magic_after_another_contender_acquires_it(self):
        # Reproduce the old race deterministically: a stale fstat(size=0) in A
        # resumed only after B wrote magic and acquired its independent OS lock.
        # Atomic publication no longer performs the vulnerable empty-file stat.
        if str(REPO / 'product') not in sys.path:
            sys.path.insert(0, str(REPO / 'product'))
        from shared_workspace import workflow
        state = self.root / 'virgin-lock'
        first_progress, second_inside = threading.Event(), threading.Event()
        original_fstat = os.fstat
        faults, entries = [], []
        def stale_fstat(descriptor):
            observed = original_fstat(descriptor)
            if threading.current_thread().name == 'first-lock' and observed.st_size == 0 and not first_progress.is_set():
                first_progress.set()
                second_inside.wait(3)
            return observed
        def first():
            try:
                with workflow._setup_lock(state):
                    entries.append('first')
            except Exception as exc:
                faults.append(type(exc).__name__)
            finally:
                first_progress.set()
        def second():
            try:
                if not first_progress.wait(3):
                    raise AssertionError('First lock contender did not progress')
                with workflow._setup_lock(state):
                    second_inside.set()
                    entries.append('second')
                    time.sleep(0.15)
            except Exception as exc:
                faults.append(type(exc).__name__)
        workers = [threading.Thread(target=first, name='first-lock'), threading.Thread(target=second, name='second-lock')]
        with patch.object(workflow.os, 'fstat', side_effect=stale_fstat):
            for worker in workers: worker.start()
            for worker in workers: worker.join(timeout=10)
        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(faults, [])
        self.assertEqual(set(entries), {'first', 'second'})
        self.assertEqual((state / workflow.SETUP_LOCK).read_bytes(), workflow.SETUP_LOCK_MAGIC)

    def test_different_state_directories_cannot_materialize_different_identities_into_same_root(self):
        project, state_a = self.fixture('root-reservation')
        state_b = self.root / 'other-private-state'
        args_a, args_b = self.init_args(project, state_a), self.init_args(project, state_b)
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--crash-worker', str(self.package),
                                    'hold-manifest', json.dumps(args_a)], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        waiting = state_a / '.setup-write-root-reservation-waiting'
        deadline = time.monotonic() + 10
        while not waiting.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(waiting.exists(), 'First setup never reached the root reservation boundary')
        # B imports a different valid source after A captured its immutable intent.
        # B reserves the root first. A must not overwrite B's selected files.
        (project / 'Home.md').write_bytes(b'SECOND-AUTHORIZED-SOURCE\r\n')
        winner = self.run_cli(args_b)['data']
        (state_a / '.setup-write-root-reservation-release').write_bytes(b'resume')
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 3, stdout.decode() + stderr.decode())
        self.assertEqual(json.loads(stdout)['code'], 'project_mismatch')
        self.assertFalse((state_a / 'client').exists(), 'Losing setup must never materialize into the selected folder')
        manifest = json.loads((project / '.shared-memory.json').read_bytes())
        self.assertEqual(manifest['project_id'], winner['project_id'])
        self.assertEqual((project / 'Home.md').read_bytes(), b'SECOND-AUTHORIZED-SOURCE\r\n')
        self.assertEqual(self.coordinator(project, state_b, 'snapshot')['files']['Home.md'], 'SECOND-AUTHORIZED-SOURCE\r\n')
        self.assertEqual((project.parent / 'Private.md').read_bytes(), b'PRIVATE-PARENT-PRESERVED\n')

    def test_competing_setup_waits_bounded_then_retries_after_process_exit(self):
        project, state = self.fixture('concurrent'); args = self.init_args(project, state)
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--crash-worker', str(self.package),
                                    'hold-intent', json.dumps(args)], cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.addCleanup(lambda: process.poll() is None and process.kill())
        marker = state / '.setup-write-test-holder'
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertTrue(marker.exists(), 'Lock-holder process did not reach the test boundary')
        started = time.monotonic()
        busy = self.run_cli(args, expected=4)
        self.assertEqual(busy['code'], 'setup_busy')
        self.assertLess(time.monotonic() - started, 10)
        process.kill(); process.communicate(timeout=5)
        self.assertEqual(self.run_cli(args)['data']['receipt']['readiness'], 'ready')


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--crash-worker':
        crash_worker(sys.argv[2], sys.argv[3], json.loads(sys.argv[4]))
    unittest.main(verbosity=2)
