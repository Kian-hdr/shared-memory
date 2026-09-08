"""Explicit immutable delivery commands for already attached selected folders."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from .client import Client
from .delivery import Delivery, GoogleDriveBinding, LocalRcloneBackend, RcloneBackend
from .errors import ProductError
from .workflow import connect, json_file, private_path, project_manifest, selected_root

COMMANDS = ('delivery-publish', 'delivery-fetch')


def add_commands(commands):
    for name in COMMANDS:
        command = commands.add_parser(name, help='Explicit verified revision delivery; requires an attached project')
        command.add_argument('project')
        command.add_argument('--state-dir', required=True)
        command.add_argument('--rclone', required=True, help='Absolute path to the reviewed installed rclone executable')
        route = command.add_mutually_exclusive_group(required=True)
        route.add_argument('--binding-file', help='Private reviewed Google Drive binding JSON; never configures or signs in')
        route.add_argument('--fixture-root', help='Local rclone fixture only; never evidence of cloud delivery')


def _separate(path, other):
    if path == other or path.is_relative_to(other) or other.is_relative_to(path):
        raise ProductError(3, 'delivery_location', 'Delivery storage, private state and the selected project must be separate trees.')


def _backend(args, root, state, provider):
    executable = Path(args.rclone).expanduser()
    if not executable.is_absolute():
        raise ProductError(2, 'usage_error', 'Supply the absolute reviewed rclone executable path.')
    if args.fixture_root:
        fixture = private_path(args.fixture_root, root)
        _separate(fixture, state)
        return LocalRcloneBackend(executable, fixture)
    if provider != 'google-drive':
        raise ProductError(3, 'delivery_provider', 'This binding requires an existing project explicitly configured for google-drive.')
    path = private_path(args.binding_file, root)
    if not path.is_file() or path.stat().st_size > 16384:
        raise ProductError(3, 'delivery_binding', 'A small private reviewed binding file is required.')
    if os.name != 'nt' and (path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid()):
        raise ProductError(3, 'delivery_binding', 'The binding must be owned by this user and inaccessible to other users.')
    try:
        binding = json.loads(path.read_text(encoding='utf-8'))
        required = {'config', 'remote', 'root_folder_id', 'account_type', 'reviewed'}
        if not isinstance(binding, dict) or set(binding) - (required | {'team_drive_id'}) or required - set(binding):
            raise ValueError()
        if binding['reviewed'] is not True or not isinstance(binding['config'], str) or not Path(binding['config']).is_absolute():
            raise ValueError()
        config = private_path(binding['config'], root)
        binding['config'] = config
        return RcloneBackend(executable, GoogleDriveBinding(**binding))
    except (ValueError, TypeError, UnicodeError):
        raise ProductError(3, 'delivery_binding', 'Invalid private binding; inspect it locally without sharing credentials.') from None


def dispatch(bundle, args):
    root = selected_root(args.project)
    state = private_path(args.state_dir, root)
    metadata = project_manifest(root)
    config = json_file(state / 'client/client.json')
    if config.get('project_id') != metadata['project_id'] or config.get('project_root') != str(root):
        raise ProductError(3, 'project_mismatch', 'Private client state belongs to another project or local folder.')
    transport = connect(state)
    status = transport('status', {'limit': 1})
    if status.get('project_id') != metadata['project_id']:
        raise ProductError(3, 'project_mismatch', 'The authenticated coordinator belongs to another project.')
    from .content import manifest_mode
    client = Client(root, state / 'client', transport, content_mode=manifest_mode(metadata))
    previous = client.accepted_snapshot()
    backend = _backend(args, root, state, metadata['provider'])
    try:
        delivery = Delivery(backend)
        if args.command == 'delivery-publish':
            # Only accepted authority bytes are published; local edits are never
            # promoted merely because they exist in the selected shared folder.
            snapshot = transport('snapshot', {})
            if snapshot.get('project_id') != metadata['project_id']:
                raise ProductError(3, 'project_mismatch', 'The authenticated snapshot belongs to another project.')
            receipt = delivery.publish(snapshot)
            return {'delivery': receipt, 'readiness': 'partial', 'initial_join': 'coordinator_attach_required'}
        expected = {key: status[key] for key in ('project_id', 'revision', 'files_hash')}
        # Keep provider bytes outside synchronized storage. No coordinator snapshot
        # download occurs on this path, including when the provider is unavailable.
        with tempfile.TemporaryDirectory(prefix='delivery-', dir=state) as parent:
            staging = private_path(Path(parent) / 'received', root)
            downloaded = delivery.fetch(expected, staging, previous=previous)
            applied = client.apply_downloaded(downloaded.snapshot)
            return {'delivery': downloaded.receipt, 'local': applied,
                    'readiness': 'partial', 'initial_join': 'coordinator_attach_required'}
    finally:
        close = getattr(backend, 'close', None)
        if close:
            close()
