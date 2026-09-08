"""Reviewed note renames through ordinary proposals and accepted materialization.

Planning and drafting never edit project files. Authority remains the authenticated
coordinator; apply uses the existing client journal, not a second transaction log.
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from . import knowledge
from .client import Client, _hash, _snapshot, _draft_coordination, _io_errors, _absolute
from .engine import PROTECTED, validate_path, validate_files, files_hash
from .errors import ProductError

COMMANDS = ('graph-rename-plan', 'graph-rename-draft', 'graph-rename-apply')
BOUNDARY = 'Only selected-folder links are checked; outer-vault backlinks are unknown and are not read or updated.'


def fail(code, message):
    raise ProductError(4, code, message)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _guard_tree(root):
    knowledge._absolute(root)
    pending = [root]
    count = 0
    while pending:
        folder = pending.pop()
        if knowledge._link_or_reparse(folder):
            fail('rename_unsafe', 'Selected paths cannot contain links or junctions.')
        with os.scandir(folder) as entries:
            for entry in entries:
                count += 1
                if count > knowledge.MAX_FILES:
                    fail('rename_limit', 'Selected inventory exceeds the rename limit.')
                if entry.name.casefold() in PROTECTED:
                    continue
                path = folder / entry.name
                if knowledge._link_or_reparse(path):
                    fail('rename_unsafe', 'Selected paths cannot contain links or junctions.')
                # Client scans non-reserved files. Refuse its broader scope rather
                # than reading a graph-excluded private tree during apply.
                if knowledge._private(entry.name) and entry.name != '.DS_Store':
                    fail('rename_unsafe', 'A private path outside the client reserved set prevents a bounded rename.')
                if entry.is_dir(follow_symlinks=False):
                    if len(path.relative_to(root).parts) >= knowledge.MAX_DEPTH:
                        fail('rename_limit', 'Selected inventory exceeds the rename depth limit.')
                    pending.append(path)
                elif not entry.is_file(follow_symlinks=False):
                    fail('rename_unsafe', 'Selected paths must be regular files or directories.')


class RenameClient(Client):
    """Keep reparse checks at the existing client's read/write boundaries too."""
    def _load(self, name, optional=False):
        _private_guard(self.state / name)
        return super()._load(name, optional)

    def _save(self, name, value):
        _private_guard(self.state / name)
        return super()._save(name, value)

    def _backup(self, text):
        _private_guard(self.state / 'backups')
        if text is not None:
            _private_guard(self.state / 'backups' / digest(text))
        return super()._backup(text)

    def _target(self, name):
        path = super()._target(name)
        for part in (path, *path.parents):
            if knowledge._link_or_reparse(part):
                fail('rename_unsafe', 'Rename paths cannot traverse a link or junction.')
            if part == self.root:
                break
        return path

    def _scan(self, required=None):
        _guard_tree(self.root)
        return super()._scan(required)


def _client(client):
    knowledge._absolute(client.root)
    _private_guard(client.state)
    return RenameClient(client.root, client.state, client.request)


def _private_guard(path):
    path = _absolute(path)
    for part in (path, *path.parents):
        if knowledge._link_or_reparse(part):
            fail('rename_unsafe', 'Private recovery state cannot traverse links or junctions.')


def _name(name):
    validate_path(name)
    if knowledge._private(name) or PurePosixPath(name).suffix.casefold() not in knowledge.NOTE_EXTENSIONS or any(c in name for c in '%#|[]\'"`'):
        fail('rename_path', 'Rename supports portable, non-private Markdown note paths only.')


def _span(line, token):
    """Return the exact raw destination span, leaving wrapper/alias/title intact."""
    raw, syntax, embed, column, _ = token
    start = column - 1 + int(embed)
    if syntax == 'wikilink':
        end = line.find(']]', start + 2)
        end = min(end, line.find('|', start + 2, end)) if '|' in line[start + 2:end] else end
        a, b = start + 2, end
        while a < b and line[a].isspace():
            a += 1
        while b > a and line[b - 1].isspace():
            b -= 1
        return a, b
    if syntax != 'markdown':
        fail('rename_unsupported', 'Affected reference-style or autolink syntax requires an explicit manual proposal.')
    end = knowledge._balanced(line, start, '[', ']')
    closing = knowledge._balanced(line, end + 1, '(', ')')
    a, b = end + 2, closing
    while a < b and line[a].isspace():
        a += 1
    if line[a:a + 1] == '<':
        return a + 1, line.find('>', a + 1, b)
    value = line[a:b]
    value = value.rstrip()
    value = re.sub(r'\s+(?:"[^"\n]*"|\x27[^\x27\n]*\x27)$', '', value)
    # Escaped destinations are parsed but cannot be losslessly matched to a
    # decoded YAML scalar. Refuse these affected forms explicitly.
    if '\\' in value:
        fail('rename_unsupported', 'Affected escaped destinations require a manual proposal.')
    return a, a + len(value)


