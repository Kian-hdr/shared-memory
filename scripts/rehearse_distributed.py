#!/usr/bin/env python3
"""Bounded synthetic same-project rehearsal using the actual packaged CLI/server.

Remote mode uses concurrent automated GitHub OS actors and a testing-only Quick
Tunnel. Selfcheck runs the same phases on one machine over loopback. Neither mode
proves independent human onboarding, storage-provider delivery, or all TEAM-11.
Only the reviewed package, rendezvous.json and report.json are public artifacts. Never upload this
script's private fixture directories, tokens, coordinator state or process logs.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import io
import json
import os
import platform
import re
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path

ROLES = ('macos', 'windows', 'linux')
INITIAL = {'Home.md': '# Synthetic shared project\n',
           'AGENTS.md': '# Fixture instructions\nPreserve private parent files.\n',
           'Research.md': 'Public synthetic starting context.\n'}
LIMITS = ['Automated OS actors, not independent humans or AI-agent sessions',
          'No Google Drive, OneDrive, iCloud or storage-provider receipt tested',
          'Temporary tunnel has no availability SLA; not a production deployment',
          'Bounded common-base proposals and handoff; not complete TEAM-11']
MAX_ARTIFACT_BYTES = 4 * 1024 * 1024


class CheckFailed(Exception):
    pass


def check(condition, message):
    if not condition:
        raise CheckFailed(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.pending')
    temporary.write_bytes(canonical(value) + b'\n')
    os.replace(temporary, path)


def private_token(path, token):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='') as stream:
        stream.write(token + '\n')


def derive(role):
    master = os.environ.get('SM_CI_MASTER', '')
    check(len(master) >= 32, 'SM_CI_MASTER must be supplied privately with at least32 characters')
    run, attempt = identity()
    token = hmac.new(master.encode(), canonical(['shared-memory-ci-v1', run, attempt, role]), hashlib.sha256).hexdigest()
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        print('::add-mask::' + token, flush=True)
    return token


def identity():
    run, attempt = os.environ.get('GITHUB_RUN_ID'), os.environ.get('GITHUB_RUN_ATTEMPT')
    check(bool(run and attempt), 'Explicit run ID and attempt are required')
    return run, attempt


def result_text(role):
    return '# ' + role + '\nShared synthetic result: café 世界.\n'


def expected_files():
    return {**INITIAL, **{'Results/' + role + '.md': result_text(role) for role in ROLES}}


def clean_environment():
    return {key: value for key, value in os.environ.items()
            if key not in {'SM_CI_MASTER', 'GITHUB_TOKEN', 'GH_TOKEN'}}


class Session:
    def __init__(self, args):
        self.args = args
        self.root = Path(args.output).absolute()
        check(not self.root.exists(), 'Choose a fresh nonexistent fixture output')
        self.root.mkdir(parents=True)
        self.package = Path(args.package).absolute()
        self.deadline = time.monotonic() + args.seconds
        self.commands = []
        self.children = []
        self.handles = []
        self.phase = 'starting'
        role = args.role or 'coordinator'
        self.report = {'status': 'failed', 'role': role,
            'system': platform.system(), 'platform_release': platform.release(),
            'python': platform.python_version(), 'run_id': identity()[0], 'attempt': identity()[1],
            'limitations': LIMITS, 'commands': self.commands}
        self.project = self.root / ('Private space ' + role) / 'Projects' / 'Shared project'
        self.state = self.root / 'private-state'

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        check(remaining > 0, 'Rehearsal deadline exceeded during ' + self.phase)
        return remaining

    def poll(self, phase, operation):
        self.phase = phase
        while True:
            self.remaining()
            result = operation()
            if result:
                return result
            time.sleep(min(2, self.remaining()))

    def cli(self, *arguments, expected=0):
        command = [sys.executable, str(self.package), *map(str, arguments)]
        result = subprocess.run(command, capture_output=True, encoding='utf-8',
            env=clean_environment(), timeout=min(40, self.remaining()))
        try:
            envelope = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise CheckFailed('CLI returned invalid JSON for ' + str(arguments[0])) from None
        self.commands.append({'command': str(arguments[0]), 'exit_code': result.returncode,
                              'code': envelope.get('code')})
        check(result.returncode == expected, 'Unexpected CLI outcome for ' + str(arguments[0])
              + ': ' + str(result.returncode) + '/' + str(envelope.get('code')))
        return envelope['data']

    def local(self, operation, *arguments, expected=0):
        return self.cli(operation, self.project, '--state-dir', self.state, *arguments, expected=expected)

    def coord(self, operation, payload=None, expected=0):
        path = self.root / 'private-payload.json'
        write_json(path, payload or {})
        return self.local('coord', operation, '--payload-file', path, expected=expected)

    def version(self):
        metadata = self.cli('version')
        if os.environ.get('GITHUB_ACTIONS') == 'true':
            check(metadata['source_revision'] == os.environ.get('GITHUB_SHA'), 'Package source commit differs from this run')
            check(not metadata['source_dirty'], 'CI must build a clean reviewed checkout')
        self.report.update(package_sha256=sha(self.package), bundle_id=metadata['bundle_id'],
                           source_revision=metadata['source_revision'])
        return metadata

    def start(self, command, log_name):
        handle = (self.root / log_name).open('wb')
        self.handles.append(handle)
        process = subprocess.Popen(list(map(str, command)), stdout=handle, stderr=subprocess.STDOUT,
                                   env=clean_environment())
        self.children.append(process)
        return process

    def finish(self):
        for process in reversed(self.children):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
        for handle in self.handles:
            handle.close()
        self.report['processes_stopped'] = all(process.poll() is not None for process in self.children)
        self.report['last_phase'] = self.phase
        write_json(self.root / 'report.json', self.report)


def claim(session, name, target):
    return session.coord('claim', {'assignment_id': name, 'targets': [target],
        'criteria': ['Verify exact synthetic bytes and current receipt'], 'dependencies': [],
        'resource_limits': {'max_proposals': 4}, 'integration_owner': 'coordinator'})


def complete(session, assignment, receipt):
    return session.coord('complete', {'assignment_id': assignment, 'revision': receipt['revision'],
        'files_hash': receipt['files_hash'], 'evidence': 'Automated runner verified exact synthetic snapshot bytes'})


def assignments(session):
    return {item['assignment_id']: item for item in session.coord('status')['assignments']}


def all_marked(session, prefix):
    current = assignments(session)
    return all(current.get(prefix + role, {}).get('status') == 'completed' for role in ROLES)


def sign_rendezvous(document):
    return hmac.new(bytes.fromhex(derive('rendezvous')), canonical(document), hashlib.sha256).hexdigest()


def verified_rendezvous(document):
    public = document['data']
    check(hmac.compare_digest(document['signature'], sign_rendezvous(public)), 'Rendezvous signature mismatch')
    check((public['run_id'], public['attempt']) == identity(), 'Rendezvous belongs to a different run/attempt')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        check(public['source_revision'] == os.environ.get('GITHUB_SHA'), 'Rendezvous source differs from this workflow commit')
    return public


def receive_artifact(content, package_path):
    """Verify signed scope and exact downloaded bytes before writing/execution."""
    check(len(content) <= MAX_ARTIFACT_BYTES, 'Rendezvous artifact exceeds4 MiB')
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        check(sorted(archive.namelist()) == ['rendezvous.json', 'shared-memory.pyz'],
              'Unexpected or duplicate rendezvous artifact members')
        check(archive.getinfo('rendezvous.json').file_size < 16384, 'Rendezvous document is too large')
        check(0 < archive.getinfo('shared-memory.pyz').file_size <= MAX_ARTIFACT_BYTES,
              'Uncompressed package exceeds4 MiB')
        check(sum(item.file_size for item in archive.infolist()) <= MAX_ARTIFACT_BYTES,
              'Uncompressed artifact exceeds4 MiB')
        document = json.loads(archive.read('rendezvous.json'))
        public = verified_rendezvous(document)
        package = archive.read('shared-memory.pyz')
    check(hashlib.sha256(package).hexdigest() == public['package_sha256'], 'Downloaded package hash mismatch')
    descriptor = os.open(package_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(package)
    return document


def coordinator(session):
    metadata = session.version()
    sys.path.insert(0, str(session.package))
    from shared_workspace.engine import Coordinator
    database = session.root / 'authority.sqlite'
    authority = Coordinator(database)
    project_id = str(uuid.uuid4())
    owner_token = derive('coordinator')
    authority.initialize(project_id, {'actor': 'coordinator', 'human': 'Automated coordinator',
        'agent': 'Synthetic CI rehearsal'}, owner_token, INITIAL)
    for role in ROLES:
        authority.request(owner_token, 'member', {'actor': role, 'human': 'Automated ' + role,
            'agent': 'Synthetic CI rehearsal', 'role': 'contributor', 'token': derive(role)})
    token_file = session.root / 'owner.token'
    private_token(token_file, owner_token)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    server = session.start([sys.executable, session.package, 'serve', '--database', database,
        '--host', '127.0.0.1', '--port', port], 'private-server.log')
    def listening():
        check(server.poll() is None, 'Packaged server exited before readiness')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return True
        except OSError:
            return False
    session.poll('server_startup', listening)
    loopback = 'http://127.0.0.1:' + str(port)
    session.project.mkdir(parents=True)
    session.local('attach', '--endpoint', loopback, '--token-file', token_file,
                  '--expected-project-id', project_id)
    endpoint = loopback
    if not session.args.loopback:
        check(session.args.cloudflared is not None, 'A verified cloudflared executable is required')
        tunnel = session.start([session.args.cloudflared, 'tunnel', '--no-autoupdate',
            '--url', loopback], 'private-tunnel.log')
        def tunnel_address():
            check(tunnel.poll() is None, 'Temporary tunnel exited before readiness')
            raw = (session.root / 'private-tunnel.log').read_text(encoding='utf-8', errors='replace')
            found = re.search(r'https://[a-z0-9-]+\.trycloudflare\.com', raw)
            return found.group(0) if found else None
        endpoint = session.poll('tunnel_startup', tunnel_address)
        from shared_workspace.transport import HTTPTransport
        from shared_workspace.errors import ProductError
        remote = HTTPTransport(endpoint, token_file, timeout=5)
        def reachable():
            check(tunnel.poll() is None and server.poll() is None, 'Tunnel/server exited before HTTPS readiness')
            try:
                snapshot = remote('snapshot', {})
                check(snapshot['project_id'] == project_id, 'HTTPS route reached a different project')
                return True
            except ProductError as error:
                if error.exit_code in {3, 5}:
                    return False
                raise
        session.poll('verified_https_readiness', reachable)
    public = {'run_id': identity()[0], 'attempt': identity()[1], 'project_id': project_id,
        'endpoint': endpoint, 'base_revision': 0, 'package_sha256': sha(session.package),
        'source_revision': metadata['source_revision'], 'bundle_id': metadata['bundle_id']}
    published_package = session.root / 'shared-memory.pyz'
    published_package.write_bytes(session.package.read_bytes())
    check(sha(published_package) == public['package_sha256'] == session.report['package_sha256'],
          'Coordinator package changed after verification')
    write_json(session.root / 'rendezvous.json', {'data': public, 'signature': sign_rendezvous(public)})
    session.report.update(project_id=project_id, transport='loopback-selfcheck' if session.args.loopback else 'verified-https-quick-tunnel')
    session.poll('all_common_base_proposals', lambda: len(session.coord('status')['proposals']) == 3)
    accepted_results = []
    for role in ROLES:
        proposal = session.coord('proposal', {'proposal_id': 'proposal-' + role})
        check(proposal['actor'] == role and proposal['base_revision'] == 0,
              'Proposal identity/common base mismatch')
        check(proposal['changes'] == {'Results/' + role + '.md': result_text(role)},
              'Synthetic proposal bytes differ from the reviewed expectation')
        check(proposal['claims'] == [], 'Unexpected semantic claims in fixture')
        accepted_results.append(session.coord('accept', {'proposal_id': 'proposal-' + role,
            'validation': 'Coordinator compared exact expected synthetic UTF8 content',
            'reason': 'Accept independent bounded common-base proposal'}))
    check([result['revision'] for result in accepted_results] == [1, 2, 3], 'Unexpected accepted revisions')
    check(all(result['rebased'] for result in accepted_results[1:]), 'Compatible stale proposals did not rebase')
    snapshot = session.coord('snapshot')
    check(snapshot['files'] == expected_files(), 'Final coordinator snapshot mismatch')
    session.poll('all_os_receipts', lambda: all_marked(session, 'receipt-'))
    session.poll('handoff_and_all_clients_done', lambda: all_marked(session, 'done-'))
    handoff = session.coord('assignment', {'assignment_id': 'work-macos'})
    check(handoff['status'] == 'completed' and handoff['actor'] == 'linux', 'Final handoff did not complete')
    check([(item['from_actor'], item['to_actor']) for item in handoff['handoffs']]
          == [('macos', 'windows'), ('windows', 'linux')], 'Handoff sequence differs')
    check(session.coord('snapshot') == snapshot, 'Handoff changed accepted content unexpectedly')
    check(len(session.coord('status')['proposals']) == 3, 'Premature handoff proposal persisted')
    session.report.update(status='passed', revision=snapshot['revision'], files_hash=snapshot['files_hash'],
        accepted_proposals=accepted_results, handoff=[{'from': item['from_actor'], 'to': item['to_actor'],
        'revision': item['revision'], 'files_hash': item['files_hash']} for item in handoff['handoffs']])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def artifact_rendezvous(session):
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    check(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository), 'Expected a GitHub repository identity')
    run, attempt = identity()
    check(run.isdigit() and attempt.isdigit(), 'GitHub run identity must be numeric')
    token = os.environ.get('GITHUB_TOKEN', '')
    check(bool(token), 'GitHub artifact read token is unavailable')
    base = 'https://api.github.com/repos/' + repository
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json',
               'X-GitHub-Api-Version': '2022-11-28'}
    opener = urllib.request.build_opener(NoRedirect())
    def find():
        request = urllib.request.Request(base + '/actions/runs/' + run + '/artifacts?per_page=100', headers=headers)
        with opener.open(request, timeout=min(20, session.remaining())) as response:
            listing = json.loads(response.read(1024 * 1024))
        matches = [item for item in listing['artifacts']
            if item['name'] == 'sm-rendezvous-' + run + '-' + attempt and not item['expired']]
        if not matches:
            return None
        check(len(matches) == 1, 'Ambiguous rendezvous artifact')
        request = urllib.request.Request(base + '/actions/artifacts/' + str(matches[0]['id']) + '/zip', headers=headers)
        try:
            response = opener.open(request, timeout=min(20, session.remaining()))
        except urllib.error.HTTPError as error:
            check(error.code == 302, 'GitHub artifact download failed')
            location = error.headers.get('Location', '')
            check(urllib.parse.urlsplit(location).scheme == 'https', 'Artifact download must use HTTPS')
            # Do not forward the GitHub bearer to the signed artifact storage URL.
            response = urllib.request.urlopen(location, timeout=min(20, session.remaining()))
        with response:
            content = response.read(MAX_ARTIFACT_BYTES + 1)
        return receive_artifact(content, session.package)
    return session.poll('rendezvous_artifact', find)


def client(session):
    role = session.args.role
    if not session.args.loopback:
        check(platform.system() == {'macos': 'Darwin', 'windows': 'Windows', 'linux': 'Linux'}[role],
              'Client role does not match the actual runner operating system')
    if session.args.rendezvous:
        path = Path(session.args.rendezvous)
        document = session.poll('local_rendezvous', lambda: json.loads(path.read_text()) if path.is_file() else None)
    else:
        document = artifact_rendezvous(session)
    public = verified_rendezvous(document)
    check(sha(session.package) == public['package_sha256'], 'Rendezvous/runtime package hash mismatch')
    # No downloaded package executes until HMAC, run, attempt, source and bytes
    # have been checked. Version then verifies the embedded build/bundle identity.
    metadata = session.version()
    for field, expected in [('package_sha256', sha(session.package)), ('source_revision', metadata['source_revision']),
                            ('bundle_id', metadata['bundle_id'])]:
        check(public[field] == expected, 'Rendezvous/runtime identity mismatch: ' + field)
    endpoint = public['endpoint']
    if session.args.loopback:
        check(re.fullmatch(r'http://127\.0\.0\.1:\d+', endpoint), 'Selfcheck only permits loopback')
    else:
        check(re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com', endpoint), 'Expected verified HTTPS Quick Tunnel origin')
    check(public['base_revision'] == 0, 'Unexpected starting revision')
    session.project.mkdir(parents=True)
    vault = session.project.parent.parent
    fixture = {vault / 'Private.md': b'PRIVATE PARENT SENTINEL\n',
        vault / '.obsidian' / 'app.json': b'{"fixture":true}\n',
        session.project / 'Attachments' / 'local.bin': b'\x00\xffPRIVATE BINARY ATTACHMENT',
        **{session.project / name: content.encode() for name, content in INITIAL.items()}}
    for path, content in fixture.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    before = {path.relative_to(session.root).as_posix(): sha(path) for path in fixture}
    token_file = session.root / 'member.token'
    private_token(token_file, derive(role))
    session.local('attach', '--endpoint', endpoint, '--token-file', token_file,
        '--expected-project-id', public['project_id'])
    claim(session, 'work-' + role, 'Results/' + role + '.md')
    target = session.project / 'Results' / (role + '.md')
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(result_text(role).encode())
    session.local('draft', '--proposal-id', 'proposal-' + role, '--assignment-id', 'work-' + role,
                  '--evidence', 'Automated OS actor compared exact synthetic UTF8 result')
    session.local('submit', '--proposal-id', 'proposal-' + role)
    session.poll('common_accepted_revision', lambda: session.coord('status')['revision'] == 3)
    session.local('refresh')
    receipt = session.local('receipt')
    check(receipt['readiness'] == 'ready' and receipt['revision'] == 3, 'Local accepted receipt is incomplete')
    snapshot = session.coord('snapshot')
    check(snapshot['files'] == expected_files() and snapshot['files_hash'] == receipt['files_hash'],
          'Common snapshot/receipt differs')
    for name, content in expected_files().items():
        check((session.project / name).read_bytes() == content.encode(), 'Materialized UTF8 bytes differ')
    if role != 'macos':
        complete(session, 'work-' + role, receipt)
    claim(session, 'receipt-' + role, 'Receipts/' + role + '.md')
    complete(session, 'receipt-' + role, receipt)
    if role == 'macos':
        session.poll('all_receipts_before_handoff', lambda: all_marked(session, 'receipt-'))
        session.coord('handoff', {'assignment_id': 'work-macos', 'to_actor': 'windows',
                                 'summary': 'Automated macOS to Windows handoff'})
    else:
        def pending():
            item = session.coord('assignment', {'assignment_id': 'work-macos'})
            return item['actor'] == role and item['status'] == 'pending_receipt'
        session.poll('incoming_handoff', pending)
        session.coord('propose', {'proposal_id': 'premature-' + role, 'assignment_id': 'work-macos',
            'base_revision': 3, 'changes': {'Results/macos.md': 'PREMATURE'},
            'evidence': 'Expected refusal before received handoff', 'claims': []}, expected=4)
        session.local('refresh')
        current = session.local('receipt')
        check(current['revision'] == receipt['revision'] and current['files_hash'] == receipt['files_hash']
              and current['readiness'] == 'ready', 'Handoff receipt changed unexpectedly')
        session.coord('receive', {'assignment_id': 'work-macos', 'revision': current['revision'],
                                 'files_hash': current['files_hash']})
        if role == 'windows':
            session.coord('handoff', {'assignment_id': 'work-macos', 'to_actor': 'linux',
                                     'summary': 'Automated Windows to Linux handoff'})
        else:
            complete(session, 'work-macos', current)
        session.report['premature_write_rejected'] = True
    session.poll('completed_handoff_chain', lambda: session.coord('assignment',
        {'assignment_id': 'work-macos'})['status'] == 'completed')
    after = {path.relative_to(session.root).as_posix(): sha(path) for path in fixture}
    check(before == after, 'Existing notes, instructions, parent, config or attachments changed')
    session.report.update(project_id=public['project_id'], revision=receipt['revision'], files_hash=receipt['files_hash'],
        preservation_before=before, preservation_after=after, local_receipt=receipt,
        transport='loopback-selfcheck' if session.args.loopback else 'verified-https-quick-tunnel')
    claim(session, 'done-' + role, 'Done/' + role + '.md')
    complete(session, 'done-' + role, receipt)
    session.report['status'] = 'passed'


def selfcheck(args):
    root = Path(args.output).absolute()
    check(not root.exists(), 'Selfcheck output must be fresh')
    root.mkdir(parents=True)
    environment = {**os.environ, 'SM_CI_MASTER': secrets.token_hex(32),
                   'GITHUB_RUN_ID': 'selfcheck-' + uuid.uuid4().hex, 'GITHUB_RUN_ATTEMPT': '1',
                   'GITHUB_ACTIONS': 'false'}
    children = []
    handles = []
    try:
        for role in ('coordinator', *ROLES):
            command = [sys.executable, __file__, 'coordinator' if role == 'coordinator' else 'client',
                '--package', str(Path(args.package).absolute()), '--output', str(root / role),
                '--seconds', str(args.seconds), '--loopback']
            if role != 'coordinator':
                command += ['--role', role, '--rendezvous', str(root / 'coordinator' / 'rendezvous.json')]
            handle = (root / (role + '.private.log')).open('wb'); handles.append(handle)
            children.append(subprocess.Popen(command, env=environment, stdout=handle, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + args.seconds
        for process in children:
            check(process.wait(timeout=max(1, deadline - time.monotonic())) == 0, 'A local selfcheck actor failed')
        reports = [json.loads((root / role / 'report.json').read_text()) for role in ('coordinator', *ROLES)]
        check(all(report['status'] == 'passed' for report in reports), 'Selfcheck report failed')
        check(len({(report['project_id'], report['revision'], report['files_hash']) for report in reports}) == 1,
              'Selfcheck actors disagree on accepted identity')
        write_json(root / 'report.json', {'status': 'passed', 'scope': 'one-machine-loopback-selfcheck',
            'limitations': LIMITS + ['OS role names are simulated on this one local operating system'],
            'actors': reports})
    finally:
        for process in children:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait(timeout=5)
        for handle in handles:
            handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('coordinator', 'client', 'selfcheck', 'wait'))
    parser.add_argument('--package')
    parser.add_argument('--output')
    parser.add_argument('--role', choices=ROLES)
    parser.add_argument('--cloudflared')
    parser.add_argument('--rendezvous')
    parser.add_argument('--loopback', action='store_true', help='Explicit local selfcheck only')
    parser.add_argument('--seconds', type=int, default=720)
    parser.add_argument('--file')
    parser.add_argument('--require-passed', action='store_true')
    args = parser.parse_args()
    check(1 <= args.seconds <= 720, 'Deadline must be between1 and720 seconds')
    def interrupted(*unused):
        raise CheckFailed('Rehearsal interrupted; stopping task-owned processes')
    signal.signal(signal.SIGTERM, interrupted)
    session = None
    try:
        if args.mode == 'wait':
            check(bool(args.file), '--file is required')
            deadline = time.monotonic() + args.seconds
            while not Path(args.file).is_file():
                check(time.monotonic() < deadline, 'Waiting for fixture artifact timed out')
                time.sleep(1)
            if args.require_passed:
                check(json.loads(Path(args.file).read_text())['status'] == 'passed', 'Coordinator rehearsal failed')
        elif args.mode == 'selfcheck':
            selfcheck(args)
        else:
            check(bool(args.package and args.output), 'Explicit package and fresh output are required')
            if args.mode == 'client':
                check(bool(args.role), 'Client role is required')
            session = Session(args)
            coordinator(session) if args.mode == 'coordinator' else client(session)
        return 0
    except Exception as error:
        message = str(error) if isinstance(error, CheckFailed) else type(error).__name__
        if session:
            session.report['failure'] = message
        print(json.dumps({'status': 'failed', 'reason': message}), flush=True)
        return 1
    finally:
        if session:
            session.finish()


if __name__ == '__main__':
    raise SystemExit(main())
