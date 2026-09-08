#!/usr/bin/env python3
"""Exercise the real packaged TLS coordinator and two synthetic local clients.

Requires optional server dependencies plus OpenSSL. Creates only a fresh fixture;
never signs in, uses cloud storage, opens Obsidian or changes an existing project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    owner = root / "Owner private vault/Projects/Shared Demo"
    recipient = root / "Recipient private vault/Team/Shared Demo"
    for path in (owner, recipient):
        path.mkdir(parents=True)
        (path.parent / "Private.md").write_text("Synthetic private sibling.\n")
    (owner / "Home.md").write_text("# Shared Memory rehearsal\n\nSynthetic project.\n")
    state = root / "private-owner-state"
    other = root / "private-recipient-state"
    records = []
    def cli(command, project=None, private=None, *options):
        call = [sys.executable, str(args.package), command]
        if project is not None:
            call += [str(project), "--state-dir", str(private)]
        call += list(map(str, options))
        completed = subprocess.run(call, capture_output=True, text=True, timeout=40)
        data = json.loads(completed.stdout)
        if completed.returncode or not data["ok"]:
            raise AssertionError((command, data, completed.stderr))
        records.append({"command": command, "ok": True, "result": data["data"]})
        return data["data"]
    counter = 0
    def coord(operation, payload, project=owner, private=state):
        nonlocal counter
        counter += 1
        path = root / f"request-{counter}.json"
        path.write_text(json.dumps(payload))
        return cli("coord", project, private, operation, "--payload-file", path)
    created = cli("init", owner, state, "--person", "Alex Fictional", "--actor", "alex",
                  "--agent", "Synthetic owner CLI", "--purpose", "TLS fixture", "--mode", "team")
    member = root / "sam.token"
    cli("member-add", owner, state, "--actor", "sam", "--person", "Sam Fictional",
        "--agent", "Synthetic recipient CLI", "--token-output", member)
    cert, key = root / "fixture.crt", root / "fixture.key"
    result = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
        "-keyout", str(key), "-out", str(cert), "-days", "1", "-subj", "/CN=localhost",
        "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost"], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("OpenSSL fixture certificate generation failed")
    key.chmod(0o600)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with (root / "server.log").open("w") as server_log:
        server = subprocess.Popen([sys.executable, str(args.package), "serve", "--database",
            str(state / "coordinator.sqlite3"), "--port", str(port), "--certfile", str(cert),
            "--keyfile", str(key)], stdout=server_log, stderr=server_log)
        try:
            ready = False
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Packaged server exited before listening")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                        ready = True
                        break
                except OSError:
                    time.sleep(0.05)
            if not ready:
                raise RuntimeError("Packaged server did not listen")
            joined = cli("attach", recipient, other, "--endpoint", f"https://127.0.0.1:{port}",
                "--ca-file", cert, "--token-file", member, "--expected-project-id", created["project_id"])
            assert joined["coordinator_membership"] == "verified"
            coord("claim", {"assignment_id": "demo", "targets": ["Result.md"], "criteria": ["Compare exact content"],
                            "dependencies": [], "resource_limits": {"max_proposals": 3}, "integration_owner": "alex"})
            (owner / "Result.md").write_text("# Result\n\nReviewed accepted knowledge.\n")
            cli("draft", owner, state, "--proposal-id", "result-1", "--assignment-id", "demo", "--evidence", "Exact fixture content reviewed")
            cli("submit", owner, state, "--proposal-id", "result-1")
            accepted = coord("accept", {"proposal_id": "result-1", "validation": "Compared fixture bytes", "reason": "Bounded rehearsal"})
            assert accepted["accepted"]
            cli("refresh", owner, state)
            cli("refresh", recipient, other)
            receipt = cli("receipt", recipient, other)
            assert receipt["revision"] == accepted["revision"] and receipt["files_hash"] == accepted["files_hash"]
            assert (recipient / "Result.md").read_bytes() == (owner / "Result.md").read_bytes()
            coord("handoff", {"assignment_id": "demo", "to_actor": "sam", "summary": "Verify actual TLS receipt"})
            coord("receive", {"assignment_id": "demo", "revision": receipt["revision"], "files_hash": receipt["files_hash"]}, recipient, other)
            coord("complete", {"assignment_id": "demo", "revision": receipt["revision"], "files_hash": receipt["files_hash"],
                               "evidence": "Recipient compared exact materialized bytes"}, recipient, other)
            cli("context", recipient, other, "--query", "accepted knowledge")
            cli("provider-check", recipient, other)
            cli("backup-coordinator", None, None, "--database", state / "coordinator.sqlite3", "--destination", root / "verified-backup.sqlite3")
            for path in (owner, recipient):
                assert (path.parent / "Private.md").read_text() == "Synthetic private sibling.\n"
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
    serialized = json.dumps(records)
    for secret in (member, state / "member.token"):
        assert secret.read_text().strip() not in serialized
    report = {"package_sha256": hashlib.sha256(args.package.read_bytes()).hexdigest(),
              "python": sys.version, "commands_passed": len(records), "records": records,
              "verified": ["actual Uvicorn TLS server", "verified fixture CA and hostname", "authenticated recipient", "accepted revision receipt", "handoff and completion", "backup readback"],
              "limitations": ["two synthetic actors on one Mac", "loopback fixture certificate", "coordinator transfer, not cloud-provider sync", "mixed-OS TEAM-11 not run"],
              "server_stopped": server.poll() is not None}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"commands_passed": len(records), "report": str(root / "report.json"), "server_stopped": report["server_stopped"]}))


if __name__ == "__main__":
    main()