def _build(base, source, destination):
    _name(source)
    _name(destination)
    files = base['files']
    if source not in files:
        fail('rename_source', 'Source must be an accepted Markdown note.')
    if knowledge._fold(source) == knowledge._fold(destination):
        fail('rename_collision', 'Same-path and case-only renames are not portable.')
    for name in files:
        a, b = knowledge._fold(name), knowledge._fold(destination)
        if a == b or a.startswith(b + '/') or b.startswith(a + '/'):
            fail('rename_collision', 'Destination collides with an accepted file or directory prefix.')
        if knowledge._private(name):
            fail('rename_unsupported', 'Accepted private paths prevent complete selected-note analysis.')
    graph = knowledge.analyze(files=files)
    # The read-only analyzer intentionally omits unsupported rendering syntax.
    # Obvious HTML destinations and unparsed frontmatter links cannot be certified
    # by a rename, so require an explicit manual proposal for those notes.
    metadata_lines = {(e['source'], e['line']) for e in graph['edges'] if e['metadata_field'] is not None}
    for name, text in files.items():
        if PurePosixPath(name).suffix.casefold() not in knowledge.NOTE_EXTENSIONS:
            continue
        lines = text.splitlines()
        _, start = knowledge._frontmatter(lines, name, lambda *args: None)
        for number, line in enumerate(lines[:start], 1):
            if knowledge._links(line, {}) and (name, number) not in metadata_lines:
                fail('rename_unsupported', 'Unparsed frontmatter links require a manual proposal: ' + name)
        for _, line in knowledge._masked_lines(lines, start, name, lambda *args: None):
            if re.search(r'<[^>]*\b(?:href|src)\s*=', knowledge._mask_inline(line), re.IGNORECASE):
                fail('rename_unsupported', 'HTML destinations require a manual proposal: ' + name)
    # Diagnostics signal a potentially incomplete graph. External links and
    # excluded/outside links are deliberately retained without following them.
    allowed = {'link_external', 'link_outside_scope', 'link_excluded',
               'anchor_missing', 'anchor_unsupported', 'anchor_unsupported_attachment_anchor'}
    for item in graph['diagnostics']:
        if item['code'] not in allowed:
            fail('rename_unsupported', 'Graph requires review before rename: ' + item['code'] + ' at ' + item.get('path', 'selected root'))
    updates = {}
    modified_edges = []
    for edge in graph['edges']:
        moving = edge['source'] == source and PurePosixPath(source).parent != PurePosixPath(destination).parent
        if edge['target'] != source and not moving:
            continue
        if edge['status'] == 'external':
            continue
        if edge['status'] != 'resolved':
            fail('rename_unsupported', 'Moving a note with unresolved or outside-scope links requires a manual proposal.')
        if edge['syntax'] not in {'wikilink', 'markdown'}:
            fail('rename_unsupported', 'Affected reference-style links require a manual proposal.')
        text = files[edge['source']]
        lines = text.splitlines(keepends=True)
        line = lines[edge['line'] - 1]
        tokens = [t for t in knowledge._links(line, {}) if t[1] == edge['syntax'] and t[2] == edge['embed']]
        if edge['metadata_field'] is None:
            tokens = [t for t in tokens if t[3] == edge['column']]
        else:
            # Metadata columns belong to a decoded scalar. Match one raw token
            # only; complex/escaped/multiple-value cases fail closed.
            tokens = [t for t in tokens if t[0] is not None]
        if len(tokens) != 1:
            fail('rename_unsupported', 'Affected metadata or link span is not uniquely rewritable.')
        token = tokens[0]
        a, b = _span(line, token)
        original = line[a:b]
        if original != token[0]:
            fail('rename_unsupported', 'Affected destination does not have an exact raw representation.')
        oldpath, sep, fragment = original.partition('#')
        newsource = destination if edge['source'] == source else edge['source']
        target = destination if edge['target'] == source else edge['target']
        if not oldpath and edge['source'] == source:
            continue  # Same-note anchors remain same-note anchors after move.
        if edge['syntax'] == 'wikilink':
            replacement = target
        else:
            replacement = quote(posixpath.relpath(target, posixpath.dirname(newsource) or '.'), safe='/.-_~')
        if sep:
            replacement += '#' + fragment
        if replacement == original:
            continue
        updates.setdefault((edge['source'], edge['line']), {})[(a, b)] = replacement
        modified_edges.append({'source': edge['source'], 'line': edge['line'], 'target': edge['target'],
                               'syntax': edge['syntax'], 'metadata_field': edge['metadata_field']})
    result = dict(files)
    for (path, number), spans in sorted(updates.items()):
        lines = result[path].splitlines(keepends=True)
        line = lines[number - 1]
        prior = len(line)
        for (a, b), replacement in sorted(spans.items(), reverse=True):
            if not 0 <= a < b <= prior:
                fail('rename_unsupported', 'Affected destination spans overlap.')
            line = line[:a] + replacement + line[b:]
            prior = a
        lines[number - 1] = line
        result[path] = ''.join(lines)
    result[destination] = result.pop(source)
    validate_files(result)
    after = knowledge.analyze(files=result)
    # Every parsed edge must retain its resolved identity, fragment and meaning.
    if len(after['edges']) != len(graph['edges']):
        fail('rename_unsupported', 'Rename would change parsed link coverage.')
    def signatures(edges, transformed):
        values = []
        for e in edges:
            src = destination if transformed and e['source'] == source else e['source']
            target = destination if transformed and e['target'] == source else e['target']
            values.append((src, e['line'], e['syntax'], e['embed'], e['relation'], e['metadata_field'],
                           target, e['status'], e['anchor'], e['anchor_status']))
        return sorted(values, key=repr)
    if signatures(graph['edges'], True) != signatures(after['edges'], False):
        fail('rename_unsupported', 'Rename would change another link resolution or anchor.')
    changes = Client._changes(files, result)
    originals = {name: files.get(name) for name in changes}
    return {'schema_version': 1, 'project_id': base['project_id'], 'base_revision': base['revision'],
            'base_files_hash': base['files_hash'], 'source': source, 'destination': destination,
            'originals': originals, 'source_hashes': {name: digest(value) if value is not None else None for name, value in originals.items()},
            'changes': changes, 'result_files_hash': files_hash(result), 'affected_links': modified_edges,
            'boundary': BOUNDARY, 'filesystem_atomicity': False, 'acceptance_required': True}


