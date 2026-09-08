"""Local, recoverable materialization of authenticated coordinator snapshots.

Receipts attest only this directory's bytes. They do not attest provider delivery.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import functools
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import uuid

from .errors import ProductError
from .path_safety import absolute_path, unsafe_ancestor

# Use one portable-path and snapshot policy for authority and materialization.
from .engine import (MAX_FILE_BYTES, MAX_SNAPSHOT_BYTES as MAX_TOTAL_BYTES,
                     PROTECTED, validate_path, validate_files)

BINARY_ARTIFACT_SUFFIXES = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico',
    '.heic', '.heif', '.tif', '.tiff', '.bmp', '.mp4', '.mov', '.m4v', '.mp3', '.wav',
    '.flac', '.aac', '.ogg', '.mkv', '.zip', '.gz', '.tar', '.7z', '.rar', '.sqlite',
    '.db', '.pptx', '.docx', '.xlsx', '.xls', '.ppt', '.doc', '.exe', '.dll',
    '.dylib', '.so', '.woff', '.woff2', '.ttf', '.otf'}


def _error(code, message, exit_code=3):
    raise ProductError(exit_code, code, message)


def _draft_coordination(value):
    """Freeze context supplied for this work, without refreshing stale authority."""
    if (not isinstance(value, dict) or set(value) != {'session_id', 'generation', 'policy_revision', 'input_hash'}
            or not isinstance(value['session_id'], str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value['session_id'])
            or any(type(value[key]) is not int or value[key] < 1 for key in ('generation', 'policy_revision'))
            or not isinstance(value['input_hash'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', value['input_hash'])):
        _error('invalid_coordination', 'Draft requires the exact session, generation, policy revision and input hash for its assigned work.')
    return dict(value)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _hash(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _path(value):
    return validate_path(value)


def _files(files):
    return validate_files(files)


def _snapshot(value, expected=None):
    if not isinstance(value, dict):
        _error('invalid_snapshot', 'Expected snapshot object.')
    project_id = value.get('project_id')
    try:
        if str(uuid.UUID(project_id)) != project_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        _error('invalid_snapshot', 'Snapshot project ID must be a canonical UUID.')
    if expected is not None and project_id != expected:
        _error('project_mismatch', 'Coordinator project identity does not match.')
    rev = value.get('revision')
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        _error('invalid_snapshot', 'Invalid accepted revision.')
    files = _files(value.get('files'))
    if value.get('files_hash') != _hash(files):
        _error('snapshot_integrity', 'Snapshot content hash does not match.')
    return {'project_id': project_id, 'revision': rev, 'files': dict(files), 'files_hash': value['files_hash']}


def _absolute(path):
    return absolute_path(path)


def _no_symlinks(path):
    if unsafe_ancestor(path) is not None:
        _error('unsafe_path', 'Symlink or reparse-point paths are not supported: ' + str(path))
    return _absolute(path)


def _fsync_dir(path):
    try:
        fd = os.open(path, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        unsupported = {errno.EINVAL, errno.ENOTSUP, errno.EBADF}
        if os.name == 'nt':
            unsupported.update({errno.EACCES, errno.EPERM})
        if exc.errno not in unsupported:
            raise


def _atomic(path, data):
    _no_symlinks(path)
    fd, temporary = tempfile.mkstemp(prefix='.shared-memory-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _no_symlinks(path)
        os.replace(temporary, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _empty_directory(path, expected=None):
    """Verify the exact empty directory selected for a journaled file write."""
    _no_symlinks(path)
    info = path.lstat()
    identity = (info.st_dev, info.st_ino)
    if not stat.S_ISDIR(info.st_mode) or (expected is not None and identity != expected):
        _error('unsafe_path', 'Directory changed during materialization: ' + str(path))
    if any(path.iterdir()):
        _error('unsafe_path', 'A nonempty directory blocks the accepted file; preserve its descendants: ' + str(path))
    return identity


def _replace_empty_directory(path, data, identity):
    """Remove only an empty directory, then install without replacing a racer.

    The caller has already durably saved its write journal. A crash after rmdir
    leaves an absent target that normal journal recovery can materialize. A crash
    after link leaves the complete file. Exclusive link creation refuses any file,
    directory or symlink another writer creates after rmdir; no recursive cleanup
    or check-then-overwrite is allowed for this conversion.
    """
    _empty_directory(path, identity)
    fd, temporary = tempfile.mkstemp(prefix='.shared-memory-write-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        _empty_directory(path, identity)
        path.rmdir()  # The filesystem rejects a concurrently added descendant.
        _fsync_dir(path.parent)
        _no_symlinks(path)
        _no_symlinks(temporary)
        os.link(temporary, path)  # Atomic no-replace installation on this filesystem.
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _io_errors(method):
    @functools.wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except OSError as exc:
            raise ProductError(5, 'client_io', 'Client I/O failed; private drafts and journal are retained: ' + str(exc)) from exc
    return wrapped


class Client:
    def __init__(self, project_root, state_dir, request):
        self.root = _no_symlinks(project_root)
        self.state = _no_symlinks(state_dir)
        self.request = request
        self._excluded = []
        self._locations()

    def _locations(self):
        _no_symlinks(self.root)
        _no_symlinks(self.state)
        if self.state == self.root or self.state.is_relative_to(self.root) or self.root.is_relative_to(self.state):
            _error('unsafe_state', 'Client state must be outside the project, without containing it.')
        for part in self.state.parts:
            folded = part.casefold()
            if (folded in ('cloudstorage', 'mobile documents', 'dropbox', 'icloud drive') or
                    folded.startswith(('onedrive', 'googledrive', 'google drive'))):
                _error('unsafe_state', 'Private client state cannot be in a known sync folder.')
        for key in ('OneDrive', 'OneDriveConsumer', 'OneDriveCommercial', 'GOOGLE_DRIVE_ROOT', 'DROPBOX_ROOT'):
            value = os.environ.get(key)
            if value and self.state.is_relative_to(Path(os.path.abspath(value))):
                _error('unsafe_state', 'Private state cannot be under configured consumer sync storage.')
        if not self.root.is_dir():
            _error('missing_project', 'Selected project directory does not exist.', 5)

    @contextlib.contextmanager
    def _locked(self, create=False):
        self._locations()
        if create:
            self.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not self.state.is_dir():
            _error('not_attached', 'Attach this client before using it.', 4)
        lock = self.state / '.lock'
        _no_symlinks(lock)
        with open(lock, 'a+b') as stream:
            if os.name == 'nt':
                import msvcrt
                stream.seek(0)
                if not stream.read(1):
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def _load(self, name, optional=False):
        path = self.state / name
        _no_symlinks(path)
        if optional and not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError, UnicodeError) as exc:
            _error('client_state', 'Cannot read valid private client state: ' + str(exc))

    def _save(self, name, value):
        path = self.state / name
        _no_symlinks(path)
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        _atomic(path, _json(value))

    def _immutable(self, name, value):
        prior = self._load(name, optional=True)
        if prior is not None:
            if prior != value:
                _error('immutable_draft', 'A saved draft ID cannot be reused with different content.', 4)
        else:
            self._save(name, value)

    def _target(self, name):
        _path(name)
        path = self.root.joinpath(*name.split('/'))
        _no_symlinks(path)
        if not path.is_relative_to(self.root):
            _error('unsafe_path', 'Project path escaped selected root.')
        return path

    def _read(self, name):
        path = self._target(name)
        if not path.exists():
            return None
        if not path.is_file():
            _error('unsafe_path', 'Expected a regular file: ' + name)
        # O_NOFOLLOW prevents final-component substitution where supported.
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                _error('unsafe_path', 'Expected a regular file: ' + name)
            if info.st_size > MAX_FILE_BYTES:
                _error('size_limit', 'Project file exceeds the 10 MiB limit: ' + name)
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                data = stream.read(MAX_FILE_BYTES + 1)
            if len(data) > MAX_FILE_BYTES:
                _error('size_limit', 'Project file exceeds the 10 MiB limit: ' + name)
            try:
                return data.decode('utf-8')
            except UnicodeError:
                _error('unsupported_content', 'Tracked project files must be UTF-8 text: ' + name)
        finally:
            os.close(fd)

    def _walk(self, required=None):
        """Inspect managed entries before descent; excluded state stays opaque."""
        from .knowledge import PRIVATE, PRIVATE_FILES
        required = set(required or ())
        excluded = getattr(self, '_excluded', [])
        _no_symlinks(self.root)
        for directory, dirs, names in os.walk(self.root, followlinks=False):
            _no_symlinks(Path(directory))
            for name in list(dirs):
                child = Path(directory) / name
                relative = child.relative_to(self.root).as_posix()
                if name.casefold() in PROTECTED:
                    dirs.remove(name)
                elif ((name.startswith('.') or name.casefold() in PRIVATE)
                      and not any(p.startswith(relative + '/') for p in required)):
                    dirs.remove(name)
                    excluded.append({'path': relative, 'reason': 'untracked-private-directory'})
                else:
                    _no_symlinks(child)
            managed = [name for name in names if name.casefold() not in PROTECTED
                       and not name.startswith('.shared-memory-write-')]
            for name in list(managed):
                relative = (Path(directory) / name).relative_to(self.root).as_posix()
                if (relative not in required and
                        (name.startswith('.') or name.casefold() in PRIVATE | PRIVATE_FILES)):
                    managed.remove(name)
                    excluded.append({'path': relative, 'reason': 'untracked-private-file'})
                    continue
                _no_symlinks(Path(directory) / name)
            yield directory, dirs, managed

    def _scan(self, required=None):
        files = {}
        required = set(required or ())
        self._excluded = []
        for directory, dirs, names in self._walk(required):
            for name in names:
                relative = (Path(directory) / name).relative_to(self.root).as_posix()
                path = self._target(relative)
                if relative not in required and (path.suffix.casefold() in BINARY_ARTIFACT_SUFFIXES or path.name == '.DS_Store'):
                    if not path.is_file():
                        _error('unsafe_path', 'An excluded artifact must still be a regular file.')
                    self._excluded.append({'path': relative, 'reason': 'untracked-binary', 'size_bytes': path.stat().st_size})
                    continue
                try:
                    files[relative] = self._read(relative)
                except ProductError as exc:
                    if relative in required or exc.code not in ('unsupported_content', 'size_limit'):
                        raise
                    path = self._target(relative)
                    self._excluded.append({'path': relative, 'reason': 'untracked-binary' if exc.code == 'unsupported_content' else 'untracked-oversize', 'size_bytes': path.stat().st_size})
        self._excluded.sort(key=lambda item: item['path'])
        return _files(files)

    def _base(self):
        value = self._load('snapshot.json', optional=True)
        if value is None:
            _error('not_attached', 'Attach this client before using it.', 4)
        saved_root = self._load('client.json')
        if saved_root.get('schema_version') != 1:
            _error('client_state', 'Unknown client state schema version.')
        if saved_root.get('project_id') != value.get('project_id'):
            _error('project_mismatch', 'Private client project identity is inconsistent.')
        if saved_root.get('project_root') != str(self.root):
            _error('client_root_mismatch', 'Use a separate private client state directory for this local project path.')
        return _snapshot(value)

    @staticmethod
    def _changes(before, after):
        return {name: after.get(name) for name in sorted(set(before) | set(after))
                if before.get(name) != after.get(name)}

    def _preserve(self, base, current, reason):
        changes = self._changes(base['files'], current)
        if not changes:
            return []
        draft = {'base_revision': base['revision'], 'project_id': base['project_id'],
                 'changes': changes, 'reason': reason, 'kind': 'preserved-local-edits'}
        draft_id = 'preserved-' + _hash(draft)
        draft['proposal_id'] = draft_id
        self._immutable('drafts/' + draft_id + '.json', draft)
        return [draft_id]

    def _backup(self, text):
        if text is None:
            return
        data = text.encode('utf-8')
        name = hashlib.sha256(data).hexdigest()
        path = self.state / 'backups' / name
        _no_symlinks(path)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                _error('backup_integrity', 'An immutable recovery backup was modified.')
        else:
            _atomic(path, data)

    def _write_project(self, name, text):
        path = self._target(name)
        if text is None:
            if path.exists():
                _no_symlinks(path)
                path.unlink()
                _fsync_dir(path.parent)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._target(name)
            _atomic(path, text.encode('utf-8'))

    def _prune_conversion_ancestors(self, base, target):
        """Prune only empty tracked-path ancestors needed for a file conversion.

        Ordinary deletions still leave their directories alone. Untracked empty
        siblings, nonempty/private descendants and divergent tracked children
        remain in place and therefore block the parent directory's replacement.
        """
        removed = set(base['files']) - set(target['files'])
        obsolete = set()
        for name in target['files']:
            if not self._target(name).is_dir():
                continue
            prefix = name + '/'
            for deleted in removed:
                if not deleted.startswith(prefix):
                    continue
                ancestor = deleted.rsplit('/', 1)[0]
                while ancestor != name:
                    obsolete.add(ancestor)
                    ancestor = ancestor.rsplit('/', 1)[0]
        for name in sorted(obsolete, key=lambda value: (-value.count('/'), value)):
            path = self._target(name)
            if not path.is_dir() or any(path.iterdir()):
                continue
            identity = _empty_directory(path)
            _empty_directory(path, identity)
            path.rmdir()  # Never recursive; a concurrently added child blocks it.
            _fsync_dir(path.parent)

    def _resume(self, recovering=True):
        journal = self._load('journal.json', optional=True)
        if journal is None:
            return []
        if journal.get('schema_version') != 1:
            _error('client_state', 'Unknown materialization journal version.')
        config = self._load('client.json')
        if config.get('schema_version') != 1 or config.get('project_root') != str(self.root):
            _error('client_state', 'Materialization belongs to incompatible private client state.')
        target = _snapshot(journal.get('target'), config.get('project_id'))
        base = _snapshot(journal.get('base'), target['project_id'])
        before = _files(journal.get('before'))
        if journal.get('paths') != sorted(set(target['files']) | set(base['files'])):
            _error('client_state', 'Materialization journal has an invalid write plan.')
        current = self._scan(set(base['files']) | set(target['files']))
        # Compare each file against both planned states. Unexpected post-crash bytes
        # are preserved even when an earlier replacement had already completed.
        expected = dict(before)
        for name in journal['paths']:
            _path(name)
            actual = current.get(name)
            if actual == target['files'].get(name):
                if actual is None:
                    expected.pop(name, None)
                else:
                    expected[name] = actual
        recovery_base = dict(base, files=expected)
        drafts = self._preserve(recovery_base, current, 'edits-during-materialization-recovery')
        if recovering:
            # A file restored to its exact pre-write bytes is indistinguishable
            # from a write that never ran. Retain the whole interrupted state as
            # an additional reviewed draft, including deletion of a new file.
            drafts += self._preserve(target, current, 'interrupted-materialization-observed-state')
        # The durable plan remains canonical/sorted, but a recipient may skip
        # intermediate revisions. Delete baseline-matching tracked children before
        # trying to replace their former ancestor with accepted text.
        deletions = [name for name in journal['paths'] if name not in target['files']]
        writes = [name for name in journal['paths'] if name in target['files']]
        pruned = False
        for name in deletions + writes:
            if name in target['files'] and not pruned:
                self._prune_conversion_ancestors(base, target)
                pruned = True
            path = self._target(name)
            desired = target['files'].get(name)
            if desired is not None and path.is_dir():
                # Empty directories are not accepted text or user file bytes.
                # Convert only this target, under the existing recovery journal.
                identity = _empty_directory(path)
                _replace_empty_directory(path, desired.encode('utf-8'), identity)
                continue
            actual = self._read(name)
            if actual == desired:
                continue
            self._backup(actual)
            # Deletion is conservative: never erase a non-baseline local version.
            if desired is None and actual != base['files'].get(name):
                continue
            # Recheck immediately before mutation and retain changed bytes.
            rechecked = self._read(name)
            if rechecked != actual:
                latest = self._scan(set(base['files']) | set(target['files']))
                drafts += self._preserve(base, latest, 'concurrent-local-edit')
                self._backup(rechecked)
                if desired is None:
                    continue
            self._write_project(name, desired)
        # Receipt validation after state commit detects mixed/current external edits.
        self._save('snapshot.json', target)
        (self.state / 'journal.json').unlink()
        _fsync_dir(self.state)
        return drafts

    def _materialize(self, target, base):
        current = self._scan(set(base['files']) | set(target['files']))
        drafts = self._preserve(base, current, 'external-editor-or-offline-edits')
        paths = sorted(set(target['files']) | set(base['files']))
        for name in paths:
            self._target(name)
            self._backup(current.get(name))
        self._save('journal.json', {'schema_version': 1, 'base': base,
                                   'target': target, 'before': current, 'paths': paths})
        return drafts + self._resume(recovering=False)

    def _receipt(self):
        base = self._base()
        current = self._scan(base['files'])
        ready = current == base['files'] and not (self.state / 'journal.json').exists()
        return {'project_id': base['project_id'], 'revision': base['revision'],
                'files_hash': base['files_hash'], 'readiness': 'ready' if ready else 'partial',
                'excluded_artifacts': list(self._excluded)}

    @_io_errors
    def attach(self, expected_project_id):
        # Fetch/validate before creating private state or touching the project.
        target = _snapshot(self.request('snapshot', {}), expected_project_id)
        # Reject unsafe selected content before even creating private client state.
        self._scan(target['files'])
        for name in target['files']:
            self._target(name)
        with self._locked(create=True):
            existing = self._load('snapshot.json', optional=True)
            config = self._load('client.json', optional=True)
            if config and (config.get('project_root') != str(self.root) or
                           config.get('project_id') != expected_project_id):
                _error('client_root_mismatch', 'Private state already belongs to another local project.')
            self._save('client.json', {'schema_version': 1, 'project_root': str(self.root),
                                       'project_id': expected_project_id})
            self._resume()
            existing = self._load('snapshot.json', optional=True)
            if existing:
                base = _snapshot(existing, expected_project_id)
                if target['revision'] < base['revision'] or (target['revision'] == base['revision'] and target['files_hash'] != base['files_hash']):
                    _error('revision_rollback', 'Coordinator snapshot disagrees with the saved accepted state.')
            else:
                local = self._scan(target['files'])
                matched_paths = {k: v for k, v in target['files'].items() if k in local}
                base = dict(target, files=matched_paths, files_hash=_hash(matched_paths))
            drafts = self._materialize(target, base)
            return dict(self._receipt(), drafts=sorted(set(drafts)))

    @_io_errors
    def refresh(self):
        with self._locked():
            base = self._base()
            target = _snapshot(self.request('snapshot', {}), base['project_id'])
            if target['revision'] < base['revision']:
                _error('revision_rollback', 'Coordinator returned an older accepted revision.')
            if target['revision'] == base['revision'] and target['files_hash'] != base['files_hash']:
                _error('revision_integrity', 'Coordinator changed content without advancing its revision.')
            drafts = self._resume()
            base = self._base()
            if target['revision'] < base['revision'] or (target['revision'] == base['revision'] and target['files_hash'] != base['files_hash']):
                _error('revision_rollback', 'Coordinator snapshot disagrees with the recovered accepted state.')
            drafts += self._materialize(target, base)
            return dict(self._receipt(), drafts=sorted(set(drafts)))

    @_io_errors
    def accepted_snapshot(self):
        """Return a fresh copy of the saved baseline, without journal recovery.

        This describes accepted bytes, not the possibly edited project files or
        a claim that this revision is still current at the coordinator.
        """
        with self._locked():
            return self._base()

    @_io_errors
    def apply_downloaded(self, snapshot):
        """Apply downloaded bytes to an attached client after authority checking.

        The authenticated request callable supplies current metadata only. The
        caller's download or provider receipt is never itself authority. A newer
        coordinator revision requires downloading again before applying bytes.
        """
        target = _snapshot(snapshot)
        with self._locked():
            base = self._base()
            if target['project_id'] != base['project_id']:
                _error('project_mismatch', 'Downloaded snapshot belongs to another project.')

            def check_progress(previous):
                if target['revision'] < previous['revision']:
                    _error('revision_rollback', 'Downloaded snapshot predates accepted client state.')
                if target['revision'] == previous['revision'] and target['files_hash'] != previous['files_hash']:
                    _error('revision_integrity', 'Downloaded bytes disagree with the same accepted revision.')

            check_progress(base)
            required_paths = set(base['files']) | set(target['files'])
            # Recovery itself writes project files. Check its saved target before
            # allowing any recovery, including the crash-after-state-commit case.
            journal = self._load('journal.json', optional=True)
            if journal is not None:
                if not isinstance(journal, dict) or journal.get('schema_version') != 1:
                    _error('client_state', 'Unknown materialization journal version.')
                pending = _snapshot(journal.get('target'), base['project_id'])
                previous = _snapshot(journal.get('base'), base['project_id'])
                if (base not in (previous, pending) or pending['revision'] < previous['revision'] or
                        (base == previous and pending['revision'] == previous['revision'] and
                         pending['files_hash'] != previous['files_hash'])):
                    _error('client_state', 'Materialization journal does not extend the saved accepted state.')
                check_progress(pending)
                required_paths.update(previous['files'])
                required_paths.update(pending['files'])

            status = self.request('status', {'limit': 1})
            if (not isinstance(status, dict) or type(status.get('revision')) is not int or
                    status['revision'] < 0 or not isinstance(status.get('files_hash'), str) or
                    not re.fullmatch(r'[0-9a-f]{64}', status['files_hash'])):
                _error('invalid_authority', 'Authenticated coordinator returned invalid snapshot metadata.')
            if status.get('project_id') != base['project_id']:
                _error('project_mismatch', 'Authenticated coordinator belongs to another project.')
            if target['revision'] != status['revision'] or target['files_hash'] != status['files_hash']:
                _error('download_not_current', 'Downloaded snapshot does not match current authenticated authority.', 4)
            authority = {key: status[key] for key in ('project_id', 'revision', 'files_hash')}
            # Preflight downloaded targets before recovery can mutate an older
            # pending revision, including newly tracked binary or symlink paths.
            self._scan(required_paths)
            for name in required_paths:
                self._target(name)
            drafts = self._resume()
            base = self._base()
            check_progress(base)
            drafts += self._materialize(target, base)
            return dict(self._receipt(), drafts=sorted(set(drafts)),
                        byte_source='provider_download', authority_check=authority)

    @_io_errors
    def draft(self, proposal_id, assignment_id, evidence, claims=None, *, coordination=None):
        for label, value in [('proposal_id', proposal_id), ('assignment_id', assignment_id)]:
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
                _error('invalid_identity', label + ' must be a safe, nonempty identifier.')
        if not isinstance(evidence, str) or not evidence.strip():
            _error('missing_evidence', 'Draft evidence is required.')
        if claims is not None and not isinstance(claims, list):
            _error('invalid_claims', 'Claims must be a list.')
        with self._locked():
            if (self.state / 'journal.json').exists():
                _error('recovery_required', 'Refresh or attach must recover interrupted materialization first.', 4)
            base = self._base()
            changes = self._changes(base['files'], self._scan(base['files']))
            if not changes:
                _error('empty_draft', 'There are no local changes to propose.', 4)
            proposal = {'proposal_id': proposal_id, 'base_revision': base['revision'],
                        'changes': changes, 'evidence': evidence, 'assignment_id': assignment_id,
                        'claims': [] if claims is None else claims}
            if coordination is not None:
                proposal['coordination'] = _draft_coordination(coordination)
            self._immutable('drafts/' + proposal_id + '.json', proposal)
            return proposal

    @_io_errors
    def promote_preserved(self, preserved_id, proposal_id, assignment_id, evidence, claims=None, *, coordination=None):
        """Review preserved original bytes into an assigned offline proposal."""
        for label, value in [('preserved_id', preserved_id), ('proposal_id', proposal_id), ('assignment_id', assignment_id)]:
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
                _error('invalid_identity', label + ' must be a safe nonempty identifier.')
        if not isinstance(evidence, str) or not evidence.strip():
            _error('missing_evidence', 'Explicit review evidence is required.')
        if claims is not None and not isinstance(claims, list):
            _error('invalid_claims', 'Claims must be a list.')
        with self._locked():
            base = self._base()
            preserved = self._load('drafts/' + preserved_id + '.json')
            if preserved.get('kind') != 'preserved-local-edits' or preserved.get('project_id') != base['project_id']:
                _error('invalid_draft', 'Expected preserved edits from this project.')
            digest_input = {k: v for k, v in preserved.items() if k != 'proposal_id'}
            if preserved_id != 'preserved-' + _hash(digest_input):
                _error('draft_integrity', 'Preserved draft identity does not match its immutable content.')
            proposal = {'proposal_id': proposal_id, 'base_revision': preserved['base_revision'],
                        'changes': preserved['changes'], 'evidence': evidence,
                        'assignment_id': assignment_id, 'claims': [] if claims is None else claims}
            if coordination is not None:
                proposal['coordination'] = _draft_coordination(coordination)
            self._immutable('drafts/' + proposal_id + '.json', proposal)
            return proposal

    @_io_errors
    def submit(self, proposal_id):
        if not isinstance(proposal_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', proposal_id):
            _error('invalid_identity', 'Invalid proposal identifier.')
        with self._locked():
            self._base()
            proposal = self._load('drafts/' + proposal_id + '.json')
            if proposal.get('kind') == 'preserved-local-edits':
                _error('review_required', 'Preserved edits require an assignment and evidence before submission.', 4)
            result = self.request('propose', proposal)
            # Preserve every returned submission result, including idempotent retries.
            self._immutable('submissions/' + proposal_id + '-' + _hash(result) + '.json', result)
            return result

    @_io_errors
    def receipt(self):
        with self._locked():
            return self._receipt()
