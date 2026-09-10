"""Ordinary shared-folder CLI. No coordinator, session or approval operations."""
from __future__ import annotations

import getpass
import json
from pathlib import Path
import secrets
import time

from .errors import ProductError
from . import workflow

COMMANDS = ('sync', 'folder-status', 'history', 'resolve', 'delete', 'rename', 'migrate-folder', 'watch')
FOLDER_PROVIDERS = ('local', 'google-drive', 'icloud', 'onedrive', 'nextcloud', 'self-hosted')


def add_commands(commands):
    for name in COMMANDS:
        command = commands.add_parser(name, help={
            'sync': 'Capture direct edits and reconcile delivered immutable history',
            'folder-status': 'Inspect folder history and conflicts without changing notes',
            'history': 'Read preserved direct-edit history',
            'resolve': 'Record an evidence-backed conflict resolution by this editing member',
            'delete': 'Record an explicit recoverable deletion; missing files alone are not deletes',
            'rename': 'Record an explicit recoverable rename',
            'migrate-folder': 'Plan or apply a backed-up migration from historical coordinator mode',
            'watch': 'Optional local history capture loop; no background AI or approval service',
        }[name])
        command.add_argument('project')
        command.add_argument('--state-dir', help='Existing private per-device state; otherwise discovered locally')
        if name in {'history', 'resolve', 'delete'}:
            command.add_argument('--path', required=name != 'history')
        if name == 'resolve':
            command.add_argument('--text-file', required=True, help='Reviewed UTF-8 resolution file; may be the locally edited note')
        if name in {'resolve', 'delete', 'rename'}:
            command.add_argument('--evidence', required=True)
        if name == 'rename':
            command.add_argument('--source', required=True)
            command.add_argument('--destination', required=True)
        if name == 'migrate-folder':
            command.add_argument('--backup-dir', required=True, help='Fresh private recovery directory outside shared storage')
            command.add_argument('--apply', action='store_true')
            command.add_argument('--replan', action='store_true', help='Preserve a superseded pre-cutover intent and use a fresh backup after newer work')
        if name == 'watch':
            command.add_argument('--interval', type=float, default=5)
            command.add_argument('--cycles', type=int, default=12, help='Bounded sync cycles; restart explicitly if more are needed')


def metadata(root):
    path = root / '.shared-memory.json'
    return workflow.json_file(path) if path.exists() else None


def is_folder(root):
    item = metadata(root)
    return isinstance(item, dict) and item.get('workflow') == 'folder'


def state_path(args, root):
    from .onboarding import default_state
    selected = workflow.private_path(args.state_dir, root) if getattr(args, 'state_dir', None) else default_state(root)
    if args.command == 'migrate-folder':
        return selected
    if not getattr(args, 'state_dir', None) or (selected / 'connection.json').exists():
        return workflow.private_path(selected / 'folder', root)
    return selected


