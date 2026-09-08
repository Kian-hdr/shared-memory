#!/usr/bin/env python3
"""Read-only local workspace diagnostics; never execute code from the target."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def diagnose(target: Path) -> dict:
    report = {
        "project": str(target),
        "python": sys.version.split()[0],
        "local_status": "blocked",
        "collaboration_mode": "unknown",
        "checks": [],
        "external_checks": {
            "agent_instructions_loaded": "unverified",
            "obsidian_vault_and_dashboard": "unverified",
            "provider_propagation": "unverified",
            "other_device_receipt": "unverified",
        },
        "next_action": "Inspect the diagnostics before setup or repair.",
    }
    checks = report["checks"]
    if not target.is_dir():
        checks.append({"name": "project_directory", "status": "fail", "detail": "Choose an existing project directory."})
        return report
    agents = target / "AGENTS.md"
    instructions = ""
    home_ok = False
    if agents.is_file():
        instructions = agents.read_text(encoding="utf-8")
        match = re.search(r"(?m)^Collaboration mode: `([^`]+)`", instructions)
        if match:
            report["collaboration_mode"] = match.group(1)
    if report["collaboration_mode"] == "local-only":
        report["external_checks"]["provider_propagation"] = "not_applicable"
        report["external_checks"]["other_device_receipt"] = "not_applicable"
    tracker = target / "Coordination" / "project_tracker.py"
    if not tracker.exists():
        if "shared-project-workspace:start" in instructions or (target / "Coordination").exists():
            checks.append({"name": "tracker", "status": "fail", "detail": "Tracker missing from an existing coordination workspace. Preserve records and obtain the owner's reviewed version; do not bootstrap to repair onboarding."})
            report["next_action"] = "Ask the project owner to review incomplete coordination files and restore the correct trusted tracker."
            return report
        report["local_status"] = "unconfigured"
        checks.append({"name": "tracker", "status": "missing", "detail": "No installed tracker; preserve existing notes and preview setup."})
        report["next_action"] = "Run setup_workspace.py with --mode audit, then preview the intended setup with --dry-run."
        return report
    home_match = re.search(r"(?m)^Project home: `([^`]+)`", instructions)
    if home_match:
        home = (target / home_match.group(1)).resolve()
        home_ok = home.is_relative_to(target) and home.is_file()
    checks.append({"name": "project_home", "status": "pass" if home_ok else "fail", "detail": "Declared home must be an existing file inside the project."})
    trusted = Path(__file__).resolve().parent.parent / "assets" / "project_tracker.py"
    installed_digest = hashlib.sha256(tracker.read_bytes()).hexdigest()
    trusted_digest = hashlib.sha256(trusted.read_bytes()).hexdigest()
    checks.append({"name": "tracker_matches_bundle", "status": "pass" if installed_digest == trusted_digest else "fail", "installed_sha256": installed_digest, "bundled_sha256": trusted_digest})
    result = subprocess.run(
        [sys.executable, str(trusted), "--project-root", str(target), "validate"],
        capture_output=True, text=True, check=False, timeout=60,
    )
    checks.append({"name": "workspace_validation", "status": "pass" if result.returncode == 0 else "fail", "detail": (result.stdout + result.stderr).strip()})
    if result.returncode == 0 and installed_digest == trusted_digest and home_ok:
        report["local_status"] = "validated"
        report["next_action"] = "Load AGENTS.md in your agent and verify the intended app and access method separately. Local validation does not establish shared readiness."
    else:
        report["next_action"] = "Review the reported mismatch or invalid records. Do not rerun bootstrap, replace the tracker, or delete history to clear a joining failure."
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Existing project root")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable diagnostics to stdout")
    args = parser.parse_args()
    target = Path(args.target).expanduser().resolve()
    try:
        report = diagnose(target)
    except (OSError, UnicodeError, subprocess.TimeoutExpired) as exc:
        report = {"project": str(target), "local_status": "blocked", "error": str(exc), "next_action": "Resolve the read or validation failure and rerun doctor; no repair was attempted."}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("Local workspace: " + report["local_status"])
        for check in report.get("checks", []):
            print(f"- {check['name']}: {check['status']}")
            if check.get("detail"):
                print(check["detail"])
        for name, status in report.get("external_checks", {}).items():
            print(f"- {name}: {status}")
        if report.get("error"):
            print(report["error"])
        print("Next: " + report["next_action"])
    return 0 if report["local_status"] == "validated" else 1


if __name__ == "__main__":
    raise SystemExit(main())
