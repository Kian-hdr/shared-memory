"""Automatic capture configuration and real subprocess failure reporting."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/install_capture.py'
spec = importlib.util.spec_from_file_location('capture', SCRIPT)
capture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(capture)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.project = self.base / 'Selected project with spaces'
        self.state = self.base / 'Private state'
        self.logs = self.base / 'Private capture'
        for path in (self.project, self.state, self.logs):
            path.mkdir()
        (self.project / '.shared-memory.json').write_text(json.dumps({'format_version': 3, 'workflow': 'folder', 'project_id': 'fixture'}))
        self.binding = dict(readonly=False, root=str(self.project), project_id='fixture')
        self.write_binding()
        self.runtime = self.base / 'Runtime with spaces.py'
        self.runtime.write_text('import json; print(json.dumps({"ok": True, "data": {"readiness": "ready"}}))')
        self.config = dict(project=str(self.project), state=str(self.state), capture=str(self.logs), python=str(Path(sys.executable).resolve()), runtime=str(self.runtime), sha256=hashlib.sha256(self.runtime.read_bytes()).hexdigest())

    def write_binding(self):
        (self.state / 'folder.json').write_text(json.dumps(self.binding))

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_spaces_are_separate_argv_and_success_has_private_bounded_status(self):
        self.assertEqual(capture.command(self.config)[3], str(self.project))
        self.assertEqual(capture.command(self.config)[-1], '--brief')
        self.assertEqual(capture.run_once(self.config), 0)
        result = self.logs / 'last-result.json'
        self.assertTrue(json.loads(result.read_text())['ok'])
        self.assertEqual(result.stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_readonly_refused_before_runtime(self):
        self.binding['readonly'] = True
        self.write_binding()
        with self.assertRaisesRegex(ValueError, 'read-only'):
            capture.validate(self.config)
        self.assertNotEqual(capture.run_once(self.config), 0)
        self.assertFalse(json.loads((self.logs / 'last-result.json').read_text())['ok'])

    def test_private_paths_and_symlinks_refused(self):
        with self.assertRaises(ValueError):
            capture.private(self.project / 'state', self.project)
        alias = self.base / 'alias'
        try:
            alias.symlink_to(self.state)
        except OSError:
            self.skipTest('This platform does not permit creating test symlinks')
        with self.assertRaises(ValueError):
            capture.physical(alias)

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_zero_exit_without_json_success_is_failure(self):
        for source in ('print("not json")', 'print(\'{"ok": false}\')', 'raise SystemExit(3)', 'print(\'{"ok": true, "data": null}\')'):
            self.runtime.write_text(source)
            self.config['sha256'] = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
            self.assertNotEqual(capture.run_once(self.config), 0)
            self.assertFalse(json.loads((self.logs / 'last-result.json').read_text())['ok'])

    def test_plist_configuration_is_stable_and_contains_no_shell(self):
        from argparse import Namespace
        args = Namespace(project=str(self.project), state_dir=str(self.state), python=self.config['python'], runtime=str(self.runtime), interval=60, sha256=self.config['sha256'])
        with patch.object(Path, 'home', return_value=self.base):
            first = capture.plan(args)
            second = capture.plan(args)
        self.assertEqual(first, second)
        plist = first[1]
        self.assertEqual(plist['StartInterval'], 60)
        self.assertNotIn('KeepAlive', plist)
        self.assertEqual(plist['ProgramArguments'][0], self.config['python'])
        self.assertNotIn('-c', plist['ProgramArguments'])

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_runtime_failure_detail_is_bounded(self):
        self.runtime.write_text('import sys; sys.stderr.write("x" * 100000); raise SystemExit(1)')
        self.config['sha256'] = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
        self.assertEqual(capture.run_once(self.config), 1)
        self.assertLess((self.logs / 'last-result.json').stat().st_size, 5000)

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_runtime_change_refused_before_execution(self):
        self.runtime.write_text('raise RuntimeError("must not execute")')
        self.assertNotEqual(capture.run_once(self.config), 0)
        result = json.loads((self.logs / 'last-result.json').read_text())
        self.assertIn('SHA-256', result['error'])

    def test_status_and_uninstall_plan_survive_missing_runtime_and_state(self):
        from argparse import Namespace
        args = Namespace(project=str(self.project), state_dir=str(self.state), python=self.config['python'], runtime=str(self.runtime), interval=60, sha256=self.config['sha256'])
        with patch.object(Path, 'home', return_value=self.base):
            config, _, _ = capture.plan(args)
            directory = Path(config['capture'])
            directory.mkdir(parents=True)
            (directory / 'config.json').write_text(json.dumps(config))
            self.runtime.unlink()
            (self.state / 'folder.json').unlink()
            for operation in ('status', 'uninstall'):
                setattr(args, operation, True)
                recovered, _, _ = capture.plan(args)
                self.assertEqual(recovered, config)

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_error_code_message_and_attention_are_preserved(self):
        self.runtime.write_text('print(\'{"ok": false, "code": "fixture_failure", "message": "Useful diagnosis", "data": {"readiness": "partial", "attention": ["review conflict"]}}\')')
        self.config['sha256'] = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
        self.assertNotEqual(capture.run_once(self.config), 0)
        result = json.loads((self.logs / 'last-result.json').read_text())
        self.assertIn('Useful diagnosis', result['error'])
        self.assertEqual(result['summary']['attention'], ['review conflict'])

    def test_known_provider_roots_are_refused_outside_selected_workspace(self):
        for folder in ('OneDrive - Example', 'Google Drive', 'GoogleDrive-user', 'Dropbox', 'CloudStorage', 'Mobile Documents', 'Nextcloud', 'Box'):
            with self.subTest(folder=folder), self.assertRaises(ValueError):
                capture.private(self.base / folder / 'state', self.project)

    def test_runner_reports_unsupported_platform_without_mutation(self):
        with patch.object(capture, 'fcntl', None), self.assertRaisesRegex(ValueError, 'POSIX'):
            capture.run_once(self.config)
        self.assertEqual(list(self.logs.iterdir()), [])

    def test_module_can_import_without_fcntl(self):
        other = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'fcntl': None}):
            spec.loader.exec_module(other)
        self.assertIsNone(other.fcntl)

    def test_prepare_does_not_require_os_getuid_or_launchctl(self):
        import contextlib
        import io
        argv = [str(SCRIPT), str(self.project), '--state-dir', str(self.state), '--runtime', str(self.runtime), '--sha256', self.config['sha256']]
        with patch.object(sys, 'argv', argv), patch.object(sys, 'platform', 'win32'), patch.object(Path, 'home', return_value=self.base), patch.object(capture.os, 'getuid', side_effect=AssertionError('must not call'), create=True), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(capture.main(), 0)

    @unittest.skipUnless(capture.fcntl is not None, 'POSIX capture runner')
    def test_partial_readiness_has_attention_and_nonzero_status(self):
        self.runtime.write_text('print(\'{"ok": true, "data": {"readiness": "partial", "counts": {"conflicts": 1}}}\')')
        self.config['sha256'] = hashlib.sha256(self.runtime.read_bytes()).hexdigest()
        self.assertEqual(capture.run_once(self.config), 2)
        result = json.loads((self.logs / 'last-result.json').read_text())
        self.assertTrue(result['ok'])  # runtime command succeeded, readiness still needs attention
        self.assertTrue(result['attention_required'])
        self.assertEqual(result['readiness'], 'partial')

    def test_status_distinguishes_loaded_from_healthy_capture(self):
        import contextlib
        import io
        import time
        from argparse import Namespace
        from subprocess import CompletedProcess
        args = Namespace(project=str(self.project), state_dir=str(self.state), python=self.config['python'], runtime=str(self.runtime), interval=60, sha256=self.config['sha256'])
        with patch.object(Path, 'home', return_value=self.base):
            config, _, _ = capture.plan(args)
            directory = Path(config['capture'])
            directory.mkdir(parents=True)
            (directory / 'config.json').write_text(json.dumps(config))
            cases = [(True, 'ready', time.time(), 0), (True, 'partial', time.time(), 2), (False, 'ready', time.time(), 2), (True, 'ready', 0, 2)]
            for ok, readiness, checked_at, expected in cases:
                (directory / 'last-result.json').write_text(json.dumps(dict(ok=ok, readiness=readiness, checked_at=checked_at)))
                with patch.object(sys, 'argv', [str(SCRIPT), str(self.project), '--status']), patch.object(sys, 'platform', 'darwin'), patch.object(capture.os, 'getuid', return_value=42, create=True), patch.object(capture, 'launchctl', return_value=CompletedProcess([], 0)), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(capture.main(), expected)
