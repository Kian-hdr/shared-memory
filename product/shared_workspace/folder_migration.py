"""One-time, recoverable conversion; old authority history stays private and intact."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3

from .errors import ProductError
from .engine import Coordinator, validate_path, files_hash
from .transport import read_token
from . import workflow
from .path_safety import unsafe_ancestor


def atomic_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    workflow.write_private(temporary, json.dumps(value, sort_keys=True, ensure_ascii=False) + '\n', exclusive=False)
    os.replace(temporary, path)


def preserve_bytes(path, data):
    """Recovery copies must not pass through Windows text newline translation."""
    workflow.private_path(path)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0)
    with os.fdopen(os.open(path, flags, 0o600), 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def verify_recovery(journal, backup):
    """A retry must prove its recovery inputs still match the completed backup."""
    from .coordinator_migration import verify_checkpoint
    database = workflow.private_path(backup / 'coordinator.sqlite3')
    if not database.is_file():
        raise ProductError(4, 'migration_backup_invalid', 'Preserved authority backup is missing; do not complete or reset this migration.')
    with database.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != journal['history_backup_sha256']:
        raise ProductError(4, 'migration_backup_invalid', 'Preserved authority backup changed; retain the original authority and inspect recovery evidence.')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        schema = db.execute('PRAGMA user_version').fetchone()[0]
        verified = verify_checkpoint(db, Coordinator(database), expected_schema=schema,
                                     expected_project_id=journal['project_id'])
        if verified['checkpoint'] != journal['history_checkpoint']:
            raise ProductError(4, 'migration_backup_invalid', 'Preserved history checkpoint differs from migration intent.')
        latest = db.execute('SELECT revision,files_hash FROM snapshots ORDER BY revision DESC LIMIT 1').fetchone()
        if tuple(latest) != (journal['from_revision'], journal['from_files_hash']):
            raise ProductError(4, 'migration_backup_invalid', 'Preserved accepted state differs from migration intent.')
        identities = [dict(r) for r in db.execute('SELECT actor,human,agent,role,active FROM members ORDER BY actor')]
    notes = workflow.json_file(backup / 'present-notes.json')
    if files_hash(notes) != journal['present_hash']:
        raise ProductError(4, 'migration_backup_invalid', 'Preserved direct-note checkpoint changed; do not substitute it for newer work.')
    original = workflow.json_file(backup / 'manifest.json')
    if (original.get('project_id') != journal['project_id'] or original.get('provider') != journal['provider']
            or hashlib.sha256((backup / 'manifest.json').read_bytes()).hexdigest() != journal['manifest_hash']
            or workflow.json_file(backup / 'legacy-identities.json') != identities):
        raise ProductError(4, 'migration_backup_invalid', 'Original project or membership recovery inputs changed.')
    return notes


def legacy_identity(state):
    connection = workflow.json_file(state / 'connection.json')
    if connection.get('transport') != 'local':
        raise ProductError(4, 'local_history_required',
            'Migrate using the operator-held private authority backup. Remote client state alone cannot preserve complete coordinator history.')
    database = workflow.private_path(connection['database'])
    engine = Coordinator(database)
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        info = engine._schema(db)
        member = engine._auth(db, read_token(state / 'member.token'))
        latest = db.execute('SELECT files_json,files_hash FROM snapshots WHERE revision=?', (info['revision'],)).fetchone()
        # No token hashes or session credentials leave private authority storage.
        people = [dict(r) for r in db.execute('SELECT actor,human,agent,role,active FROM members ORDER BY actor')]
        counts = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                  for name in ('snapshots', 'events', 'assignments', 'proposals')}
    return database, info, {k: member[k] for k in ('actor', 'human', 'agent', 'role', 'active')}, json.loads(latest['files_json']), latest['files_hash'], people, counts


def current_files(root, accepted):
    result = workflow.initial_files(root, None, mode='markdown')
    # Initial discovery is reused only for paths; preserve exact current UTF-8 newline bytes.
    result = {path: (root / path).read_bytes().decode('utf-8') for path in result}
    missing = []
    for path in accepted:
        validate_path(path)
        selected = root / path
        if unsafe_ancestor(selected) is not None:
            raise ProductError(3, 'migration_path', 'A previously accepted path now crosses a link; preserve and reconcile it before migration.')
        if selected.is_file():
            if selected.stat().st_size > 10 * 1024 * 1024:
                raise ProductError(3, 'migration_size', 'Previously accepted file exceeds the bounded text size.')
            result[path] = selected.read_bytes().decode('utf-8')
        else:
            # Missing files may be delayed provider delivery; never infer a deletion.
            missing.append(path)
    return result, missing


def migrate(root, state, backup_dir, *, apply=False, replan=False):
    from .folder import Folder
    from .maintenance import backup_coordinator
    root, state = workflow.selected_root(root), workflow.private_path(state, root)
    backup = workflow.private_path(backup_dir, root)
    if backup == state or backup.is_relative_to(state) or state.is_relative_to(backup):
        raise ProductError(3, 'backup_location', 'Use a separate private backup tree, not the active private state.')
    journal_path = state / 'folder-migration.json'
    journal = workflow.json_file(journal_path) if journal_path.exists() else None
    manifest_path = root / workflow.MANIFEST
    metadata = workflow.json_file(manifest_path) if manifest_path.exists() else None
    if replan:
        if (not journal or journal.get('status') != 'backed_up' or not metadata
                or metadata.get('format_version') not in {1, 2} or metadata.get('protocol') != 1
                or metadata.get('provider') != journal.get('provider')
                or metadata.get('workflow') == 'folder' or (state / 'folder').exists()
                or journal.get('root') != str(root) or str(backup) == journal.get('backup_dir') or backup.exists()):
            raise ProductError(4, 'migration_replan', 'Replanning requires an unchanged pre-cutover format, no new folder state, and a fresh different private backup directory.')
        _, current, authorized, _, _, _, _ = legacy_identity(state)
        if authorized['role'] == 'reader' or current['project_id'] != journal['project_id'] or metadata['project_id'] != journal['project_id']:
            raise ProductError(4, 'migration_replan', 'Replanning cannot widen read-only access or switch project identity.')
        if apply:
            old = journal_path.read_bytes()
            history = state / 'folder-migration-intents'
            history.mkdir(mode=0o700, exist_ok=True)
            destination = history / (hashlib.sha256(old).hexdigest() + '.json')
            if destination.exists():
                if destination.read_bytes() != old:
                    raise ProductError(4, 'migration_replan', 'Preserved migration intent differs; inspect private recovery history.')
            else:
                preserve_bytes(destination, old)
        # The original authority and prior backup are not edited or restored.
        # A read-only replan reports the fresh plan without changing its intent.
        journal = None
    if metadata and metadata.get('workflow') != 'folder':
        # Unknown formats cannot be treated as legacy solely because their UUID matches.
        metadata = workflow.project_manifest(root)
    if journal and (journal['root'] != str(root) or journal['backup_dir'] != str(backup)):
        raise ProductError(3, 'migration_binding', 'Resume the original migration with its original private backup directory.')
    if journal:
        verify_recovery(journal, backup)
    if metadata and metadata.get('workflow') == 'folder':
        if not journal:
            raise ProductError(4, 'already_folder', 'This project already uses direct folder editing; no coordinator migration is needed.')
        if apply and journal['status'] != 'complete':
            origin = {'project_id': journal['project_id'], 'revision': journal['from_revision'],
                      'files_hash': journal['from_files_hash'], 'backup_hash': journal['history_backup_sha256']}
            folder = Folder.initialize(root, state / 'folder', actor=journal['actor'], person=journal['person'],
                agent=journal['agent'], provider=journal['provider'], project_id=journal['project_id'],
                initial_files=workflow.json_file(backup / 'present-notes.json'), migration_origin=origin)
        else:
            folder = Folder(root, state / 'folder')
        if apply:
            journal['status'] = 'complete'
            atomic_json(journal_path, journal)
        return {'migrated': True, 'resumed': True, 'project_id': metadata['project_id'],
                'history_preserved': True, 'backup_dir': str(backup), 'state_dir': str(state / 'folder'), 'status': folder.status()}
    database, info, member, accepted, accepted_hash, people, counts = legacy_identity(state)
    if member['role'] == 'reader':
        raise ProductError(4, 'read_only', 'A read-only member cannot change project format or widen editing access.')
    if metadata and metadata.get('project_id') != info['project_id']:
        raise ProductError(3, 'migration_identity', 'Local folder and private history belong to different projects.')
    if not metadata and not journal:
        raise ProductError(3, 'migration_metadata', 'No original project metadata or saved migration intent was found.')
    files, missing = current_files(root, accepted)
    changed = sorted(p for p, text in files.items() if accepted.get(p) != text)
    plan = {'project_id': info['project_id'], 'from_revision': info['revision'], 'from_files_hash': accepted_hash,
            'present_notes': len(files), 'local_changes_preserved': changed, 'missing_accepted_files': missing,
            'historical_records': counts, 'members_preserved': len(people), 'workflow': 'folder',
            'coordinator_required_after_migration': False, 'backup_dir': str(backup),
            'read_only_access': 'Existing provider/OS restrictions remain; legacy reader bindings are retained privately.',
            'applied': False}
    plan['replanned'] = replan
    if not apply:
        return plan
    if missing:
        raise ProductError(4, 'migration_missing_files',
            'Previously accepted files are missing. Restore availability or deliberately reconcile their deletion before migration; history was not changed.', data=plan)
    if journal is None:
        if backup.exists():
            raise ProductError(3, 'backup_exists', 'Choose a fresh private backup directory.')
        backup.mkdir(parents=True, mode=0o700)
        archive = backup_coordinator(database, backup / 'coordinator.sqlite3', info['project_id'])
        # Match the independently verified backup revision to the inspected plan.
        with closing(sqlite3.connect((backup / 'coordinator.sqlite3').as_uri() + '?mode=ro', uri=True)) as db:
            row = db.execute('SELECT revision,files_hash FROM snapshots ORDER BY revision DESC LIMIT 1').fetchone()
            if row != (info['revision'], accepted_hash):
                raise ProductError(4, 'migration_changed', 'Authority changed during backup. Retain the backup and inspect the new state before retrying.')
        preserve_bytes(backup / 'manifest.json', manifest_path.read_bytes())
        workflow.write_private(backup / 'present-notes.json', json.dumps(files, ensure_ascii=False))
        workflow.write_private(backup / 'legacy-identities.json', json.dumps(people, ensure_ascii=False))
        workflow.write_private(backup / 'migration-plan.json', json.dumps(plan, ensure_ascii=False))
        journal = {'root': str(root), 'backup_dir': str(backup), 'status': 'backed_up',
                   'project_id': info['project_id'], 'provider': metadata['provider'],
                   'from_revision': info['revision'], 'from_files_hash': accepted_hash,
                   'history_backup_sha256': archive['backup_sha256'], 'present_hash': files_hash(files),
                   'history_checkpoint': archive['checkpoint'],
                   'manifest_hash': hashlib.sha256((backup / 'manifest.json').read_bytes()).hexdigest(),
                   'actor': member['actor'], 'person': member['human'], 'agent': member['agent']}
        atomic_json(journal_path, journal)
    if journal['from_revision'] != info['revision'] or journal['from_files_hash'] != accepted_hash:
        raise ProductError(4, 'migration_changed', 'Old authority advanced after the preserved migration checkpoint; retain both histories and replan.')
    preserved = verify_recovery(journal, backup)
    if files != preserved:
        raise ProductError(4, 'migration_local_changed', 'Local notes changed after the checkpoint; preserve newer work and replan instead of overwriting it.')
    origin = {'project_id': journal['project_id'], 'revision': journal['from_revision'],
              'files_hash': journal['from_files_hash'], 'backup_hash': journal['history_backup_sha256']}
    # Freeze old local writers only during format cutover. No permanent service or
    # approval role is carried forward. Existing readers/history remain intact.
    with closing(sqlite3.connect(database)) as guard:
        guard.execute('BEGIN IMMEDIATE')
        row = guard.execute('SELECT revision,files_hash FROM snapshots ORDER BY revision DESC LIMIT 1').fetchone()
        if row != (info['revision'], accepted_hash):
            raise ProductError(4, 'migration_changed', 'Authority advanced immediately before cutover; existing material was preserved.')
        if manifest_path.exists():
            if manifest_path.read_bytes() != (backup / 'manifest.json').read_bytes():
                raise ProductError(4, 'migration_changed', 'Project metadata changed after the backup.')
            os.replace(manifest_path, backup / 'manifest-original.json')
        journal['status'] = 'initializing_folder'
        atomic_json(journal_path, journal)
        folder = Folder.initialize(root, state / 'folder', actor=journal['actor'], person=journal['person'],
            agent=journal['agent'], provider=journal['provider'], project_id=journal['project_id'],
            initial_files=preserved, migration_origin=origin)
        guard.rollback()
    journal['status'] = 'complete'
    atomic_json(journal_path, journal)
    return dict(plan, applied=True, migrated=True, history_preserved=True, state_dir=str(state / 'folder'), status=folder.status())