def _clean(client, base, destination):
    _guard_tree(client.root)
    graph = knowledge._Graph()
    graph.collect(client.root, None)
    expected = {name: text for name, text in base['files'].items() if PurePosixPath(name).suffix.casefold() in knowledge.NOTE_EXTENSIONS}
    if graph.notes != expected:
        fail('rename_stale', 'Selected Markdown files differ from the accepted baseline; preserve/propose edits and refresh before planning.')
    # Include untracked attachments and empty directories in collision checking.
    target = client._target(destination)
    if target.exists():
        fail('rename_collision', 'Destination already exists in the selected folder.')
    for name in graph.inventory:
        if knowledge._fold(name) == knowledge._fold(destination):
            fail('rename_collision', 'Destination has a portable local path collision.')
    # A differently cased existing directory also collides on portable systems.
    parts = PurePosixPath(destination).parts
    parent = client.root
    for part in parts:
        if parent.exists() and not parent.is_dir():
            fail('rename_collision', 'Destination parent is an existing file.')
        if not parent.is_dir():
            break
        with os.scandir(parent) as entries:
            for entry in entries:
                if knowledge._fold(entry.name) == knowledge._fold(part) and entry.name != part:
                    fail('rename_collision', 'Destination casing differs from an existing path.')
        parent = parent / part


def _load_plan(client, plan_id):
    if not isinstance(plan_id, str) or not re.fullmatch(r'rename-[0-9a-f]{64}', plan_id):
        fail('rename_plan', 'A saved rename plan identifier is required.')
    value = client._load('rename-plans/' + plan_id + '.json')
    if not isinstance(value, dict) or plan_id != 'rename-' + _hash(value):
        fail('rename_plan', 'Saved rename plan failed its exact content hash.')
    return value


@_io_errors
def plan(client, source, destination):
    client = _client(client)
    with client._locked():
        if (client.state / 'journal.json').exists():
            fail('recovery_required', 'Recover existing materialization before planning a rename.')
        base = client._base()
        value = _build(base, source, destination)
        _clean(client, base, destination)
        identity = 'rename-' + _hash(value)
        client._immutable('rename-plans/' + identity + '.json', value)
        return dict(value, plan_id=identity)


