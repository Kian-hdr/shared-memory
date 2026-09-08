#!/usr/bin/env python3
"""Exercise normal packaged setup, recovery and two own-member TLS clients.

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
    parser.add_argument("--sha256", help="Required expected digest when validating a downloaded release")
    args = parser.parse_args()
    package_hash = hashlib.sha256(args.package.read_bytes()).hexdigest()
    if args.sha256 is not None and package_hash != args.sha256:
        raise ValueError("Package differs from the expected reviewed SHA-256")
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    owner = root / "Owner private vault/Projects/Shared Demo"
    recipient = root / "Recipient private vault/Team/Shared Demo"
    for path in (owner, recipient):
        path.mkdir(parents=True)
        (path.parent / "Private.md").write_text("Synthetic private sibling.\n")
    (owner / "Home.md").write_text("# Shared Memory rehearsal\n\nSynthetic project.\n")
    (owner / 'AGENTS.md').write_bytes(b'# Existing instructions\r\nPreserve this exact text.\n')
    (owner / 'secrets.md').write_bytes(b'SYNTHETIC-PRIVATE-NOTE\n')
    (owner / 'photo.png').write_bytes(b'\x89PNG\r\n\x1a\nSYNTHETIC-BINARY')
    originals = {p.name: p.read_bytes() for p in owner.iterdir() if p.is_file()}
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
    created = cli("setup", owner, state, "--person", "Alex Fictional", "--actor", "alex",
                  "--agent", "Synthetic owner CLI", "--purpose", "TLS fixture")
    assert created['readiness'] == 'ready' and created['workspace_scope'] == 'local'
    original_token = (state / 'member.token').read_bytes()
    (state / 'connection.json').unlink()  # A generated setup file in this test only.
    repaired = cli('setup', owner, state)
    assert repaired['project_id'] == created['project_id'] and repaired['repairs']
    assert (state / 'member.token').read_bytes() == original_token
    for name, content in originals.items():
        assert (owner / name).read_bytes() == content
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
            joined = cli("setup", recipient, other, "--endpoint", f"https://127.0.0.1:{port}",
                "--ca-file", cert, "--token-file", member, "--expected-project-id", created["project_id"])
            assert joined["coordinator_membership"] == "verified"
            assert joined['readiness'] == 'ready' and joined['current_authority_match']
            assert not (other / 'coordinator.sqlite3').exists()
            assert (other / 'member.token').read_bytes() != original_token
            coord("claim", {"assignment_id": "demo", "targets": ["Result.md"], "criteria": ["Compare exact content"],
                            "dependencies": [], "resource_limits": {"max_proposals": 3}, "integration_owner": "alex"})
            (owner / "Result.md").write_text("# Result\n\nReviewed accepted knowledge.\n")
            cli("draft", owner, state, "--proposal-id", "result-1", "--assignment-id", "demo", "--evidence", "Exact fixture content reviewed")
            cli("submit", owner, state, "--proposal-id", "result-1")
            accepted = coord("accept", {"proposal_id": "result-1", "validation": "Compared fixture bytes", "reason": "Bounded rehearsal"})
            assert accepted["accepted"]
            cli("setup", owner, state)
            cli("setup", recipient, other)
            receipt = cli("receipt", recipient, other)
            assert receipt["revision"] == accepted["revision"] and receipt["files_hash"] == accepted["files_hash"]
            assert (recipient / "Result.md").read_bytes() == (owner / "Result.md").read_bytes()
            coord("handoff", {"assignment_id": "demo", "to_actor": "sam", "summary": "Verify actual TLS receipt"})
            coord("receive", {"assignment_id": "demo", "revision": receipt["revision"], "files_hash": receipt["files_hash"]}, recipient, other)
            coord("complete", {"assignment_id": "demo", "revision": receipt["revision"], "files_hash": receipt["files_hash"],
                               "evidence": "Recipient compared exact materialized bytes"}, recipient, other)
            cli("context", recipient, other, "--query", "accepted knowledge")
            (recipient / 'Home.md').write_bytes(b'PRESERVE-UNSUBMITTED-RECIPIENT-EDIT\n')
            recovered = cli('setup', recipient, other)
            assert recovered['preserved_drafts'] and recovered['readiness'] == 'ready'
            assert any(b'PRESERVE-UNSUBMITTED-RECIPIENT-EDIT' in p.read_bytes()
                       for p in (other / 'client/drafts').glob('*.json'))
            assert (recipient / 'Home.md').read_bytes() == (owner / 'Home.md').read_bytes()
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
    report = {"package_sha256": package_hash,
              "python": sys.version, "commands_passed": len(records),
              "records": [{"command": r['command'], "ok": r['ok']} for r in records],
              "accepted_revision": receipt['revision'], "accepted_files_hash": receipt['files_hash'],
              "verified": ["normal owner setup and rerun", "missing generated connection recovery", "selected files and private sibling preservation", "actual Uvicorn TLS server", "verified fixture CA and hostname", "own-member recipient setup", "accepted revision receipt", "preserved recipient edits on rerun", "handoff and completion", "backup readback"],
              "limitations": ["two synthetic actors on one computer", "loopback fixture certificate", "coordinator transfer, not cloud-provider sync", "independent-person onboarding not run"],
              "server_stopped": server.poll() is not None}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"commands_passed": len(records), "report": str(root / "report.json"), "server_stopped": report["server_stopped"]}))


if __name__ == "__main__":
    main()
