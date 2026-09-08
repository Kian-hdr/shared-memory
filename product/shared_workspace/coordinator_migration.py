"""Explicit local schema-1 upgrade with a verified, retained private backup.

No provider calls, project materialization, automatic restore, or implicit upgrade.
The backup is completed before taking the authority's exclusive write lock.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid

from .engine import Coordinator, canonical, digest, identifier
from .errors import ProductError
from .workflow import private_path

LOCK_WAIT_MS = 2000
BACKUP_TIMEOUT_SECONDS = 60
RECEIPT_KEY = "coordination_upgrade"
LEGACY = {
    "meta": "key", "members": "actor", "snapshots": "revision",
    "proposals": "id", "events": "seq", "assignments": "id",
    "conflicts": "id", "resolutions": "id", "sqlite_sequence": "name",
}
COORD_TABLES = {
    "coord_meta", "coord_bindings", "coord_sessions", "coord_policies",
    "coord_outputs", "coord_inbox", "coord_defects", "coord_invalidations",
    "coord_interfaces",
}


def _fail(message, code="migration_invalid", exit_code=3):
    raise ProductError(exit_code, code, message)


@contextmanager
def _errors():
    try:
        yield
    except ProductError:
        raise
    except (OSError, sqlite3.Error) as exc:
        raise ProductError(5, "migration_environment",
                           "Local migration could not complete; preserve the authority, journal and any backup.") from exc
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise ProductError(3, "migration_invalid", "Migration input or stored records failed verification.") from exc


def _boundary(name):
    """No-op boundary for subprocess termination tests; never driven by input."""


def _row_digest(connection, query, parameters=()):
    hashed, count = hashlib.sha256(), 0
    for row in connection.execute(query, parameters):
        encoded = canonical(list(row)).encode("utf-8")
        hashed.update(len(encoded).to_bytes(8, "big"))
        hashed.update(encoded)
        count += 1
    return hashed.hexdigest(), count


def verify_checkpoint(connection, engine, *, expected_schema, expected_project_id):
    """Verify all historical content and hash raw rows on one supplied connection.

