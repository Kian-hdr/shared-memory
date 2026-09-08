"""Explicit, immutable accepted-snapshot delivery. No login or project writes.

The caller supplies coordinator-authenticated expected identity and accepted
snapshots. This module proves downloaded bytes, not acceptance authority, account
permissions, recipient materialization, or a mixed-OS team gate. A single approved
publisher owns each revision namespace; Drive is not a conditional-write store.
Remote revision history is retained. There are no sync, delete or sharing commands.
"""
from __future__ import annotations

import configparser
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .engine import (MAX_FILE_BYTES, MAX_FILES, MAX_SNAPSHOT_BYTES, canonical,
                     files_hash, path_inventory, validate_files, validate_path)
from .errors import ProductError

MANIFEST_LIMIT = 16 * 1024 * 1024
LIST_LIMIT = 32 * 1024 * 1024
ENTRY_LIMIT = 25000
MANIFEST_NAME = 'delivery-manifest.json'


def fail(code, message, exit_code=3):
    # Provider stderr, credential-bearing config parse errors and local paths
    # must not become the displayed context of a public operational error.
    raise ProductError(exit_code, code, message) from None


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('delivery_invalid', 'Duplicate JSON keys are not allowed.')
            result[key] = value
        return result
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda _: fail('delivery_invalid', 'Invalid JSON constant.'))
    except (ValueError, UnicodeError, RecursionError):
        fail('delivery_invalid', 'Delivery metadata is not bounded UTF-8 JSON.')


def _identity(value):
    if not isinstance(value, dict):
        fail('delivery_identity', 'Expected a trusted snapshot identity.')
    project_id, revision, digest = (value.get(k) for k in ('project_id', 'revision', 'files_hash'))
    try:
        valid_id = isinstance(project_id, str) and str(uuid.UUID(project_id)) == project_id
    except (ValueError, AttributeError):
        valid_id = False
    if (not valid_id or type(revision) is not int or not 0 <= revision <= 2**63 - 1
            or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)):
        fail('delivery_identity', 'Expected a canonical project UUID, revision and SHA-256.')
    return {'project_id': project_id, 'revision': revision, 'files_hash': digest}


def _snapshot(value):
    identity = _identity(value)
    files = validate_files(value.get('files'))
    if files_hash(files) != identity['files_hash']:
        fail('delivery_integrity', 'Snapshot content does not match its accepted hash.')
    return dict(identity, files=files)


def _prefix(identity):
    return f"{identity['project_id']}/revisions/{identity['revision']}-{identity['files_hash']}"


def _parents(paths):
    result = set()
    for name in paths:
        parts = name.split('/')
        result.update('/'.join(parts[:i]) for i in range(1, len(parts)))
    if len(result) + len(paths) > ENTRY_LIMIT:
        fail('delivery_limit', 'Delivery directory inventory exceeds its bounded route limit.')
    return result


def _object_path(name):
    # The namespace adds characters to otherwise valid 1024-byte project paths.
    try:
        valid = isinstance(name, str) and len(name.encode('utf-8')) <= 1400
    except UnicodeError:
        valid = False
    if not valid:
        fail('delivery_path', 'Invalid delivery object path.')
    parts = name.split('/')
    if not parts or any(not part for part in parts):
        fail('delivery_path', 'Invalid delivery object path.')
    for part in parts:
        validate_path(part)
    return name


def _safe_local(path, *, directory=False, fresh=False):
    path = Path(os.path.abspath(path))
    # Resolve the fixed macOS /var and /tmp aliases, not arbitrary user symlinks.
    if sys.platform == 'darwin':
        for alias in ('/var', '/tmp', '/etc'):
            prefix = Path(alias)
            if path.is_relative_to(prefix) and prefix.is_symlink() and prefix.resolve() == Path('/private' + alias):
                path = Path('/private' + alias) / path.relative_to(prefix)
                break
    for parent in (path, *path.parents):
        if parent.is_symlink():
            fail('delivery_path', 'Private delivery paths cannot use symlinks.')
    if fresh:
        if path.exists() or not path.parent.is_dir():
            fail('delivery_staging', 'Staging must be a fresh path with an existing private parent.')
    elif directory and not path.is_dir():
        fail('delivery_path', 'Expected an existing private directory.')
    return path


@dataclass(frozen=True)
class Entry:
    path: str
    size: int
    is_dir: bool = False


