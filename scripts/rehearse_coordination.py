#!/usr/bin/env python3
"""Rehearse schema-2 coordination through an explicitly selected real package.

Sequential fictional actors on one computer. No provider, accounts, UI or network
service. Requires Python 3.11+ and a fresh output directory whose parent exists.
The preserved fixture contains PRIVATE credentials/state: never share it wholesale.
Only report.json is a sanitized demonstration report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class RehearsalFailure(Exception):
    """Deliberately contains only a fixed phase label, never tool output."""


def require(condition, label):
    if not condition:
        raise RehearsalFailure(label)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rehearse(package, root):
    started = time.monotonic()
    report = {
        "schema_version": 1, "status": "running", "package_sha256": sha(package.read_bytes()),
        "coordination_schema": 2, "commands": [], "checks": {}, "accepted_revisions": [],
        "claim_limits": {"max_proposals": 4, "max_files": 1, "max_bytes": 4096,
                         "lease_seconds": 240, "session_seconds": 900},
        "limitations": [
            "Sequential synthetic actors on one computer; not independent people or AI model sessions.",
            "Same-machine database route, not hosted coordinator or provider-delivered bytes.",
            "No cloud synchronization, independent-recipient onboarding or TEAM-11 acceptance.",
            "Ownership refusal does not block arbitrary external editor writes.",
            "Duplicate outcome keys are checked; no perfect semantic duplicate detection claimed.",
            "Read-only graph analysis is not an Obsidian UI or native rename test.",
            "Credentials and runtime state remain private in this fixture; only report.json is sanitized.",
        ],
    }
    phase = "prepare_fixture"
    counter = 0
    projects, states = {}, {}
    preserved = {}

    def save_report():
        report["commands_checked"] = len(report["commands"])
        report["expected_refusals"] = sum(x["expected_exit"] != 0 for x in report["commands"])
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        serialized = json.dumps(report, indent=2) + "\n"
        require(str(root) not in serialized and str(package) not in serialized, "report_path_leak")
        for token_file in root.rglob("*.token"):
            require(token_file.read_text().strip() not in serialized, "report_credential_leak")
        (root / "report.json").write_text(serialized, encoding="utf-8")

    def payload(value):
        nonlocal counter
        counter += 1
        file = root / "inputs" / f"request-{counter:03d}.json"
        file.write_text(json.dumps(value), encoding="utf-8")
        return file

    def cli(label, command, actor=None, *options, expected=0):
        nonlocal phase
        phase = label
        remaining = 180 - (time.monotonic() - started)
        require(remaining > 0, "rehearsal_deadline")
        args = [sys.executable, str(package), command]
        if actor:
            args += [str(projects[actor]), "--state-dir", str(states[actor])]
        args += list(map(str, options))
        completed = subprocess.run(args, cwd=root, capture_output=True, timeout=min(30, remaining))
        require(len(completed.stdout) <= 2 * 1024 * 1024, "cli_output_limit")
        record = {"step": label, "command": command, "actor": actor,
                  "expected_exit": expected, "actual_exit": completed.returncode}
        report["commands"].append(record)
        require(completed.returncode == expected, label)
        response = json.loads(completed.stdout)
        require(response.get("ok") is (expected == 0), label)
        record["matched_expectation"] = True
        return response.get("data") if expected == 0 else None

    def coord(label, operation, value=None, actor="alex", session=False, expected=0):
        options = [operation, "--payload-file", payload(value or {})]
        if session:
            options += ["--session-token-file", states[actor] / "sessions" / (actor + "-run") / "session.token"]
        return cli(label, "coord", actor, *options, expected=expected)

    def policy():
        return coord("read_policy", "policy")

    def assignment(identity="demo"):
        return coord("read_assignment", "assignment", {"assignment_id": identity})

    def context(actor, identity="demo"):
        item = assignment(identity)
        return {"session_id": actor + "-run", "generation": item["generation"],
                "input_hash": item["input_hash"], "policy_revision": policy()["policy_revision"]}

    def acquire(actor, receipt, identity="demo", expected=0):
        return coord("acquire_" + identity + "_" + actor, "acquire", {
            "assignment_id": identity, "expected_generation": assignment(identity)["generation"],
            "ttl_seconds": 240, "revision": receipt["revision"], "files_hash": receipt["files_hash"],
            "policy_revision": policy()["policy_revision"]}, actor, True, expected)

    def draft(actor, proposal_id, ctx):
        return cli("draft_" + proposal_id, "draft", actor, "--proposal-id", proposal_id,
                   "--assignment-id", "demo", "--evidence", "Compared exact synthetic Markdown bytes",
                   "--coordination-file", payload(ctx))

    def submit(actor, proposal_id, expected=0):
        return cli("submit_" + proposal_id, "submit", actor, "--proposal-id", proposal_id,
                   "--session-token-file", states[actor] / "sessions" / (actor + "-run") / "session.token",
                   expected=expected)

    def accept(proposal_id):
        accepted = coord("accept_" + proposal_id, "accept", {
            "proposal_id": proposal_id, "validation": "Exact synthetic proposal content reviewed",
            "reason": "Bounded local CLI rehearsal", "coordination": context("alex")}, session=True)
        require(accepted.get("accepted") is True, "acceptance_required")
        report["accepted_revisions"].append({"revision": accepted["revision"], "files_hash": accepted["files_hash"]})
        return accepted

    try:
        (root / "inputs").mkdir()
        home = b"# Shared project\n\n[Demo result](Result.md)\n"
        instructions = b"# Project instructions\n\nPreserve existing project evidence.\n"
        first = "# Demo result\n\nOwner verified the offline plan.\n\n[Project](Home.md)\n"
        second = "# Demo result\n\nRecipient verified the offline plan.\n\n[Project](Home.md)\n"
        for actor in ("alex", "sam"):
            parent = root / (actor + "-private-folder")
            projects[actor] = parent / "Projects" / "Shared Demo"
            states[actor] = root / (actor + "-private-state")
            projects[actor].mkdir(parents=True)
            fixtures = {parent / "Private.md": b"Synthetic private parent note.\r\n",
                        parent / "Home.md": b"Private parent home.\n",
                        parent / "AGENTS.md": b"Private parent instructions.\n",
                        projects[actor] / "Home.md": home,
                        projects[actor] / "AGENTS.md": instructions,
                        projects[actor] / "attachment.bin": b"\x00Synthetic binary attachment\xff"}
            for file, content in fixtures.items():
                file.write_bytes(content)
                preserved[file] = content
        config = payload({"person_id": "person-alex", "agent_id": "agent-alex", "policy": {}})
        created = cli("initialize_schema2", "init", "alex", "--person", "Alex Fictional", "--actor", "alex",
                      "--agent", "Synthetic owner CLI", "--purpose", "Local coordination rehearsal",
                      "--coordination-file", config)
        status = coord("verify_schema2", "status")
        require(status["coordination"]["schema_version"] == 2, "schema2_required")
        member = root / "sam.token"
        cli("add_recipient_member", "member-add", "alex", "--actor", "sam", "--person", "Sam Fictional",
            "--agent", "Synthetic recipient CLI", "--token-output", member)
        coord("bind_recipient_identity", "member-binding", {"actor": "sam", "person_id": "person-sam", "agent_id": "agent-sam"})
        joined = cli("attach_recipient", "attach", "sam", "--database", states["alex"] / "coordinator.sqlite3",
                     "--token-file", member, "--expected-project-id", created["project_id"])
        require(joined["coordinator_membership"] == "verified", "recipient_membership")
        for actor, role in (("alex", "owner"), ("sam", "contributor")):
            grants = payload({"ttl_seconds": 900, "scopes": policy()["policy"]["session_scopes"][role], "targets": ["."]})
            result = cli("create_own_session_" + actor, "session-create", actor,
                         "--session-id", actor + "-run", "--grants-file", grants)
            require(result["session"]["actor"] == actor and result["credential_saved"], "session_identity")
        def plan(identity, outcome, targets, expected=0):
            return coord("plan_" + identity, "plan", {"assignment_id": identity, "outcome_key": outcome,
                "summary": "Deliver the synthetic offline result", "targets": targets,
                "criteria": ["Compare exact accepted and materialized content"], "dependencies": [],
                "interface_paths": [], "resource_limits": {"max_proposals": 4, "max_files": 1, "max_bytes": 4096},
                "integration_owner": "alex", "policy_revision": policy()["policy_revision"]}, session=True, expected=expected)
        plan("demo", "offline-result", ["Result.md"])
        initial = cli("initial_recipient_receipt", "receipt", "sam")
        first_lease = acquire("alex", initial)
        before_refusals = coord("before_refusals", "snapshot")
        plan("duplicate", "offline-result", ["Other.md"], expected=4)
        plan("overlap", "separate-outcome", ["Result.md"])
        acquire("sam", initial, "overlap", expected=4)
        require(coord("after_refusals", "snapshot") == before_refusals, "refusals_preserve_accepted_state")
        owner_context = context("alex")
        (projects["alex"] / "Result.md").write_bytes(first.encode())
        draft("alex", "owner-result", owner_context)
        proposed = submit("alex", "owner-result")
        require(proposed["changes"] == {"Result.md": first}, "owner_proposal_bytes")
        accepted1 = accept("owner-result")
        require(accepted1["revision"] == initial["revision"] + 1, "first_revision")
        cli("refresh_owner", "refresh", "alex")
        (projects["alex"] / "Result.md").write_bytes(b"# Stale owner edit\n")
        draft("alex", "stale-owner", owner_context)
        old_draft = states["alex"] / "client/drafts/stale-owner.json"
        old_bytes = old_draft.read_bytes()
        coord("handoff_to_recipient", "handoff", {"assignment_id": "demo", "to_actor": "sam",
            "summary": "Verify exact receipt and continue the synthetic plan", "coordination": owner_context}, session=True)
        submit("alex", "stale-owner", expected=4)
        acquire("sam", initial, expected=4)
        require(old_draft.read_bytes() == old_bytes, "stale_draft_preserved")
        current = coord("after_handoff_refusals", "snapshot")
        require(current["revision"] == accepted1["revision"] and current["files"]["Result.md"] == first,
                "handoff_refusals_preserve_revision")
        cli("refresh_recipient", "refresh", "sam")
        receipt1 = cli("recipient_receipt", "receipt", "sam")
        require(receipt1["readiness"] == "ready" and receipt1["revision"] == accepted1["revision"]
                and receipt1["files_hash"] == accepted1["files_hash"], "recipient_exact_receipt")
        require((projects["sam"] / "Result.md").read_bytes() == first.encode(), "recipient_first_bytes")
        new_lease = acquire("sam", receipt1)
        require(new_lease["actor"] == "sam" and new_lease["generation"] > first_lease["generation"], "new_owner_generation")
        recipient_context = context("sam")
        (projects["sam"] / "Result.md").write_bytes(second.encode())
        draft("sam", "recipient-result", recipient_context)
        proposed = submit("sam", "recipient-result")
        require(proposed["changes"] == {"Result.md": second}, "recipient_proposal_bytes")
        accepted2 = accept("recipient-result")
        require(accepted2["revision"] == accepted1["revision"] + 1, "second_revision")
        for actor in ("alex", "sam"):
            cli("final_refresh_" + actor, "refresh", actor)
            receipt = cli("final_receipt_" + actor, "receipt", actor)
            require(receipt["readiness"] == "ready" and receipt["revision"] == accepted2["revision"]
                    and receipt["files_hash"] == accepted2["files_hash"], "final_receipts_agree")
            require((projects[actor] / "Result.md").read_bytes() == second.encode(), "final_exact_content")
        finished = coord("recipient_completes", "complete", {"assignment_id": "demo", "revision": accepted2["revision"],
            "files_hash": accepted2["files_hash"], "evidence": "Both materialized files compared byte for byte",
            "coordination": recipient_context}, "sam", True)
        require(finished["status"] == "completed", "completion")
        before_graph = {p.relative_to(projects["sam"]).as_posix(): sha(p.read_bytes()) for p in projects["sam"].rglob('*') if p.is_file()}
        graph = cli("read_only_graph", "graph", None, projects["sam"])
        require(graph["summary"]["resolved_links"] == 2 and not graph["diagnostics"], "graph_links")
        after_graph = {p.relative_to(projects["sam"]).as_posix(): sha(p.read_bytes()) for p in projects["sam"].rglob('*') if p.is_file()}
        require(before_graph == after_graph, "graph_does_not_mutate")
        require(all(file.read_bytes() == content for file, content in preserved.items()), "fixture_preservation")
        require(old_draft.read_bytes() == old_bytes, "immutable_stale_draft")
        require(sha(package.read_bytes()) == report["package_sha256"], "package_unchanged")
        report["checks"] = {"distinct_member_and_session_identities": True, "duplicate_outcome_refused": True,
            "overlapping_lease_refused": True, "stale_owner_submission_refused": True,
            "stale_recipient_receipt_refused": True, "two_accepted_revisions": True,
            "exact_materialized_content": True, "immutable_old_draft": True,
            "parent_home_instructions_attachment_preserved": True, "read_only_graph": True}
        report["preservation_sha256"] = {file.relative_to(root).as_posix(): sha(content) for file, content in preserved.items()}
        report["graph_summary"] = graph["summary"]
        report["preserved_stale_draft_sha256"] = sha(old_bytes)
        report["final_result_sha256"] = sha(second.encode())
        if os.name != "nt":
            require(root.stat().st_mode & 0o077 == 0, "private_fixture_mode")
            require(all(p.stat().st_mode & 0o077 == 0 for p in root.rglob("*.token")), "private_token_modes")
            report["private_posix_modes"] = "verified"
        else:
            report["private_posix_modes"] = "not_applicable; enclosing Windows ACL requires operator review"
        report["unacquired_overlap_plan_retained"] = True
        report["status"] = "passed"
    except Exception:
        report["status"] = "failed"
        report["failed_step"] = phase
        save_report()
        raise RehearsalFailure(phase) from None
    save_report()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous_umask = os.umask(0o077)
    try:
        require(sys.version_info >= (3, 11), "python_311_required")
        package = args.package.expanduser().resolve(strict=True)
        require(package.is_file() and package.suffix == ".pyz" and package.stat().st_size <= 32 * 1024 * 1024,
                "explicit_package_required")
        requested = args.output.expanduser().absolute()
        require(not os.path.lexists(requested), "output_already_exists")
        parent = requested.parent.resolve(strict=True)
        root = parent / requested.name
        root.mkdir(mode=0o700, exist_ok=False)
        report = rehearse(package, root)
        print(json.dumps({"status": report["status"], "commands_checked": report["commands_checked"],
                          "expected_refusals": report["expected_refusals"], "report": "report.json"}))
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        label = str(exc) if isinstance(exc, RehearsalFailure) else "rehearsal_unavailable"
        print(json.dumps({"status": "failed", "reason": label}), file=sys.stderr)
        return 1
    finally:
        os.umask(previous_umask)


if __name__ == "__main__":
    raise SystemExit(main())
