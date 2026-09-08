"""Opt-in session-fenced coordination using the engine's existing transaction.

No method opens a database, commits, runs workers, or treats note text as policy.
Schema 1 callers retain their explicitly legacy coordination semantics.
"""
from __future__ import annotations

import hmac
import json
import re
import time

from .engine import (READ_OPERATIONS as LEGACY_READS, canonical, digest, evidence,
                     fields, identifier, malformed, rejected, text, validate_path)
from .errors import ProductError

READ_OPERATIONS = {'policy', 'session', 'inbox', 'defect', 'outputs', 'output', 'interface'}
CONTROL = {'member-binding', 'session-open', 'session-delegate', 'session-revoke', 'policy-update'}
WORK = {'plan', 'acquire', 'renew', 'release', 'interface-publish', 'ack', 'rebind',
        'defect-report', 'defect-resolve', 'replan'}
OPERATIONS = READ_OPERATIONS | CONTROL | WORK
SUPPORTED_LEGACY = LEGACY_READS | {'member', 'revoke', 'propose', 'accept', 'resolve', 'reject', 'supersede',
                                  'complete', 'handoff', 'transfer-authority', 'transfer-integration'}
SESSION_OPERATIONS = (OPERATIONS | SUPPORTED_LEGACY) - {'session-open', 'member'}
OWNER_ONLY = {'member', 'revoke', 'member-binding', 'policy-update', 'transfer-authority', 'resolve'}
TABLES = ('coord_meta', 'coord_bindings', 'coord_sessions', 'coord_policies',
          'coord_outputs', 'coord_interfaces', 'coord_inbox', 'coord_defects', 'coord_invalidations')
MAX_RECORDS = 10000
MAX_SESSIONS = 1000
MAX_DEPTH = 8


def _get(connection, table, key, optional=False):
    if table not in TABLES:
        malformed('Invalid coordination table.')
    row = connection.execute(f'SELECT document,document_hash FROM {table} WHERE id=?', (key,)).fetchone()
    if row is None:
        if optional:
            return None
        rejected('Unknown coordination record.')
    value = json.loads(row[0])
    if not isinstance(value, dict) or digest(value) != row[1]:
        malformed('Coordination document failed hash verification.')
    return value


def _all(connection, table):
    return [_get(connection, table, row[0]) for row in connection.execute(f'SELECT id FROM {table} ORDER BY rowid')]


def _put(connection, table, key, value, *, immutable=False):
    previous = _get(connection, table, key, optional=True)
    if immutable and previous is not None:
        if previous != value:
            rejected('Immutable coordination identity was reused with different content.')
        return
    if previous is None and connection.execute(f'SELECT count(*) FROM {table}').fetchone()[0] >= MAX_RECORDS:
        rejected('Coordination record limit reached; preserve history and revise workload.')
    connection.execute(f'INSERT INTO {table}(id,document,document_hash) VALUES(?,?,?) '
                       'ON CONFLICT(id) DO UPDATE SET document=excluded.document,document_hash=excluded.document_hash',
                       (key, canonical(value), digest(value)))


def _number(value, label, low=0, high=2147483647):
    if type(value) is not int or not low <= value <= high:
        malformed(f'{label} must be an integer from {low} to {high}.')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        malformed('Expected a lowercase SHA-256 digest.')
    return value


