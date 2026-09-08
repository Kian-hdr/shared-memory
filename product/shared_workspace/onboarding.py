"""Bounded, resumable selected-folder onboarding over the existing workflow."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
from pathlib import Path
import secrets
import sys

from . import workflow
from .errors import ProductError
from .transport import read_token

COMMANDS = ('setup',)
IDENTITY = ('person', 'actor', 'agent', 'purpose')
JOIN = ('expected_project_id', 'endpoint', 'database', 'token_file', 'ca_file')


def add_commands(commands):
    setup = commands.add_parser('setup', help='Diagnose and finish or resume setup in the selected existing folder')
    setup.add_argument('project')
    setup.add_argument('--state-dir', help='Private local state; defaults to a deterministic per-folder application-data directory')
    for name in IDENTITY:
        setup.add_argument('--' + name)
    setup.add_argument('--provider', choices=workflow.PROVIDERS)
    setup.add_argument('--expected-project-id')
    route = setup.add_mutually_exclusive_group()
    route.add_argument('--endpoint')
    route.add_argument('--database', help='Existing same-machine authority only, never a synced database')
    setup.add_argument('--token-file', help='Your own private membership credential for joining')
    setup.add_argument('--ca-file')


def default_state(root):
    """No directory is created until workflow validation succeeds."""
    home = Path.home()
    if sys.platform == 'win32':
        base = Path(os.environ.get('LOCALAPPDATA') or home / 'AppData/Local')
    elif sys.platform == 'darwin':
        base = home / 'Library/Application Support'
    else:
        base = Path(os.environ.get('XDG_STATE_HOME') or home / '.local/state')
    if not base.is_absolute():
        raise ProductError(3, 'state_path_unsafe', 'The platform private-state directory must be absolute; supply --state-dir.')
    key = hashlib.sha256(os.path.normcase(str(root)).encode('utf-8')).hexdigest()
    return workflow.private_path(base / 'Shared Memory/projects' / key, root)


def mismatch(field):
    raise ProductError(3, 'setup_mismatch', 'Explicit --' + field.replace('_', '-') +
                       ' conflicts with saved setup. Existing identity and access were preserved.')


def _value(name, value, root):
    if name in {'database', 'token_file', 'ca_file'} and value is not None:
        return str(workflow.private_path(value, root))
    return value


def _resume_arguments(args, root, state, intent):
    if not isinstance(intent, dict) or not isinstance(intent.get('binding'), dict):
        raise ProductError(3, 'setup_invalid', 'Private setup intent is malformed; preserve it for recovery.')
    binding = intent['binding']
    if binding.get('command') not in {'init', 'attach'} or binding.get('project_root') != str(root):
        mismatch('project')
    for field in (*IDENTITY, 'provider', *JOIN):
        supplied = getattr(args, field)
        if supplied is None:
            continue
        stored = intent.get('project_id') if field == 'expected_project_id' else binding.get(field)
        if _value(field, supplied, root) != stored:
            mismatch(field)
    values = dict(binding)
    values.pop('project_root', None)
    values['project'] = str(root)
    values['state_dir'] = str(state)
    if binding['command'] == 'init':
        values['coordination_config'] = values.pop('coordination', None)
        values['coordination_file'] = None
    else:
        values['expected_project_id'] = values.pop('project_id')
    resumed = argparse.Namespace(**values)
    # Verify the immutable digest, private binding and existing material before
    # workflow restoration. Never infer repair from an unvalidated JSON object.
    workflow._check_setup_state(root, state, intent, workflow._setup_binding(root, resumed))
    return resumed


def _existing_arguments(args, root, state, metadata):
    """Older successful state remains usable without fabricating setup intent."""
    connection = workflow.json_file(state / 'connection.json')
    for field in IDENTITY:
        if getattr(args, field) is not None:
            raise ProductError(3, 'setup_identity_unverified',
                               'This existing installation has no setup intent. Omit identity overrides to keep its authenticated membership.')
    expected = {'provider': metadata['provider'], 'expected_project_id': metadata['project_id'],
                'endpoint': connection.get('endpoint'), 'database': connection.get('database'),
                'ca_file': connection.get('ca_file')}
    for field, stored in expected.items():
        supplied = getattr(args, field)
        if supplied is not None and _value(field, supplied, root) != stored:
            mismatch(field)
    if args.token_file is not None:
        if read_token(workflow.private_path(args.token_file, root)) != read_token(state / 'member.token'):
            mismatch('token_file')
    return argparse.Namespace(command='refresh', project=str(root), state_dir=str(state), session_token_file=None)


def _fresh_arguments(args, root, state, metadata):
    joining = metadata is not None or any(getattr(args, name) is not None for name in JOIN)
    provider = args.provider or (metadata['provider'] if metadata else 'local')
    if joining:
        identity = args.expected_project_id or (metadata['project_id'] if metadata else None)
        missing = []
        if not identity:
            missing.append('expected_project_id')
        if not (args.endpoint or args.database):
            missing.append('endpoint_or_database')
        if not args.token_file:
            missing.append('token_file')
        if missing:
            raise ProductError(4, 'setup_access_required',
                               'This is an existing team or joining request. Supply your own member token, expected project ID and authorized coordinator access; no new authority was created.',
                               data={'readiness': 'blocked', 'missing_inputs': missing, 'route': 'attach'})
        if any(getattr(args, name) is not None for name in IDENTITY):
            raise ProductError(3, 'setup_identity_unverified',
                               'Joining uses the identity issued with your membership token. Omit owner identity fields.')
        return argparse.Namespace(command='attach', project=str(root), state_dir=str(state),
                                  expected_project_id=identity, endpoint=args.endpoint, database=args.database,
                                  token_file=args.token_file, ca_file=args.ca_file, provider=provider)
    try:
        person = getpass.getuser()
    except (KeyError, OSError):
        person = 'Local user'
    return argparse.Namespace(command='init', project=str(root), state_dir=str(state), mode='local',
                              provider=provider, person=args.person or person,
                              actor=args.actor or 'local-' + secrets.token_hex(8), agent=args.agent or 'Local agent',
                              purpose=args.purpose or 'Shared work in ' + root.name, include=None,
                              coordination_file=None, coordination_config=None)


def dispatch(bundle, args):
    for field in ('state_dir', *IDENTITY, 'provider', *JOIN):
        value = getattr(args, field)
        if value is not None and not value.strip():
            raise ProductError(2, 'usage_error', '--' + field.replace('_', '-') + ' cannot be empty.')
    root = workflow.selected_root(args.project)
    state = workflow.private_path(args.state_dir, root) if args.state_dir else default_state(root)
    intent_path = workflow.private_path(state / workflow.SETUP_INTENT)
    metadata = workflow.project_manifest(root) if (root / workflow.MANIFEST).exists() else None
    repairs = []
    if intent_path.exists():
        intent = workflow.json_file(intent_path)
        selected = _resume_arguments(args, root, state, intent)
        route = 'resume_' + selected.command
        for name in ('member.token', 'connection.json', 'client/client.json', 'client/snapshot.json'):
            if not (state / name).exists():
                repairs.append({'kind': 'restore_missing_setup_file', 'file': name})
        result = workflow.dispatch(bundle, selected)
        receipt = result['receipt']
    elif metadata is not None and (state / 'client/client.json').exists():
        selected = _existing_arguments(args, root, state, metadata)
        route = 'existing_binding'
        receipt = workflow.dispatch(bundle, selected)
    else:
        selected = _fresh_arguments(args, root, state, metadata)
        route = selected.command
        result = workflow.dispatch(bundle, selected)
        receipt = result['receipt']
    # A local receipt alone does not prove it is current at the authority.
    checked = workflow.dispatch(bundle, argparse.Namespace(command='team-status', project=str(root),
                                state_dir=str(state), session_token_file=None))
    status, current = checked['coordinator'], checked['local']
    same = all(current[key] == status[key] for key in ('project_id', 'revision', 'files_hash'))
    ready = current['readiness'] == 'ready' and same
    drafts = sorted(set(receipt.get('drafts', [])))
    metadata = workflow.project_manifest(root)
    connection = workflow.json_file(state / 'connection.json')
    local_owner = (connection.get('transport') == 'local' and
                   connection.get('database') == str(state / 'coordinator.sqlite3'))
    data = {'route': route, 'readiness': 'ready' if ready else 'partial',
            'project_id': current['project_id'], 'state_dir': str(state),
            'actor': getattr(selected, 'actor', None),
            'actor_source': 'saved_owner_identity' if hasattr(selected, 'actor') else 'issued_membership_not_exposed_by_status',
            'receipt': current, 'authority_revision': status['revision'],
            'authority_files_hash': status['files_hash'], 'current_authority_match': same,
            'coordinator_membership': 'verified', 'repairs': repairs, 'preserved_drafts': drafts,
            'workspace_scope': 'local' if local_owner else 'joined',
            'provider_delivery': 'not_applicable' if local_owner and metadata['provider'] == 'local' else 'unverified',
            'host_and_sharing': 'not_applicable' if local_owner and connection.get('mode') == 'local' else 'unverified',
            'next': 'Claim bounded work, draft changes and submit for integration-owner acceptance.' if ready else
                    'Inspect preserved drafts and local differences; the receipt is not current or fully materialized.',
            'recovery_note': 'Accepted bytes are materialized; edited originals are preserved in private drafts and backups.' if drafts else None}
    if not ready:
        raise ProductError(4, 'setup_incomplete',
                           'Setup preserved available work but the local receipt is not current or fully materialized. Inspect preserved drafts and local differences before continuing.', data=data)
    return data