The caller owns the transaction. No connections, transactions or writes are made
here. Hashing stored JSON strings also preserves their exact original spelling.
    """
    with _errors():
        if not connection.in_transaction:
            _fail("Checkpoint verification requires a caller-owned consistent transaction.")
        if connection.execute("PRAGMA journal_mode").fetchone()[0].lower() != "delete":
            _fail("Migration requires the coordinator's supported DELETE journal mode.")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version != expected_schema or version not in (1, 2):
            _fail("Authority schema differs from the explicit migration expectation.")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            _fail("Authority failed SQLite integrity verification.")
        state = engine._schema(connection)
        if state["project_id"] != expected_project_id:
            _fail("Authority identity differs from the expected project.")
        for row in connection.execute("SELECT revision FROM snapshots ORDER BY revision"):
            engine._snapshot(connection, row[0])
        for table in ("assignments", "conflicts", "resolutions"):
            for row in connection.execute(f"SELECT id FROM {table}"):
                engine._document(connection, table, row[0])
        for row in connection.execute("SELECT id FROM proposals"):
            engine._proposal(connection, row[0])
        event_count = engine._events(connection)
        sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
        if sequence is None or sequence[0] != event_count:
            _fail("Event sequence metadata differs from preserved history.")
        for row in connection.execute("SELECT actor,human,agent,role,token_hash,active FROM members"):
            identifier(row[0], "actor")
            if (row[3] not in ("owner", "contributor", "reader") or row[5] not in (0, 1)
                    or not re.fullmatch(r"[0-9a-f]{64}", row[4])):
                _fail("Stored membership is malformed.")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        allowed = set(LEGACY) | (COORD_TABLES if version == 2 else set())
        if not set(LEGACY).issubset(tables) or tables - allowed:
            _fail("Unexpected coordinator tables; migration cannot discard or reinterpret them.")
        if version == 2:
            from . import coordination
            coordination.verify_schema(connection, full=True)
        hashes, counts = {}, {}
        for table in sorted(tables):
            # Fixed internal names only; ordering every column also covers tables
            # whose forthcoming coordination schema uses a composite key.
            order = LEGACY.get(table)
            if order is None:
                columns = list(connection.execute(f'PRAGMA table_info("{table}")'))
                order = ",".join(str(index + 1) for index in range(len(columns)))
            hashes[table], counts[table] = _row_digest(connection, f'SELECT * FROM "{table}" ORDER BY {order}')
        schema_hash, _ = _row_digest(connection,
            "SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name")
        tail = connection.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        _, _, current_hash = engine._snapshot(connection, state["revision"])
        checkpoint = digest({"schema_version": version, "schema_hash": schema_hash,
                             "table_hashes": hashes, "table_counts": counts})
        return {"schema_version": version, **state, "files_hash": current_hash,
                "event_count": event_count, "event_head": tail[0],
                "checkpoint": checkpoint, "table_counts": counts, "table_hashes": hashes}


def _legacy_schema(connection):
    names = sorted(LEGACY)
    return _row_digest(connection,
        "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE tbl_name IN ("
        + ",".join("?" for _ in names) + ") ORDER BY type,name", names)[0]


def _arguments(database, expected_project_id, config):
    if not isinstance(expected_project_id, str) or str(uuid.UUID(expected_project_id)) != expected_project_id:
        _fail("Use the exact canonical project UUID.")
    from .coordination import validate_configuration
    config = validate_configuration(config)
    path = private_path(database)
    for parent in path.parents:
        if (parent / ".shared-memory.json").exists() or (parent / ".workspace-project.json").exists():
            _fail("Authority and backup must be outside project storage.")
    return Coordinator(path), config


def _owner(connection, engine, token):
    member = engine._auth(connection, token)
    return engine._owner(connection, member["actor"])


def _connect(engine, readonly=False):
    engine._safe_db_path(engine.db_path)
    if not engine.db_path.is_file():
        _fail("A regular existing private authority is required.", "migration_environment", 5)
    connection = sqlite3.connect(engine.db_path.as_uri() + ("?mode=ro" if readonly else "?mode=rw"),
                                 uri=True, timeout=LOCK_WAIT_MS / 1000, isolation_level=None)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            connection.execute("PRAGMA synchronous=FULL")
        return connection
    except BaseException:
        connection.close()
        raise


def _plan_details(connection, engine):
    unfinished = pending = 0
    for row in connection.execute("SELECT id FROM assignments"):
        unfinished += engine._document(connection, "assignments", row[0])["status"] != "completed"
    for row in connection.execute("SELECT id FROM proposals"):
        pending += engine._proposal(connection, row[0])["status"] in ("pending", "conflict")
    return {"assignments_requiring_rebind": unfinished,
            "legacy_proposals_requiring_new_context": pending}


def plan(database, token, *, expected_project_id, coordination):
    with _errors():
        engine, config = _arguments(database, expected_project_id, coordination)
        with closing(_connect(engine, readonly=True)) as connection:
            connection.execute("BEGIN")
            _owner(connection, engine, token)
            result = verify_checkpoint(connection, engine, expected_schema=1,
                                       expected_project_id=expected_project_id)
            result.update(_plan_details(connection, engine))
            result.update({"status": "planned", "target_schema": 2,
                           "coordination_hash": digest(config), "authority_changed": False})
            return result


def _file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _fsync_directory(path):
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _backup_path(value, engine):
    destination = private_path(value)
    if (destination in {engine.db_path, *(Path(str(engine.db_path) + suffix) for suffix in ("-journal", "-wal", "-shm"))}
            or not destination.parent.is_dir()):
        _fail("Choose a separate backup below an existing private directory.")
    for parent in destination.parents:
        if (parent / ".shared-memory.json").exists() or (parent / ".workspace-project.json").exists():
            _fail("Backup cannot be stored in a shared project.")
    return destination


def _verify_backup(destination, expected_project_id, expected_checkpoint, expected_hash=None):
    if not destination.is_file() or destination.is_symlink():
        _fail("The retained migration backup is missing or unsafe.")
    hashed = _file_hash(destination)
    if expected_hash is not None and hashed != expected_hash:
        _fail("The retained migration backup differs from its committed digest.")
    backup_engine = Coordinator(destination)
    with closing(_connect(backup_engine, readonly=True)) as check:
        check.execute("BEGIN")
        result = verify_checkpoint(check, backup_engine, expected_schema=1,
                                   expected_project_id=expected_project_id)
    if result["checkpoint"] != expected_checkpoint or _file_hash(destination) != hashed:
        _fail("Backup history differs from the verified migration checkpoint.")
    return hashed


def _create_backup(source, destination, expected_project_id, checkpoint):
    if destination.exists():
        _fail("A migration backup already exists; preserve it and select a fresh destination.",
              "migration_backup_exists", 4)
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    os.close(descriptor)
    deadline = time.monotonic() + BACKUP_TIMEOUT_SECONDS

    def progress(status, remaining, total):
        if time.monotonic() > deadline:
            _fail("Backup exceeded its deadline; the authority is unchanged. Preserve the partial backup.",
                  "migration_timeout", 5)
        _boundary("during_backup")

    with closing(sqlite3.connect(destination, timeout=LOCK_WAIT_MS / 1000)) as target:
        target.execute("PRAGMA synchronous=FULL")
        source.backup(target, pages=128, progress=progress, sleep=0.05)
    hashed = _verify_backup(destination, expected_project_id, checkpoint)
    with destination.open("rb") as stream:
        os.fsync(stream.fileno())
    _fsync_directory(destination.parent)
    return hashed


def _event_receipt(receipt):
    """Commit the private destination without exposing host paths to readers.

    The complete receipt stays in local authority metadata and the owner-facing
    migration result. Project events are readable by ordinary members, so their
    payload uses an explicit public projection rather than copying private state.
    """
    keys = ("migration_id", "project_id", "source_checkpoint", "coordination_hash",
            "from_schema", "to_schema", "actor", "assignments_requiring_rebind",
            "legacy_proposals_requiring_new_context", "backup_sha256", "revision",
            "files_hash", "migration_event_seq")
    result = {key: receipt[key] for key in keys}
    result["backup_binding_hash"] = digest({"kind": "private_migration_backup_v1",
                                           "destination": receipt["backup_destination"]})
    return result


def _retry(connection, engine, token, expected_project_id, binding, destination):
    _owner(connection, engine, token)
    verify_checkpoint(connection, engine, expected_schema=2, expected_project_id=expected_project_id)
    row = connection.execute("SELECT value FROM meta WHERE key=?", (RECEIPT_KEY,)).fetchone()
    if row is None:
        _fail("Schema 2 was not created by this migration; no upgrade was attempted.", "migration_mismatch", 4)
    receipt = json.loads(row[0])
    if any(receipt.get(key) != value for key, value in binding.items()):
        _fail("Existing migration differs from this retry's identity, configuration or checkpoint.",
              "migration_mismatch", 4)
    event = connection.execute("SELECT event_json FROM events WHERE seq=?", (receipt["migration_event_seq"],)).fetchone()
    document = json.loads(event[0]) if event else {}
    if (document.get("data") != _event_receipt(receipt) or document.get("operation") != "upgrade-coordination"
            or document.get("actor") != receipt["actor"] or document.get("revision") != receipt["revision"]):
        _fail("Migration receipt differs from immutable upgrade history.")
    _verify_backup(destination, expected_project_id, binding["source_checkpoint"], receipt["backup_sha256"])
    return {**receipt, "status": "upgraded", "idempotent": True, "authority_changed": False}


def upgrade(database, token, *, expected_project_id, expected_checkpoint, coordination,
            backup_destination, migration_id):
    with _errors():
        engine, config = _arguments(database, expected_project_id, coordination)
        identifier(migration_id, "migration_id")
        if not isinstance(expected_checkpoint, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_checkpoint):
            _fail("Use the exact checkpoint from the reviewed migration plan.")
        destination = _backup_path(backup_destination, engine)
        binding = {"migration_id": migration_id, "project_id": expected_project_id,
                   "source_checkpoint": expected_checkpoint, "coordination_hash": digest(config),
                   "backup_destination": str(destination), "from_schema": 1, "to_schema": 2}
        with closing(_connect(engine, readonly=True)) as source:
            source.execute("BEGIN")
            owner = _owner(source, engine, token)
            binding["actor"] = owner["actor"]
            if source.execute("PRAGMA user_version").fetchone()[0] == 2:
                return _retry(source, engine, token, expected_project_id, binding, destination)
            before = verify_checkpoint(source, engine, expected_schema=1, expected_project_id=expected_project_id)
            if before["checkpoint"] != expected_checkpoint:
                _fail("Authority changed since the migration plan; review a new plan.", "migration_changed", 4)
            if source.execute("SELECT 1 FROM meta WHERE key=?", (RECEIPT_KEY,)).fetchone():
                _fail("Legacy authority already contains migration metadata.")
            details = _plan_details(source, engine)
            legacy_schema = _legacy_schema(source)
            _boundary("before_backup")
            backup_hash = _create_backup(source, destination, expected_project_id, expected_checkpoint)
        _boundary("after_backup")
        with closing(_connect(engine)) as connection:
            try:
                connection.execute("BEGIN EXCLUSIVE")
                _boundary("after_exclusive")
                owner = _owner(connection, engine, token)
                current = verify_checkpoint(connection, engine, expected_schema=1, expected_project_id=expected_project_id)
                if current["checkpoint"] != expected_checkpoint or owner["actor"] != binding["actor"]:
                    _fail("Authority changed after backup; preserve the backup and review a fresh migration plan.",
                          "migration_changed", 4)
                # Recheck retained backup immediately before the first authority write.
                _verify_backup(destination, expected_project_id, expected_checkpoint, backup_hash)
                from .coordination import initialize_schema
                initialize_schema(connection, engine, owner["actor"], config)
                _boundary("after_schema")
                connection.execute("PRAGMA user_version=2")
                receipt = {**binding, **details, "backup_sha256": backup_hash,
                           "revision": current["revision"], "files_hash": current["files_hash"],
                           "migration_event_seq": current["event_count"] + 1}
                connection.execute("INSERT INTO meta(key,value) VALUES(?,?)", (RECEIPT_KEY, canonical(receipt)))
                engine._event(connection, owner["actor"], "upgrade-coordination", _event_receipt(receipt), current["revision"])
                _boundary("after_event")
                after = verify_checkpoint(connection, engine, expected_schema=2, expected_project_id=expected_project_id)
                if _legacy_schema(connection) != legacy_schema:
                    _fail("Migration changed the preserved legacy table definitions.")
                for table in set(LEGACY) - {"meta", "events", "sqlite_sequence"}:
                    if after["table_hashes"][table] != before["table_hashes"][table]:
                        _fail("Migration changed a preserved legacy record; transaction rolled back.")
                legacy_meta, _ = _row_digest(connection, "SELECT * FROM meta WHERE key<>? ORDER BY key", (RECEIPT_KEY,))
                prefix, _ = _row_digest(connection, "SELECT * FROM events WHERE seq<=? ORDER BY seq", (current["event_count"],))
                sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
                if (legacy_meta != before["table_hashes"]["meta"] or prefix != before["table_hashes"]["events"]
                        or after["event_count"] != current["event_count"] + 1 or sequence[0] != after["event_count"]):
                    _fail("Migration did not preserve the exact legacy event prefix and metadata.")
                _boundary("before_commit")
                connection.commit()
                _boundary("after_commit")
            except BaseException:
                connection.rollback()
                raise
        with closing(_connect(engine, readonly=True)) as check:
            check.execute("BEGIN")
            result = _retry(check, engine, token, expected_project_id, binding, destination)
        return {**result, "idempotent": False, "authority_changed": True}
