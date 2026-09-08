"""Read-only selected-folder and accepted-snapshot knowledge graph entry point."""
from __future__ import annotations

from pathlib import Path

from .errors import ProductError
from .workflow import connect, json_file, private_path, project_manifest, selected_root

COMMANDS = ('graph',)


def add_commands(commands):
    command = commands.add_parser('graph', help='Inspect portable note links/backlinks without changing notes or policy')
    command.add_argument('project')
    command.add_argument('--accepted', action='store_true', help='Analyze the authenticated coordinator snapshot instead of local notes')
    command.add_argument('--state-dir', help='Private attached client state, required only with --accepted')


def dispatch(bundle, args):
    from .knowledge import analyze, _absolute
    try:
        root = selected_root(args.project)
    except ProductError as exc:
        if exc.code == 'project_path_unsafe':
            # Keep the graph command's established error contract when the shared
            # root guard rejects before graph-specific validation can run.
            raise ProductError(3, 'knowledge_root',
                               'The selected graph root cannot use symlinks or reparse points.') from exc
        raise
    # Retain graph-specific validation before notes or private bindings are read.
    _absolute(Path(args.project).expanduser())
    if not args.accepted:
        if args.state_dir:
            raise ProductError(2, 'usage_error', '--state-dir is used only with --accepted; local graph reads the selected folder.')
        graph = analyze(root=root)
        graph['source'] = 'local_selected_folder'
        graph['acceptance_authority'] = False
        return graph
    if not args.state_dir:
        raise ProductError(2, 'usage_error', '--accepted requires the attached private --state-dir.')
    state = private_path(args.state_dir, root)
    metadata = project_manifest(root)
    config = json_file(state / 'client/client.json')
    if config.get('project_id') != metadata['project_id'] or config.get('project_root') != str(root):
        raise ProductError(3, 'project_mismatch', 'Private client state belongs to another selected project.')
    snapshot = connect(state)('snapshot', {})
    from .client import _snapshot
    snapshot = _snapshot(snapshot, metadata['project_id'])
    graph = analyze(files=snapshot['files'])
    graph['source'] = 'accepted_coordinator_snapshot'
    graph['accepted_identity'] = {key: snapshot[key] for key in ('project_id', 'revision', 'files_hash')}
    graph['acceptance_authority'] = False
    return graph