@_io_errors
def draft(client, plan_id, proposal_id, assignment_id, evidence, *, coordination=None):
    client = _client(client)
    for value in (proposal_id, assignment_id):
        if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
            fail('invalid_identity', 'Safe proposal and assignment identifiers are required.')
    if not isinstance(evidence, str) or not evidence.strip():
        fail('missing_evidence', 'Explicit rename review evidence is required.')
    with client._locked():
        if (client.state / 'journal.json').exists():
            fail('recovery_required', 'Recover existing materialization before drafting a rename.')
        saved = _load_plan(client, plan_id)
        base = client._base()
        if saved != _build(base, saved['source'], saved['destination']):
            fail('rename_stale', 'Saved rename plan no longer matches the accepted baseline.')
        _clean(client, base, saved['destination'])
        authority = client.request('status', {'limit': 1})
        if any(authority.get(key) != base[key] for key in ('project_id', 'revision', 'files_hash')):
            fail('rename_stale', 'Coordinator advanced since the reviewed plan; refresh and plan again.')
        proposal = {'proposal_id': proposal_id, 'assignment_id': assignment_id, 'base_revision': base['revision'],
                    'changes': saved['changes'], 'claims': [], 'evidence': evidence}
        if coordination is not None:
            proposal['coordination'] = _draft_coordination(coordination)
        client._immutable('drafts/' + proposal_id + '.json', proposal)
        return dict(proposal=proposal, plan_id=plan_id, project_files_changed=False, boundary=BOUNDARY)


@_io_errors
def apply(client, plan_id):
    client = _client(client)
    # This preflight never resumes a journal. The subsequent authenticated client
    # operation revalidates the current base and pending target under its lock.
    with client._locked():
        saved = _load_plan(client, plan_id)
        base = client._base()
        if base['project_id'] != saved['project_id']:
            fail('project_mismatch', 'Rename plan belongs to another project.')
        _guard_tree(client.root)
        target = _snapshot(client.request('snapshot', {}), base['project_id'])
        if target['revision'] <= saved['base_revision'] or target['files_hash'] != saved['result_files_hash']:
            fail('rename_not_accepted', 'Current accepted bytes do not exactly match this reviewed rename. Submit and accept first, or review a new plan.')
        for name, content in saved['changes'].items():
            if target['files'].get(name) != content:
                fail('rename_not_accepted', 'Accepted rename content disagrees with the saved plan.')
    result = client.apply_downloaded(target)
    return dict(result, plan_id=plan_id, byte_source='authenticated_coordinator_snapshot', boundary=BOUNDARY,
                filesystem_atomicity=False, recovery='existing_private_client_journal_and_backups')


def add_commands(commands):
    for name in COMMANDS:
        cmd = commands.add_parser(name, help='Review, draft or materialize an accepted selected-folder note rename')
        cmd.add_argument('project')
        cmd.add_argument('--state-dir', required=True)
        cmd.add_argument('--session-token-file')
        if name == 'graph-rename-plan':
            cmd.add_argument('--source', required=True)
            cmd.add_argument('--destination', required=True)
        else:
            cmd.add_argument('--plan-id', required=True)
        if name == 'graph-rename-draft':
            for field in ('proposal-id', 'assignment-id', 'evidence'):
                cmd.add_argument('--' + field, required=True)
            cmd.add_argument('--coordination-file')


def dispatch(bundle, args):
    from .workflow import private_path, project_manifest, json_file, connect
    for field in ('coordination_file', 'session_token_file'):
        value = getattr(args, field, None)
        if value is not None and not value.strip():
            raise ProductError(2, 'usage_error', 'An explicit private input path must not be empty.')
    root = knowledge._absolute(Path(args.project).expanduser())
    _private_guard(Path(args.state_dir).expanduser().absolute())
    state = private_path(args.state_dir, root)
    _private_guard(state / 'client/client.json')
    _private_guard(state / 'connection.json')
    metadata = project_manifest(root)
    config = json_file(state / 'client/client.json')
    if config.get('project_id') != metadata['project_id'] or config.get('project_root') != str(root):
        fail('project_mismatch', 'Selected project and private client identity disagree.')
    if args.session_token_file is not None:
        _private_guard(Path(args.session_token_file).expanduser().absolute())
    else:
        _private_guard(state / 'member.token')
    credential = private_path(args.session_token_file, root) if args.session_token_file is not None else None
    client = Client(root, state / 'client', connect(state, credential))
    if args.command == 'graph-rename-plan':
        return plan(client, args.source, args.destination)
    if args.command == 'graph-rename-draft':
        if args.coordination_file is not None:
            _private_guard(Path(args.coordination_file).expanduser().absolute())
        context = _draft_coordination(json_file(private_path(args.coordination_file, root))) if args.coordination_file is not None else None
        return draft(client, args.plan_id, args.proposal_id, args.assignment_id, args.evidence, coordination=context)
    return apply(client, args.plan_id)