class Backend(Protocol):
    """Implementations must retain objects and fail writes to differing objects."""
    def start(self): ...
    def info(self) -> dict: ...
    def list(self, prefix: str) -> list[Entry]: ...
    def read(self, path: str, maximum: int) -> bytes: ...
    def put_new(self, path: str, data: bytes): ...


@dataclass(frozen=True)
class DownloadedSnapshot:
    snapshot: dict
    receipt: dict
    staging: Path = field(repr=False)


class Delivery:
    def __init__(self, backend: Backend):
        self.backend = backend

    def _inventory(self, prefix, expected, *, partial=False):
        entries = self.backend.list(prefix)
        if not isinstance(entries, list) or len(entries) > ENTRY_LIMIT:
            fail('delivery_limit', 'Delivery inventory exceeds the entry limit.')
        dirs = _parents(expected)
        seen, found = set(), {}
        for entry in entries:
            if not isinstance(entry, Entry):
                fail('delivery_invalid', 'Backend returned an invalid inventory entry.')
            _object_path(entry.path)
            if entry.path.casefold() in seen or type(entry.is_dir) is not bool:
                fail('delivery_duplicate', 'Duplicate or ambiguous delivery entries were found.')
            seen.add(entry.path.casefold())
            if entry.is_dir:
                if entry.path not in dirs:
                    fail('delivery_extra', 'Unexpected delivery directory was found.')
            elif (entry.path not in expected or type(entry.size) is not int
                  or entry.size != expected[entry.path]):
                fail('delivery_integrity', 'Delivery inventory differs from the expected revision.')
            else:
                found[entry.path] = entry.size
        if not partial and set(found) != set(expected):
            fail('delivery_incomplete', 'The revision is not completely published.', 5)
        return found

    def _receipt(self, snapshot, previous, operation):
        info = self.backend.info()
        route = info.get('route')
        if route not in {'local_fixture', 'google_drive_rclone'}:
            fail('delivery_backend', 'Backend evidence route must be explicit.')
        if route == 'google_drive_rclone' and not isinstance(self.backend, RcloneBackend):
            fail('delivery_backend', 'Injected fixture backends cannot assert a Google Drive receipt.')
        base = None
        deleted = []
        if previous is not None:
            previous = _snapshot(previous)
            if (previous['project_id'] != snapshot['project_id'] or previous['revision'] > snapshot['revision']
                    or (previous['revision'] == snapshot['revision'] and previous['files_hash'] != snapshot['files_hash'])):
                fail('delivery_base', 'Deletion base does not match this accepted project history.')
            base = _identity(previous)
            deleted = sorted(set(previous['files']) - set(snapshot['files']))
        return dict(_identity(snapshot), schema_version=1, route=route, operation=operation,
                    transfer='verified', provider_receipt='not_run' if route == 'local_fixture' else 'downloaded_bytes_verified',
                    rclone_version=info.get('rclone_version'), account_type=info.get('account_type'),
                    file_count=len(snapshot['files']), bytes=sum(len(v.encode()) for v in snapshot['files'].values()),
                    deletion_base=base, deleted_paths=deleted, local_deletions='not_applied',
                    remote_history='retained', mixed_os_team_gate='not_run')

    def publish(self, snapshot, *, previous=None):
        snapshot = _snapshot(snapshot)
        receipt = self._receipt(snapshot, previous, 'publish')
        # Publication verifies storage reads; it is not a recipient receipt.
        receipt['provider_receipt'] = 'not_run' if receipt['route'] == 'local_fixture' else 'publication_verified'
        manifest = dict(_identity(snapshot), schema_version=1, files={
            name: {'size': len(value.encode('utf-8')), 'sha256': hashlib.sha256(value.encode('utf-8')).hexdigest()}
            for name, value in snapshot['files'].items()})
        raw = canonical(manifest).encode('utf-8')
        if len(raw) > MANIFEST_LIMIT:
            fail('delivery_limit', 'Delivery manifest exceeds its byte limit.')
        objects = {'files/' + name: value.encode('utf-8') for name, value in snapshot['files'].items()}
        objects[MANIFEST_NAME] = raw
        expected = {name: len(value) for name, value in objects.items()}
        prefix = _prefix(snapshot)
        self.backend.start()
        found = self._inventory(prefix, expected, partial=True)
        if MANIFEST_NAME in found and len(found) != len(expected):
            fail('delivery_incomplete', 'A published manifest has missing content; refusing to modify history.', 5)
        for name in sorted(found):
            if self.backend.read(prefix + '/' + name, len(objects[name])) != objects[name]:
                fail('delivery_integrity', 'An existing revision object has different bytes.')
        # Only this order makes the manifest a completion marker.
        for name in [*sorted(set(objects) - {MANIFEST_NAME}), MANIFEST_NAME]:
            if name not in found:
                self.backend.put_new(prefix + '/' + name, objects[name])
            if self.backend.read(prefix + '/' + name, len(objects[name])) != objects[name]:
                fail('delivery_integrity', 'Published bytes differ from the accepted snapshot.')
        self._inventory(prefix, expected)
        receipt['rclone_version'] = self.backend.info().get('rclone_version')
        return receipt

    def fetch(self, expected, staging, *, previous=None):
        expected = _identity(expected)
        staging = _safe_local(staging, fresh=True)
        # Check prior identity before touching provider or creating staging.
        if previous is not None:
            previous = _snapshot(previous)
            if (previous['project_id'] != expected['project_id'] or previous['revision'] > expected['revision']
                    or (previous['revision'] == expected['revision'] and previous['files_hash'] != expected['files_hash'])):
                fail('delivery_base', 'Deletion base does not match the requested identity.')
        self.backend.start()
        prefix = _prefix(expected)
        raw = self.backend.read(prefix + '/' + MANIFEST_NAME, MANIFEST_LIMIT)
        if not isinstance(raw, bytes) or len(raw) > MANIFEST_LIMIT:
            fail('delivery_limit', 'Published manifest exceeds its byte limit.')
        manifest = _json(raw)
        if (not isinstance(manifest, dict) or set(manifest) != {'project_id', 'revision', 'files_hash', 'schema_version', 'files'}
                or manifest['schema_version'] != 1 or type(manifest['schema_version']) is not int
                or _identity(manifest) != expected or canonical(manifest).encode('utf-8') != raw):
            fail('delivery_integrity', 'Published manifest differs from the trusted expected revision.')
        inventory = manifest['files']
        if not isinstance(inventory, dict) or len(inventory) > MAX_FILES:
            fail('delivery_limit', 'Invalid manifest file inventory.')
        total = 0
        sizes = {MANIFEST_NAME: len(raw)}
        for name, metadata in inventory.items():
            validate_path(name)
            if (not isinstance(metadata, dict) or set(metadata) != {'size', 'sha256'}
                    or type(metadata['size']) is not int or not 0 <= metadata['size'] <= MAX_FILE_BYTES
                    or not isinstance(metadata['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', metadata['sha256'])):
                fail('delivery_invalid', 'Invalid manifest file metadata.')
            total += metadata['size']
            sizes['files/' + name] = metadata['size']
        path_inventory(inventory)
        if total > MAX_SNAPSHOT_BYTES:
            fail('delivery_limit', 'Delivery snapshot exceeds its byte limit.')
        self._inventory(prefix, sizes)
        files = {}
        for name, metadata in inventory.items():
            content = self.backend.read(prefix + '/files/' + name, metadata['size'])
            if len(content) != metadata['size'] or hashlib.sha256(content).hexdigest() != metadata['sha256']:
                fail('delivery_integrity', 'Downloaded file bytes do not match the published manifest.')
            try:
                files[name] = content.decode('utf-8')
            except UnicodeError:
                fail('delivery_invalid', 'Accepted project content must be UTF-8 text.')
        snapshot = _snapshot(dict(expected, files=files))
        # Check again after reads to catch observed partial/replaced inventories.
        self._inventory(prefix, sizes)
        if self.backend.read(prefix + '/' + MANIFEST_NAME, MANIFEST_LIMIT) != raw:
            fail('delivery_integrity', 'Publication changed during download.')
        receipt = self._receipt(snapshot, previous, 'fetch')
        _safe_local(staging, fresh=True)
        try:
            staging.mkdir(mode=0o700)
            for name, content in files.items():
                target = staging / 'files' / name
                _safe_local(target)
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open('xb') as stream:
                    stream.write(content.encode('utf-8'))
                    stream.flush()
                    os.fsync(stream.fileno())
            with (staging / MANIFEST_NAME).open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            fail('delivery_staging', 'Private staging could not be completed; retained for inspection.', 5)
        return DownloadedSnapshot(snapshot, receipt, staging)


@dataclass(frozen=True)
class GoogleDriveBinding:
    config: Path = field(repr=False)
    remote: str = field(repr=False)
    root_folder_id: str = field(repr=False)
    account_type: str
    reviewed: bool = False
    team_drive_id: str = field(default='', repr=False)


class _Rclone:
    """Bounded subprocess transport, with no ambient remote or proxy overrides."""
    route = 'local_fixture'

    def __init__(self, executable, *, timeout=30, operation_timeout=720):
        self.executable = Path(executable).resolve()
        if not self.executable.is_file() or not 0 < timeout <= 60 or not 0 < operation_timeout <= 720:
            fail('delivery_driver', 'Select an installed executable and bounded timeouts.')
        self.timeout, self.operation_timeout = timeout, operation_timeout
        self.deadline = 0
        self.version = None

    def start(self):
        self.deadline = time.monotonic() + self.operation_timeout
        raw = self._run(['version'], maximum=16384)
        first = raw.decode('utf-8', errors='replace').splitlines()[0] if raw else ''
        if not re.fullmatch(r'rclone v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', first):
            fail('delivery_driver', 'Executable did not report a supported rclone version.')
        self.version = first.removeprefix('rclone ')
        numbers = tuple(int(part) for part in self.version[1:].split('-', 1)[0].split('+', 1)[0].split('.'))
        if numbers < (1, 75, 0):
            fail('delivery_driver', 'This delivery route requires rclone 1.75.0 or later.')

    def info(self):
        return {'route': self.route, 'rclone_version': self.version,
                'account_type': getattr(getattr(self, 'binding', None), 'account_type', 'fixture')}

    def _config(self):
        raise NotImplementedError

    def _flags(self):
        return []

    def _run(self, args, *, maximum, allowed=()):
        config = self._config()
        remaining = min(self.timeout, self.deadline - time.monotonic())
        if remaining <= 0:
            fail('delivery_timeout', 'Delivery operation exceeded its time budget.', 5)
        env = {key: value for key, value in os.environ.items()
               if key.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'TMPDIR'}}
        env['LANG'] = 'C.UTF-8'
        command = [str(self.executable), '--config', str(config), '--retries', '1', '--low-level-retries', '1',
                   '--contimeout', '10s', '--timeout', f'{self.timeout}s', '--stats', '0',
                   '--log-level', 'ERROR', *self._flags(), *args]
        output, exceeded, diagnostics = bytearray(), threading.Event(), threading.Event()
        def drain(stream, cap, capture=False):
            count = 0
            try:
                while chunk := stream.read(65536):
                    if not capture:
                        diagnostics.set()
                    count += len(chunk)
                    if count > cap:
                        exceeded.set()
                        try:
                            process.kill()
                        except OSError:
                            pass
                        break
                    if capture:
                        output.extend(chunk)
            finally:
                stream.close()
        try:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, env=env, shell=False)
            readers = [threading.Thread(target=drain, args=(process.stdout, maximum, True), daemon=True),
                       threading.Thread(target=drain, args=(process.stderr, 65536), daemon=True)]
            for thread in readers:
                thread.start()
            try:
                code = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                fail('delivery_timeout', 'Delivery command exceeded its time budget.', 5)
            finally:
                for thread in readers:
                    thread.join(timeout=2)
            if exceeded.is_set():
                fail('delivery_limit', 'Delivery command exceeded its output budget.', 5)
            if code not in (0, *allowed):
                fail('delivery_unavailable', 'Delivery command failed; credentials and provider diagnostics were not exposed.', 5)
            # In rclone 1.75.0 a Drive query with incompleteSearch can log ERROR
            # yet exit zero. --log-level ERROR plus any stderr is fail-closed.
            if diagnostics.is_set():
                fail('delivery_unavailable', 'Delivery command reported an error; incomplete results cannot establish receipt.', 5)
            return bytes(output) if code == 0 else None
        except OSError:
            fail('delivery_driver', 'Delivery executable could not be started.', 5)

    def _location(self, path):
        raise NotImplementedError

    def read(self, path, maximum):
        _object_path(path)
        if type(maximum) is not int or not 0 <= maximum <= MANIFEST_LIMIT:
            fail('delivery_limit', 'Invalid object read bound.')
        self._before(path)
        return self._run(['cat', self._location(path)], maximum=maximum)

    def _before(self, path):
        pass

    def put_new(self, path, data):
        _object_path(path)
        if not isinstance(data, bytes) or len(data) > MANIFEST_LIMIT:
            fail('delivery_limit', 'Invalid object upload bound.')
        self._before(path)
        with tempfile.TemporaryDirectory(prefix='shared-memory-delivery-upload-') as directory:
            source = Path(directory) / 'object'
            source.write_bytes(data)
            # Explicit immutable copy only. The caller rechecks exact bytes and
            # duplicate inventory; this is not a Drive compare-and-swap guarantee.
            self._run(['copyto', str(source), self._location(path), '--immutable', '--checksum'], maximum=65536)


