#!/usr/bin/env python3
"""Behavioral regression tests for the generated workspace and tracker."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
SETUP = SKILL_ROOT / "scripts" / "setup_workspace.py"
PORTABLE_ITEMS_FILTER = 'this.file.ext == "base" && file.inFolder(this.file.folder + "/Items")'


def load_script(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }


def read_note(path: Path) -> tuple[dict, str]:
    parts = path.read_text(encoding="utf-8").split("---", 2)
    return yaml.safe_load(parts[1]), parts[2]


def write_note(path: Path, data: dict, body: str) -> None:
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False, width=1000000) + "---" + body, encoding="utf-8")


class WorkspaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="shared-workspace-test-")
        self.root = Path(self.temporary.name) / "Project"
        self.root.mkdir()
        self.setup_project(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_command(self, command: list[str], expected: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def setup_project(self, root: Path, extra: list[str] | None = None, expected: int = 0) -> subprocess.CompletedProcess:
        return self.run_command([
            sys.executable, str(SETUP), str(root), "--purpose", "Test shared project",
            "--actor", "taylor-codex", "--initiated-by", "Taylor", "--agent", "Codex",
        ] + (extra or []), expected)

    def tracker(self, *arguments: str, expected: int = 0) -> subprocess.CompletedProcess:
        return self.run_command([sys.executable, str(self.root / "Coordination" / "project_tracker.py"), *arguments], expected)

    def claim(self, work_id: str = "ARCH-001", target: str = "architecture.md", actor: str = "taylor-codex", owner: str = "Taylor", extra: list[str] | None = None) -> subprocess.CompletedProcess:
        return self.tracker(
            "claim", "--work-id", work_id, "--title", work_id,
            "--actor", actor, "--owner", owner, "--agent", "Codex", "--initiated-by", owner,
            "--target", target, "--objective", "Produce a tested output",
            "--acceptance", "Output exists", "--acceptance", "Validation passes",
            "--next-action", "Implement output", *(extra or []),
        )

    def change(self, work_id: str = "ARCH-001", actor: str = "taylor-codex", extra: list[str] | None = None, expected: int = 0) -> subprocess.CompletedProcess:
        return self.tracker(
            "change", "--work-id", work_id, "--actor", actor, "--summary", "Output updated",
            "--change-kind", "implementation", "--impact", "compatible", "--next-action", "Review output",
            *(extra or []), expected=expected,
        )

    def work_path(self, work_id: str = "ARCH-001") -> Path:
        return self.root / "Coordination" / "Items" / f"WORK-{work_id}.md"

    def test_bootstrap_has_only_lean_fixed_files(self) -> None:
        self.assertTrue((self.root / "AGENTS.md").exists())
        self.assertTrue((self.root / "CLAUDE.md").exists())
        self.assertTrue((self.root / "README.md").exists())
        self.assertFalse((self.root / "AI-README.md").exists())
        self.assertFalse((self.root / "Project Memory.md").exists())
        self.tracker("validate")

    def plan_work(self, work_id="BACKLOG-001", target="future.md", extra=None):
        return self.tracker("plan", "--work-id", work_id, "--title", "Review historical work",
            "--actor", "taylor-codex", "--owner", "Taylor", "--agent", "Codex", "--initiated-by", "Taylor",
            "--suggested-owner", "Morgan", "--target", target,
            "--objective", "Reconcile recorded state", "--acceptance", "Owner verifies current evidence",
            "--source-summary", "Historical: baseline passed; current status unverified",
            "--source-evidence", "legacy.md", "--next-action", "Review source", *(extra or []))

    def start_work(self, work_id="BACKLOG-001", expected=0):
        return self.tracker("start", "--work-id", work_id, "--actor", "morgan-agent-session",
            "--owner", "Morgan", "--agent", "Claude", "--summary", "Reviewed historical context and scope",
            "--evidence", "owner-review.md", "--next-action", "Perform the bounded work", expected=expected)

    def test_backlog_does_not_claim_or_assign_suggested_owner(self):
        self.plan_work()
        data, _ = read_note(self.work_path("BACKLOG-001"))
        self.assertEqual(data["status"], "not_started")
        self.assertEqual(data["owner"], "Unassigned")
        self.assertEqual(data["actor_id"], "")
        self.assertEqual(data["claim_expires"], "")
        self.assertEqual(data["suggested_owner"], "Morgan")
        self.assertEqual(data["acceptance_passed"], 0)
        actor, _ = read_note(self.root / "Coordination/Items/ACTOR-TAYLOR-CODEX.md")
        self.assertNotIn("BACKLOG-001", actor["active_work"])
        self.tracker("validate")

    def test_backlog_allows_overlap_but_start_rejects_active_conflict(self):
        self.claim(target="shared.md")
        self.plan_work(target="shared.md")
        before = snapshot(self.root)
        self.start_work(expected=1)
        self.assertEqual(before, snapshot(self.root))

    def test_start_backlog_records_actor_review_and_preserves_events(self):
        self.plan_work()
        events = {p: p.read_bytes() for p in (self.root / "Coordination/Items").glob("EVENT-*.md")}
        self.start_work()
        data, _ = read_note(self.work_path("BACKLOG-001"))
        self.assertEqual(data["actor_id"], "MORGAN-AGENT-SESSION")
        self.assertEqual(data["revision"], 2)
        self.assertEqual(data["status"], "claimed")
        self.assertEqual(data["source_evidence"], ["legacy.md"])
        self.assertIn("owner-review.md", data["evidence"])
        self.tracker("check", "--actor", "morgan-agent-session", "--work-id", "BACKLOG-001")
        for path, original in events.items():
            self.assertEqual(path.read_bytes(), original)
        self.tracker("validate")

    def test_start_cannot_steal_existing_claim(self):
        self.claim()
        before = snapshot(self.root)
        self.start_work("ARCH-001", expected=1)
        self.assertEqual(before, snapshot(self.root))

    def test_backlog_start_refreshes_reviewed_dependency_baseline(self):
        self.claim()
        self.plan_work(extra=["--depends-on", "ARCH-001"])
        self.change()
        self.start_work()
        data, _ = read_note(self.work_path("BACKLOG-001"))
        self.assertEqual(data["dependency_baseline"], ["ARCH-001@2"])
        self.tracker("validate")

    def test_idempotent_setup(self) -> None:
        before = snapshot(self.root)
        self.setup_project(self.root)
        self.assertEqual(before, snapshot(self.root))

    def test_retrofit_preserves_existing_instructions_and_dossier(self) -> None:
        root = Path(self.temporary.name) / "Legacy"
        root.mkdir()
        (root / "AGENTS.md").write_text("# Existing rules\n\nNever publish.\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("# Existing Claude settings\n", encoding="utf-8")
        (root / "Legacy.md").write_text("# Existing dossier\n", encoding="utf-8")
        self.setup_project(root, ["--mode", "retrofit"])
        self.assertTrue((root / "AGENTS.md").read_text().startswith("# Existing rules\n\nNever publish."))
        self.assertTrue((root / "CLAUDE.md").read_text().startswith("# Existing Claude settings"))
        self.assertFalse((root / "README.md").exists())

    def test_existing_home_note_is_reused(self) -> None:
        root = Path(self.temporary.name) / "HomeVault"
        root.mkdir()
        home = root / "Home.md"
        home.write_text("# Shared vault home\n", encoding="utf-8")
        self.setup_project(root)
        self.assertFalse((root / "README.md").exists())
        self.assertEqual(home.read_text(encoding="utf-8"), "# Shared vault home\n")
        self.assertIn("Project home: `Home.md`", (root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_project_home_outside_share_is_rejected_without_writes(self) -> None:
        root = Path(self.temporary.name) / "NewShare"
        root.mkdir()
        outside = Path(self.temporary.name) / "Personal home.md"
        outside.write_text("# Personal home\n", encoding="utf-8")
        before = snapshot(Path(self.temporary.name))
        result = self.setup_project(root, ["--project-home", str(outside)], expected=1)
        self.assertIn("Project home must be inside the project root", result.stderr)
        self.assertEqual(before, snapshot(Path(self.temporary.name)))

    def test_project_home_uses_portable_separators(self) -> None:
        root = Path(self.temporary.name) / "OtherShare"
        (root / "Notes").mkdir(parents=True)
        (root / "Notes" / "Project home.md").write_text("# Home\n", encoding="utf-8")
        self.setup_project(root, ["--project-home", "Notes\\Project home.md"])
        self.assertIn("Project home: `Notes/Project home.md`", (root / "AGENTS.md").read_text(encoding="utf-8"))

    def test_legacy_absolute_home_pointer_is_diagnosed_without_writes(self) -> None:
        path = self.root / "AGENTS.md"
        path.write_text(path.read_text(encoding="utf-8").replace("Project home: `README.md`", f"Project home: `{self.root / 'README.md'}`"), encoding="utf-8")
        before = snapshot(self.root)
        result = self.tracker("validate", expected=1)
        self.assertIn("nonportable project-home pointer", result.stdout)
        self.assertEqual(before, snapshot(self.root))

    def test_dry_run_has_no_writes(self) -> None:
        before = snapshot(self.root)
        self.setup_project(self.root, ["--dry-run"])
        self.assertEqual(before, snapshot(self.root))

    def test_audit_has_no_writes(self) -> None:
        before = snapshot(self.root)
        self.run_command([sys.executable, str(SETUP), str(self.root), "--mode", "audit"])
        self.assertEqual(before, snapshot(self.root))

    def test_unsigned_conflict_stops_before_mutation(self) -> None:
        root = Path(self.temporary.name) / "Conflict"
        (root / "Coordination").mkdir(parents=True)
        (root / "Coordination" / "project_tracker.py").write_text("print('mine')\n")
        before = snapshot(root)
        self.setup_project(root, expected=1)
        self.assertEqual(before, snapshot(root))

    def test_modified_generated_file_requires_review(self) -> None:
        path = self.root / "Coordination" / "project_tracker.py"
        path.write_text(path.read_text() + "\n# user customization\n")
        before = snapshot(self.root)
        self.setup_project(self.root, expected=1)
        self.assertEqual(before, snapshot(self.root))

    def test_audit_does_not_execute_project_tracker(self) -> None:
        path = self.root / "Coordination" / "project_tracker.py"
        path.write_text("from pathlib import Path\nPath('UNSAFE-AUDIT').write_text('ran')\n")
        result = self.run_command([sys.executable, str(SETUP), str(self.root), "--mode", "audit"], expected=1)
        self.assertIn("differs from the trusted", result.stdout)
        self.assertFalse((self.root / "UNSAFE-AUDIT").exists())

    def test_claims_allow_distinct_targets(self) -> None:
        self.claim()
        self.claim("DATA-002", "data.md", "jordan-codex", "Jordan")
        self.tracker("validate")

    def test_overlapping_claim_is_rejected(self) -> None:
        self.claim(target="src")
        result = self.tracker(
            "claim", "--work-id", "OTHER", "--title", "Other", "--actor", "jordan-codex",
            "--owner", "Jordan", "--agent", "Codex", "--initiated-by", "Jordan",
            "--target", "src/adapter.py", "--objective", "Test", "--acceptance", "Done",
            "--next-action", "Test", expected=1,
        )
        self.assertIn("Target conflict", result.stderr)

    def test_windows_and_case_aliases_conflict(self) -> None:
        self.claim(target="src/adapter.py")
        result = self.tracker(
            "claim", "--work-id", "OTHER", "--title", "Other", "--actor", "jordan-codex",
            "--owner", "Jordan", "--agent", "Codex", "--initiated-by", "Jordan",
            "--target", "SRC\\adapter.py", "--objective", "Test", "--acceptance", "Done",
            "--next-action", "Test", expected=1,
        )
        self.assertIn("Target conflict", result.stderr)

    def test_absolute_local_targets_survive_relocation(self) -> None:
        document = self.root / "Shared notes ü.md"
        document.write_text("Shared contents\n", encoding="utf-8")
        self.claim(target=str(document))
        data, _ = read_note(self.work_path())
        self.assertEqual(data["targets"], ["Shared notes ü.md"])
        self.assertEqual(json.loads(data["target_hashes"][0])["path"], "Shared notes ü.md")
        for path in (self.root / "Coordination" / "Items").glob("*.md"):
            self.assertNotIn(str(self.root), path.read_text(encoding="utf-8"))

        recipient = Path(self.temporary.name) / "Different recipient folder" / "Project"
        shutil.copytree(self.root, recipient)
        document.write_text("Only the original machine changed\n", encoding="utf-8")
        self.run_command([sys.executable, str(recipient / "Coordination" / "project_tracker.py"),
                          "check", "--actor", "taylor-codex", "--work-id", "ARCH-001"])
        self.run_command([sys.executable, str(recipient / "Coordination" / "project_tracker.py"), "validate"])

    def test_absolute_and_relative_claims_conflict(self) -> None:
        self.claim(target="shared.md")
        before = snapshot(self.root)
        result = self.tracker(
            "claim", "--work-id", "OTHER", "--title", "Other", "--actor", "jordan-codex",
            "--owner", "Jordan", "--agent", "Codex", "--initiated-by", "Jordan",
            "--target", str(self.root / "shared.md"), "--objective", "Test",
            "--acceptance", "Done", "--next-action", "Test", expected=1,
        )
        self.assertIn("Target conflict", result.stderr)
        self.assertEqual(before, snapshot(self.root))

    def test_unportable_new_targets_are_rejected_without_writes(self) -> None:
        targets = ["~/private.md", "../private.md", "src/../shared.md", "C:\\OtherUser\\private.md",
                   "\\\\other-server\\share\\private.md", str(self.root.parent / "private.md")]
        for target in targets:
            with self.subTest(target=target):
                before = snapshot(self.root)
                self.tracker(
                    "claim", "--work-id", "BAD", "--title", "Bad target", "--actor", "new-actor",
                    "--owner", "Jordan", "--agent", "Codex", "--initiated-by", "Jordan",
                    "--target", target, "--objective", "Test", "--acceptance", "Done",
                    "--next-action", "Test", expected=1,
                )
                self.assertEqual(before, snapshot(self.root))

    def test_project_root_claim_conflicts_with_descendants(self) -> None:
        self.claim(target=".")
        result = self.tracker(
            "claim", "--work-id", "OTHER", "--title", "Other", "--actor", "jordan-codex",
            "--owner", "Jordan", "--agent", "Codex", "--initiated-by", "Jordan",
            "--target", "notes/shared.md", "--objective", "Test", "--acceptance", "Done",
            "--next-action", "Test", expected=1,
        )
        self.assertIn("Target conflict", result.stderr)

    def test_existing_nonportable_work_is_diagnosed_without_rewriting(self) -> None:
        self.claim(target="shared.md")
        path = self.work_path()
        data, body = read_note(path)
        old_target = str(self.root / "shared.md")
        data["targets"] = [old_target]
        data["target_hashes"] = [json.dumps({"path": old_target, "sha256": "missing"})]
        write_note(path, data, body)
        before = snapshot(self.root)
        result = self.tracker("validate", expected=1)
        self.assertIn("Nonportable stored target", result.stdout)
        self.assertIn("explicit migration", result.stdout)
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001", expected=1)
        self.assertEqual(before, snapshot(self.root))

    def test_historical_nonportable_target_is_diagnosed_without_rewriting(self) -> None:
        self.claim(target="shared.md")
        event = next((self.root / "Coordination" / "Items").glob("EVENT-*.md"))
        data, body = read_note(event)
        data["hashes_before"] = [json.dumps({"path": "C:/FormerUser/shared.md", "sha256": "missing"})]
        write_note(event, data, body)
        before = snapshot(self.root)
        result = self.tracker("validate", expected=1)
        self.assertIn(event.name, result.stdout)
        self.assertIn("Nonportable stored target", result.stdout)
        self.assertEqual(before, snapshot(self.root))

    def test_logical_resource_labels_remain_advisory(self) -> None:
        labels = ["branch:feature/docs", "environment:staging", "env:preview", "artifact:report/final"]
        self.claim(target=labels[0], extra=[argument for label in labels[1:] for argument in ("--target", label)])
        data, _ = read_note(self.work_path())
        self.assertEqual(data["targets"], labels)
        self.assertTrue(all(json.loads(item)["sha256"] == "missing" for item in data["target_hashes"]))
        self.tracker("validate")

    def test_dependency_change_requires_acknowledgement(self) -> None:
        self.claim()
        self.claim("CONTROL-002", "control.py", "jordan-codex", "Jordan", ["--depends-on", "ARCH-001"])
        self.change(extra=["--impact", "breaking"])
        self.assertIn("NEEDS SYNC", self.tracker("status").stdout)
        self.change("CONTROL-002", "jordan-codex", expected=1)
        self.tracker("acknowledge", "--actor", "jordan-codex", "--work-id", "CONTROL-002", "--dependency", "ARCH-001", "--summary", "Reviewed the new interface", "--next-action", "Update adapter")
        self.change("CONTROL-002", "jordan-codex")

    def test_unrecorded_change_is_detected_and_recorded(self) -> None:
        self.claim()
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        (self.root / "architecture.md").write_text("new content\n")
        self.tracker("reconcile", expected=1)
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001", expected=1)
        self.change()
        self.tracker("reconcile")

    def test_directory_claim_detects_descendant_content_and_structure_changes(self) -> None:
        folder = self.root / "notes"
        folder.mkdir()
        document = folder / "document.md"
        document.write_text("Original\n", encoding="utf-8")
        self.claim(target="notes")
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        for action in ("edit", "add", "rename", "delete", "empty-directory"):
            with self.subTest(action=action):
                if action == "edit":
                    document.write_text("Changed\n", encoding="utf-8")
                elif action == "add":
                    (folder / "added.md").write_text("Added\n", encoding="utf-8")
                elif action == "rename":
                    (folder / "added.md").rename(folder / "renamed.md")
                elif action == "delete":
                    (folder / "renamed.md").unlink()
                else:
                    (folder / "empty").mkdir()
                self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001", expected=1)
                self.change()
                self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        recipient = self.root.parent / "Recipient"
        shutil.copytree(self.root, recipient)
        self.run_command([sys.executable, str(recipient / "Coordination/project_tracker.py"),
                          "check", "--actor", "taylor-codex", "--work-id", "ARCH-001"])

    def test_root_directory_hash_excludes_tracker_owned_records(self) -> None:
        self.claim(target=".")
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        self.tracker("sync", "--actor", "taylor-codex")
        self.change()
        self.tracker("heartbeat", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        self.tracker("validate")

    def test_directory_symlink_is_rejected_without_writes(self) -> None:
        folder = self.root / "notes"
        folder.mkdir()
        (self.root / "document.md").write_text("Original\n", encoding="utf-8")
        try:
            (folder / "linked.md").symlink_to(self.root / "document.md")
        except OSError:
            self.skipTest("Symbolic links unavailable on this platform")
        before = snapshot(self.root)
        result = self.tracker(
            "claim", "--work-id", "LINK", "--title", "Link", "--actor", "new-actor",
            "--owner", "Jordan", "--agent", "Codex", "--initiated-by", "Jordan",
            "--target", "notes", "--objective", "Test", "--acceptance", "Done",
            "--next-action", "Test", expected=1,
        )
        self.assertIn("symbolic link", result.stderr)
        self.assertEqual(before, snapshot(self.root))

    def test_change_rejects_undeclared_drift_without_mutating_records(self) -> None:
        self.claim(target="a.md", extra=["--target", "b.md"])
        (self.root / "a.md").write_text("Reported edit\n", encoding="utf-8")
        (self.root / "b.md").write_text("Unreported edit\n", encoding="utf-8")
        before = snapshot(self.root)
        result = self.change(extra=["--changed-target", "a.md"], expected=1)
        self.assertIn("b.md", result.stderr)
        self.assertEqual(before, snapshot(self.root))
        self.tracker("reconcile", expected=1)
        self.change(extra=["--changed-target", "a.md", "--changed-target", "b.md"])
        self.tracker("reconcile")
        events = [read_note(path)[0] for path in (self.root / "Coordination/Items").glob("EVENT-*.md")]
        event = next(data for data in events if data["event_type"] == "change")
        self.assertEqual(event["changed_targets"], ["a.md", "b.md"])

    def test_child_change_cannot_absorb_other_drift_under_directory_claim(self) -> None:
        folder = self.root / "notes"
        folder.mkdir()
        self.claim(target="notes")
        (folder / "a.md").write_text("Reported\n", encoding="utf-8")
        (folder / "b.md").write_text("Unreported\n", encoding="utf-8")
        before = snapshot(self.root)
        result = self.change(extra=["--changed-target", "notes/a.md"], expected=1)
        self.assertIn("notes", result.stderr)
        self.assertEqual(before, snapshot(self.root))
        self.change(extra=["--changed-target", "notes"])
        self.tracker("reconcile")

    def test_exact_acceptance_criteria_and_completion_gate(self) -> None:
        self.claim()
        self.change(extra=["--pass-criterion", "2"])
        data, body = read_note(self.work_path())
        self.assertEqual(data["passed_criteria"], [2])
        self.assertIn("- [ ] 1. Output exists", body)
        self.assertIn("- [x] 2. Validation passes", body)
        self.tracker("complete", "--actor", "taylor-codex", "--work-id", "ARCH-001", "--summary", "Complete", "--evidence", "test.log", "--validation", "Tests passed", expected=1)
        self.change(extra=["--pass-criterion", "1", "--evidence", "test.log", "--validation", "Tests passed"])
        self.tracker("complete", "--actor", "taylor-codex", "--work-id", "ARCH-001", "--summary", "Complete", "--evidence", "test.log", "--validation", "Tests passed")
        self.assertEqual(read_note(self.work_path())[0]["status"], "verified")

    def test_handoff_requires_acceptance_and_blocks_old_owner(self) -> None:
        self.claim()
        self.tracker("handoff", "--actor", "taylor-codex", "--work-id", "ARCH-001", "--to-actor", "jordan-codex", "--to-owner", "Jordan", "--to-agent", "Codex", "--last-verified", "Initial claim", "--next-action", "Continue implementation")
        self.change(expected=1)
        self.change(actor="jordan-codex", expected=1)
        self.tracker("accept-handoff", "--actor", "jordan-codex", "--work-id", "ARCH-001", "--summary", "Reviewed handoff", "--next-action", "Continue implementation")
        self.change(actor="jordan-codex")

    def test_large_exact_file_content_drift_is_detected(self) -> None:
        document = self.root / "large.bin"
        with document.open("wb") as handle:
            handle.seek(21 * 1024 * 1024)
            handle.write(b"A")
        self.claim(target="large.bin")
        data, _ = read_note(self.work_path())
        recorded = json.loads(data["target_hashes"][0])["sha256"]
        self.assertEqual(recorded, hashlib.sha256(document.read_bytes()).hexdigest())
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        with document.open("r+b") as handle:
            handle.seek(21 * 1024 * 1024)
            handle.write(b"B")
        before = snapshot(self.root)
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001", expected=1)
        self.assertEqual(before, snapshot(self.root))
        self.change()
        self.tracker("reconcile")

    def test_complete_rejects_unrecorded_drift_without_writes(self) -> None:
        self.claim()
        self.change(extra=["--pass-criterion", "1", "--pass-criterion", "2"])
        (self.root / "architecture.md").write_text("Unrecorded after validation\n", encoding="utf-8")
        before = snapshot(self.root)
        result = self.tracker(
            "complete", "--actor", "taylor-codex", "--work-id", "ARCH-001",
            "--summary", "Complete", "--evidence", "test.log", "--validation", "Tests passed", expected=1,
        )
        self.assertIn("Unrecorded target changes", result.stderr)
        self.assertEqual(before, snapshot(self.root))
        self.assertEqual(read_note(self.work_path())[0]["status"], "in_progress")
        self.change(extra=["--evidence", "test.log", "--validation", "Revalidated changed output"])
        self.tracker("complete", "--actor", "taylor-codex", "--work-id", "ARCH-001",
                     "--summary", "Complete", "--evidence", "test.log", "--validation", "Revalidated changed output")
        self.assertEqual(read_note(self.work_path())[0]["status"], "verified")

    def test_legacy_hash_sentinels_require_explicit_review_without_history_rewrite(self) -> None:
        for work_id, target, old_hash in (("FILE", "file.md", "too-large"), ("DIR", "notes", "directory")):
            with self.subTest(old_hash=old_hash):
                if old_hash == "directory":
                    (self.root / target).mkdir()
                else:
                    (self.root / target).write_text("Original\n", encoding="utf-8")
                self.claim(work_id=work_id, target=target)
                self.change(work_id=work_id, extra=["--pass-criterion", "1", "--pass-criterion", "2"])
                path = self.work_path(work_id)
                data, body = read_note(path)
                data["target_hashes"] = [json.dumps({"path": target, "sha256": old_hash})]
                write_note(path, data, body)
                before = snapshot(self.root)
                self.tracker("check", "--actor", "taylor-codex", "--work-id", work_id, expected=1)
                self.tracker("complete", "--actor", "taylor-codex", "--work-id", work_id,
                             "--summary", "Complete", "--evidence", "test.log", "--validation", "Tests passed", expected=1)
                self.assertEqual(before, snapshot(self.root))
                history = {p: p.read_bytes() for p in (self.root / "Coordination/Items").glob("EVENT-*.md")}
                self.change(work_id=work_id, extra=["--summary", "Reviewed legacy hash and current file contents"])
                self.tracker("check", "--actor", "taylor-codex", "--work-id", work_id)
                self.assertTrue(all(p.read_bytes() == content for p, content in history.items()))

    def test_stale_claim_is_detected_and_renewed(self) -> None:
        self.claim()
        data, body = read_note(self.work_path())
        data["claim_expires"] = "2000-01-01T00:00:00Z"
        write_note(self.work_path(), data, body)
        self.assertIn("STALE CLAIM", self.tracker("status").stdout)
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001", expected=1)
        self.tracker("heartbeat", "--actor", "taylor-codex", "--work-id", "ARCH-001")
        self.tracker("check", "--actor", "taylor-codex", "--work-id", "ARCH-001")

    def test_late_arriving_older_event_is_not_lost(self) -> None:
        self.tracker("sync", "--actor", "taylor-codex")
        self.tracker("decision", "--decision-key", "late-arrival", "--actor", "taylor-codex", "--owner", "Taylor", "--agent", "Codex", "--initiated-by", "Taylor", "--summary", "Late decision", "--rationale", "Offline event", "--impact", "compatible")
        path = next((self.root / "Coordination" / "Items").glob("DECISION-*-LATE-ARRIVAL-*.md"))
        data, body = read_note(path)
        data["timestamp"] = "2000-01-01T00:00:00Z"
        write_note(path, data, body)
        self.assertIn("Late decision", self.tracker("sync", "--actor", "taylor-codex").stdout)
        self.assertIn("0 new immutable", self.tracker("sync", "--actor", "taylor-codex").stdout)

    def test_existing_events_remain_byte_identical(self) -> None:
        self.claim()
        items = self.root / "Coordination" / "Items"
        before = {path.name: path.read_bytes() for path in items.glob("EVENT-*.md")}
        self.change()
        for name, content in before.items():
            self.assertEqual((items / name).read_bytes(), content)

    def test_correction_supersedes_without_rewriting(self) -> None:
        self.claim()
        event_path = next((self.root / "Coordination" / "Items").glob("EVENT-*.md"))
        before = event_path.read_bytes()
        event_id = read_note(event_path)[0]["event_id"]
        self.change(extra=["--supersedes", event_id])
        self.assertEqual(event_path.read_bytes(), before)
        events = [read_note(path)[0] for path in (self.root / "Coordination" / "Items").glob("EVENT-*.md")]
        self.assertTrue(any(event.get("supersedes") == event_id for event in events))

    def test_same_second_events_have_unique_ids(self) -> None:
        self.claim()
        self.change()
        self.change()
        ids = [read_note(path)[0]["event_id"] for path in (self.root / "Coordination" / "Items").glob("EVENT-*.md")]
        self.assertEqual(len(ids), len(set(ids)))

    def test_actor_identity_collision_is_rejected(self) -> None:
        self.tracker("sync", "--actor", "taylor-codex", "--human", "Not Taylor", "--agent", "Codex", expected=1)

    def test_email_actor_id_is_rejected(self) -> None:
        self.tracker("sync", "--actor", "test@example.com", "--human", "Test", "--agent", "Codex", expected=1)

    def test_dependency_cycle_is_detected(self) -> None:
        self.claim()
        self.claim("CONTROL-002", "control.py", "jordan-codex", "Jordan", ["--depends-on", "ARCH-001"])
        data, body = read_note(self.work_path())
        data["depends_on"] = ["CONTROL-002"]
        data["dependency_baseline"] = ["CONTROL-002@1"]
        write_note(self.work_path(), data, body)
        self.assertIn("Dependency cycle", self.tracker("validate", expected=1).stdout)

    def test_base_yaml_and_view_structure(self) -> None:
        base = yaml.safe_load((self.root / "Coordination" / "Workspace.base").read_text())
        self.assertIn(PORTABLE_ITEMS_FILTER, base["filters"]["and"])
        names = {view["name"] for view in base["views"]}
        self.assertTrue({"Current work", "Recent activity", "Open handoffs", "Stale claims"}.issubset(names))
        self.assertTrue(all(view["type"] == "table" for view in base["views"]))

    def test_nested_obsidian_path_is_scoped(self) -> None:
        vault = Path(self.temporary.name) / "Vault"
        (vault / ".obsidian").mkdir(parents=True)
        target = vault / "Projects" / "Nested"
        target.mkdir(parents=True)
        self.setup_project(target)
        base = yaml.safe_load((target / "Coordination" / "Workspace.base").read_text())
        self.assertIn(PORTABLE_ITEMS_FILTER, base["filters"]["and"])
        self.assertEqual(read_note(target / "README.md")[0]["type"], "project")

    def test_dashboard_special_characters_roundtrip_through_yaml(self) -> None:
        setup_module = load_script("workspace_setup_fixture", SETUP)
        tracker_module = load_script("workspace_tracker_fixture", SKILL_ROOT / "assets" / "project_tracker.py")
        # Test even characters disallowed in actual Windows filenames without
        # making the cross-platform suite create an invalid local directory.
        folder = 'Projects/Team\'s café: "notes"/Coordination/Items'
        content = setup_module.dashboard_content(folder)
        filters = yaml.safe_load(content)["filters"]["and"]
        expected = f"file.inFolder({json.dumps(folder, ensure_ascii=False)})"
        self.assertIn(expected, filters)
        self.assertTrue(all(isinstance(expression, str) for expression in filters))
        self.assertEqual(tracker_module.configured_items_folder(content), folder)
        self.assertEqual(tracker_module.configured_items_folder('    - file.inFolder("Coordination/Items")\n'), "Coordination/Items")
        self.assertEqual(tracker_module.configured_items_folder("    - '" + expected.replace("'", "''") + "'\n"), folder)
        self.assertIsNone(tracker_module.configured_items_folder("    - " + expected + "\n"))

        vault = Path(self.temporary.name) / "QuotedVault"
        (vault / ".obsidian").mkdir(parents=True)
        target = vault / "Projects" / "Team's café ‘notes’"
        target.mkdir(parents=True)
        self.setup_project(target)
        installed = (target / "Coordination" / "Workspace.base").read_text(encoding="utf-8")
        installed_filters = yaml.safe_load(installed)["filters"]["and"]
        self.assertIn(PORTABLE_ITEMS_FILTER, installed_filters)
        self.run_command([sys.executable, str(target / "Coordination" / "project_tracker.py"), "validate"])

    def test_dashboard_layout_change_is_detected_and_reviewed_rebase_works(self) -> None:
        vault = Path(self.temporary.name) / "OriginalVault"
        (vault / ".obsidian").mkdir(parents=True)
        target = vault / "Projects" / "Nested"
        target.mkdir(parents=True)
        self.setup_project(target)
        setup_module = load_script("workspace_legacy_setup_fixture", SETUP)
        (target / "Coordination/Workspace.base").write_text(
            setup_module.dashboard_content("Projects/Nested/Coordination/Items"), encoding="utf-8"
        )
        self.run_command([sys.executable, str(target / "Coordination/project_tracker.py"), "validate"])
        recipient = Path(self.temporary.name) / "CopiedProjectVault"
        shutil.copytree(target, recipient)
        (recipient / ".obsidian").mkdir()
        before = snapshot(recipient)
        result = self.run_command([sys.executable, str(recipient / "Coordination" / "project_tracker.py"), "validate"], expected=1)
        self.assertIn("does not match this vault layout", result.stdout)
        self.assertIn("--dry-run --upgrade-managed", result.stdout)
        self.assertEqual(before, snapshot(recipient))
        self.setup_project(recipient, ["--dry-run", "--upgrade-managed"])
        self.assertEqual(before, snapshot(recipient))
        self.setup_project(recipient, ["--upgrade-managed"])
        self.run_command([sys.executable, str(recipient / "Coordination" / "project_tracker.py"), "validate"])

    def test_shared_project_relocates_between_private_vaults_without_shared_writes(self) -> None:
        owner_vault = self.root.parent / "OwnerVault"
        recipient_vault = self.root.parent / "RecipientVault"
        for vault in (owner_vault, recipient_vault):
            (vault / ".obsidian").mkdir(parents=True)
            (vault / ".obsidian/private-settings.json").write_text('{"private": true}\n', encoding="utf-8")
            (vault / "Private.md").write_text("Private notes stay local\n", encoding="utf-8")
        private_before = {vault: snapshot(vault) for vault in (owner_vault, recipient_vault)}
        target = owner_vault / "Projects/Team"
        target.mkdir(parents=True)
        self.setup_project(target)
        recipient = recipient_vault / "Shared/Collaborations/Team"
        shutil.copytree(target, recipient)
        before = snapshot(target)
        self.assertEqual(before, snapshot(recipient))
        for project in (target, recipient):
            self.run_command([sys.executable, str(project / "Coordination/project_tracker.py"), "validate"])
            self.assertEqual(before, snapshot(project))
            self.assertFalse((project / ".obsidian").exists())
        for vault, original in private_before.items():
            current = snapshot(vault)
            self.assertTrue(all(current.get(path) == digest for path, digest in original.items()))

    def test_portable_dashboard_filter_contract_excludes_siblings_and_note_embeds(self) -> None:
        # Exercise the emitted expression against documented Bases semantics.
        # This is a contract test, not evidence of native Obsidian rendering.
        base = yaml.safe_load((self.root / "Coordination/Workspace.base").read_text())
        filters = base["filters"]["and"]
        self.assertIn(PORTABLE_ITEMS_FILTER, filters)
        for folder in ("Projects/Team/Coordination", "Shared/Collaborations/Team/Coordination"):
            record_paths = [folder + "/Items/WORK-ONE.md", folder + "/Items-copy/WORK-OTHER.md",
                            "Private/Coordination/Items/WORK-PRIVATE.md", "OtherTeam/Coordination/Items/WORK-OTHER.md"]
            def selected(context_ext: str) -> list[str]:
                context = SimpleNamespace(file=SimpleNamespace(ext=context_ext, folder=folder))
                result = []
                for path in record_paths:
                    record = SimpleNamespace(ext="md", inFolder=lambda value: path == value or path.startswith(value + "/"))
                    if all(eval(expression.replace("&&", "and"), {"__builtins__": {}},
                                {"this": context, "file": record}) for expression in filters):
                        result.append(path)
                return result
            self.assertEqual(selected("base"), [record_paths[0]])
            self.assertEqual(selected("md"), [])
            self.assertEqual(selected("canvas"), [])

    def test_portable_dashboard_requires_context_guard(self) -> None:
        path = self.root / "Coordination/Workspace.base"
        path.write_text(path.read_text().replace('this.file.ext == "base" && ', ''), encoding="utf-8")
        before = snapshot(self.root)
        self.tracker("validate", expected=1)
        self.assertEqual(before, snapshot(self.root))

    def test_git_and_hybrid_modes(self) -> None:
        root = Path(self.temporary.name) / "GitProject"
        (root / ".git").mkdir(parents=True)
        self.setup_project(root)
        self.assertIn("Collaboration mode: `git`", (root / "AGENTS.md").read_text())
        self.setup_project(root, ["--collaboration-mode", "hybrid", "--upgrade-managed"])
        self.assertIn("Collaboration mode: `hybrid`", (root / "AGENTS.md").read_text())

    def test_nested_project_inherits_enclosing_git_mode(self) -> None:
        repository = Path(self.temporary.name) / "Repository"
        (repository / ".git").mkdir(parents=True)
        root = repository / "Projects" / "Nested"
        root.mkdir(parents=True)
        self.setup_project(root)
        self.assertIn("Collaboration mode: `git`", (root / "AGENTS.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