def _targets(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 200:
        malformed('Scopes require 1–200 portable targets.')
    result = [validate_path(value, target=True) for value in values]
    if len({value.casefold() for value in result}) != len(result):
        malformed('Duplicate target scope.')
    return result


def _contains(scope, target):
    return scope == '.' or scope == target or (scope.endswith('/') and target.startswith(scope))


def _within(targets, scopes):
    if any(not any(_contains(scope, target) for scope in scopes) for target in targets):
        rejected('Operation targets exceed the authenticated session scope.')


def _policy(value):
    fields(value, set(), {'max_session_seconds', 'max_lease_seconds', 'allow_delegation', 'session_scopes'})
    writer = sorted(LEGACY_READS | READ_OPERATIONS | WORK | {'session-delegate', 'session-revoke',
                    'propose', 'accept', 'reject', 'supersede', 'complete', 'handoff', 'transfer-integration'})
    defaults = {'owner': sorted(SESSION_OPERATIONS), 'contributor': writer,
                'reader': sorted(LEGACY_READS | READ_OPERATIONS | {'ack', 'session-revoke'})}
    scopes = value.get('session_scopes', defaults)
    fields(scopes, {'owner', 'contributor', 'reader'})
    for role, operations in scopes.items():
        if (not isinstance(operations, list) or len(operations) > len(SESSION_OPERATIONS) or
                any(not isinstance(op, str) or op not in SESSION_OPERATIONS for op in operations) or
                len(set(operations)) != len(operations)):
            malformed('Policy session scopes contain unsupported or duplicate operations.')
        if role == 'reader' and set(operations) - set(defaults['reader']):
            malformed('Reader policy cannot grant writing capabilities.')
    delegation = value.get('allow_delegation', True)
    if type(delegation) is not bool:
        malformed('allow_delegation must be boolean.')
    return {'max_session_seconds': _number(value.get('max_session_seconds', 3600), 'Session lifetime', 1, 86400),
            'max_lease_seconds': _number(value.get('max_lease_seconds', 300), 'Lease lifetime', 1, 3600),
            'allow_delegation': delegation,
            'session_scopes': {role: sorted(operations) for role, operations in scopes.items()}}


def validate_configuration(config):
    fields(config, {'person_id', 'agent_id', 'policy'})
    return {'person_id': identifier(config['person_id'], 'person_id'),
            'agent_id': identifier(config['agent_id'], 'agent_id'), 'policy': _policy(config['policy'])}


def initialize_schema(connection, engine, owner_actor, config):
    """Create v2 coordination records inside a caller-owned transaction only."""
    config = validate_configuration(config)
    engine._owner(connection, owner_actor)
    for table in TABLES:
        extra = ',token_hash TEXT UNIQUE' if table == 'coord_sessions' else ''
        connection.execute(f'CREATE TABLE {table}(id TEXT PRIMARY KEY,document TEXT NOT NULL,document_hash TEXT NOT NULL{extra})')
    _put(connection, 'coord_meta', 'state', {'coordination_revision': 0, 'policy_revision': 1, 'clock_ms': 0})
    _put(connection, 'coord_bindings', owner_actor,
         {'actor': owner_actor, 'person_id': config['person_id'], 'agent_id': config['agent_id']}, immutable=True)
    _put(connection, 'coord_policies', '1', {'policy_revision': 1, 'policy': config['policy'],
         'policy_hash': digest(config['policy']), 'actor': owner_actor, 'reason': 'Explicit coordination initialization'}, immutable=True)


def verify_schema(connection, full=False):
    actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not set(TABLES) <= actual:
        malformed('Coordination schema is incomplete.')
    meta = _get(connection, 'coord_meta', 'state')
    fields(meta, {'coordination_revision', 'policy_revision', 'clock_ms'})
    for key in meta:
        _number(meta[key], key, 1 if key == 'policy_revision' else 0, 9223372036854775807)
    policy = _get(connection, 'coord_policies', str(meta['policy_revision']))
    if policy['policy_revision'] != meta['policy_revision'] or digest(_policy(policy['policy'])) != policy['policy_hash']:
        malformed('Coordination policy integrity check failed.')
    if full:
        for table in TABLES:
            _all(connection, table)


def summary(connection):
    meta = _get(connection, 'coord_meta', 'state')
    policy = _get(connection, 'coord_policies', str(meta['policy_revision']))
    return {'schema_version': 2, 'coordination_revision': meta['coordination_revision'],
            'policy_revision': meta['policy_revision'], 'policy_hash': policy['policy_hash'],
            'publication_requires_session': True}


def record_event(connection):
    meta = _get(connection, 'coord_meta', 'state')
    meta['coordination_revision'] += 1
    _put(connection, 'coord_meta', 'state', meta)


def _clock(connection, write=False):
    now = time.time_ns() // 1000000
    meta = _get(connection, 'coord_meta', 'state')
    if now < meta['clock_ms']:
        rejected('Coordinator clock moved backwards; lease operations are paused until clock recovery.')
    if write:
        _put(connection, 'coord_meta', 'state', dict(meta, clock_ms=now))
    return now


def _live_session(connection, engine, session_id, now):
    session = _get(connection, 'coord_sessions', session_id)
    seen = set()
    current = session
    while current:
        if current['session_id'] in seen or len(seen) > MAX_DEPTH:
            malformed('Session delegation lineage is cyclic or too deep.')
        seen.add(current['session_id'])
        if not current['active'] or now >= current['expires_ms']:
            rejected('Session or delegated authority has expired or been revoked.')
        member = engine._member(connection, current['actor'])
        binding = _get(connection, 'coord_bindings', member['actor'])
        if any(current[key] != binding[key] for key in ('person_id', 'agent_id')):
            rejected('Session identity no longer matches its member binding.')
        parent_id = current['parent_session_id']
        parent = _get(connection, 'coord_sessions', parent_id) if parent_id else None
        if parent and current['actor'] != parent['actor']:
            rejected('Stored cross-actor delegation is unauthorized; use independently authenticated member sessions.')
        current = parent
    return session


def authenticate(connection, engine, token):
    hashed = engine._token(token)
    row = connection.execute('SELECT id,token_hash FROM coord_sessions WHERE token_hash=?', (hashed,)).fetchone()
    if row:
        if not hmac.compare_digest(row['token_hash'], hashed):
            rejected('Session authentication failed.')
        session = _live_session(connection, engine, row['id'], _clock(connection))
        return {**engine._member(connection, session['actor']), '_session': session}
    return engine._auth(connection, token)


class Coordination:
    def __init__(self, connection, engine, state, member):
        self.db, self.engine, self.state, self.member = connection, engine, state, member
        self.actor = member['actor']
        self.session = member.get('_session')
        self.now = _clock(connection)
        self.policy_record = _get(connection, 'coord_policies', str(_get(connection, 'coord_meta', 'state')['policy_revision']))
        self.policy = self.policy_record['policy']

    def emit(self, operation, data):
        self.engine._event(self.db, self.actor, operation, data, self.state['revision'])

    def policy_revision(self, value, *, session=None, exact=False):
        _number(value, 'policy_revision', 1)
        current = self.policy_record['policy_revision']
        if value == current:
            return
        if value > current or exact:
            rejected('Reviewed policy revision is stale or unknown; read current authenticated policy.')
        subject = session if session is not None else self.session
        roles = self.session_roles(subject) if subject else {self.member['role']}
        previous = _get(self.db, 'coord_policies', str(value))['policy']
        relevant = self.effective_policy(previous, roles)
        # Compare the whole intervening history. Checking endpoints alone could
        # resurrect a proposal after its authorization was restricted/restored.
        for revision in range(value + 1, current + 1):
            policy = _get(self.db, 'coord_policies', str(revision))['policy']
            if self.effective_policy(policy, roles) != relevant:
                rejected('Policy relevant to this session or its delegation authority changed; review a fresh context.')

    def session_roles(self, session):
        roles = set()
        current = session
        while current:
            roles.add(self.engine._member(self.db, current['actor'])['role'])
            current = _get(self.db, 'coord_sessions', current['parent_session_id']) if current['parent_session_id'] else None
        return roles

    @staticmethod
    def effective_policy(policy, roles):
        return {'max_session_seconds': policy['max_session_seconds'],
                'max_lease_seconds': policy['max_lease_seconds'],
                'allow_delegation': policy['allow_delegation'],
                'session_scopes': {role: sorted(policy['session_scopes'][role]) for role in sorted(roles)}}

    def scoped(self, targets):
        if self.session:
            _within(targets, self.session['targets'])

    def assignment(self, assignment_id):
        item = self.engine._document(self.db, 'assignments', identifier(assignment_id))
        self.scoped(item['targets'])
        if 'generation' not in item:
            rejected('Legacy assignment requires explicit coordination rebinding before mutation.')
        return item

    def save_assignment(self, item):
        self.engine._put(self.db, 'assignments', item['assignment_id'], item)

    def require_session(self):
        if not self.session:
            rejected('This operation requires an authenticated running-session credential.')

    def requester(self):
        self.require_session()
        return {key: self.session[key] for key in ('actor', 'person_id', 'agent_id', 'session_id')}

    def guard(self, operation, payload):
        reads = LEGACY_READS | READ_OPERATIONS
        if operation not in SUPPORTED_LEGACY | OPERATIONS:
            rejected('This legacy operation is not implemented for fenced coordination; no mutation occurred.')
        if self.session:
            if operation not in self.session['scopes'] or operation not in self.policy['session_scopes'][self.member['role']]:
                rejected('Authenticated session lacks this operation under current policy.')
            ancestor = self.session
            while ancestor['parent_session_id']:
                ancestor = _get(self.db, 'coord_sessions', ancestor['parent_session_id'])
                ancestor_member = self.engine._member(self.db, ancestor['actor'])
                if operation not in ancestor['scopes'] or operation not in self.policy['session_scopes'][ancestor_member['role']]:
                    rejected('Delegating authority no longer grants this operation under current policy.')
                if operation in OWNER_ONLY and ancestor_member['role'] != 'owner':
                    rejected('Delegation cannot elevate a non-owner ancestor into owner-only authority.')
            if operation in {'snapshot', 'status', 'events', 'facts', 'member', 'revoke', 'member-binding', 'policy-update', 'transfer-authority'}:
                self.scoped(['.'])
        elif operation not in reads | {'member', 'revoke', 'member-binding', 'session-open', 'session-revoke', 'policy-update'}:
            self.require_session()
        if operation not in reads:
            _clock(self.db, write=True)
        if operation in {'member', 'revoke', 'member-binding', 'policy-update'}:
            self.engine._owner(self.db, self.actor)

    def notify(self, actors, kind, assignment_id=None, data=None):
        # Exact persisted recipients and message IDs permit durable targeted ack.
        for actor in sorted(set(actors)):
            if not self.db.execute('SELECT 1 FROM members WHERE actor=?', (actor,)).fetchone():
                malformed('Targeted message names an unknown member.')
            sequence = self.db.execute('SELECT count(*) FROM coord_inbox').fetchone()[0] + 1
            message = {'message_id': 'message-' + str(sequence), 'sequence': sequence,
                       'to_actor': actor, 'kind': kind, 'assignment_id': assignment_id,
                       'data': data or {}, 'acknowledged': False}
            _put(self.db, 'coord_inbox', message['message_id'], message)

    def publish_notice(self, item, kind, data=None):
        self.notify([item['actor'], item['integration_owner']], kind, item['assignment_id'], data)

    def dependencies(self, values, assignment_id):
        if not isinstance(values, list) or len(values) > 100:
            malformed('Dependencies must be a list of at most 100 pinned references.')
        result, seen = [], set()
        for edge in values:
            kind = edge.get('kind', 'output') if isinstance(edge, dict) else None
            if kind not in {'output', 'interface'}:
                malformed('Dependency kind must be output or interface.')
            revision_key = kind + '_revision'
            fields(edge, {'assignment_id', revision_key, 'interface_hash'}, {'kind'})
            upstream = identifier(edge['assignment_id'])
            self.engine._document(self.db, 'assignments', upstream)
            if upstream == assignment_id or upstream in seen:
                malformed('Self-dependencies and duplicate upstream dependencies are unsupported.')
            seen.add(upstream)
            result.append({'assignment_id': upstream, 'kind': kind,
                           revision_key: _number(edge[revision_key], revision_key, 1),
                           'interface_hash': _hash(edge['interface_hash'])})
        # Every traversed edge is an actual coordinator record, never note text.
        visited = set()
        def visit(node, ancestors):
            if len(ancestors) > 64:
                rejected('Dependency depth exceeds the 64-assignment bound.')
            if node in ancestors:
                rejected('Dependency graph would contain a cycle.')
            if node in visited:
                return
            document = self.engine._document(self.db, 'assignments', node)
            edges = result if node == assignment_id else document['dependencies']
            for edge in edges:
                if isinstance(edge, str):
                    rejected('Legacy dependencies require explicit coordination replanning.')
                visit(edge['assignment_id'], ancestors | {node})
            visited.add(node)
        # The new node does not exist yet; traverse its existing parents.
        for edge in result:
            visit(edge['assignment_id'], {assignment_id})
        return sorted(result, key=lambda edge: edge['assignment_id'])

    def key(self, assignment_id, revision):
        return assignment_id + ':' + str(revision)

    def valid_reference(self, edge):
        kind = edge['kind']
        key = self.key(edge['assignment_id'], edge[kind + '_revision'])
        record = _get(self.db, 'coord_interfaces' if kind == 'interface' else 'coord_outputs', key, optional=True)
        invalidated = _get(self.db, 'coord_invalidations', kind + ':' + key, optional=True)
        return bool(record and not invalidated and record['interface_hash'] == edge['interface_hash'])

    def inputs_valid(self, item):
        return all(self.valid_reference(edge) for edge in item['dependencies'])

    def refresh_ready(self):
        for item in self.engine._documents(self.db, 'assignments'):
            if item['status'] in {'queued', 'ready'} and 'generation' in item:
                desired = 'ready' if self.inputs_valid(item) else 'queued'
                if item['status'] != desired:
                    item['status'] = desired
                    self.save_assignment(item)
                    self.publish_notice(item, 'dependencies-' + desired)

    def fence(self, item, context, *, producer=False):
        self.require_session()
        fields(context, {'session_id', 'generation', 'policy_revision', 'input_hash'})
        if context['session_id'] != self.session['session_id']:
            rejected('Payload session identity is not the authenticated session.')
        self.policy_revision(context['policy_revision'])
        _number(context['generation'], 'generation', 1)
        lease = item.get('lease')
        if (item['status'] != 'active' or not lease or self.now >= lease['expires_ms'] or
                item['generation'] != context['generation'] or item['input_hash'] != context['input_hash']):
            rejected('Assignment lease, ownership generation, or input context is stale.')
        _live_session(self.db, self.engine, lease['session_id'], self.now)
        if producer and lease['session_id'] != self.session['session_id']:
            rejected('Only the currently leased producer session may publish work.')
        if not self.inputs_valid(item):
            rejected('Pinned input or interface has been invalidated.')

    def op_member_binding(self, payload):
        fields(payload, {'actor', 'person_id', 'agent_id'})
        actor = self.engine._member(self.db, identifier(payload['actor']))['actor']
        record = {'actor': actor, 'person_id': identifier(payload['person_id']), 'agent_id': identifier(payload['agent_id'])}
        for existing in _all(self.db, 'coord_bindings'):
            if existing['agent_id'] == record['agent_id'] and existing['actor'] != actor:
                rejected('Agent identity is already bound to another member.')
        previous = _get(self.db, 'coord_bindings', actor, optional=True)
        _put(self.db, 'coord_bindings', actor, record, immutable=True)
        if previous is None:
            self.emit('member-binding', record)
        return record

    def new_session(self, payload, delegate):
        fields(payload, {'session_id', 'token', 'ttl_seconds', 'scopes', 'targets'} | ({'to_actor'} if delegate else set()))
        session_id = identifier(payload['session_id'])
        if delegate:
            self.require_session()
            if not self.policy['allow_delegation'] or self.session['depth'] >= MAX_DEPTH:
                rejected('Delegation is disabled or its depth limit was reached.')
            member = self.engine._member(self.db, identifier(payload['to_actor']))
            if member['actor'] != self.actor:
                rejected('Delegation may narrow only the same authenticated actor; another member must open its own session.')
        else:
            if self.session:
                rejected('Running sessions must use bounded delegation to create child sessions.')
            member = self.member
        binding = _get(self.db, 'coord_bindings', member['actor'])
        scopes, targets = payload['scopes'], _targets(payload['targets'])
        if (not isinstance(scopes, list) or not scopes or any(not isinstance(op, str) for op in scopes) or
                len(set(scopes)) != len(scopes) or set(scopes) - set(self.policy['session_scopes'][member['role']])):
            malformed('Session scopes must be distinct operations allowed by current member policy.')
        if delegate:
            if set(scopes) - set(self.session['scopes']):
                rejected('A delegated session cannot expand operation scope.')
            _within(targets, self.session['targets'])
        ttl = _number(payload['ttl_seconds'], 'ttl_seconds', 1, self.policy['max_session_seconds'])
        expires = self.now + ttl * 1000
        if delegate and expires > self.session['expires_ms']:
            rejected('Delegated session lifetime cannot exceed its parent.')
        hashed = self.engine._token(payload['token'])
        existing = _get(self.db, 'coord_sessions', session_id, optional=True)
        intent = {**binding, 'session_id': session_id, 'scopes': sorted(scopes), 'targets': targets,
                  'parent_session_id': self.session['session_id'] if delegate else None,
                  'depth': self.session['depth'] + 1 if delegate else 0, 'ttl_seconds': ttl}
        if existing:
            stored_token = self.db.execute('SELECT token_hash FROM coord_sessions WHERE id=?', (session_id,)).fetchone()[0]
            if any(existing[key] != value for key, value in intent.items()) or not hmac.compare_digest(stored_token, hashed):
                rejected('Session identity cannot be reused with changed credentials or grants.')
            return existing
        if any(record['session_id'].casefold() == session_id.casefold() for record in _all(self.db, 'coord_sessions')):
            rejected('Session identity collides with an existing canonical spelling.')
        if self.db.execute('SELECT 1 FROM members WHERE token_hash=?', (hashed,)).fetchone() or self.db.execute('SELECT 1 FROM coord_sessions WHERE token_hash=?', (hashed,)).fetchone():
            rejected('Session credential must be unique and distinct from member credentials.')
        if self.db.execute('SELECT count(*) FROM coord_sessions').fetchone()[0] >= MAX_SESSIONS:
            rejected('Session history limit reached.')
        result = dict(intent, active=True, expires_ms=expires, created_policy_revision=self.policy_record['policy_revision'])
        self.db.execute('INSERT INTO coord_sessions VALUES(?,?,?,?)', (session_id, canonical(result), digest(result), hashed))
        self.emit('session-delegate' if delegate else 'session-open', result)
        return result

    def op_session_open(self, payload):
        return self.new_session(payload, False)

    def op_session_delegate(self, payload):
        return self.new_session(payload, True)

    def op_session_revoke(self, payload):
        fields(payload, {'session_id', 'reason'})
        record = _get(self.db, 'coord_sessions', identifier(payload['session_id']))
        reason = text(payload['reason'], 'revocation reason')
        if self.session:
            current = record
            while current['session_id'] != self.session['session_id'] and current['parent_session_id']:
                current = _get(self.db, 'coord_sessions', current['parent_session_id'])
            if current['session_id'] != self.session['session_id']:
                rejected('Sessions may revoke only themselves or their delegated descendants.')
        elif record['actor'] != self.actor and self.member['role'] != 'owner':
            rejected('Only a member or project owner may revoke that member session.')
        if record['active']:
            record.update(active=False, revocation_reason=reason)
            self.db.execute('UPDATE coord_sessions SET document=?,document_hash=? WHERE id=?',
                            (canonical(record), digest(record), record['session_id']))
            self.emit('session-revoke', {'session_id': record['session_id'], 'reason': reason})
        return record

    def op_policy(self, payload):
        fields(payload, set())
        return self.policy_record

    def op_policy_update(self, payload):
        fields(payload, {'expected_revision', 'policy', 'reason'})
        self.policy_revision(payload['expected_revision'], exact=True)
        policy = _policy(payload['policy'])
        reason = text(payload['reason'], 'policy reason')
        meta = _get(self.db, 'coord_meta', 'state')
        revision = meta['policy_revision'] + 1
        result = {'policy_revision': revision, 'policy': policy, 'policy_hash': digest(policy),
                  'actor': self.actor, 'reason': reason}
        _put(self.db, 'coord_policies', str(revision), result, immutable=True)
        _put(self.db, 'coord_meta', 'state', dict(meta, policy_revision=revision))
        self.emit('policy-update', result)
        changed_roles = {role for role in ('owner', 'contributor', 'reader')
                         if self.effective_policy(policy, {role}) != self.effective_policy(self.policy, {role})}
        affected = {row['actor'] for row in self.db.execute('SELECT actor,role FROM members WHERE active=1')
                    if row['role'] in changed_roles}
        for session in _all(self.db, 'coord_sessions'):
            try:
                _live_session(self.db, self.engine, session['session_id'], self.now)
            except ProductError as exc:
                if exc.exit_code != 4:
                    raise
                continue
            if self.session_roles(session) & changed_roles:
                affected.add(session['actor'])
        affected.add(self.actor)  # Keep the authenticated policy author's audit receipt.
        self.notify(affected, 'policy-updated', data={'policy_revision': revision, 'changed_roles': sorted(changed_roles)})
        return result

    def op_session(self, payload):
        fields(payload, {'session_id'})
        result = _get(self.db, 'coord_sessions', identifier(payload['session_id']))
        if self.session and result['session_id'] != self.session['session_id']:
            rejected('Session readers may inspect their own session only.')
        if not self.session and result['actor'] != self.actor and self.member['role'] != 'owner':
            rejected('Session belongs to another member.')
        return result

    def op_plan(self, payload):
        fields(payload, {'assignment_id', 'outcome_key', 'summary', 'targets', 'criteria', 'dependencies',
                         'interface_paths', 'resource_limits', 'integration_owner', 'policy_revision'})
        self.policy_revision(payload['policy_revision'])
        assignment_id, outcome = identifier(payload['assignment_id']), identifier(payload['outcome_key'])
        if self.db.execute('SELECT 1 FROM assignments WHERE id=?', (assignment_id,)).fetchone():
            previous = self.assignment(assignment_id)
            if previous.get('plan_request_hash') != digest(payload) or previous.get('creator_session_id') != self.session['session_id']:
                rejected('Assignment identity already exists with different planning context.')
            return previous
        if self.db.execute('SELECT count(*) FROM assignments').fetchone()[0] >= MAX_RECORDS:
            rejected('Assignment history limit reached.')
        targets = _targets(payload['targets'])
        self.scoped(targets)
        summary_text = text(payload['summary'], 'outcome summary')
        criteria = payload['criteria']
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= 100:
            malformed('Plans require 1–100 acceptance criteria.')
        criteria = [text(value, 'criterion') for value in criteria]
        interfaces = payload['interface_paths']
        if not isinstance(interfaces, list) or len(interfaces) > 100:
            malformed('Interface paths must be a bounded list.')
        interfaces = [validate_path(path) for path in interfaces]
        if len(set(interfaces)) != len(interfaces):
            malformed('Duplicate interface paths.')
        _within(interfaces, targets)
        limits = payload['resource_limits']
        fields(limits, set(), {'max_proposals', 'max_files', 'max_bytes'})
        for key, maximum in {'max_proposals': 1000, 'max_files': 10000, 'max_bytes': 100 * 1024 * 1024}.items():
            if key in limits:
                _number(limits[key], key, 1, maximum)
        integration = self.engine._member(self.db, identifier(payload['integration_owner']))
        if integration['role'] == 'reader' or 'accept' not in self.policy['session_scopes'][integration['role']]:
            rejected('Integration actor lacks policy authorization to integrate.')
        duplicates = []
        words = set(re.findall(r'\w+', summary_text.casefold()))
        for item in self.engine._documents(self.db, 'assignments'):
            if item.get('outcome_key', '').casefold() == outcome.casefold():
                rejected('Outcome already belongs to an existing assignment; reuse or explicitly replan that outcome.')
            if item['status'] == 'completed':
                continue
            other = set(re.findall(r'\w+', item.get('summary', '').casefold()))
            if words and other and len(words & other) / len(words | other) >= 0.6:
                duplicates.append(item['assignment_id'])
        dependencies = self.dependencies(payload['dependencies'], assignment_id)
        item = {'assignment_id': assignment_id, 'outcome_key': outcome, 'summary': summary_text,
                'actor': self.actor, 'human': self.member['human'], 'agent': self.member['agent'],
                'person_id': self.session['person_id'], 'agent_id': self.session['agent_id'],
                'integration_owner': integration['actor'], 'targets': targets, 'criteria': criteria,
                'dependencies': dependencies, 'interface_paths': interfaces, 'resource_limits': limits,
                'base_revision': self.state['revision'], 'generation': 0, 'plan_revision': 1,
                'lease': None, 'input_hash': digest(dependencies), 'handoffs': [], 'status': 'queued',
                'plan_request_hash': digest(payload), 'creator_session_id': self.session['session_id'],
                'requester': self.requester()}
        item['status'] = 'ready' if self.inputs_valid(item) else 'queued'
        self.save_assignment(item)
        self.emit('plan', item)
        self.publish_notice(item, 'assignment-planned')
        return dict(item, likely_duplicates=duplicates, duplicate_evidence='Advisory normalized-word overlap, not semantic equivalence')

    def op_acquire(self, payload):
        fields(payload, {'assignment_id', 'expected_generation', 'ttl_seconds', 'revision', 'files_hash', 'policy_revision'})
        self.policy_revision(payload['policy_revision'])
        self.engine._receipt(self.db, self.state, payload)
        item = self.assignment(payload['assignment_id'])
        if (item['status'] == 'active' and item.get('acquire_request_hash') == digest(payload) and
                item['lease']['session_id'] == self.session['session_id'] and self.lease_live(item['lease'])):
            return item
        if _number(payload['expected_generation'], 'expected_generation') != item['generation']:
            rejected('Ownership generation changed; refresh before acquiring.')
        ttl = _number(payload['ttl_seconds'], 'ttl_seconds', 1, self.policy['max_lease_seconds'])
        if item.get('designated_actor', self.actor) != self.actor:
            rejected('Handoff is reserved for its intended recipient.')
        if item['status'] not in {'ready', 'active'} or not self.inputs_valid(item):
            rejected('Assignment is not ready; required pinned inputs are unavailable.')
        if item['lease'] and self.lease_live(item['lease']):
            rejected('Assignment already has a live ownership lease.')
        for other in self.engine._documents(self.db, 'assignments'):
            lease = other.get('lease')
            if other['assignment_id'] != item['assignment_id'] and lease and self.lease_live(lease):
                def overlap(a, b):
                    a, b = a.rstrip('/').casefold(), b.rstrip('/').casefold()
                    return a == '.' or b == '.' or a == b or a.startswith(b + '/') or b.startswith(a + '/')
                if any(overlap(a, b) for a in item['targets'] for b in other['targets']):
                    rejected('Targets overlap another live ownership lease.')
        expiry = min(self.now + ttl * 1000, self.session['expires_ms'])
        item.update(status='active', actor=self.actor, human=self.member['human'], agent=self.member['agent'],
                    person_id=self.session['person_id'], agent_id=self.session['agent_id'],
                    generation=item['generation'] + 1, lease={'session_id': self.session['session_id'], 'expires_ms': expiry},
                    acquire_request_hash=digest(payload))
        self.save_assignment(item)
        self.emit('acquire', item)
        self.publish_notice(item, 'ownership-acquired', {'generation': item['generation']})
        return item

    def lease_live(self, lease):
        if self.now >= lease['expires_ms']:
            return False
        try:
            _live_session(self.db, self.engine, lease['session_id'], self.now)
            return True
        except ProductError as exc:
            if exc.exit_code != 4:
                raise
            return False

    def own_lease(self, payload):
        self.policy_revision(payload['policy_revision'])
        item = self.assignment(payload['assignment_id'])
        context = {'session_id': self.session['session_id'], 'generation': payload['generation'],
                   'policy_revision': payload['policy_revision'], 'input_hash': item['input_hash']}
        self.fence(item, context, producer=True)
        return item

    def op_renew(self, payload):
        fields(payload, {'assignment_id', 'generation', 'ttl_seconds', 'policy_revision'})
        item = self.own_lease(payload)
        ttl = _number(payload['ttl_seconds'], 'ttl_seconds', 1, self.policy['max_lease_seconds'])
        item['lease']['expires_ms'] = min(self.now + ttl * 1000, self.session['expires_ms'])
        self.save_assignment(item)
        self.emit('renew', {'assignment_id': item['assignment_id'], 'generation': item['generation'], 'lease': item['lease']})
        return item

    def op_release(self, payload):
        fields(payload, {'assignment_id', 'generation', 'reason', 'policy_revision'})
        item = self.own_lease(payload)
        reason = text(payload['reason'], 'release reason')
        item.update(status='ready', lease=None, generation=item['generation'] + 1)
        self.save_assignment(item)
        self.emit('release', {'assignment_id': item['assignment_id'], 'generation': item['generation'], 'reason': reason})
        self.publish_notice(item, 'ownership-released')
        return item

    def op_interface_publish(self, payload):
        fields(payload, {'assignment_id', 'interface_revision', 'contract', 'evidence', 'coordination'})
        item = self.assignment(payload['assignment_id'])
        self.fence(item, payload['coordination'])
        if self.session['session_id'] != item['lease']['session_id'] and self.actor != item['integration_owner']:
            rejected('Only the leased producer or integration actor may publish an interface.')
        revision = _number(payload['interface_revision'], 'interface_revision', 1)
        contract = text(payload['contract'], 'interface contract', maximum=65536)
        proof = evidence(payload['evidence'])
        key = self.key(item['assignment_id'], revision)
        previous = _get(self.db, 'coord_interfaces', key, optional=True)
        if previous:
            if previous['contract'] != contract or previous['evidence'] != proof:
                rejected('Interface revision already names different immutable bytes or evidence.')
            return previous
        versions = [record for record in _all(self.db, 'coord_interfaces') if record['assignment_id'] == item['assignment_id']]
        if revision != len(versions) + 1:
            rejected('Interface revisions must be contiguous.')
        result = {'assignment_id': item['assignment_id'], 'interface_revision': revision, 'contract': contract,
                  'interface_hash': digest(contract), 'evidence': proof, 'actor': self.actor,
                  'session_id': self.session['session_id'], 'generation': item['generation'],
                  'accepted_revision': self.state['revision'], 'dependencies': item['dependencies']}
        _put(self.db, 'coord_interfaces', key, result, immutable=True)
        self.emit('interface-publish', result)
        self.refresh_ready()
        self.publish_notice(item, 'interface-published', {'interface_revision': revision, 'interface_hash': result['interface_hash']})
        return result

    def op_interface(self, payload):
        fields(payload, {'assignment_id', 'interface_revision'})
        self.assignment(payload['assignment_id'])
        revision = _number(payload['interface_revision'], 'interface_revision', 1)
        key = self.key(payload['assignment_id'], revision)
        return dict(_get(self.db, 'coord_interfaces', key), valid=_get(self.db, 'coord_invalidations', 'interface:' + key, optional=True) is None)

    def op_outputs(self, payload):
        fields(payload, {'assignment_id'}, {'offset', 'limit'})
        self.assignment(payload['assignment_id'])
        offset, limit = self.engine._page(payload)
        prefix = payload['assignment_id'] + ':'
        query = 'FROM coord_outputs WHERE substr(id,1,?)=?'
        parameters = (len(prefix), prefix)
        total = self.db.execute('SELECT count(*) ' + query, parameters).fetchone()[0]
        items = []
        for row in self.db.execute('SELECT id ' + query + ' ORDER BY rowid LIMIT ? OFFSET ?', (*parameters, limit, offset)):
            item = _get(self.db, 'coord_outputs', row[0])
            keys = ('assignment_id', 'output_revision', 'revision', 'files_hash', 'output_hash',
                    'interface_hash', 'generation', 'input_hash')
            items.append({**{key: item[key] for key in keys}, 'interface_count': len(item['interfaces']),
                          'dependency_count': len(item['dependencies']), 'detail_hash': digest(item),
                          'details_available': True, 'evidence_summary': self.engine._evidence_summary(item['evidence']),
                          'valid': _get(self.db, 'coord_invalidations', 'output:' + row[0], optional=True) is None})
        return {'outputs': items, 'offset': offset, 'limit': limit, 'total': total,
                'next_offset': offset + len(items) if offset + len(items) < total else None}

    def op_output(self, payload):
        fields(payload, {'assignment_id', 'output_revision'})
        self.assignment(payload['assignment_id'])
        revision = _number(payload['output_revision'], 'output_revision', 1)
        key = self.key(payload['assignment_id'], revision)
        return dict(_get(self.db, 'coord_outputs', key),
                    valid=_get(self.db, 'coord_invalidations', 'output:' + key, optional=True) is None)

    def op_inbox(self, payload):
        fields(payload, set(), {'after_seq', 'limit'})
        after, limit = self.engine._page(payload, 'after_seq')
        items = [item for item in _all(self.db, 'coord_inbox') if item['to_actor'] == self.actor and item['sequence'] > after]
        if self.session:
            items = [item for item in items if item['assignment_id'] is None or
                     all(any(_contains(scope, target) for scope in self.session['targets']) for target in
                         self.engine._document(self.db, 'assignments', item['assignment_id'])['targets'])]
        page = items[:limit]
        return {'messages': page, 'next_after_seq': page[-1]['sequence'] if page else after, 'has_more': len(items) > limit}

    def op_ack(self, payload):
        fields(payload, {'message_id'})
        item = _get(self.db, 'coord_inbox', identifier(payload['message_id']))
        if item['to_actor'] != self.actor:
            rejected('Only an addressed member may acknowledge this message.')
        if item['assignment_id']:
            self.assignment(item['assignment_id'])
        if not item['acknowledged']:
            item.update(acknowledged=True, acknowledged_by=self.session['session_id'])
            _put(self.db, 'coord_inbox', item['message_id'], item)
            self.emit('ack', {'message_id': item['message_id'], 'session_id': self.session['session_id']})
        return item

    def invalidate(self, source, kind, revision, defect_id):
        source_key = kind + ':' + self.key(source['assignment_id'], revision)
        _put(self.db, 'coord_invalidations', source_key, {'reference': source_key, 'defect_id': defect_id}, immutable=True)
        affected = {source['assignment_id']}
        invalid = {source_key}
        assignments = self.engine._documents(self.db, 'assignments')
        records = [(table, output_kind, item) for table, output_kind in
                   [('coord_outputs', 'output'), ('coord_interfaces', 'interface')]
                   for item in _all(self.db, table)]
        def broken(edges):
            return any(isinstance(edge, dict) and edge['kind'] + ':' +
                       self.key(edge['assignment_id'], edge[edge['kind'] + '_revision']) in invalid for edge in edges)
        while True:
            expanded = invalid | {output_kind + ':' + self.key(record['assignment_id'], record[output_kind + '_revision'])
                                  for _, output_kind, record in records if broken(record.get('dependencies', []))}
            if expanded == invalid:
                break
            invalid = expanded
        affected |= {item['assignment_id'] for item in assignments if broken(item['dependencies'])}
        # Unpublished descendants still need replanning when an upstream plan is
        # invalidated, even though the requested future output does not exist yet.
        while True:
            expanded = affected | {item['assignment_id'] for item in assignments if any(
                isinstance(edge, dict) and edge['assignment_id'] in affected and not self.valid_reference(edge)
                for edge in item['dependencies'])}
            if expanded == affected:
                break
            affected = expanded
        for key in sorted(invalid):
            if _get(self.db, 'coord_invalidations', key, optional=True) is None:
                _put(self.db, 'coord_invalidations', key, {'reference': key, 'defect_id': defect_id}, immutable=True)
        for item in assignments:
            if item['assignment_id'] not in affected or 'generation' not in item:
                continue
            item.update(status='invalidated', lease=None, generation=item['generation'] + 1)
            self.save_assignment(item)
            self.publish_notice(item, 'work-invalidated', {'defect_id': defect_id, 'generation': item['generation']})
        return sorted(affected)

    def op_rebind(self, payload):
        fields(payload, {'assignment_id', 'expected_assignment_hash', 'outcome_key', 'summary', 'dependencies',
                         'interface_paths', 'revision', 'files_hash', 'policy_revision', 'evidence'})
        self.policy_revision(payload['policy_revision'])
        self.engine._receipt(self.db, self.state, payload)
        item = self.engine._document(self.db, 'assignments', identifier(payload['assignment_id']))
        self.scoped(item['targets'])
        if 'generation' in item or item['status'] == 'completed' or self.actor != item['integration_owner']:
            rejected('Only the integration actor may explicitly rebind unfinished legacy work.')
        if _hash(payload['expected_assignment_hash']) != digest(item):
            rejected('Legacy assignment changed since review.')
        proof = evidence(payload['evidence'])
        outcome = identifier(payload['outcome_key'])
        if any(other.get('outcome_key', '').casefold() == outcome.casefold()
               for other in self.engine._documents(self.db, 'assignments')):
            rejected('Outcome is already reserved.')
        dependencies = self.dependencies(payload['dependencies'], item['assignment_id'])
        interfaces = payload['interface_paths']
        if not isinstance(interfaces, list) or len(interfaces) > 100:
            malformed('Interface paths must be a bounded list.')
        interfaces = [validate_path(path) for path in interfaces]
        _within(interfaces, item['targets'])
        archived = []
        for row in self.db.execute('SELECT id FROM proposals WHERE assignment_id=?', (item['assignment_id'],)).fetchall():
            proposal = self.engine._proposal(self.db, row[0])
            if proposal['status'] in {'pending', 'conflict'}:
                archived.append({'proposal_id': proposal['id'], 'previous_status': proposal['status'], 'request_hash': proposal['request_hash']})
                self.engine._proposal_state(self.db, proposal['id'], 'legacy_blocked')
        for conflict in self.engine._documents(self.db, 'conflicts'):
            if conflict['assignment_id'] == item['assignment_id'] and conflict['status'] == 'unresolved':
                conflict.update(status='legacy_blocked', resolution='Legacy context retired; preserved proposal bytes require a new reviewed proposal.')
                self.engine._put(self.db, 'conflicts', conflict['conflict_id'], conflict)
        previous_hash = digest(item)
        item.update(outcome_key=outcome, summary=text(payload['summary'], 'outcome summary'),
                    dependencies=dependencies, interface_paths=interfaces, generation=1, plan_revision=1,
                    lease=None, input_hash=digest(dependencies), base_revision=self.state['revision'],
                    legacy_assignment_hash=previous_hash, requester=self.requester())
        item['status'] = 'ready' if self.inputs_valid(item) else 'queued'
        self.save_assignment(item)
        self.emit('rebind', {'assignment': item, 'evidence': proof, 'archived_proposals': archived})
        self.publish_notice(item, 'legacy-work-rebound')
        return item

    def op_defect_report(self, payload):
        kind = payload.get('kind', 'output')
        if kind not in {'output', 'interface'}:
            malformed('Defect kind must be output or interface.')
        fields(payload, {'defect_id', 'assignment_id', kind + '_revision', 'summary', 'evidence', 'policy_revision'}, {'kind'})
        self.policy_revision(payload['policy_revision'])
        defect_id = identifier(payload['defect_id'])
        source = self.assignment(payload['assignment_id'])
        if self.actor not in {source['actor'], source['integration_owner']}:
            rejected('Only the source producer or integration actor may invalidate its published contract/output.')
        revision = _number(payload[kind + '_revision'], 'defect revision', 1)
        _get(self.db, 'coord_interfaces' if kind == 'interface' else 'coord_outputs', self.key(source['assignment_id'], revision))
        request = {**payload, 'kind': kind, 'summary': text(payload['summary'], 'defect summary'), 'evidence': evidence(payload['evidence'])}
        previous = _get(self.db, 'coord_defects', defect_id, optional=True)
        if previous:
            if previous['request'] != request or previous['actor'] != self.actor:
                rejected('Defect identity already records different evidence.')
            return previous
        affected = self.invalidate(source, kind, revision, defect_id)
        result = {'defect_id': defect_id, 'request': request, 'actor': self.actor, 'status': 'open', 'affected_assignments': affected}
        _put(self.db, 'coord_defects', defect_id, result)
        self.emit('defect-report', result)
        return result

    def op_defect(self, payload):
        fields(payload, {'defect_id'})
        item = _get(self.db, 'coord_defects', identifier(payload['defect_id']))
        self.assignment(item['request']['assignment_id'])
        return item

    def op_replan(self, payload):
        fields(payload, {'assignment_id', 'expected_plan_revision', 'dependencies', 'reason', 'policy_revision'})
        self.policy_revision(payload['policy_revision'])
        item = self.assignment(payload['assignment_id'])
        if self.actor != item['integration_owner']:
            rejected('Only the authorized integration actor may replan this assignment.')
        if any(other['assignment_id'] != item['assignment_id'] and
               other.get('outcome_key', '').casefold() == item['outcome_key'].casefold()
               for other in self.engine._documents(self.db, 'assignments')):
            rejected('Another assignment already reserves this outcome.')
        if _number(payload['expected_plan_revision'], 'expected_plan_revision', 1) != item['plan_revision']:
            rejected('Plan revision changed before replanning.')
        reason = text(payload['reason'], 'replanning reason')
        dependencies = self.dependencies(payload['dependencies'], item['assignment_id'])
        item.update(plan_revision=item['plan_revision'] + 1, generation=item['generation'] + 1,
                    dependencies=dependencies, input_hash=digest(dependencies), lease=None,
                    base_revision=self.state['revision'])
        item['status'] = 'ready' if self.inputs_valid(item) else 'queued'
        self.save_assignment(item)
        self.emit('replan', {'assignment': item, 'reason': reason})
        self.publish_notice(item, 'work-replanned', {'plan_revision': item['plan_revision']})
        return item

    def op_defect_resolve(self, payload):
        fields(payload, {'defect_id', 'replacement_assignment_id', 'replacement_output_revision', 'evidence', 'policy_revision'})
        self.policy_revision(payload['policy_revision'])
        defect = _get(self.db, 'coord_defects', identifier(payload['defect_id']))
        source = self.assignment(defect['request']['assignment_id'])
        if self.actor != source['integration_owner']:
            rejected('Only the source integration actor may resolve its defect.')
        replacement = self.assignment(payload['replacement_assignment_id'])
        revision = _number(payload['replacement_output_revision'], 'replacement_output_revision', 1)
        output = _get(self.db, 'coord_outputs', self.key(replacement['assignment_id'], revision))
        if not self.valid_reference({'kind': 'output', 'assignment_id': replacement['assignment_id'],
                                     'output_revision': revision, 'interface_hash': output['interface_hash']}):
            rejected('Replacement output has been invalidated.')
        proof = evidence(payload['evidence'])
        resolution = {'assignment_id': replacement['assignment_id'], 'output_revision': revision, 'evidence': proof}
        if defect['status'] == 'resolved':
            if defect['resolution'] != resolution:
                rejected('Defect already has a different preserved resolution.')
            return defect
        defect.update(status='resolved', resolution=resolution)
        _put(self.db, 'coord_defects', defect['defect_id'], defect)
        self.emit('defect-resolve', defect)
        self.publish_notice(source, 'defect-resolved', {'defect_id': defect['defect_id']})
        return defect

    def publication(self, operation, payload):
        proposal = self.engine._proposal(self.db, identifier(payload['proposal_id'])) if operation in {'accept', 'resolve'} else None
        item = self.assignment(proposal['assignment_id'] if proposal else payload['assignment_id'])
        self.fence(item, payload.get('coordination'), producer=operation in {'propose', 'complete'})
        if proposal:
            original = proposal.get('coordination')
            if not isinstance(original, dict):
                rejected('Legacy pending proposal has no authenticated session fencing context.')
            producer_session = _live_session(self.db, self.engine, original.get('session_id'), self.now)
            self.policy_revision(original['policy_revision'], session=producer_session)
            if (producer_session['session_id'] != item['lease']['session_id'] or
                    producer_session['actor'] != proposal['actor'] or original['generation'] != item['generation'] or
                    original['input_hash'] != item['input_hash']):
                rejected('Pending proposal belongs to a superseded session, generation, policy, or input context.')
        if operation == 'complete':
            fields(payload, {'assignment_id', 'revision', 'files_hash', 'evidence', 'coordination'})
            result = self.engine._op_complete(self.db, self.state, self.member, {k: v for k, v in payload.items() if k != 'coordination'})
            files, _, hashed = self.engine._snapshot(self.db, self.state['revision'])
            paths = {path: value for path, value in files.items() if any(_contains(target, path) for target in item['targets'])}
            interfaces = {path: files.get(path) for path in item['interface_paths']}
            versions = [value for value in _all(self.db, 'coord_outputs') if value['assignment_id'] == item['assignment_id']]
            output = {'assignment_id': item['assignment_id'], 'output_revision': len(versions) + 1,
                      'revision': self.state['revision'], 'files_hash': hashed, 'output_hash': digest(paths),
                      'interface_hash': digest(interfaces), 'interfaces': interfaces,
                      'generation': item['generation'], 'input_hash': item['input_hash'], 'evidence': payload['evidence'],
                      'dependencies': list(item['dependencies'])}
            interfaces_published = [value for value in _all(self.db, 'coord_interfaces') if value['assignment_id'] == item['assignment_id']]
            if interfaces_published:
                latest = interfaces_published[-1]
                output['dependencies'].append({'assignment_id': item['assignment_id'], 'kind': 'interface',
                    'interface_revision': latest['interface_revision'], 'interface_hash': latest['interface_hash']})
                if not self.valid_reference(output['dependencies'][-1]):
                    rejected('Latest published interface is invalidated; publish a replacement contract first.')
            _put(self.db, 'coord_outputs', self.key(item['assignment_id'], output['output_revision']), output, immutable=True)
            result['lease'] = None
            self.save_assignment(result)
            self.emit('output-publish', output)
            self.refresh_ready()
            self.publish_notice(item, 'output-published', {'output_revision': output['output_revision']})
            return dict(result, output=output)
        previous_event = self.db.execute('SELECT max(seq) FROM events').fetchone()[0]
        request = payload
        if operation == 'resolve':
            fields(payload, {'proposal_id', 'resolutions', 'coordination'})
            request = {key: value for key, value in payload.items() if key != 'coordination'}
        result = getattr(self.engine, '_op_' + operation)(self.db, self.state, self.member, request)
        if self.db.execute('SELECT max(seq) FROM events').fetchone()[0] != previous_event:
            self.publish_notice(item, 'proposal-' + operation, {'proposal_id': payload['proposal_id']})
        return result

    def handoff(self, payload):
        fields(payload, {'assignment_id', 'to_actor', 'summary', 'coordination'})
        item = self.assignment(payload['assignment_id'])
        self.fence(item, payload['coordination'])
        if self.session['session_id'] != item['lease']['session_id'] and self.actor != item['integration_owner']:
            rejected('Only the current producer or integrator may hand off work.')
        recipient = self.engine._member(self.db, identifier(payload['to_actor']))
        if recipient['role'] == 'reader':
            rejected('Handoff requires a writing recipient.')
        summary_text = text(payload['summary'], 'handoff summary')
        item['handoffs'].append({'from_actor': item['actor'], 'to_actor': recipient['actor'],
                                 'from_generation': item['generation'], 'summary': summary_text})
        item.update(status='ready', lease=None, generation=item['generation'] + 1, designated_actor=recipient['actor'])
        self.save_assignment(item)
        self.emit('handoff', item)
        self.notify([item['actor'], recipient['actor'], item['integration_owner']], 'handoff', item['assignment_id'])
        return item


def dispatch(connection, engine, state, member, operation, payload):
    handler = Coordination(connection, engine, state, member)
    handler.guard(operation, payload)
    method = getattr(handler, 'op_' + operation.replace('-', '_'), None)
    if method:
        return method(payload)
    if operation in {'propose', 'accept', 'resolve', 'complete'}:
        return handler.publication(operation, payload)
    if operation == 'handoff':
        return handler.handoff(payload)
    if operation == 'transfer-authority':
        fields(payload, {'key', 'to_actor', 'evidence', 'reason', 'policy_revision', 'revision', 'files_hash'})
        handler.policy_revision(payload['policy_revision'])
        engine._receipt(connection, state, payload)
        request = {key: value for key, value in payload.items() if key not in {'policy_revision', 'revision', 'files_hash'}}
        result = engine._op_transfer_authority(connection, state, member, request)
        handler.notify([member['actor'], result['to_actor']], 'fact-authority-transferred', data={'key': result['key'], 'revision': result['revision']})
        return result
    if operation == 'transfer-integration':
        fields(payload, {'assignment_id', 'to_actor', 'reason', 'coordination'})
        item = handler.assignment(payload['assignment_id'])
        handler.fence(item, payload['coordination'])
        recipient = engine._member(connection, identifier(payload['to_actor']))
        if recipient['role'] == 'reader' or 'accept' not in handler.policy['session_scopes'][recipient['role']]:
            rejected('Recipient is not authorized to integrate under current policy.')
        result = engine._op_transfer_integration(connection, state, member, {key: value for key, value in payload.items() if key != 'coordination'})
        handler.notify([item['integration_owner'], recipient['actor'], item['actor']], 'integration-transferred', item['assignment_id'])
        return result
    if operation in {'reject', 'supersede'}:
        fields(payload, {'proposal_id', 'reason', 'coordination'} | ({'replacement_id'} if operation == 'supersede' else set()))
        proposal = engine._proposal(connection, identifier(payload['proposal_id']))
        item = handler.assignment(proposal['assignment_id'])
        handler.fence(item, payload['coordination'])
        result = getattr(engine, '_op_' + operation)(connection, state, member, {k: v for k, v in payload.items() if k != 'coordination'})
        handler.publish_notice(item, 'proposal-' + operation, {'proposal_id': proposal['id']})
        return result
    if operation in {'assignment', 'proposal', 'conflict'}:
        if operation == 'assignment':
            item = engine._document(connection, 'assignments', identifier(payload.get('assignment_id')))
        elif operation == 'proposal':
            proposal = engine._proposal(connection, identifier(payload.get('proposal_id')))
            item = engine._document(connection, 'assignments', proposal['assignment_id'])
        else:
            conflict = engine._document(connection, 'conflicts', identifier(payload.get('conflict_id')))
            item = engine._document(connection, 'assignments', conflict['assignment_id'])
        handler.scoped(item['targets'])
    if operation == 'member' and connection.execute('SELECT 1 FROM coord_sessions WHERE token_hash=?', (engine._token(payload.get('token')),)).fetchone():
        rejected('Membership credential cannot reuse an existing session credential.')
    return getattr(engine, '_op_' + operation.replace('-', '_'))(connection, state, member, payload)