class LocalRcloneBackend(_Rclone):
    """Actual rclone local backend, always reported as fixture evidence."""
    def __init__(self, executable, fixture_root, **kwargs):
        super().__init__(executable, **kwargs)
        self.root = _safe_local(fixture_root, directory=True)
        self._temporary = tempfile.TemporaryDirectory(prefix='shared-memory-rclone-config-')
        self.config = Path(self._temporary.name) / 'empty.conf'
        self.config.touch(mode=0o600)

    def close(self):
        self._temporary.cleanup()

    def _config(self):
        return self.config

    def _location(self, path):
        return str(_safe_local(self.root / _object_path(path)))

    def list(self, prefix):
        path = _safe_local(self.root / _object_path(prefix))
        if not path.exists():
            return []
        # Local symlinks would otherwise be hidden from rclone listings.
        count = 0
        for base, dirs, files in os.walk(path, followlinks=False):
            count += len(dirs) + len(files)
            if count > ENTRY_LIMIT:
                fail('delivery_limit', 'Fixture directory inventory exceeds its entry limit.')
            for name in dirs + files:
                entry = Path(base) / name
                if entry.is_symlink() or not (entry.is_dir() or entry.is_file()):
                    fail('delivery_path', 'Fixture transport requires ordinary files and directories.')
        raw = self._run(['lsjson', str(path), '--recursive', '--no-modtime'], maximum=LIST_LIMIT)
        entries = _json(raw)
        if not isinstance(entries, list) or len(entries) > ENTRY_LIMIT:
            fail('delivery_limit', 'Invalid rclone inventory.')
        try:
            return [Entry(item['Path'], item['Size'], item['IsDir']) for item in entries]
        except (KeyError, TypeError):
            fail('delivery_invalid', 'Invalid rclone inventory entry.')


