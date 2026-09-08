#!/usr/bin/env python3
"""Isolated automated schema2 fault rehearsal against a hash-pinned package.

Requires the package's optional Uvicorn dependency and OpenSSL. Uses verified
loopback HTTPS, private synthetic credentials, and fresh disposable directories.
Never points at an existing authority. Report JSON may be shared; the private/
directory contains test credentials and must not be published. No independent
people, real editor application, cloud provider, or remote device is simulated as
having participated. Fault hooks instrument the imported exact packaged runtime;
they do not edit it or substitute a model authority.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
import zipfile


def require(value, message):
    if not value:
        raise AssertionError(message)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def write_json(path, value):
    with Path(path).open('xb') as stream:
        stream.write(encoded(value) + b'\n')


def load_runtime(package, expected_hash):
    package = Path(package).resolve(strict=True)
    require(hashlib.sha256(package.read_bytes()).hexdigest() == expected_hash,
            'Package SHA-256 differs from explicit reviewed artifact')
    with zipfile.ZipFile(package) as archive:
        metadata = json.loads(archive.read('BUILD.json'))
        for name, expected in metadata['files'].items():
            require(hashlib.sha256(archive.read(name)).hexdigest() == expected,
                    'Package member hash mismatch')
    sys.path.insert(0, str(package))
    global Client, Coordinator, HTTPTransport, ProductError
    from shared_workspace.client import Client
    from shared_workspace.engine import Coordinator
    from shared_workspace.transport import HTTPTransport
    from shared_workspace.errors import ProductError
    require(str(Client.__module__) == 'shared_workspace.client', 'Wrong Client module')
    import shared_workspace.client as module
    require(str(package) in module.__file__, 'Runtime was not loaded from reviewed package')
    return package, metadata


def checkpoint(database):
    """Compare all logical rows; separately normalize only the monotonic clock.

    Retried schema2 mutations legitimately advance coord_meta.clock_ms and its
    document hash. Everything else, including credentials' hashes, must match.
    Values remain private; only final digests/counts enter the public report.
    """
    with sqlite3.connect(f'file:{Path(database).as_posix()}?mode=ro', uri=True) as connection:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        rows = {name: connection.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
                for name in tables}
        rows['user_version'] = connection.execute('PRAGMA user_version').fetchone()
    stable = dict(rows)
    normalized = []
    for key, document, document_hash in stable['coord_meta']:
        parsed = json.loads(document)
        parsed.pop('clock_ms', None)
        normalized.append([key, parsed])
    stable['coord_meta'] = normalized
    return {'exact': digest(rows), 'without_clock': digest(stable),
            'counts': {name: len(values) for name, values in rows.items() if name != 'user_version'}}


def wait_for(predicate, message, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.03)
    raise AssertionError(message)


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class Fixture:
    def __init__(self, root, package, package_hash):
        self.root, self.package, self.package_hash = root, package, package_hash
        self.private = root / 'private'
        self.private.mkdir(mode=0o700)
        self.database = self.private / 'authority.sqlite3'
        self.server = None
        self.server_handles = []
        self.calls = 0
        self.project_id = str(uuid.uuid4())
        self.initial = {'Race.md': 'ORIGINAL RACE\r\n', 'Offline.md': 'ORIGINAL OFFLINE\n',
                        'Delete.md': 'ORIGINAL DELETE\r\n', 'Independent.md': 'ORIGINAL INDEPENDENT\n',
                        'Crash/a.md': 'ORIGINAL A\n', 'Crash/b.md': 'ORIGINAL B\n',
                        'Atomic.md': 'ORIGINAL ATOMIC\n'}
        self.tokens = {}
        owner = self.token('owner-member')
        worker = self.token('worker-member')
        authority = Coordinator(self.database)
        authority.initialize(self.project_id, {'actor': 'owner', 'human': 'Synthetic person owner',
            'agent': 'Automated fault integrator'}, owner, self.initial,
            coordination={'person_id': 'fixture-owner', 'agent_id': 'fixture-integrator', 'policy': {}})
        authority.request(owner, 'member', {'actor': 'worker', 'human': 'Synthetic person worker',
            'agent': 'Automated fault worker', 'role': 'contributor', 'token': worker})
        authority.request(owner, 'member-binding', {'actor': 'worker', 'person_id': 'fixture-worker',
                                                   'agent_id': 'fixture-worker-agent'})
        for role, member in [('owner', owner), ('worker', worker)]:
            scopes = authority.request(member, 'policy', {})['policy']['session_scopes'][
                'owner' if role == 'owner' else 'contributor']
            authority.request(member, 'session-open', {'session_id': role + '-run',
                'token': self.token(role), 'ttl_seconds': 3600, 'scopes': scopes, 'targets': ['.']})
        self.cert, self.key = self.private / 'localhost.crt', self.private / 'localhost.key'
        result = subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(self.key), '-out', str(self.cert), '-days', '1', '-subj', '/CN=localhost',
            '-addext', 'subjectAltName=IP:127.0.0.1,DNS:localhost'], capture_output=True, timeout=30)
        require(result.returncode == 0, 'Fixture certificate generation failed')
        self.key.chmod(0o600)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        self.endpoint = 'https://127.0.0.1:' + str(self.port)
        try:
            self.start()
        except Exception:
            self.close()
            raise

    def token(self, role):
        token = secrets.token_urlsafe(48)
        path = self.private / (role + '.token')
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(token.encode() + b'\n')
        self.tokens[role] = path
        return token

    def transport(self, role='owner'):
        return HTTPTransport(self.endpoint, self.tokens[role], self.cert, timeout=4)

    def call(self, op, payload=None, role='owner'):
        self.calls += 1
        return self.transport(role)(op, payload or {})

    def start(self):
        handle = (self.private / ('server-' + str(len(self.server_handles)) + '.log')).open('xb')
        self.server_handles.append(handle)
        self.server = subprocess.Popen([sys.executable, str(self.package), 'serve', '--database',
            str(self.database), '--port', str(self.port), '--certfile', str(self.cert),
            '--keyfile', str(self.key)], stdout=handle, stderr=handle)
        def ready():
            require(self.server.poll() is None, 'Packaged TLS server exited before readiness')
            try:
                self.call('snapshot')
                return True
            except ProductError as exc:
                if exc.code != 'coordinator_unavailable':
                    raise
                return False
        wait_for(ready, 'Verified HTTPS server did not become ready')

    def halt(self):
        stop(self.server)

    def close(self):
        self.halt()
        for handle in self.server_handles:
            handle.close()

    def plan(self, identity, targets, worker='worker'):
        self.call('plan', {'assignment_id': identity, 'outcome_key': 'fault-' + identity,
            'summary': 'Automated fault check ' + identity, 'targets': targets,
            'criteria': ['Exact fixture bytes and history retained'], 'dependencies': [],
            'interface_paths': [], 'resource_limits': {}, 'integration_owner': 'owner', 'policy_revision': 1})
        snapshot = self.call('snapshot')
        self.call('acquire', {'assignment_id': identity, 'expected_generation': 0, 'ttl_seconds': 300,
            'revision': snapshot['revision'], 'files_hash': snapshot['files_hash'], 'policy_revision': 1}, worker)

    def context(self, assignment, role='worker'):
        document = self.call('assignment', {'assignment_id': assignment})
        return {'session_id': role + '-run', 'generation': document['generation'],
                'input_hash': document['input_hash'], 'policy_revision': 1}

    def proposal(self, assignment, identity, changes, role='worker', base=None):
        return {'proposal_id': identity, 'assignment_id': assignment,
            'base_revision': self.call('snapshot')['revision'] if base is None else base,
            'changes': changes, 'claims': [], 'evidence': 'Reviewed synthetic exact bytes for fault check',
            'coordination': self.context(assignment, role)}

    def accept_payload(self, assignment, identity):
        return {'proposal_id': identity, 'validation': 'Automated exact fixture validation',
            'reason': 'Isolated fault rehearsal', 'coordination': self.context(assignment, 'owner')}

    def publish(self, assignment, identity, changes, role='worker'):
        self.call('propose', self.proposal(assignment, identity, changes, role), role)
        return self.call('accept', self.accept_payload(assignment, identity))

    def client(self, name):
        parent = self.private / (name + '-vault')
        project = parent / 'Projects' / 'Shared Demo'
        project.mkdir(parents=True)
        (parent / 'Private.md').write_bytes(b'OUTER PRIVATE SENTINEL\r\n')
        (parent / '.obsidian').mkdir()
        (parent / '.obsidian/app.json').write_bytes(b'{"fixture":"preserve"}')
        state = self.private / (name + '-state')
        client = Client(project, state, self.transport('worker'))
        require(client.attach(self.project_id)['readiness'] == 'ready', 'Fresh attach not ready')
        return client, project, state

    def child(self, mode, config):
        path = self.private / (mode + '-config.json')
        write_json(path, config)
        handle = (self.private / (mode + '-child.log')).open('xb')
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--package', str(self.package),
            '--sha256', self.package_hash, '--child', mode, '--config', str(path)], stdout=handle, stderr=handle)
        return process, handle


def race(f):
    f.plan('race', ['Race.md'])
    base = f.call('snapshot')
    proposals = [f.proposal('race', 'race-' + str(i), {'Race.md': 'COMPETING ' + str(i) + '\r\n'},
                            base=base['revision']) for i in range(2)]
    for proposal in proposals:
        f.call('propose', proposal, 'worker')
    payloads = [f.accept_payload('race', proposal['proposal_id']) for proposal in proposals]
    barrier = threading.Barrier(3)
    def contender(payload):
        transport = f.transport()
        barrier.wait(timeout=10)
        return transport('accept', payload)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(contender, payload) for payload in payloads]
        barrier.wait(timeout=10)
        results = [future.result(timeout=20) for future in futures]
    require(sum(result['accepted'] for result in results) == 1, 'Exactly one competing proposal must accept')
    winner = next(i for i, result in enumerate(results) if result['accepted'])
    loser = 1 - winner
    require(results[loser]['status'] == 'conflict', 'Losing proposal must be preserved as conflict')
    snapshot = f.call('snapshot')
    require(snapshot['revision'] == base['revision'] + 1, 'Race created unexpected accepted revisions')
    require(snapshot['files'] == dict(base['files'], **proposals[winner]['changes']), 'Race lost accepted files')
    conflict = f.call('conflict', {'conflict_id': results[loser]['conflicts'][0]['conflict_id']})
    require((conflict['base'], conflict['accepted'], conflict['proposed']) ==
            (base['files']['Race.md'], proposals[winner]['changes']['Race.md'], proposals[loser]['changes']['Race.md']),
            'Conflict failed to retain all three versions')
    before = checkpoint(f.database)
    for i in (winner, loser):
        f.call('propose', proposals[i], 'worker')
        retried = f.call('accept', payloads[i])
        require(retried['accepted'] == results[i]['accepted'], 'Retry changed race outcome')
        if i == winner:
            require(checkpoint(f.database)['without_clock'] == before['without_clock'],
                    'Accepted winner replay changed state beyond clock')
    after = checkpoint(f.database)
    require(f.call('snapshot') == snapshot, 'Conflicted replay changed accepted state')
    require(f.call('conflict', {'conflict_id': conflict['conflict_id']}) == conflict,
            'Conflicted replay changed preserved conflict bytes')
    require(after['counts']['conflicts'] == before['counts']['conflicts'], 'Conflicted replay duplicated conflict records')
    for proposal in proposals:
        stored = f.call('proposal', {'proposal_id': proposal['proposal_id']})
        require(all(stored[key] == value for key, value in proposal.items()), 'Replay altered original proposal request')
    return {'name': 'same_file_https_acceptance_race', 'passed': True, 'accepted_count': 1,
        'conflict_count': 1, 'barrier_participants': 2, 'revision': snapshot['revision'],
        'files_hash': snapshot['files_hash'], 'retry_state': after,
        'conflicted_retry_audit_event_delta': after['counts']['events'] - before['counts']['events'],
        'conflicted_retry_limit': 'Conflicted accept retries may append audit events; accepted state and conflict bytes remain fixed',
        'identity_limit': 'Two proposals under one valid worker lease; concurrent integrator requests, not two owners'}


def offline(f):
    f.plan('offline', ['Offline.md'])
    f.plan('online', ['Delete.md', 'Independent.md'], worker='owner')
    client, project, state = f.client('offline')
    base = f.call('snapshot')
    context = f.context('offline')
    f.halt()  # Actual endpoint outage: no callable-only offline stand-in.
    draft_text = 'OFFLINE original draft α\r\n'
    editor_text = 'EXTERNAL EDIT after draft β\r\nlast\rline'
    deleted_text = 'EDITOR DIVERGENCE on remotely deleted note\r\n'
    (project / 'Offline.md').write_bytes(draft_text.encode())
    client.draft('offline-saved', 'offline', 'Offline immutable proposal', coordination=context)
    saved = state / 'drafts/offline-saved.json'
    saved_bytes = saved.read_bytes()
    before = checkpoint(f.database)
    for operation in (lambda: client.submit('offline-saved'), client.refresh):
        try:
            operation()
        except ProductError as exc:
            require(exc.code == 'coordinator_unavailable', 'Wrong offline refusal')
        else:
            raise AssertionError('Offline request unexpectedly succeeded')
    require(checkpoint(f.database) == before, 'Outage changed authority')
    require(saved.read_bytes() == saved_bytes, 'Offline refusal rewrote draft')
    (project / 'Offline.md').write_bytes(editor_text.encode())
    (project / 'Delete.md').write_bytes(deleted_text.encode())
    (project / 'Local-Untracked.md').write_bytes(b'UNTRACKED NOTE\n')
    (project / 'Attachment.bin').write_bytes(b'\x00\xff\x80UNCHANGED')
    f.start()
    f.publish('online', 'online-change', {'Delete.md': None, 'Independent.md': 'ONLINE CHANGED\n'}, 'owner')
    advanced = f.call('snapshot')
    client = Client(project, state, f.transport('worker'))
    refreshed = client.refresh()
    require(refreshed['readiness'] == 'partial', 'Divergent deleted and untracked notes must prevent ready receipt')
    require((project / 'Delete.md').read_bytes() == deleted_text.encode(), 'Accepted deletion erased local divergence')
    require((project / 'Attachment.bin').read_bytes() == b'\x00\xff\x80UNCHANGED', 'Binary attachment changed')
    require((project / 'Local-Untracked.md').read_bytes() == b'UNTRACKED NOTE\n', 'Untracked note erased')
    require(saved.read_bytes() == saved_bytes, 'Refresh rewrote original proposal')
    preserved = [json.loads(path.read_bytes()) for path in (state / 'drafts').glob('preserved-*.json')]
    require(any(item['base_revision'] == base['revision'] and
                item['changes'].get('Offline.md') == editor_text and
                item['changes'].get('Delete.md') == deleted_text for item in preserved),
            'Post-draft editor divergence not preserved against original baseline')
    client.submit('offline-saved')
    accepted = f.call('accept', f.accept_payload('offline', 'offline-saved'))
    require(accepted['accepted'] and accepted['rebased'], 'Original offline proposal did not compatibly rebase')
    final = f.call('snapshot')
    require(final['files'] == {**advanced['files'], 'Offline.md': draft_text}, 'Offline rebase lost accepted changes')
    client.refresh()
    require(saved.read_bytes() == saved_bytes, 'Accepted original proposal bytes changed')
    require((project / 'Offline.md').read_bytes() == draft_text.encode(), 'Accepted draft did not materialize exactly')
    require(client.receipt()['readiness'] == 'partial', 'Remaining local deletion divergence falsely reported ready')
    return {'name': 'offline_reconnect_external_editor_and_deletion', 'passed': True,
        'base_revision': base['revision'], 'accepted_revision': final['revision'], 'rebased': True,
        'draft_sha256': hashlib.sha256(saved_bytes).hexdigest(), 'preserved_drafts': len(preserved),
        'final_readiness': 'partial', 'outage': 'Actual packaged HTTPS server stopped and restarted',
        'editor_limit': 'Separate filesystem writes, no native editor or provider application'}


def lost_response(f):
    f.plan('response', ['Response.md'])
    request = f.proposal('response', 'response-lost', {'Response.md': 'DURABLE RESPONSE\r\n'})
    f.call('propose', request, 'worker')
    payload = f.accept_payload('response', 'response-lost')
    base = f.call('snapshot')
    # Deliberately discard the complete real HTTPS response at the caller boundary.
    # This does not claim packet loss or kill the HTTP server before socket flush.
    def discard():
        f.call('accept', payload)
        raise TimeoutError('Injected lost response after real HTTPS completed')
    try:
        discard()
    except TimeoutError:
        pass
    accepted = f.call('snapshot')
    require(accepted['revision'] == base['revision'] + 1, 'Acceptance was not durable before lost response')
    before = checkpoint(f.database)
    f.halt(); f.start()
    result = f.call('accept', payload)
    require(result['accepted'] and result['idempotent'], 'Restart/replay did not return original acceptance')
    require(f.call('snapshot') == accepted, 'Replay changed accepted state')
    after = checkpoint(f.database)
    require(before['without_clock'] == after['without_clock'], 'Replay changed authority beyond monotonic clock')
    return {'name': 'acceptance_response_discard_restart_replay', 'passed': True,
        'revision': accepted['revision'], 'idempotent': True, 'checkpoint': after,
        'fault_boundary': 'Caller discards delivered HTTPS response; not transport packet loss',
        'comparison': 'Every logical row unchanged except coord_meta.clock_ms and its derived document hash'}


def materialization(f):
    f.plan('materialization', ['Crash/'])
    client, project, state = f.client('crash')
    before = {name: (project / name).read_bytes() for name in ('Crash/a.md', 'Crash/b.md')}
    f.publish('materialization', 'crash-two-files', {'Crash/a.md': 'ACCEPTED A\r\n', 'Crash/b.md': 'ACCEPTED B\r\n'})
    marker = f.private / 'materialization-boundary.json'
    process, handle = f.child('materialize', {'project': str(project), 'state': str(state),
        'endpoint': f.endpoint, 'token_file': str(f.tokens['worker']), 'cert': str(f.cert), 'marker': str(marker)})
    try:
        wait_for(lambda: marker.exists() or process.poll() is not None, 'Child missed materialization boundary')
        require(marker.exists() and process.poll() is None, 'Child exited before paused materialization')
        process.kill(); process.wait(timeout=10)
    finally:
        stop(process); handle.close()
    require((state / 'journal.json').exists(), 'Killed writer did not retain durable journal')
    require(client.receipt()['readiness'] == 'partial', 'Mixed project falsely reported ready')
    require((project / 'Crash/a.md').read_bytes() == b'ACCEPTED A\r\n', 'First boundary was not after actual write')
    require((project / 'Crash/b.md').read_bytes() == before['Crash/b.md'], 'Second file was already written')
    edit = 'EDITOR AFTER KILL 世界\r\n'
    (project / 'Crash/a.md').write_bytes(edit.encode())
    resumed = Client(project, state, f.transport('worker'))
    result = resumed.refresh()
    require(result['readiness'] == 'ready', 'Recovered materialization failed ready receipt')
    snapshot = f.call('snapshot')
    require(all((project / name).read_bytes() == text.encode() for name, text in snapshot['files'].items()),
            'Recovered files differ from exact accepted snapshot')
    drafts = [json.loads(path.read_bytes()) for path in (state / 'drafts').glob('preserved-*.json')]
    require(any(item['changes'].get('Crash/a.md') == edit for item in drafts), 'Post-kill edit lost in recovery')
    backups = [path.read_bytes() for path in (state / 'backups').iterdir() if path.is_file()]
    require(all(value in backups for value in before.values()), 'Original bytes missing from backups')
    require(not (state / 'journal.json').exists(), 'Recovered journal remains active')
    return {'name': 'materialization_process_kill_post_crash_editor_recovery', 'passed': True,
        'killed_exit_code': process.returncode, 'boundary': json.loads(marker.read_bytes()),
        'interrupted_readiness': 'partial', 'recovered_readiness': 'ready',
        'revision': result['revision'], 'files_hash': result['files_hash'], 'preserved_drafts': len(drafts)}


def atomic_acceptance(f):
    f.plan('atomic', ['Atomic.md'])
    f.call('propose', f.proposal('atomic', 'atomic-kill', {'Atomic.md': 'ATOMIC ACCEPTED\n'}), 'worker')
    payload = f.accept_payload('atomic', 'atomic-kill')
    f.halt()
    before = checkpoint(f.database)
    marker = f.private / 'acceptance-boundary.json'
    process, handle = f.child('acceptance', {'database': str(f.database), 'token_file': str(f.tokens['owner']),
        'payload': payload, 'marker': str(marker)})
    try:
        wait_for(lambda: marker.exists() or process.poll() is not None, 'Child missed acceptance boundary')
        require(marker.exists() and process.poll() is None, 'Child exited before uncommitted acceptance boundary')
        journal = Path(str(f.database) + '-journal')
        require(journal.exists() and journal.stat().st_size > 512, 'No real rollback journal before kill')
        journal_bytes = journal.stat().st_size
        process.kill(); process.wait(timeout=10)
    finally:
        stop(process); handle.close()
    # Real packaged server startup calls Coordinator.recover(), no test recovery implementation.
    f.start()
    recovered = checkpoint(f.database)
    require(recovered == before, 'Uncommitted acceptance did not roll back every logical row')
    accepted = f.call('accept', payload)
    require(accepted['accepted'], 'Fresh authenticated retry failed after hot-journal recovery')
    with sqlite3.connect(f.database) as connection:
        require(connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'SQLite integrity failed')
    return {'name': 'acceptance_process_kill_hot_journal_recovery', 'passed': True,
        'boundary': 'After real acceptance inbox write, before transaction commit; forced real SQLite dirty-page spill',
        'journal_bytes_before_kill': journal_bytes, 'killed_exit_code': process.returncode,
        'recovered_exact_logical_checkpoint': recovered, 'retry_revision': accepted['revision']}


def child(mode, config):
    marker = Path(config['marker'])
    def pause(value):
        write_json(marker, value)
        time.sleep(60)  # Parent kills this child at the observable boundary.
        raise AssertionError('Parent failed to kill paused fixture child')
    if mode == 'materialize':
        class InterruptedClient(Client):
            def _write_project(self, name, text):
                result = super()._write_project(name, text)
                pause({'path': name, 'after_project_write': True})
                return result
        transport = HTTPTransport(config['endpoint'], config['token_file'], config['cert'])
        InterruptedClient(config['project'], config['state'], transport).refresh()
    else:
        from shared_workspace import coordination
        from shared_workspace.transport import read_token
        original = coordination.Coordination.publish_notice
        def interrupted(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.db.execute('PRAGMA cache_size=2')
            self.db.execute('PRAGMA cache_spill=ON')
            for index in range(40):
                coordination._put(self.db, 'coord_inbox', 'fault-spill-' + str(index),
                                  {'fixture': 'X' * 65536, 'index': index})
            pause({'after_acceptance_notice': True, 'transaction_uncommitted': True})
        coordination.Coordination.publish_notice = interrupted
        Coordinator(config['database']).request(read_token(config['token_file']), 'accept', config['payload'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', choices=['materialize', 'acceptance'], help=argparse.SUPPRESS)
    parser.add_argument('--config', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    package, metadata = load_runtime(args.package, args.sha256)
    if args.child:
        child(args.child, json.loads(args.config.read_bytes()))
        return
    require(args.output is not None, '--output is required')
    root = args.output.resolve()
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {'status': 'failed', 'started_at': datetime.now(timezone.utc).isoformat(),
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'package_sha256': args.sha256,
        'source_revision': metadata['source_revision'], 'source_dirty': metadata['source_dirty'],
        'python': platform.python_version(), 'system': platform.system(), 'coordination_schema': 2,
        'evidence_kind': 'Automated disposable fixture, real packaged runtime and verified loopback HTTPS',
        'checks': [], 'limitations': ['No independent humans or real reasoning agents in this rehearsal',
            'No Windows/Linux device execution implied by a Mac run',
            'No storage provider, native editor application, or live Brev authority used',
            'Fault hooks instrument exact imported package only in disposable child processes',
            'Response loss is caller-side discard of a delivered response, not measured packet loss',
            'Idempotent mutations may advance monotonic coordinator clock; report distinguishes exact and normalized checks']}
    fixture = None
    try:
        fixture = Fixture(root, package, args.sha256)
        for scenario in (race, offline, lost_response, materialization, atomic_acceptance):
            report['checks'].append(scenario(fixture))
        for path in fixture.private.glob('*-vault'):
            require((path / 'Private.md').read_bytes() == b'OUTER PRIVATE SENTINEL\r\n', 'Private sibling changed')
            require((path / '.obsidian/app.json').read_bytes() == b'{"fixture":"preserve"}', 'Parent settings changed')
        report['parent_sentinels_preserved'] = True
        report['status'] = 'passed'
    except Exception as exc:
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        if fixture:
            fixture.close()
            report['server_stopped'] = fixture.server.poll() is not None
            report['counted_control_requests'] = fixture.calls
            serialized = encoded(report)
            require(all(path.read_bytes().strip() not in serialized for path in fixture.tokens.values()),
                    'Report contains a disposable secret')
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write_json(root / 'report.json', report)
        print(json.dumps({'status': report['status'], 'checks_passed': len(report['checks']),
                          'report': str(root / 'report.json')}))


if __name__ == '__main__':
    main()
