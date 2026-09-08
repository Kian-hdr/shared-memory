#!/usr/bin/env python3
"""Exercise onboarding diagnostics without desktop or network dependencies."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()

    def setup_project(self, mode="local-only"):
        result = subprocess.run([sys.executable, str(SCRIPTS / "setup_workspace.py"), str(self.root), "--actor", "demo-owner", "--initiated-by", "Owner", "--agent", "Test", "--purpose", "Diagnostic fixture", "--collaboration-mode", mode], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def doctor(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "doctor_workspace.py"), str(self.root), "--json"], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def test_unconfigured_project_is_not_ready_and_not_modified(self):
        (self.root / "Notes.md").write_text("Preserve me")
        before = self.snapshot()
        code, report = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(report["local_status"], "unconfigured")
        self.assertEqual(self.snapshot(), before)

    def test_local_mode_is_explicit_and_diagnostics_do_not_write(self):
        self.setup_project()
        before = self.snapshot()
        code, report = self.doctor()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["collaboration_mode"], "local-only")
        self.assertEqual(report["external_checks"]["provider_propagation"], "not_applicable")
        self.assertEqual(report["external_checks"]["obsidian_vault_and_dashboard"], "unverified")
        self.assertEqual(self.snapshot(), before)

    def test_shared_mode_cannot_claim_receipt(self):
        self.setup_project("shared-folder")
        code, report = self.doctor()
        self.assertEqual(code, 0, report)
        self.assertEqual(report["external_checks"]["other_device_receipt"], "unverified")

    def test_target_tracker_is_never_executed(self):
        self.setup_project()
        sentinel = self.root / "EXECUTED"
        (self.root / "Coordination/project_tracker.py").write_text("from pathlib import Path\nPath(" + repr(str(sentinel)) + ").write_text('unsafe')\n")
        before = self.snapshot()
        code, report = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(report["local_status"], "blocked")
        self.assertFalse(sentinel.exists())
        self.assertEqual(self.snapshot(), before)

    def test_missing_tracker_in_existing_workspace_is_blocked(self):
        self.setup_project()
        tracker = self.root / "Coordination/project_tracker.py"
        tracker.rename(self.root / "saved-tracker.txt")
        before = self.snapshot()
        code, report = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(report["local_status"], "blocked")
        self.assertIn("owner", report["next_action"])
        self.assertEqual(self.snapshot(), before)

    def test_missing_canonical_home_is_blocked(self):
        self.setup_project()
        (self.root / "README.md").rename(self.root / "saved-home.md")
        before = self.snapshot()
        code, report = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(report["local_status"], "blocked")
        self.assertEqual(self.snapshot(), before)

    def test_missing_project_is_blocked_without_creation(self):
        self.root = self.root / "missing"
        code, report = self.doctor()
        self.assertEqual(code, 1)
        self.assertEqual(report["local_status"], "blocked")
        self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
