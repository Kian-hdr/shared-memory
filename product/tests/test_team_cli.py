"""Real engine/transport loopback checks; no hosted provider or mixed-device evidence."""
from __future__ import annotations

import asyncio
import importlib
import json
import secrets
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace.errors import ProductError

REPO = PRODUCT.parent


def file_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob('*') if p.is_file()}


class ASGIBridge(BaseHTTPRequestHandler):
    """Local test HTTP server invoking the actual production ASGI app."""
    def log_message(self, *args):
        pass

    def do_POST(self):
        self.server.requests_seen += 1
        body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
        if self.server.redirect:
            self.send_response(307)
            self.send_header('Location', self.server.redirect)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        sent = []
        async def receive():
            return {'type': 'http.request', 'body': body, 'more_body': False}
        async def send(event):
            sent.append(event)
        scope = {'type': 'http', 'method': 'POST', 'path': self.path,
                 'headers': [(key.lower().encode(), value.encode()) for key, value in self.headers.items()]}
        asyncio.run(self.server.application(scope, receive, send))
        start = next(event for event in sent if event['type'] == 'http.response.start')
        payload = b''.join(event.get('body', b'') for event in sent if event['type'] == 'http.response.body')
        self.send_response(start['status'])
        for name, value in start['headers']:
            self.send_header(name.decode(), value.decode())
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class TeamTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine_module = importlib.import_module('shared_workspace.engine')
        cls.transport_module = importlib.import_module('shared_workspace.transport')

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='shared-memory-loopback-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.db = self.root / 'authority.sqlite'
        self.token = secrets.token_urlsafe(32)
        self.token_file = self.root / 'owner.token'
        self.token_file.write_text(self.token)
        self.token_file.chmod(0o600)
        self.project_id = str(uuid.uuid4())
        self.engine = self.engine_module.Coordinator(self.db)
        self.engine.initialize(self.project_id, {'actor': 'owner', 'human': 'Owner', 'agent': 'Loopback test'},
                               self.token, {'Home.md': '# UTF-8 fixture: Grüße 世界\n'})
        self.server = self.start_server()
        self.endpoint = 'http://127.0.0.1:' + str(self.server.server_address[1])
        self.transport = self.transport_module.HTTPTransport(self.endpoint, self.token_file, timeout=5)

    def start_server(self, redirect=None):
        server = ThreadingHTTPServer(('127.0.0.1', 0), ASGIBridge)
        server.application = self.transport_module.CoordinatorApp(self.db)
        server.redirect = redirect
        server.requests_seen = 0
        thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.02}, daemon=True)
        thread.start()
        def close():
            server.shutdown(); server.server_close(); thread.join(timeout=5)
        self.addCleanup(close)
        return server

    def test_authenticated_loopback_uses_actual_snapshot_and_utf8_bytes(self):
        direct = self.engine.request(self.token, 'snapshot', {})
        delivered = self.transport('snapshot', {})
        self.assertEqual(delivered, direct)
        self.assertEqual(delivered['project_id'], self.project_id)
        self.assertEqual(delivered['files']['Home.md'], '# UTF-8 fixture: Grüße 世界\n')
        self.assertNotIn(self.token, json.dumps(delivered))
        self.assertEqual(self.server.requests_seen, 1)

    def test_loopback_invalid_credentials_and_revocation_are_enforced(self):
        contributor = secrets.token_urlsafe(32)
        self.transport('member', {'actor': 'recipient', 'human': 'Recipient', 'agent': 'Loopback test',
                                 'role': 'reader', 'token': contributor})
        contributor_file = self.root / 'recipient.token'
        contributor_file.write_text(contributor); contributor_file.chmod(0o600)
        reader = self.transport_module.HTTPTransport(self.endpoint, contributor_file, timeout=5)
        self.assertEqual(reader('snapshot', {})['project_id'], self.project_id)
        self.transport('revoke', {'actor': 'recipient'})
        with self.assertRaises(ProductError) as error:
            reader('snapshot', {})
        self.assertEqual(error.exception.exit_code, 4)
        contributor_file.write_text(secrets.token_urlsafe(32))
        with self.assertRaises(ProductError):
            reader('status', {})

    def test_redirect_does_not_forward_bearer_to_other_origin(self):
        sink = self.start_server()
        redirect = self.start_server('http://127.0.0.1:' + str(sink.server_address[1]) + '/v1/request')
        transport = self.transport_module.HTTPTransport(
            'http://127.0.0.1:' + str(redirect.server_address[1]), self.token_file, timeout=5)
        with self.assertRaises(ProductError) as error:
            transport('snapshot', {})
        self.assertEqual(error.exception.code, 'redirect_refused', repr(error.exception.__cause__))
        self.assertEqual(sink.requests_seen, 0)

    def test_remote_plain_http_rejected_without_network_request(self):
        with self.assertRaises(ProductError) as error:
            self.transport_module.HTTPTransport('http://example.invalid', self.token_file)
        self.assertEqual(error.exception.code, 'tls_required')
        self.assertEqual(self.server.requests_seen, 0)

    def test_missing_token_and_stopped_server_do_not_claim_receipt(self):
        missing = self.transport_module.HTTPTransport(self.endpoint, self.root / 'missing.token', timeout=1)
        with self.assertRaises(ProductError) as error:
            missing('snapshot', {})
        self.assertEqual(error.exception.exit_code, 5)

        self.assertEqual(self.server.requests_seen, 0)
        # Refused loopback TCP port establishes an actual failed transport, not a mock result.
        unused = ThreadingHTTPServer(('127.0.0.1', 0), ASGIBridge)
        port = unused.server_address[1]; unused.server_close()
        unavailable = self.transport_module.HTTPTransport('http://127.0.0.1:' + str(port), self.token_file, timeout=1)
        with self.assertRaises(ProductError) as error:
            unavailable('snapshot', {})
        self.assertEqual(error.exception.exit_code, 5)


class TeamCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build_temp = tempfile.TemporaryDirectory(prefix='shared-memory-cli-package-')
        cls.addClassCleanup(cls.build_temp.cleanup)
        cls.archive = Path(cls.build_temp.name) / 'candidate.pyz'
        result = subprocess.run([sys.executable, str(REPO / 'scripts/build_product.py'),
            '--output', str(cls.archive)], cwd=REPO, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise AssertionError('Actual package build failed: ' + result.stdout + result.stderr)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='shared-memory-team-cli-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / 'Private vault' / 'Shared project'
        self.project.mkdir(parents=True)
        (self.project.parent / 'Private.md').write_text('PRIVATE-PARENT')
        (self.project / 'Home.md').write_text('# Existing project home\n')
        self.state = self.root / 'owner-private-state'
        self.outputs = []

    def cli(self, command, project=None, state=None, *args, expected=0):
        result = subprocess.run([sys.executable, str(self.archive), command,
            str(project or self.project), '--state-dir', str(state or self.state), *map(str, args)],
            cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['schema_version'], 1)
        self.assertEqual(output['ok'], expected == 0)
        self.outputs.append(output)
        return output['data']

    def initialize(self, project=None, state=None):
        return self.cli('init', project, state, '--person', 'Alex Fictional', '--actor', 'alex',
            '--agent', 'Independent packaged test', '--purpose', 'Synthetic team lifecycle')

    def coord(self, operation, payload, project=None, state=None, expected=0):
        path = self.root / ('payload-' + str(uuid.uuid4()) + '.json')
        path.write_text(json.dumps(payload))
        return self.cli('coord', project, state, operation, '--payload-file', path, expected=expected)

    def test_packaged_owner_to_recipient_workflow_uses_real_engine_and_client(self):
        initialized = self.initialize()
        project_id = initialized['project_id']
        self.assertEqual(initialized['readiness'], 'ready')
        self.coord('claim', {'assignment_id': 'a', 'targets': ['Result.md'], 'criteria': ['Verify fixture'],
            'dependencies': [], 'resource_limits': {'max_proposals': 4}, 'integration_owner': 'alex'})
        (self.project / 'Result.md').write_text('PACKAGED-ACCEPTED-FIXTURE')
        self.cli('draft', None, None, '--proposal-id', 'p', '--assignment-id', 'a', '--evidence', 'Exact fixture checked')
        self.cli('submit', None, None, '--proposal-id', 'p')
        self.coord('accept', {'proposal_id': 'p', 'validation': 'Explicit fixture review', 'reason': 'Accept bounded output'})
        proposal = self.coord('proposal', {'proposal_id': 'p'})
        self.assertEqual(proposal['changes'], {'Result.md': 'PACKAGED-ACCEPTED-FIXTURE'})
        self.assertEqual(proposal['status'], 'accepted')
        assignment = self.coord('assignment', {'assignment_id': 'a'})
        self.assertEqual(assignment['criteria'], ['Verify fixture'])
        first_events = self.coord('events', {'limit': 1})
        self.assertTrue(first_events['has_more'])
        second_events = self.coord('events', {'after_seq': first_events['next_after_seq'], 'limit': 1})
        self.assertEqual(second_events['events'][0]['sequence'], first_events['events'][0]['sequence'] + 1)
        self.cli('refresh')
        accepted = self.cli('receipt')
        self.assertEqual(accepted['readiness'], 'ready')
        recipient_token = self.root / 'recipient.token'
        self.cli('member-add', None, None, '--actor', 'sam', '--person', 'Sam Fictional',
            '--agent', 'Independent recipient', '--token-output', recipient_token)
        recipient = self.root / 'Other private folder' / 'Shared project'
        recipient.mkdir(parents=True)
        (recipient.parent / 'Private.md').write_text('RECIPIENT-PRIVATE-PARENT')
        recipient_state = self.root / 'recipient-private-state'
        joined = self.cli('attach', recipient, recipient_state, '--database', self.state / 'coordinator.sqlite3',
            '--token-file', recipient_token, '--expected-project-id', project_id)
        self.assertEqual(joined['readiness'], 'partial', 'Same-machine transport is not provider readiness')
        self.assertEqual((recipient / 'Result.md').read_text(), 'PACKAGED-ACCEPTED-FIXTURE')
        self.coord('handoff', {'assignment_id': 'a', 'to_actor': 'sam', 'summary': 'Recipient checks accepted fixture'})
        self.coord('receive', {'assignment_id': 'a', 'revision': accepted['revision'], 'files_hash': accepted['files_hash']},
                   recipient, recipient_state)
        self.coord('complete', {'assignment_id': 'a', 'revision': accepted['revision'],
            'files_hash': accepted['files_hash'], 'evidence': 'Recipient compared actual accepted bytes'},
            recipient, recipient_state)
        self.cli('team-status', recipient, recipient_state)
        self.assertEqual((self.project.parent / 'Private.md').read_text(), 'PRIVATE-PARENT')
        self.assertEqual((recipient.parent / 'Private.md').read_text(), 'RECIPIENT-PRIVATE-PARENT')
        for token in [self.state / 'member.token', recipient_token]:
            self.assertNotIn(token.read_text().strip(), json.dumps(self.outputs))

    def test_selected_project_and_private_state_mismatch_rejected_before_authority_mutation(self):
        self.initialize()
        other = self.root / 'Other project'; other.mkdir()
        other_state = self.root / 'other-state'
        self.initialize(other, other_state)
        before_owner = self.coord('status', {})
        before_other = self.coord('status', {}, other, other_state)
        # Supplying valid credentials for A with selected project B must not mutate A.
        self.coord('claim', {'assignment_id': 'wrong-binding', 'targets': ['Wrong.md'],
            'criteria': ['No cross-project mutation'], 'dependencies': [], 'resource_limits': {},
            'integration_owner': 'alex'}, other, self.state, expected=3)
        self.assertEqual(self.coord('status', {}), before_owner)
        self.assertEqual(self.coord('status', {}, other, other_state), before_other)

    def test_wrong_expected_attach_identity_leaves_recipient_unchanged(self):
        self.initialize()
        token = self.root / 'recipient.token'
        self.cli('member-add', None, None, '--actor', 'sam', '--person', 'Sam', '--agent', 'Test',
                 '--token-output', token)
        recipient = self.root / 'Recipient'; recipient.mkdir()
        (recipient / 'Private.md').write_text('KEEP-RECIPIENT-CONTENT')
        private = self.root / 'recipient-state'
        before = file_bytes(self.root)
        self.cli('attach', recipient, private, '--database', self.state / 'coordinator.sqlite3',
            '--token-file', token, '--expected-project-id', str(uuid.uuid4()), expected=3)
        self.assertEqual(file_bytes(self.root), before)
        self.assertFalse(private.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
