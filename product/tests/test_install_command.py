import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

script = Path(__file__).resolve().parents[2]/'scripts/install_command.py'
spec = importlib.util.spec_from_file_location('install_command', script)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class LauncherTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "The installed command launcher is POSIX-only; Windows uses Python .pyz")
    def test_checksum_argv_and_full_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve()
            runtime=base/'runtime with spaces.py'
            runtime.write_text('import json,sys; print(json.dumps(sys.argv[1:]))')
            wrapper=base/'command.py'
            digest=hashlib.sha256(runtime.read_bytes()).hexdigest()
            wrapper.write_text(module.launcher(Path(sys.executable).resolve(),runtime,digest))
            def run(*args):
                return subprocess.run([sys.executable,str(wrapper),*args],capture_output=True,text=True)
            self.assertEqual(json.loads(run('sync','project with spaces').stdout), ['sync','project with spaces','--brief'])
            self.assertEqual(json.loads(run('folder-status','--full').stdout), ['folder-status'])
            runtime.write_text('raise RuntimeError("must not execute")')
            result=run('sync')
            self.assertEqual(result.returncode,5)
            self.assertEqual(json.loads(result.stdout)['code'],'launcher_error')

    @unittest.skipUnless(os.name == "nt", "Windows-specific installer rejection")
    def test_windows_installer_reports_supported_route(self):
        result = subprocess.run([sys.executable, str(script), '--runtime', 'unused.pyz',
                                 '--sha256', '0'*64], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('on Windows use Python with the verified .pyz directly', result.stderr)
