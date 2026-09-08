#!/usr/bin/env python3
"""Demonstrate one Markdown project folder, optionally in a synthetic existing vault."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SETUP = REPO / "skills/setup-shared-project-workspace/scripts/setup_workspace.py"
TRACKER = REPO / "skills/setup-shared-project-workspace/assets/project_tracker.py"
LIMITATIONS = (
    "Synthetic fictional actors run sequentially on one computer. No real agents, "
    "sharing permissions, cloud synchronization, cross-device locking, authentication, Obsidian UI, "
    "load testing, or production readiness are demonstrated. Claims are advisory."
)


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


class Demo:
    def __init__(self, output: Path, step: bool, layout: str = "plain"):
        self.output = output
        self.layout = layout
        self.parent = output / ("existing-vault" if layout == "existing-vault" else "plain-folder")
        self.root = self.parent / "Projects" / "Shared Demo"
        self.root.mkdir(parents=True)
        # Fixtures only: no real vault is read, opened, registered, or configured.
        if layout == "existing-vault":
            (self.parent / ".obsidian").mkdir()
        (self.parent / "Private.md").write_text(
            "# Private synthetic note\n\nKeep outside the shared project folder.\n", encoding="utf-8")
        (self.parent / "AGENTS.md").write_text(
            "# Synthetic parent instructions\n\nPreserve private notes and parent configuration.\n",
            encoding="utf-8")
        (self.root / "Home.md").write_text(
            "# Existing shared project\n\nThis fictional project note predates toolkit setup.\n",
            encoding="utf-8")
        self.parent_before = self.parent_snapshot()
        self.home_before = hashlib.sha256((self.root / "Home.md").read_bytes()).hexdigest()
        self.step = step
        self.report = {
            "schema_version": 1, "status": "running",
            "started_utc": datetime.now(timezone.utc).isoformat(),
            "layout": layout, "workspace": self.root.relative_to(output).as_posix(),
            "limitations": LIMITATIONS,
            "fixture_boundary": {"parent_before": self.parent_before,
                                 "existing_home_sha256_before": self.home_before},
            "source_sha256": {p.relative_to(REPO).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (SETUP, TRACKER)},
            "commands": [],
        }
        self.save()

    def parent_snapshot(self) -> dict[str, str]:
        return {p.relative_to(self.parent).as_posix():
                ("directory" if p.is_dir() else hashlib.sha256(p.read_bytes()).hexdigest())
                for p in sorted(self.parent.rglob("*"))
                if p != self.root and not p.is_relative_to(self.root)}

    def verify_boundary(self) -> bool:
        after = self.parent_snapshot()
        home = self.root / "Home.md"
        home_after = hashlib.sha256(home.read_bytes()).hexdigest() if home.is_file() else "missing"
        preserved = (after == self.parent_before and home_after == self.home_before
                     and not (self.root / ".obsidian").exists())
        self.report["fixture_boundary"].update(
            parent_after=after, existing_home_sha256_after=home_after,
            parent_and_existing_home_unchanged=preserved,
            obsidian_fixture_present=(self.parent / ".obsidian").is_dir(),
            nested_vault_configuration_absent=not (self.root / ".obsidian").exists())
        return preserved

    def save(self):
        (self.output / "report.json").write_text(
            json.dumps(self.report, indent=2) + "\n", encoding="utf-8")

    def stage(self, title: str):
        print("\n" + title, flush=True)
        if self.step:
            input("Press Enter to run this stage (Ctrl-C stops and preserves files): ")

    def run(self, label: str, command: list[str], reject: str = ""):
        before = snapshot(self.root) if reject else None
        result = subprocess.run(command, cwd=self.root, text=True, capture_output=True,
                                check=False, timeout=60)
        outcome = {"label": label, "argv": command, "exit_code": result.returncode,
                   "expected_exit_code": 1 if reject else 0,
                   "stdout": result.stdout, "stderr": result.stderr}
        outcome["fixture_boundary_preserved"] = self.verify_boundary()
        passed = result.returncode == outcome["expected_exit_code"] and outcome["fixture_boundary_preserved"]
        if reject:
            outcome["expected_error_contains"] = reject
            outcome["workspace_unchanged"] = before == snapshot(self.root)
            passed = passed and reject.lower() in (result.stdout + result.stderr).lower()
            passed = passed and outcome["workspace_unchanged"]
        outcome["passed"] = passed
        self.report["commands"].append(outcome)
        self.save()
        print(("PASS" if passed else "FAIL") + ": " + label, flush=True)
        if reject:
            print("  " + result.stderr.strip(), flush=True)
        if not passed:
            raise RuntimeError(f"{label}: unexpected command result; see report.json")
        return result

    def tracker(self, label: str, *args: str, reject: str = ""):
        return self.run(label, [sys.executable, str(self.root / "Coordination/project_tracker.py"),
                                *args], reject=reject)

    def claim(self, work: str, actor: str, owner: str, target: str, reject: str = ""):
        self.tracker(f"{owner} claims {target}", "claim", "--work-id", work,
                     "--title", f"Fictional demo: {target}", "--actor", actor,
                     "--owner", owner, "--agent", "Scripted demo actor",
                     "--initiated-by", owner, "--target", target,
                     "--target", f"Evidence/{work}.json",
                     "--objective", "Produce the tiny example note and check its exact content",
                     "--acceptance", "Note contains the expected demo text",
                     "--acceptance", "Recipient or owner reruns the content validation",
                     "--next-action", "Check ownership and write the example note", reject=reject)

    def check(self, work: str, actor: str):
        self.tracker(f"{actor} checks {work} before mutation", "check", "--actor", actor,
                     "--work-id", work)

    def validate_note(self, work: str, target: str, expected: str):
        # A separate Python process checks actual bytes before recording evidence.
        code = (
            "import hashlib,json,pathlib,sys; "
            "p=pathlib.Path(sys.argv[1]); actual=p.read_text(encoding='utf-8'); "
            "expected=sys.argv[2]; "
            "result={'check':'exact demo content','target':sys.argv[1],"
            "'passed':actual==expected,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}; "
            "pathlib.Path(sys.argv[3]).write_text(json.dumps(result,indent=2)+'\\n',encoding='utf-8'); "
            "print(json.dumps(result)); sys.exit(0 if result['passed'] else 1)"
        )
        self.run(f"Validate actual content of {target}", [sys.executable, "-c", code,
                 target, expected, f"Evidence/{work}.json"])

    def change(self, work: str, actor: str, summary: str, both: bool = False):
        args = ["change", "--actor", actor, "--work-id", work,
                "--summary", summary, "--change-kind", "validation", "--impact", "none",
                "--pass-criterion", "1", "--evidence", f"Evidence/{work}.json",
                "--validation", "Separate Python process compared exact note content and recorded SHA-256.",
                "--limitations", LIMITATIONS,
                "--next-action", "Complete the bounded demo work" if both else "Hand off for a second scripted check"]
        if both:
            args += ["--pass-criterion", "2"]
        self.tracker(f"Record change and evidence for {work}", *args)

    def complete(self, work: str, actor: str):
        self.tracker(f"Complete {work}", "complete", "--actor", actor, "--work-id", work,
                     "--summary", "Both tiny demo acceptance criteria passed",
                     "--evidence", f"Evidence/{work}.json",
                     "--validation", "Exact content validation passed in a separate Python process.",
                     "--limitations", LIMITATIONS, "--impact", "none",
                     "--next-action", "Demo finished; no actual project work or deployment implied")

    def execute(self):
        self.stage(f"1/6 Retrofit one existing project folder (layout: {self.layout})")
        self.run("Bundled setup", [sys.executable, str(SETUP), str(self.root),
                 "--mode", "retrofit", "--collaboration-mode", "local-only",
                 "--project-name", "Fictional small-team stage demo",
                 "--project-home", "Home.md",
                 "--actor", "alex-demo", "--initiated-by", "Alex (fictional)",
                 "--agent", "Scripted demo actor"])
        (self.root / "Evidence").mkdir()
        for actor, human in (("alex-demo", "Alex (fictional)"), ("sam-demo", "Sam (fictional)")):
            self.tracker(f"Register and refresh {actor}", "sync", "--actor", actor,
                         "--human", human, "--agent", "Scripted demo actor")

        self.stage("2/6 Two fictional contributors claim separate files")
        self.claim("BRIEF", "alex-demo", "Alex (fictional)", "Brief.md")
        self.claim("CHECKLIST", "sam-demo", "Sam (fictional)", "Checklist.md")
        self.tracker("Show distinct ownership", "status")

        self.stage("3/6 Reject an overlapping claim without changing records")
        self.claim("OVERLAP", "sam-demo", "Sam (fictional)", "Brief.md", reject="overlaps")

        self.stage("4/6 Write a tiny note, check it, and record evidence")
        brief = "# Demo brief\n\nA shared workspace makes ownership and handoffs visible.\n"
        self.check("BRIEF", "alex-demo")
        (self.root / "Brief.md").write_text(brief, encoding="utf-8")
        self.validate_note("BRIEF", "Brief.md", brief)
        self.change("BRIEF", "alex-demo", "Created and checked the fictional demo brief")

        self.stage("5/6 Hand off, reject premature continuation, then accept")
        self.tracker("Alex hands off BRIEF to Sam", "handoff", "--actor", "alex-demo",
                     "--work-id", "BRIEF", "--to-actor", "sam-demo",
                     "--to-owner", "Sam (fictional)", "--to-agent", "Scripted demo actor",
                     "--last-verified", "Exact brief content passed; evidence records its SHA-256.",
                     "--evidence", "Evidence/BRIEF.json", "--limitations", LIMITATIONS,
                     "--next-action", "Accept the handoff, check ownership, rerun validation, and complete")
        self.tracker("Reject check before handoff acceptance", "check", "--actor", "sam-demo",
                     "--work-id", "BRIEF", reject="Accept the pending handoff")
        self.tracker("Reject change before handoff acceptance", "change", "--actor", "sam-demo",
                     "--work-id", "BRIEF", "--summary", "Premature continuation probe",
                     "--change-kind", "validation", "--impact", "none",
                     "--next-action", "Accept handoff first", reject="Accept the pending handoff")
        self.tracker("Sam refreshes records", "sync", "--actor", "sam-demo")
        self.tracker("Sam accepts handoff", "accept-handoff", "--actor", "sam-demo",
                     "--work-id", "BRIEF", "--summary", "Scripted recipient reviewed the handoff and actual note",
                     "--next-action", "Check ownership and rerun exact content validation")
        self.check("BRIEF", "sam-demo")
        self.validate_note("BRIEF", "Brief.md", brief)
        self.change("BRIEF", "sam-demo", "Scripted recipient reran the actual content check", both=True)
        self.complete("BRIEF", "sam-demo")

        self.stage("6/6 Finish the second file and validate the workspace")
        checklist = "# Demo checklist\n\n- Claim a target.\n- Record evidence.\n- Accept a handoff.\n"
        self.check("CHECKLIST", "sam-demo")
        (self.root / "Checklist.md").write_text(checklist, encoding="utf-8")
        self.validate_note("CHECKLIST", "Checklist.md", checklist)
        self.change("CHECKLIST", "sam-demo", "Created and checked the fictional checklist")
        self.check("CHECKLIST", "sam-demo")
        self.validate_note("CHECKLIST", "Checklist.md", checklist)
        self.change("CHECKLIST", "sam-demo", "Owner reran exact checklist validation", both=True)
        self.complete("CHECKLIST", "sam-demo")
        self.tracker("Validate generated records", "validate")
        final_check = (
            "import importlib.util,json,pathlib,sys; "
            "spec=importlib.util.spec_from_file_location('demo_tracker',sys.argv[1]); "
            "tracker=importlib.util.module_from_spec(spec); spec.loader.exec_module(tracker); "
            "records=[tracker.read_record(pathlib.Path('Coordination/Items')/('WORK-'+w+'.md'))[0] "
            "for w in ('BRIEF','CHECKLIST')]; "
            "summary=[{k:r[k] for k in ('work_id','status','actor_id','acceptance_passed',"
            "'acceptance_total','handoff_pending')} for r in records]; "
            "print(json.dumps(summary)); "
            "sys.exit(0 if all(r['status']=='verified' and r['actor_id']=='SAM-DEMO' "
            "and r['acceptance_passed']==r['acceptance_total']==2 "
            "and not r['handoff_pending'] for r in records) else 1)"
        )
        final_result = self.run("Verify final owners and acceptance state", [
            sys.executable, "-c", final_check, str(self.root / "Coordination/project_tracker.py")])
        self.report["final_work"] = json.loads(final_result.stdout)
        result = self.tracker("Show final work status", "status")
        print(result.stdout.strip(), flush=True)
        self.report["workspace_sha256"] = snapshot(self.root)
        if not self.verify_boundary():
            raise RuntimeError("Fixture boundary changed; inspect report.json")
        print("PASS: Private parent notes, parent layout, and existing project Home.md preserved", flush=True)
        self.report["status"] = "passed"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Fresh nonexistent directory under an existing parent; choose outside synced folders")
    parser.add_argument("--layout", choices=("plain", "existing-vault"), default="plain",
                        help="Plain Markdown folder by default; existing-vault adds only an empty synthetic .obsidian fixture")
    parser.add_argument("--step", action="store_true", help="Pause before each of the six stages")
    args = parser.parse_args()
    if args.step and not sys.stdin.isatty():
        parser.error("--step requires an interactive terminal")
    output = args.output.expanduser().absolute()
    try:
        output.mkdir(exist_ok=False)
    except OSError as exc:
        print(f"Refusing output: must be a fresh directory under an existing parent: {exc}", file=sys.stderr)
        return 2
    demo = None
    try:
        demo = Demo(output, args.step, args.layout)
        print(LIMITATIONS, flush=True)
        demo.execute()
    except (KeyboardInterrupt, EOFError):
        if demo:
            demo.report.update(status="interrupted", error="Stopped before all stages completed")
        return 130
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        if demo:
            demo.report.update(status="failed", error=str(exc))
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        if demo:
            demo.report["finished_utc"] = datetime.now(timezone.utc).isoformat()
            demo.save()
            print(f"Preserved workspace: {demo.root}\nReport: {output / 'report.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
