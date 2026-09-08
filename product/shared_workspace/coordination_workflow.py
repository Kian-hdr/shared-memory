"""Explicit private session credentials and coordinator schema upgrades."""
from __future__ import annotations

import secrets

from .errors import ProductError
from .transport import read_token
from .workflow import (connect, json_file, private_path, project_manifest, selected_root,
                       _setup_lock, _publish_setup_json, _publish_setup_bytes, _setup_digest)

COMMANDS = ('session-create', 'coordination-plan-upgrade', 'coordination-upgrade')


def add_commands(commands):
    session = commands.add_parser('session-create', help='Create or retry a bounded session with a durable private credential')
    session.add_argument('project')
    session.add_argument('--state-dir', required=True)
    session.add_argument('--session-id', required=True)
    session.add_argument('--grants-file', required=True, help='JSON ttl_seconds, scopes, targets; no credential value')
    session.add_argument('--delegate-to', help='Same authenticated actor for a narrower child session; other actors create their own sessions')
    session.add_argument('--session-token-file', help='Private parent session credential for delegation')
    for name in COMMANDS[1:]:
        command = commands.add_parser(name, help='Explicit local authority upgrade with preserved history and private backup')
        command.add_argument('--database', required=True)
        command.add_argument('--token-file', required=True)
        command.add_argument('--expected-project-id', required=True)
        command.add_argument('--coordination-file', required=True)
        if name == 'coordination-upgrade':
            command.add_argument('--expected-checkpoint', required=True)
            command.add_argument('--backup-destination', required=True)
            command.add_argument('--migration-id', required=True)


def create_session(args):
    from .engine import fields, identifier
    root = selected_root(args.project)
    state = private_path(args.state_dir, root)
    metadata = project_manifest(root)
    client = json_file(state / 'client/client.json')
    if client.get('project_id') != metadata['project_id'] or client.get('project_root') != str(root):
        raise ProductError(3, 'project_mismatch', 'Session state belongs to another selected project.')
    identity = identifier(args.session_id, 'session_id')
    grants = json_file(private_path(args.grants_file, root))
    fields(grants, {'ttl_seconds', 'scopes', 'targets'})
    delegated = args.delegate_to is not None
    if delegated != (args.session_token_file is not None):
        raise ProductError(2, 'usage_error', 'Delegation requires both --delegate-to and its private parent --session-token-file.')
    if delegated:
        if not args.delegate_to.strip():
            raise ProductError(2, 'usage_error', 'An explicit delegation actor must not be empty.')
        identifier(args.delegate_to, 'to_actor')
        if not args.session_token_file.strip():
            raise ProductError(2, 'usage_error', 'An explicit parent session credential path must not be empty.')
    credential = private_path(args.session_token_file, root) if delegated else state / 'member.token'
    request = connect(state, credential)
    status = connect(state)('status', {})
    if status['project_id'] != metadata['project_id']:
        raise ProductError(3, 'project_mismatch', 'Session connection points to another authority.')
    if status.get('coordination', {}).get('schema_version') != 2:
        raise ProductError(3, 'coordination_required', 'Session creation requires explicitly initialized or upgraded schema 2.')
    binding = {'project_id': metadata['project_id'], 'session_id': identity, 'grants': grants,
               'to_actor': args.delegate_to, 'parent_credential_hash': _setup_digest(read_token(credential))}
    directory = private_path(state / 'sessions' / identity, root)
    with _setup_lock(directory):
        intent_file = directory / 'intent.json'
        if intent_file.exists():
            intent = json_file(intent_file)
            if (not isinstance(intent, dict) or intent.get('binding') != binding
                    or intent.get('intent_hash') != _setup_digest({k: v for k, v in intent.items() if k != 'intent_hash'})):
                raise ProductError(3, 'session_intent_mismatch', 'Session retry inputs changed; preserve this credential and use a distinct identity for new work.')
        else:
            intent = {'binding': binding, 'token': secrets.token_urlsafe(48)}
            intent['intent_hash'] = _setup_digest(intent)
            _publish_setup_json(intent_file, intent)
        token_file = private_path(directory / 'session.token', root)
        if token_file.exists():
            if read_token(token_file) != intent['token']:
                raise ProductError(3, 'session_intent_mismatch', 'Session credential differs from its durable intent.')
        else:
            _publish_setup_bytes(token_file, (intent['token'] + '\n').encode('utf-8'))
        payload = {'session_id': identity, 'token': intent['token'], **grants}
        if delegated:
            payload['to_actor'] = identifier(args.delegate_to, 'to_actor')
        result = request('session-delegate' if delegated else 'session-open', payload)
        return {'session': result, 'credential_file': str(token_file), 'credential_saved': True,
                'automatic_renewal': False, 'next': 'Use this private --session-token-file on session operations. Record acquired context with drafts.'}


def dispatch(bundle, args):
    if args.command == 'session-create':
        return create_session(args)
    from . import coordinator_migration
    database = private_path(args.database)
    token = read_token(private_path(args.token_file))
    config = json_file(private_path(args.coordination_file))
    common = {'expected_project_id': args.expected_project_id, 'coordination': config}
    if args.command == 'coordination-plan-upgrade':
        return coordinator_migration.plan(database, token, **common)
    if args.command == 'coordination-upgrade':
        return coordinator_migration.upgrade(database, token, **common,
            expected_checkpoint=args.expected_checkpoint, backup_destination=private_path(args.backup_destination),
            migration_id=args.migration_id)
    raise ProductError(2, 'usage_error', 'Unknown coordination command.')
