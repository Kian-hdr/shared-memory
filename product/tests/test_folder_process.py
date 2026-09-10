"""Actual packaged worker exits and independent process recovery of folder setup."""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
WORKER = r'''
import os, sys
from pathlib import Path
package, project, state, action, boundary = sys.argv[1:]
sys.path.insert(0, package)
from shared_workspace import folder
real = folder.atomic
def crashing(path, data, immutable=False):
    result = real(path, data, immutable=immutable)
    if Path(path).name == boundary:
        os._exit(87)
    return result
folder.atomic = crashing
if action == 'init':
    folder.Folder.initialize(project, state, 'process-a', 'Fixture user', 'Fixture agent')
elif action == 'attach':
    import json
    identity = json.loads((Path(project)/'.shared-memory.json').read_text())['project_id']
    folder.Folder.attach(project, state, 'process-b', 'Fixture user', 'Fixture agent', identity)
elif action == 'sync':
    folder.Folder(project,state).sync()
'''


class FolderProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.built = tempfile.TemporaryDirectory(prefix='folder-process-package-')
        cls.addClassCleanup(cls.built.cleanup)
        cls.package = Path(cls.built.name).resolve() / 'runtime.pyz'
        build = subprocess.run([sys.executable, str(REPO/'scripts/build_product.py'), '--output', str(cls.package)], capture_output=True, text=True)
        if build.returncode:
            raise AssertionError(build.stdout + build.stderr)

    def cli(self, command, *args):
        value = subprocess.run([sys.executable, str(self.package), command, *map(str,args)], capture_output=True, text=True, timeout=60)
        self.assertEqual(value.returncode, 0, value.stdout + value.stderr)
        return json.loads(value.stdout)['data']

    def crash(self, project, state, action, boundary):
        value = subprocess.run([sys.executable, '-c', WORKER, str(self.package), str(project), str(state), action, boundary], capture_output=True, text=True, timeout=60)
        self.assertEqual(value.returncode, 87, value.stdout + value.stderr)

    def test_real_process_exit_at_each_initialization_checkpoint_resumes_original_identity(self):
        for boundary in ('initialization.json', 'folder.json', '.shared-memory.json', 'baseline.json'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(prefix='folder-process-init-') as temporary:
                root = Path(temporary).resolve(); project = root/'project'; state=root/'private'; project.mkdir()
                raw=b'# Notes\r\nPreserve direct bytes\r\n'; (project/'Note.md').write_bytes(raw)
                self.crash(project,state,'init',boundary)
                result=self.cli('setup',project,'--state-dir',state)
                self.assertEqual(result['readiness'],'ready')
                self.assertEqual((project/'Note.md').read_bytes(),raw)
                config=json.loads((state/'folder.json').read_text())
                self.assertEqual(config['author']['actor'],'process-a')
                again=self.cli('setup',project,'--state-dir',state)
                self.assertEqual(result['project_id'],again['project_id'])

    def test_real_process_exit_after_attach_config_preserves_reader_identity_and_notes(self):
        with tempfile.TemporaryDirectory(prefix='folder-process-attach-') as temporary:
            root=Path(temporary).resolve(); project=root/'project';project.mkdir();(project/'Note.md').write_text('Original\n')
            self.cli('setup',project,'--state-dir',root/'owner','--actor','owner')
            state=root/'other'
            self.crash(project,state,'attach','folder.json')
            result=self.cli('setup',project,'--state-dir',state)
            self.assertEqual(result['readiness'],'ready')
            self.assertEqual(json.loads((state/'folder.json').read_text())['author']['actor'],'process-b')
            self.assertEqual((project/'Note.md').read_text(),'Original\n')


if __name__ == '__main__':
    unittest.main()