class RcloneBackend(_Rclone):
    """Google Drive only. Configuration review is explicit, not an OAuth grant.

    The root folder is a software target, not a Google OAuth scope boundary.
    The caller must keep configuration/staging outside project and sync roots.
    Only ordinary files and real directories are accepted, never shortcuts or
    native Google documents. Existing unrelated remote sections are not used.
    """
    route = 'google_drive_rclone'

    def __init__(self, executable, binding: GoogleDriveBinding, **kwargs):
        super().__init__(executable, **kwargs)
        self.binding = binding
        self._config()  # Local preflight only. No Drive connection or login.

    def _config(self):
        b = self.binding
        if (not isinstance(b, GoogleDriveBinding) or b.reviewed is not True
                or not re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,63}', b.remote)
                or not re.fullmatch('[A-Za-z0-9_-]{1,256}', b.root_folder_id)
                or b.account_type not in {'personal', 'workspace_my_drive', 'workspace_shared_drive'}
                or (b.account_type == 'workspace_shared_drive') != bool(b.team_drive_id)
                or (b.team_drive_id and not re.fullmatch('[A-Za-z0-9_-]{1,256}', b.team_drive_id))):
            fail('delivery_binding', 'An explicit reviewed Drive account and folder binding is required.')
        path = _safe_local(b.config)
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > 1024 * 1024:
                fail('delivery_binding', 'Expected a bounded private rclone configuration.')
            if os.name != 'nt' and (info.st_mode & 0o077 or info.st_uid != os.getuid()):
                fail('delivery_binding', 'Rclone configuration must be private to the current user.')
            parser = configparser.ConfigParser(interpolation=None, strict=True)
            parser.read_string(path.read_text(encoding='utf-8'))
            section = parser[b.remote]
            allowed = {'type', 'client_id', 'client_secret', 'scope', 'token', 'root_folder_id', 'team_drive'}
            if (set(section) - allowed or parser.defaults() or section.get('type') != 'drive'
                    or section.get('root_folder_id') != b.root_folder_id
                    or section.get('team_drive', '') != b.team_drive_id or not section.get('client_id')
                    or section.get('scope') not in {'drive', 'drive.readonly', 'drive.file'}):
                fail('delivery_binding', 'Reviewed binding differs from the explicit Drive backend configuration.')
            token = _json(section.get('token', '').encode())
            if not isinstance(token, dict) or not token.get('refresh_token'):
                fail('delivery_binding', 'Existing authorized OAuth configuration is required; no login is performed.')
        except (OSError, UnicodeError, configparser.Error, KeyError):
            fail('delivery_binding', 'Private rclone configuration could not be validated.')
        return path

    def _flags(self):
        return ['--drive-skip-shortcuts', '--drive-show-all-gdocs', '--drive-use-trash']

    def _location(self, path):
        return self.binding.remote + ':' + _object_path(path)

    def _children(self, folder):
        if not isinstance(folder, str) or not re.fullmatch('[A-Za-z0-9_-]{1,256}', folder):
            fail('delivery_invalid', 'Invalid provider directory identity.')
        raw = self._run(['backend', 'query', self.binding.remote + ':',
                         f"'{folder}' in parents and trashed = false"], maximum=LIST_LIMIT)
        values = _json(raw)
        # rclone 1.75.0 query returns a nil Go slice (JSON null) on no matches.
        if values is None:
            values = []
        if not isinstance(values, list) or len(values) > ENTRY_LIMIT:
            fail('delivery_limit', 'Provider directory inventory exceeds its limit.')
        seen = set()
        for item in values:
            if not isinstance(item, dict) or not isinstance(item.get('name'), str):
                fail('delivery_invalid', 'Invalid provider inventory entry.')
            name = item['name']
            validate_path(name)
            if '/' in name or name.casefold() in seen:
                fail('delivery_duplicate', 'Provider directory has unsafe or duplicate names.')
            seen.add(name.casefold())
            mime = item.get('mimeType', '')
            if not isinstance(mime, str) or (mime.startswith('application/vnd.google-apps.')
                    and mime != 'application/vnd.google-apps.folder'):
                fail('delivery_path', 'Shortcuts and native Google documents are outside this delivery route.')
            if (not isinstance(item.get('id'), str) or not re.fullmatch('[A-Za-z0-9_-]{1,256}', item['id'])
                    or item.get('parents') != [folder]):
                fail('delivery_invalid', 'Provider entry has an unexpected parent or identity.')
        return values

    def _resolve(self, path):
        folder = self.binding.root_folder_id
        for part in _object_path(path).split('/'):
            found = [item for item in self._children(folder) if item['name'] == part]
            if not found:
                return None
            item = found[0]
            if item['mimeType'] != 'application/vnd.google-apps.folder':
                fail('delivery_path', 'A provider path ancestor is not a directory.')
            folder = item['id']
        return folder

    def _before(self, path):
        # Reject ambiguous/shortcut ancestors before path-addressed rclone IO.
        parent = self._resolve(path.rsplit('/', 1)[0])
        if parent is not None:
            self._children(parent)

    def list(self, prefix):
        folder = self._resolve(prefix)
        if folder is None:
            return []
        entries, pending = [], [('', folder)]
        visited = set()
        while pending:
            parent, identity = pending.pop()
            if identity in visited:
                fail('delivery_path', 'Repeated provider directory identity.')
            visited.add(identity)
            for item in self._children(identity):
                name = parent + item['name']
                directory = item['mimeType'] == 'application/vnd.google-apps.folder'
                try:
                    size = 0 if directory else int(item['size'])
                except (KeyError, ValueError, TypeError):
                    fail('delivery_invalid', 'Provider file lacks a bounded size.')
                entries.append(Entry(name, size, directory))
                if len(entries) > ENTRY_LIMIT:
                    fail('delivery_limit', 'Provider inventory exceeds its entry limit.')
                if directory:
                    pending.append((name + '/', item['id']))
        return entries