def setup(args):
    from .folder import Folder
    if not args.project.strip():
        raise ProductError(2, 'usage_error', 'Select a nonempty project path.')
    if getattr(args, 'content_mode', None) not in (None, 'markdown'):
        raise ProductError(3, 'content_mode', 'Direct folder workflow uses Markdown discovery; legacy content mode belongs to historical coordinator setup.')
    root = workflow.selected_root(args.project)
    state = state_path(args, root)
    item = metadata(root)
    if item and args.expected_project_id and args.expected_project_id != item.get('project_id'):
        raise ProductError(3, 'identity_mismatch', 'The selected folder differs from the explicitly expected project identity.')
    if item and item.get('workflow') != 'folder':
        raise ProductError(4, 'migration_required',
            'Existing coordinator history is preserved. Use migrate-folder with a private backup directory to convert it; do not initialize a replacement.',
            data={'workflow': 'historical_coordinator', 'project_id': item.get('project_id'), 'next': 'migrate-folder'})
    if any(getattr(args, k, None) for k in ('endpoint', 'database', 'token_file', 'ca_file')):
        raise ProductError(3, 'folder_access', 'Folder workflow uses existing provider/OS access, not coordinator credentials. Use --workflow coordinator only for historical projects.')
    if ((state / 'folder-migration.json').exists() or (state.parent / 'folder-migration.json').exists()) and not item:
        raise ProductError(4, 'migration_incomplete', 'Resume the recorded migrate-folder operation; existing history must not be reset.')
    if (state / 'folder.json').exists():
        saved = workflow.json_file(state / 'folder.json')
        if item is None and (state / 'initialization.json').exists():
            intent = workflow.json_file(state / 'initialization.json')
            Folder.initialize(root, state, **saved['author'], provider=intent['provider'], project_id=intent['project_id'])
            item = metadata(root)
        folder = Folder(root, state)
        if args.provider and item.get('provider') != args.provider:
            raise ProductError(3, 'provider_mismatch', 'Keep one provider per physical project; existing binding is unchanged.')
        # Identity and read-only grants are saved, never silently widened by setup.
        saved = workflow.json_file(state / 'folder.json')
        if getattr(args, 'read_only', False) and not saved.get('readonly'):
            raise ProductError(3, 'readonly_mismatch', 'This binding is writable. Use a separate explicitly read-only binding; setup does not silently ignore or change access intent.')
        for field in ('actor', 'person', 'agent'):
            if getattr(args, field, None) and saved.get('author', {}).get(field) != getattr(args, field):
                raise ProductError(3, 'identity_mismatch', 'Keep this device identity or use a separate private state directory.')
        if (state / 'initialization.json').exists():
            folder = Folder.initialize(root, state, **saved['author'], provider=item['provider'], project_id=item['project_id'])
        elif not (state / 'baseline.json').exists():
            folder = Folder.attach(root, state, **saved['author'], expected_project_id=item['project_id'], readonly=saved['readonly'])
        elif not saved['readonly']:
            folder.sync()
        route = 'resume_folder'
    else:
        try:
            person = getpass.getuser()
        except (KeyError, OSError):
            person = 'Local user'
        pending = workflow.json_file(state / 'initialization.json') if (state / 'initialization.json').exists() else None
        if pending:
            for field in ('actor', 'person', 'agent'):
                if getattr(args, field, None) and pending['author'][field] != getattr(args, field):
                    raise ProductError(3, 'identity_mismatch', 'Resume the original initialization identity.')
            if args.provider and args.provider != pending['provider']:
                raise ProductError(3, 'provider_mismatch', 'Resume the original initialization provider.')
        identity = {'actor': args.actor or 'device-' + secrets.token_hex(8),
                    'person': args.person or person, 'agent': args.agent or 'Local agent'}
        if pending:
            identity = pending['author']
        readonly = getattr(args, 'read_only', False)
        if item and (state.parent / 'connection.json').exists():
            from .folder_migration import legacy_identity
            _, legacy, member, _, _, _, _ = legacy_identity(state.parent)
            if legacy['project_id'] != item['project_id']:
                raise ProductError(3, 'identity_mismatch', 'Prior private membership belongs to another project.')
            readonly = readonly or member['role'] == 'reader'
            if not args.actor:
                identity = {'actor': member['actor'], 'person': member['human'], 'agent': member['agent']}
        if item:
            if args.provider and item.get('provider') != args.provider:
                raise ProductError(3, 'provider_mismatch', 'Joining retains the selected project provider.')
            folder = Folder.attach(root, state, expected_project_id=args.expected_project_id or item['project_id'],
                                   readonly=readonly, **identity)
            route = 'join_folder'
        else:
            if args.expected_project_id:
                raise ProductError(4, 'folder_not_delivered', 'Expected project metadata/history has not arrived. Do not create a new project identity.')
            if any((base / name).exists() for base in (state, state.parent) for name in ('connection.json', 'setup-intent.json')):
                raise ProductError(4, 'existing_history', 'Existing private coordinator history needs reviewed migration, not fresh setup.')
            folder = Folder.initialize(root, state, provider=args.provider or (pending['provider'] if pending else 'local'), readonly=readonly,
                                       project_id=pending['project_id'] if pending else None, **identity)
            route = 'new_folder'
    result = folder.status()
    return {'workflow': 'folder', 'route': route, 'project_id': result['project_id'],
            'state_dir': str(state), 'status': result, 'readiness': result.get('readiness', 'inspect_status'),
            'next': 'Edit local notes directly, then sync to preserve/reconcile history. Reviews are optional.',
            'provider_delivery': 'unverified', 'coordinator_required': False, 'approval_queue': False}


def dispatch(bundle, args):
    from .folder import Folder
    root = workflow.selected_root(args.project)
    state = state_path(args, root)
    if args.command == 'migrate-folder':
        from .folder_migration import migrate
        return migrate(root, state, args.backup_dir, apply=args.apply, replan=args.replan)
    folder = Folder(root, state)
    command = args.command
    if command in {'folder-status', 'status', 'receipt', 'team-status', 'provider-check'}:
        return folder.status()
    if command == 'sync':
        return folder.sync()
    if command == 'history':
        return folder.history(args.path)
    if command == 'resolve':
        path = Path(args.text_file).expanduser().absolute()
        from .path_safety import unsafe_ancestor
        if unsafe_ancestor(path) is not None or not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            raise ProductError(3, 'resolution_file', 'Choose a regular bounded UTF-8 resolution file.')
        return folder.resolve(args.path, path.read_bytes().decode('utf-8'), args.evidence)
    if command == 'delete':
        return folder.delete(args.path, args.evidence)
    if command == 'rename':
        return folder.rename(args.source, args.destination, args.evidence)
    if command == 'watch':
        if not 0.1 <= args.interval <= 3600 or not 1 <= args.cycles <= 100000:
            raise ProductError(3, 'watch_bounds', 'Use interval 0.1–3600 seconds and 1–100000 cycles.')
        result = None
        for index in range(args.cycles):
            result = folder.sync()
            if index + 1 < args.cycles:
                time.sleep(args.interval)
        return {'cycles': args.cycles, 'last': result, 'background_agent': False}
    raise ProductError(2, 'usage_error', 'Unknown folder command.')
