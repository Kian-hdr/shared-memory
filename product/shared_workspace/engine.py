"""Transactional project authority. SQLite belongs on private coordinator storage.

Tokens authenticate membership; evidence remains an explicit reviewer assertion.
No provider transport, arbitrary Markdown truth inference, or text merging occurs.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .errors import ProductError

SCHEMA_VERSION = 1
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 100 * 1024 * 1024
MAX_FILES = 10000
MAX_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_PROPOSALS = 1000
MAX_PAGE_SIZE = 1000
EVENT_PAGE_BYTES = 4 * 1024 * 1024
PROTECTED = {".git", ".obsidian", ".workspace-project.json", ".shared-memory.json",
             ".shared-memory", ".shared-workspace", "coordinator.db", "coordinator.sqlite",
             "coordinator.sqlite3", "coordinator-state", "client-state", "client-state.json",
             "state.json", "client.json", "snapshot.json", "journal.json", ".lock",
             "setup-intent.json", "setup-recovery", ".setup.lock"}
READ_OPERATIONS = {"status", "snapshot", "events", "proposal", "conflict", "assignment", "facts"}
OPERATIONS = READ_OPERATIONS | {"member", "revoke", "claim", "propose", "accept", "resolve",
                                 "reject", "supersede", "handoff", "receive", "complete",
                                 "transfer-authority", "transfer-integration"}


def malformed(message):
    raise ProductError(3, "engine_invalid", message)


def rejected(message):
    raise ProductError(4, "engine_rejected", message)


def canonical(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ProductError(3, "engine_invalid", "Value is not canonical JSON data.") from exc


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def files_hash(files):
    return digest(files)


def text(value, field, *, maximum=16384, empty=False):
    if not isinstance(value, str) or (not empty and not value.strip()):
        malformed(f"{field} must be a {'nonempty ' if not empty else ''}string.")
    try:
        if len(value.encode("utf-8")) > maximum:
            malformed(f"{field} exceeds its {maximum}-byte limit.")
    except UnicodeError as exc:
        raise ProductError(3, "engine_invalid", f"{field} is not valid UTF-8 text.") from exc
    return value


def identifier(value, field="identifier"):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        malformed(f"{field} must be 1–128 portable ASCII identifier characters.")
    return value


def validate_path(value, target=False):
    text(value, "path", maximum=1024)
    if unicodedata.normalize("NFC", value) != value:
        malformed("Project paths must use Unicode NFC normalization.")
    if target and value == ".":
        return value
    directory = target and value.endswith("/")
    name = value[:-1] if directory else value
    path = PurePosixPath(name)
    if (not path.parts or name.startswith("/") or "\\" in name or ":" in name
            or str(path) != name or any(part in {".", ".."} for part in name.split("/"))
            or any(unicodedata.category(c) in {"Cc", "Cf"} for c in name)):
        malformed("Paths must be canonical project-relative POSIX paths without traversal or control characters.")
    for part in path.parts:
        if len(part.encode("utf-8")) > 255 or part.endswith((".", " ")) or any(c in part for c in '<>"|?*'):
            malformed("Path contains a name unsupported on Windows.")
        stem = part.split(".", 1)[0].casefold()
        if stem in {"con", "prn", "aux", "nul"} or re.fullmatch(r"(?:com|lpt)[1-9¹²³]", stem):
            malformed("Path contains a reserved Windows device name.")
        if part.casefold() in PROTECTED or part.casefold().endswith((".sqlite-wal", ".sqlite-shm", ".db-journal")):
            malformed("Private configuration and coordinator/client state are not project content.")
    return name + ("/" if directory else "")


def path_inventory(paths):
    seen = {}
    spellings = {}
    for path in paths:
        parts = path.split("/")
        for count in range(1, len(parts) + 1):
            prefix = "/".join(parts[:count])
            if prefix.casefold() in spellings and spellings[prefix.casefold()] != prefix:
                malformed("Casefold-colliding path components are not portable.")
            spellings[prefix.casefold()] = prefix
        folded = path.casefold()
        if folded in seen and seen[folded] != path:
            malformed("Casefold-colliding file names are not portable.")
        seen[folded] = path
    for path in seen:
        parts = path.split("/")
        if any("/".join(parts[:i]) in seen for i in range(1, len(parts))):
            malformed("A file cannot also be a parent directory of another file.")


def validate_files(files):
    if not isinstance(files, dict) or len(files) > MAX_FILES:
        malformed(f"A snapshot must be a file map with at most {MAX_FILES} files.")
    total = 0
    for path, content in files.items():
        validate_path(path)
        text(content, "file content", maximum=MAX_FILE_BYTES, empty=True)
        total += len(content.encode("utf-8"))
    path_inventory(files)
    if total > MAX_SNAPSHOT_BYTES:
        malformed("Snapshot content exceeds the 100 MiB limit.")
    return dict(files)


def evidence(value):
    if isinstance(value, str):
        return text(value, "evidence")
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        malformed("Evidence must be a nonempty string or 1–100 evidence strings.")
    return [text(item, "evidence") for item in value]


def fields(payload, required, optional=()):
    if not isinstance(payload, dict) or set(payload) - set(required) - set(optional) or set(required) - set(payload):
        malformed("Operation payload has missing or unsupported fields.")


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Coordinator:
    def __init__(self, db_path):
        self.db_path = self._safe_db_path(db_path)
        names = [part.casefold() for part in self.db_path.parts]
        if any(part in {"cloudstorage", "mobile documents", "icloud drive", "dropbox"}
               or part.startswith(("googledrive", "google drive", "onedrive")) for part in names):
            malformed("Coordinator SQLite must be outside known consumer-sync storage.")

    @staticmethod
    def _safe_db_path(db_path):
        source = Path(os.path.abspath(Path(db_path).expanduser()))
        if sys.platform == "darwin":
            for alias in ("/var", "/tmp", "/etc"):
                prefix = Path(alias)
                if source.is_relative_to(prefix) and prefix.is_symlink() and prefix.resolve() == Path("/private" + alias):
                    source = Path("/private" + alias) / source.relative_to(prefix)
                    break
        if any(path.is_symlink() for path in (source, *source.parents)):
            malformed("Coordinator database and parent directories may not use symbolic links.")
        return source

    def _connect(self, readonly=False):
        self._safe_db_path(self.db_path)
        if not self.db_path.is_file() or self.db_path.is_symlink():
            raise ProductError(5, "engine_environment", "Coordinator database is missing or not a regular local file.")
        uri = self.db_path.as_uri() + ("?mode=ro" if readonly else "?mode=rw")
        connection = sqlite3.connect(uri, uri=True, timeout=20, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        if not readonly:
            connection.execute("PRAGMA synchronous=FULL")
        return connection

    def _schema(self, connection):
        if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            malformed("Unknown or incomplete coordinator schema; no migration was attempted.")
        row = connection.execute("SELECT value FROM meta WHERE key='state'").fetchone()
        if not row:
            malformed("Coordinator initialization is incomplete.")
        state = json.loads(row[0])
        if (set(state) != {"project_id", "revision"} or type(state["revision"]) is not int
                or state["revision"] < 0 or str(uuid.UUID(state["project_id"])) != state["project_id"]):
            malformed("Coordinator state metadata is invalid.")
        count = 0
        for row in connection.execute("SELECT revision FROM snapshots ORDER BY revision"):
            if row[0] != count:
                malformed("Accepted snapshot history has a missing revision.")
            count += 1
        if count != state["revision"] + 1:
            malformed("Accepted snapshot history is incomplete or inconsistent.")
        initial = connection.execute("SELECT event_json FROM events WHERE seq=1").fetchone()
        if not initial or json.loads(initial[0])["data"]["project_id"] != state["project_id"]:
            malformed("Project identity differs from immutable initialization history.")
        return state

    def _token(self, token):
        text(token, "authentication token", maximum=4096)
        if len(token.encode("utf-8")) < 16:
            malformed("Authentication secrets must contain at least 16 bytes; use a random caller-generated token.")
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _member(self, connection, actor):
        row = connection.execute("SELECT * FROM members WHERE actor=?", (actor,)).fetchone()
        if not row or not row["active"]:
            rejected("Referenced project member is inactive or unknown.")
        return dict(row)

    def _auth(self, connection, token):
        hashed = self._token(token)
        row = connection.execute("SELECT * FROM members WHERE token_hash=?", (hashed,)).fetchone()
        if not row or not hmac.compare_digest(row["token_hash"], hashed) or not row["active"]:
            rejected("Authentication failed or membership was revoked.")
        return dict(row)

    def _owner(self, connection, actor):
        member = self._member(connection, actor)
        if member["role"] != "owner":
            rejected("This operation requires an active project owner.")
        return member

    def _document(self, connection, table, item_id):
        if table not in {"assignments", "conflicts", "resolutions"}:
            malformed("Invalid internal document table.")
        row = connection.execute(f"SELECT document,document_hash FROM {table} WHERE id=?", (item_id,)).fetchone()
        if not row:
            rejected(f"Unknown {table.rstrip('s')} identity.")
        document = json.loads(row["document"])
        if digest(document) != row["document_hash"]:
            malformed("Stored coordinator document failed hash verification.")
        if table == "assignments" and document.get("assignment_id") != item_id:
            malformed("Use the assignment's exact canonical identity spelling.")
        return document

    def _put(self, connection, table, item_id, document):
        if table not in {"assignments", "conflicts", "resolutions"}:
            malformed("Invalid internal document table.")
        connection.execute(f"INSERT INTO {table}(id,document,document_hash) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document,document_hash=excluded.document_hash",
                           (item_id, canonical(document), digest(document)))

    def _documents(self, connection, table):
        return [self._document(connection, table, row[0]) for row in connection.execute(f"SELECT id FROM {table} ORDER BY rowid")]

    def _snapshot(self, connection, revision):
        if type(revision) is not int or revision < 0:
            malformed("Snapshot revision must be a nonnegative integer.")
        row = connection.execute("SELECT * FROM snapshots WHERE revision=?", (revision,)).fetchone()
        if not row:
            rejected("Unknown or future accepted revision.")
        files = validate_files(json.loads(row["files_json"]))
        facts = json.loads(row["facts_json"])
        if files_hash(files) != row["files_hash"] or digest(facts) != row["facts_hash"]:
            malformed("Accepted snapshot failed content hash verification.")
        return files, facts, row["files_hash"]

    def _events(self, connection, *, after_seq=None, limit=100):
        """Verify the entire chain, retaining only a contiguous requested page."""
        previous = ""
        events = []
        total = used_bytes = 0
        collecting = after_seq is not None
        for sequence, row in enumerate(connection.execute("SELECT * FROM events ORDER BY seq"), 1):
            value = json.loads(row["event_json"])
            calculated = hashlib.sha256((previous + canonical(value)).encode("utf-8")).hexdigest()
            if row["seq"] != sequence or row["previous_hash"] != previous or row["event_hash"] != calculated:
                malformed("Coordinator event history failed chain verification.")
            previous = calculated
            total = sequence
            if collecting and sequence > after_seq:
                item = {"sequence": sequence, **value}
                item_bytes = len(canonical(item).encode("utf-8")) + 1
                if len(events) >= limit or (events and used_bytes + item_bytes > EVENT_PAGE_BYTES):
                    collecting = False
                else:
                    # A single historical event can exceed the normal page budget.
                    # Preserve it exactly, reserving room for the response envelope.
                    if item_bytes > MAX_RESPONSE_BYTES - 4096:
                        rejected("One historical event exceeds the response envelope; inspect the preserved local database.")
                    events.append(item)
                    used_bytes += item_bytes
        if after_seq is None:
            return total
        cursor = events[-1]["sequence"] if events else after_seq
        return {"events": events, "next_after_seq": cursor, "has_more": total > cursor,
                "page_byte_budget": EVENT_PAGE_BYTES}

    def _event(self, connection, actor, operation, payload, revision):
        self._events(connection)
        row = connection.execute("SELECT event_hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
        previous = row[0] if row else ""
        document = {"event_id": str(uuid.uuid4()), "actor": actor, "operation": operation,
                    "timestamp": timestamp(), "revision": revision, "data": payload}
        hashed = hashlib.sha256((previous + canonical(document)).encode("utf-8")).hexdigest()
        connection.execute("INSERT INTO events(event_json,event_hash,previous_hash) VALUES(?,?,?)", (canonical(document), hashed, previous))

    def _proposal(self, connection, proposal_id):
        row = connection.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if not row:
            rejected("Unknown proposal identity.")
        result = dict(row)
        request = json.loads(result.pop("request_json"))
        if digest(request) != result["request_hash"]:
            malformed("Stored proposal bytes failed hash verification.")
        state = {key: result[key] for key in ("id", "actor", "assignment_id", "base_revision", "request_hash", "status", "accepted_revision")}
        if digest(state) != result.pop("state_hash"):
            malformed("Stored proposal state failed hash verification.")
        return {**request, **result, "proposal_id": result["id"]}

    def _proposal_state(self, connection, proposal_id, status, revision=None):
        proposal = self._proposal(connection, proposal_id)
        state = {key: proposal[key] for key in ("id", "actor", "assignment_id", "base_revision", "request_hash")}
        state.update(status=status, accepted_revision=revision)
        connection.execute("UPDATE proposals SET status=?,accepted_revision=?,state_hash=? WHERE id=?",
                           (status, revision, digest(state), proposal_id))

    @staticmethod
    def _page(payload, cursor="offset"):
        offset, limit = payload.get(cursor, 0), payload.get("limit", 100)
        if type(offset) is not int or not 0 <= offset <= 9223372036854775807:
            malformed(f"{cursor} must be a nonnegative SQLite-range integer.")
        if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
            malformed(f"limit must be an integer from 1 to {MAX_PAGE_SIZE}.")
        return offset, limit

    @staticmethod
    def _evidence_summary(value):
        return {"count": len(value) if isinstance(value, list) else 1, "sha256": digest(value)}

    @staticmethod
    def _conflict_summary(document):
        keys = ("conflict_id", "proposal_id", "assignment_id", "status", "revision", "kind",
                "path", "key", "responsible_owner", "resolution")
        return {**{key: document[key] for key in keys if key in document},
                "detail_hash": digest(document), "details_available": True}

    @staticmethod
    def _assignment_summary(document):
        keys = ("assignment_id", "actor", "integration_owner", "base_revision", "status")
        result = {key: document[key] for key in keys}
        result.update({key + "_count": len(document.get(key, []))
                       for key in ("targets", "criteria", "dependencies", "handoffs")})
        result.update(detail_hash=digest(document), details_available=True)
        return result

    def _proposal_summary(self, document):
        keys = ("id", "proposal_id", "actor", "assignment_id", "base_revision", "request_hash", "status", "accepted_revision")
        return {**{key: document[key] for key in keys}, "change_count": len(document["changes"]),
                "changed_bytes": sum(len(value.encode("utf-8")) for value in document["changes"].values() if value is not None),
                "claim_count": len(document.get("claims", [])),
                "evidence_summary": self._evidence_summary(document["evidence"]), "details_available": True}

    def _status(self, connection, state, offset=0, limit=100):
        _, _, hashed = self._snapshot(connection, state["revision"])
        self._events(connection)
        members = []
        for row in connection.execute("SELECT actor,human,agent,role,active FROM members ORDER BY actor LIMIT ? OFFSET ?", (limit, offset)):
            member = dict(row)
            member["active"] = bool(member["active"])
            for key in ("human", "agent"):
                member[key + "_truncated"] = len(member[key]) > 256
                member[key] = member[key][:256]
            members.append(member)
        collections = {"members": members}
        for table, summarizer in (("assignments", self._assignment_summary), ("proposals", self._proposal_summary),
                                  ("conflicts", self._conflict_summary)):
            collections[table] = []
            for row in connection.execute(f"SELECT id FROM {table} ORDER BY rowid LIMIT ? OFFSET ?", (limit, offset)):
                document = self._proposal(connection, row[0]) if table == "proposals" else self._document(connection, table, row[0])
                collections[table].append(summarizer(document))
        totals = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in collections}
        next_offsets = {table: offset + len(items) if offset + len(items) < totals[table] else None
                        for table, items in collections.items()}
        return {**state, "files_hash": hashed, **collections,
                "paging": {"offset": offset, "limit": limit, "totals": totals, "next_offsets": next_offsets}}

    def initialize(self, project_id, owner, token, files):
        try:
            if str(uuid.UUID(project_id)) != project_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            malformed("Project identity must be a canonical UUID.")
        fields(owner, {"actor", "human", "agent"})
        actor = identifier(owner["actor"], "actor")
        human, agent = text(owner["human"], "human"), text(owner["agent"], "agent")
        hashed_token = self._token(token)
        files = validate_files(files)
        connection = None
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._safe_db_path(self.db_path)
            try:
                descriptor = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            except FileExistsError:
                rejected("Coordinator state already exists; initialization cannot replace it.")
            os.close(descriptor)
            connection = self._connect()
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("BEGIN IMMEDIATE")
            statements = ["CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)",
                          "CREATE TABLE members(actor TEXT PRIMARY KEY COLLATE NOCASE,human TEXT NOT NULL,agent TEXT NOT NULL,role TEXT NOT NULL,token_hash TEXT UNIQUE NOT NULL,active INTEGER NOT NULL)",
                          "CREATE TABLE snapshots(revision INTEGER PRIMARY KEY,files_json TEXT NOT NULL,files_hash TEXT NOT NULL,facts_json TEXT NOT NULL,facts_hash TEXT NOT NULL)",
                          "CREATE TABLE proposals(id TEXT PRIMARY KEY COLLATE NOCASE,actor TEXT NOT NULL,assignment_id TEXT NOT NULL,base_revision INTEGER NOT NULL,request_json TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,accepted_revision INTEGER,state_hash TEXT NOT NULL)",
                          "CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,event_json TEXT NOT NULL,event_hash TEXT NOT NULL,previous_hash TEXT NOT NULL)"]
            statements += [f"CREATE TABLE {name}(id TEXT PRIMARY KEY COLLATE NOCASE,document TEXT NOT NULL,document_hash TEXT NOT NULL)" for name in ("assignments", "conflicts", "resolutions")]
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            state = {"project_id": project_id, "revision": 0}
            connection.execute("INSERT INTO meta VALUES('state',?)", (canonical(state),))
            connection.execute("INSERT INTO members VALUES(?,?,?,?,?,1)", (actor, human, agent, "owner", hashed_token))
            connection.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)", (0, canonical(files), files_hash(files), "{}", digest({})))
            self._event(connection, actor, "initialize", {"project_id": project_id, "files_hash": files_hash(files)}, 0)
            result = self._status(connection, state)
            connection.commit()
            return result
        except ProductError:
            if connection:
                connection.rollback()
            raise
        except (OSError, sqlite3.Error) as exc:
            if connection:
                connection.rollback()
            raise ProductError(5, "engine_environment", "Coordinator initialization could not complete; preserve partial state for inspection.") from exc
        finally:
            if connection:
                connection.close()

    def request(self, token, operation, payload):
        if not isinstance(operation, str) or operation not in OPERATIONS or not isinstance(payload, dict):
            malformed("Unknown coordinator operation or invalid payload.")
        if len(canonical(payload).encode("utf-8")) > MAX_RESPONSE_BYTES:
            malformed("Request exceeds the 128 MiB envelope limit.")
        connection = None
        try:
            connection = self._connect(readonly=operation in READ_OPERATIONS)
            connection.execute("BEGIN" if operation in READ_OPERATIONS else "BEGIN IMMEDIATE")
            state = self._schema(connection)
            member = self._auth(connection, token)
            if operation not in READ_OPERATIONS and member["role"] == "reader":
                rejected("Read-only members cannot mutate coordinator state.")
            self._events(connection)
            result = getattr(self, "_op_" + operation.replace("-", "_"))(connection, state, member, payload)
            if len(canonical(result).encode("utf-8")) > MAX_RESPONSE_BYTES:
                rejected("Response exceeds 128 MiB; use a bounded snapshot or revise the workload.")
            connection.commit()
            return result
        except ProductError:
            if connection:
                connection.rollback()
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeError) as exc:
            if connection:
                connection.rollback()
            raise ProductError(3, "engine_invalid", "Stored coordinator data is malformed; no repair was attempted.") from exc
        except (OSError, sqlite3.Error) as exc:
            if connection:
                connection.rollback()
            raise ProductError(5, "engine_environment", "Coordinator IO or transaction failed; the operation was rolled back.") from exc
        finally:
            if connection:
                connection.close()

    def recover(self):
        """Local-host maintenance, deliberately absent from request operations.

        SQLite rolls back a hot journal when this writable connection opens its
        transaction. Accepted logical state is verified, never repaired or merged.
        """
        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                malformed("Coordinator database failed SQLite integrity checks; preserve it for recovery review.")
            state = self._schema(connection)
            _, _, hashed = self._snapshot(connection, state["revision"])
            events = self._events(connection)
            for table in ("assignments", "conflicts", "resolutions"):
                for row in connection.execute(f"SELECT id FROM {table}"):
                    self._document(connection, table, row[0])
            proposals = 0
            for row in connection.execute("SELECT id FROM proposals"):
                self._proposal(connection, row[0])
                proposals += 1
            connection.commit()
            return {**state, "files_hash": hashed, "status": "recovered", "logical_state_changed": False,
                    "events_verified": events, "proposals_verified": proposals,
                    "scope": "local_host_sqlite_journal_recovery"}
        except ProductError:
            if connection:
                connection.rollback()
            raise
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeError) as exc:
            if connection:
                connection.rollback()
            raise ProductError(3, "engine_invalid", "Stored coordinator data failed recovery verification; no logical repair was attempted.") from exc
        except (OSError, sqlite3.Error) as exc:
            if connection:
                connection.rollback()
            raise ProductError(5, "engine_environment", "Local SQLite recovery could not complete; preserve the database and journal for inspection.") from exc
        finally:
            if connection:
                connection.close()

    def _op_status(self, connection, state, member, payload):
        fields(payload, set(), {"offset", "limit"})
        offset, limit = self._page(payload)
        return self._status(connection, state, offset, limit)

    def _op_snapshot(self, connection, state, member, payload):
        fields(payload, set(), {"revision"})
        revision = payload.get("revision", state["revision"])
        files, _, hashed = self._snapshot(connection, revision)
        return {"project_id": state["project_id"], "revision": revision, "files": files, "files_hash": hashed}

    def _op_events(self, connection, state, member, payload):
        fields(payload, set(), {"after_seq", "limit"})
        after_seq, limit = self._page(payload, "after_seq")
        return {"project_id": state["project_id"], **self._events(connection, after_seq=after_seq, limit=limit)}

    def _op_proposal(self, connection, state, member, payload):
        fields(payload, {"proposal_id"})
        return self._proposal(connection, identifier(payload["proposal_id"], "proposal_id"))

    def _op_conflict(self, connection, state, member, payload):
        fields(payload, {"conflict_id"})
        return self._document(connection, "conflicts", identifier(payload["conflict_id"], "conflict_id"))

    def _op_assignment(self, connection, state, member, payload):
        fields(payload, {"assignment_id"})
        return self._document(connection, "assignments", identifier(payload["assignment_id"], "assignment_id"))

    def _op_facts(self, connection, state, member, payload):
        fields(payload, set(), {"offset", "limit"})
        offset, limit = self._page(payload)
        _, facts, _ = self._snapshot(connection, state["revision"])
        keys = sorted(facts)[offset:offset + limit]
        items = [{"key": key, **facts[key]} for key in keys]
        return {**state, "facts": items, "offset": offset, "limit": limit, "total": len(facts),
                "next_offset": offset + len(items) if offset + len(items) < len(facts) else None}

    def _op_member(self, connection, state, member, payload):
        fields(payload, {"actor", "human", "agent", "role", "token"})
        self._owner(connection, member["actor"])
        actor = identifier(payload["actor"], "actor")
        if payload["role"] not in {"owner", "contributor", "reader"}:
            malformed("Unknown member role.")
        token_hash = self._token(payload["token"])
        if connection.execute("SELECT 1 FROM members WHERE actor=? OR token_hash=?", (actor, token_hash)).fetchone():
            rejected("Member identity or authentication secret is already registered, including revoked history.")
        if connection.execute("SELECT count(*) FROM members").fetchone()[0] >= 1000:
            rejected("Membership limit of 1000 reached.")
        data = {key: text(payload[key], key) for key in ("human", "agent")}
        data.update(actor=actor, role=payload["role"], active=True)
        connection.execute("INSERT INTO members VALUES(?,?,?,?,?,1)", (actor, data["human"], data["agent"], data["role"], token_hash))
        self._event(connection, member["actor"], "member", data, state["revision"])
        return data

    def _op_revoke(self, connection, state, member, payload):
        fields(payload, {"actor"})
        self._owner(connection, member["actor"])
        target = self._member(connection, identifier(payload["actor"], "actor"))
        if target["role"] == "owner" and connection.execute("SELECT count(*) FROM members WHERE active=1 AND role='owner'").fetchone()[0] <= 1:
            rejected("The last active owner cannot be revoked.")
        _, facts, _ = self._snapshot(connection, state["revision"])
        if any(fact["authority"] == target["actor"] for fact in facts.values()):
            rejected("Transfer current factual authority explicitly before revoking this owner.")
        if any(item["status"] != "completed" and item["integration_owner"] == target["actor"]
               for item in self._documents(connection, "assignments")):
            rejected("Transfer active integration responsibilities before revoking this owner.")
        connection.execute("UPDATE members SET active=0 WHERE actor=?", (target["actor"],))
        data = {"actor": target["actor"], "active": False}
        self._event(connection, member["actor"], "revoke", data, state["revision"])
        return data

    def _op_transfer_authority(self, connection, state, member, payload):
        fields(payload, {"key", "to_actor", "evidence", "reason"})
        key = text(payload["key"], "fact key", maximum=256)
        current, facts, hashed = self._snapshot(connection, state["revision"])
        self._owner(connection, member["actor"])
        if key not in facts or facts[key]["authority"] != member["actor"]:
            rejected("Only the current authenticated factual authority can transfer its responsibility.")
        recipient = self._owner(connection, identifier(payload["to_actor"], "to_actor"))
        if recipient["actor"] == member["actor"]:
            rejected("Factual authority transfer requires a different active owner.")
        proof, reason = evidence(payload["evidence"]), text(payload["reason"], "authority transfer reason")
        before = dict(facts[key])
        facts[key] = {**before, "authority": recipient["actor"]}
        state = {**state, "revision": state["revision"] + 1}
        connection.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)", (state["revision"], canonical(current), hashed, canonical(facts), digest(facts)))
        connection.execute("UPDATE meta SET value=? WHERE key='state'", (canonical(state),))
        data = {"key": key, "from_actor": member["actor"], "to_actor": recipient["actor"], "fact": facts[key],
                "previous_fact_hash": digest(before), "evidence": proof, "reason": reason, "revision": state["revision"], "files_hash": hashed}
        self._event(connection, member["actor"], "transfer-authority", data, state["revision"])
        return data

    def _op_transfer_integration(self, connection, state, member, payload):
        fields(payload, {"assignment_id", "to_actor", "reason"})
        assignment = self._document(connection, "assignments", identifier(payload["assignment_id"]))
        self._owner(connection, member["actor"])
        if assignment["integration_owner"] != member["actor"] or assignment["status"] == "completed":
            rejected("Only the current integration owner can transfer an active assignment's integration responsibility.")
        recipient = self._owner(connection, identifier(payload["to_actor"], "to_actor"))
        if recipient["actor"] == member["actor"]:
            rejected("Integration transfer requires a different active owner.")
        reason = text(payload["reason"], "integration transfer reason")
        assignment["integration_owner"] = recipient["actor"]
        self._put(connection, "assignments", assignment["assignment_id"], assignment)
        self._event(connection, member["actor"], "transfer-integration",
                    {"assignment_id": assignment["assignment_id"], "from_actor": member["actor"], "to_actor": recipient["actor"], "reason": reason}, state["revision"])
        return assignment

    def _op_claim(self, connection, state, member, payload):
        fields(payload, {"assignment_id", "targets", "criteria", "dependencies", "resource_limits", "integration_owner"})
        assignment_id = identifier(payload["assignment_id"], "assignment_id")
        if connection.execute("SELECT 1 FROM assignments WHERE id=?", (assignment_id,)).fetchone():
            rejected("Assignment identity already exists.")
        if not isinstance(payload["targets"], list) or not 1 <= len(payload["targets"]) <= 200:
            malformed("Assignments require 1–200 targets.")
        targets = [validate_path(value, target=True) for value in payload["targets"]]
        if len({value.casefold() for value in targets}) != len(targets):
            malformed("Assignment targets contain duplicate/case-colliding names.")
        def overlap(a, b):
            a, b = a.rstrip("/").casefold(), b.rstrip("/").casefold()
            return a == "." or b == "." or a == b or a.startswith(b + "/") or b.startswith(a + "/")
        for assignment in self._documents(connection, "assignments"):
            if assignment["status"] != "completed" and any(overlap(a, b) for a in targets for b in assignment["targets"]):
                rejected("Targets overlap an active assignment.")
        criteria = payload["criteria"]
        if not isinstance(criteria, list) or not 1 <= len(criteria) <= 100:
            malformed("Assignments require 1–100 acceptance criteria.")
        criteria = [text(item, "criterion") for item in criteria]
        dependencies = payload["dependencies"]
        if not isinstance(dependencies, list) or len(dependencies) > 100:
            malformed("Assignment dependencies must be a list of at most 100 identities.")
        for dependency in dependencies:
            if self._document(connection, "assignments", identifier(dependency))["status"] != "completed":
                rejected("Dependencies must refer to completed assignments.")
        limits = payload["resource_limits"]
        if not isinstance(limits, dict) or len(canonical(limits).encode()) > 65536:
            malformed("Resource limits must be a bounded JSON object.")
        for key, ceiling in (("max_proposals", MAX_PROPOSALS), ("max_files", MAX_FILES), ("max_bytes", MAX_SNAPSHOT_BYTES)):
            if key in limits and (type(limits[key]) is not int or not 1 <= limits[key] <= ceiling):
                malformed(f"Resource limit {key} must be a positive integer at most {ceiling}.")
        integration_owner = self._owner(connection, identifier(payload["integration_owner"], "integration_owner"))["actor"]
        data = {"assignment_id": assignment_id, "actor": member["actor"], "human": member["human"], "agent": member["agent"],
                "targets": targets, "criteria": criteria, "dependencies": dependencies, "resource_limits": limits,
                "unenforced_resource_limits": sorted(set(limits) - {"max_proposals", "max_files", "max_bytes"}),
                "integration_owner": integration_owner, "base_revision": state["revision"], "status": "active", "handoffs": []}
        self._put(connection, "assignments", assignment_id, data)
        self._event(connection, member["actor"], "claim", data, state["revision"])
        return data

    def _claims(self, connection, claims):
        if not isinstance(claims, list) or len(claims) > 100:
            malformed("Semantic claims must be a list of at most 100 facts.")
        result = []
        seen = set()
        for claim in claims:
            fields(claim, {"key", "value", "source", "authority"})
            key = text(claim["key"], "fact key", maximum=256)
            if key in seen:
                malformed("A proposal cannot contain duplicate semantic keys.")
            seen.add(key)
            result.append({"key": key, "value": text(claim["value"], "fact value", empty=True),
                           "source": text(claim["source"], "fact source"),
                           "authority": self._owner(connection, identifier(claim["authority"], "authority"))["actor"]})
        return result

    def _op_propose(self, connection, state, member, payload):
        fields(payload, {"proposal_id", "base_revision", "changes", "evidence", "assignment_id"}, {"claims"})
        proposal_id = identifier(payload["proposal_id"], "proposal_id")
        assignment_id = identifier(payload["assignment_id"], "assignment_id")
        proposal_request = {**payload, "claims": payload.get("claims", [])}
        existing = connection.execute("SELECT id FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if existing:
            previous = self._proposal(connection, existing[0])
            if previous["actor"] != member["actor"] or previous["request_hash"] != digest(proposal_request):
                rejected("Proposal identity reuse with different bytes or actor is forbidden.")
            return previous
        assignment = self._document(connection, "assignments", assignment_id)
        if assignment["actor"] != member["actor"] or assignment["status"] != "active":
            rejected("Only the active assigned actor with received ownership may propose.")
        base_revision = payload["base_revision"]
        base_files, _, _ = self._snapshot(connection, base_revision)
        if base_revision < assignment["base_revision"]:
            rejected("Proposal base predates this assignment's accepted starting context.")
        changes = payload["changes"]
        if not isinstance(changes, dict) or len(changes) > MAX_FILES:
            malformed("Proposal changes must be a bounded path-to-content map.")
        for path, content in changes.items():
            validate_path(path)
            if content is not None:
                text(content, "proposed content", maximum=MAX_FILE_BYTES, empty=True)
            if not any(target == "." or (target.endswith("/") and path.startswith(target)) or path == target for target in assignment["targets"]):
                rejected("Proposed path is outside assignment targets.")
        path_inventory(changes)
        claims = self._claims(connection, proposal_request["claims"])
        if not changes and not claims:
            malformed("A proposal must change files or include explicit semantic claims.")
        proposal_request["evidence"] = evidence(payload["evidence"])
        proposal_request["claims"] = claims
        resulting = dict(base_files)
        for path, content in changes.items():
            if content is None:
                resulting.pop(path, None)
            else:
                resulting[path] = content
        validate_files(resulting)
        limits = assignment["resource_limits"]
        count = connection.execute("SELECT count(*) FROM proposals WHERE assignment_id=?", (assignment_id,)).fetchone()[0]
        if count >= limits.get("max_proposals", MAX_PROPOSALS):
            rejected("Assignment proposal budget is exhausted.")
        if len(changes) > limits.get("max_files", MAX_FILES) or sum(len(value.encode()) for value in changes.values() if value is not None) > limits.get("max_bytes", MAX_SNAPSHOT_BYTES):
            rejected("Proposal exceeds the assignment's declared file/byte budget.")
        hashed = digest(proposal_request)
        record = {"id": proposal_id, "actor": member["actor"], "assignment_id": assignment_id, "base_revision": base_revision,
                  "request_hash": hashed, "status": "pending", "accepted_revision": None}
        connection.execute("INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?)", (proposal_id, member["actor"], assignment_id,
                           base_revision, canonical(proposal_request), hashed, "pending", None, digest(record)))
        self._event(connection, member["actor"], "propose", {"proposal_id": proposal_id, "request_hash": hashed}, state["revision"])
        return self._proposal(connection, proposal_id)

    def _integration(self, connection, member, proposal):
        assignment = self._document(connection, "assignments", proposal["assignment_id"])
        self._owner(connection, member["actor"])
        if member["actor"] != assignment["integration_owner"]:
            rejected("Only this assignment's integration owner may make the acceptance decision.")
        return assignment

    def _resolution(self, connection, state, member, proposal, resolutions):
        if not isinstance(resolutions, list) or not 1 <= len(resolutions) <= 100:
            malformed("Resolutions require 1–100 explicit owner decisions.")
        _, facts, _ = self._snapshot(connection, state["revision"])
        proposed = {claim["key"]: claim for claim in proposal["claims"]}
        decisions = []
        for resolution in resolutions:
            fields(resolution, {"key", "value", "source", "reason", "authority"})
            key = text(resolution["key"], "resolution key", maximum=256)
            if key not in proposed or key not in facts:
                rejected("Resolution must refer to an existing disputed fact in this proposal.")
            responsible = self._owner(connection, facts[key]["authority"])["actor"]
            if member["actor"] != responsible or resolution["authority"] != responsible:
                rejected("Only the authenticated responsible fact owner may record its resolution.")
            data = {"proposal_id": proposal["id"], "key": key, "value": text(resolution["value"], "resolution value", empty=True),
                    "source": text(resolution["source"], "resolution source"), "reason": text(resolution["reason"], "resolution reason"),
                    "authority": responsible, "fact_hash": digest(facts[key]), "request_hash": proposal["request_hash"], "revision": state["revision"]}
            decision_id = digest({"proposal_id": proposal["id"], "key": key, "fact_hash": data["fact_hash"]})
            existing = connection.execute("SELECT id FROM resolutions WHERE id=?", (decision_id,)).fetchone()
            if existing:
                if self._document(connection, "resolutions", decision_id) != data:
                    rejected("An immutable factual decision already exists; submit a new reviewed proposal to supersede it.")
            else:
                self._put(connection, "resolutions", decision_id, data)
                self._event(connection, member["actor"], "resolve", data, state["revision"])
            decisions.append(data)
        return decisions

    def _op_resolve(self, connection, state, member, payload):
        fields(payload, {"proposal_id", "resolutions"})
        proposal = self._proposal(connection, identifier(payload["proposal_id"]))
        if proposal["status"] not in {"pending", "conflict"}:
            rejected("Only an unresolved proposal may receive a factual decision.")
        return {"proposal_id": proposal["id"], "decisions": self._resolution(connection, state, member, proposal, payload["resolutions"])}

    def _clear_conflicts(self, connection, proposal_id, resolution):
        for conflict in self._documents(connection, "conflicts"):
            if conflict["proposal_id"] == proposal_id and conflict["status"] == "unresolved":
                conflict.update(status="resolved", resolution=resolution)
                self._put(connection, "conflicts", conflict["conflict_id"], conflict)

    def _op_accept(self, connection, state, member, payload):
        fields(payload, {"proposal_id", "validation", "reason"}, {"resolutions"})
        validation, reason = text(payload["validation"], "validation"), text(payload["reason"], "acceptance reason")
        proposal = self._proposal(connection, identifier(payload["proposal_id"]))
        assignment = self._integration(connection, member, proposal)
        if proposal["status"] in {"accepted", "deduplicated"}:
            _, _, hashed = self._snapshot(connection, proposal["accepted_revision"])
            return {"proposal_id": proposal["id"], "status": proposal["status"], "accepted": True,
                    "revision": proposal["accepted_revision"], "files_hash": hashed, "idempotent": True}
        if proposal["status"] not in {"pending", "conflict"} or assignment["status"] == "completed":
            rejected("Proposal is no longer eligible for acceptance.")
        current, facts, current_hash = self._snapshot(connection, state["revision"])
        base, _, _ = self._snapshot(connection, proposal["base_revision"])
        if payload.get("resolutions"):
            self._resolution(connection, state, member, proposal, payload["resolutions"])
        conflicts = []
        resulting = dict(current)
        for path, content in proposal["changes"].items():
            if current.get(path) != content and current.get(path) != base.get(path):
                conflicts.append({"kind": "file", "path": path, "base": base.get(path), "accepted": current.get(path), "proposed": content})
            if content is None:
                resulting.pop(path, None)
            else:
                resulting[path] = content
        next_facts = dict(facts)
        for claim in proposal["claims"]:
            key = claim["key"]
            previous = facts.get(key)
            self._owner(connection, claim["authority"])
            if previous and (claim["value"] != previous["value"] or claim["authority"] != previous["authority"]):
                decision_id = digest({"proposal_id": proposal["id"], "key": key, "fact_hash": digest(previous)})
                row = connection.execute("SELECT id FROM resolutions WHERE id=?", (decision_id,)).fetchone()
                decision = self._document(connection, "resolutions", decision_id) if row else None
                if (not decision or decision["request_hash"] != proposal["request_hash"] or decision["value"] != claim["value"]
                        or decision["authority"] != previous["authority"]):
                    conflicts.append({"kind": "semantic", "key": key, "accepted": previous, "proposed": claim,
                                      "responsible_owner": previous["authority"]})
                    continue
                self._owner(connection, decision["authority"])
                next_facts[key] = {"key": key, "value": decision["value"], "source": decision["source"], "authority": previous["authority"]}
            elif previous:
                next_facts[key] = previous
            else:
                next_facts[key] = claim
        try:
            validate_files(resulting)
        except ProductError as exc:
            conflicts.append({"kind": "portable_path", "detail": str(exc)})
        if conflicts:
            stored = []
            for details in conflicts:
                conflict_id = digest({"proposal_id": proposal["id"], "revision": state["revision"], **details})
                data = {"conflict_id": conflict_id, "proposal_id": proposal["id"], "assignment_id": proposal["assignment_id"],
                        "status": "unresolved", "revision": state["revision"], **details}
                self._put(connection, "conflicts", conflict_id, data)
                stored.append(self._conflict_summary(data))
            self._proposal_state(connection, proposal["id"], "conflict")
            self._event(connection, member["actor"], "conflict", {"proposal_id": proposal["id"], "conflicts": stored,
                        "validation": validation, "reason": reason}, state["revision"])
            return {"proposal_id": proposal["id"], "status": "conflict", "accepted": False, "revision": state["revision"],
                    "files_hash": current_hash, "conflicts": stored}
        deduplicated = resulting == current and next_facts == facts
        if not deduplicated:
            state = {**state, "revision": state["revision"] + 1}
            connection.execute("INSERT INTO snapshots VALUES(?,?,?,?,?)", (state["revision"], canonical(resulting), files_hash(resulting), canonical(next_facts), digest(next_facts)))
            connection.execute("UPDATE meta SET value=? WHERE key='state'", (canonical(state),))
        status = "deduplicated" if deduplicated else "accepted"
        self._proposal_state(connection, proposal["id"], status, state["revision"])
        self._clear_conflicts(connection, proposal["id"], "accepted after explicit review")
        self._event(connection, member["actor"], "accept", {"proposal_id": proposal["id"], "status": status, "validation": validation,
                    "reason": reason, "files_hash": files_hash(resulting)}, state["revision"])
        return {"proposal_id": proposal["id"], "status": status, "accepted": True, "revision": state["revision"],
                "files_hash": files_hash(resulting), "rebased": proposal["base_revision"] < state["revision"] - (0 if deduplicated else 1)}

    def _op_reject(self, connection, state, member, payload):
        fields(payload, {"proposal_id", "reason"})
        proposal = self._proposal(connection, identifier(payload["proposal_id"]))
        self._integration(connection, member, proposal)
        reason = text(payload["reason"], "rejection reason")
        if proposal["status"] not in {"pending", "conflict"}:
            rejected("Only unresolved proposals can be rejected.")
        self._proposal_state(connection, proposal["id"], "rejected")
        self._clear_conflicts(connection, proposal["id"], "rejected by integration owner")
        self._event(connection, member["actor"], "reject", {"proposal_id": proposal["id"], "reason": reason}, state["revision"])
        return self._proposal(connection, proposal["id"])

    def _op_supersede(self, connection, state, member, payload):
        fields(payload, {"proposal_id", "replacement_id", "reason"})
        proposal = self._proposal(connection, identifier(payload["proposal_id"]))
        replacement = self._proposal(connection, identifier(payload["replacement_id"]))
        self._integration(connection, member, proposal)
        reason = text(payload["reason"], "supersession reason")
        if (proposal["status"] not in {"pending", "conflict"} or replacement["status"] not in {"accepted", "deduplicated"}
                or proposal["assignment_id"] != replacement["assignment_id"]):
            rejected("Supersession requires an unresolved proposal and accepted replacement in the same assignment.")
        self._proposal_state(connection, proposal["id"], "superseded")
        self._clear_conflicts(connection, proposal["id"], "superseded by " + replacement["id"])
        self._event(connection, member["actor"], "supersede", {"proposal_id": proposal["id"], "replacement_id": replacement["id"], "reason": reason}, state["revision"])
        return self._proposal(connection, proposal["id"])

    def _op_handoff(self, connection, state, member, payload):
        fields(payload, {"assignment_id", "to_actor", "summary"})
        assignment = self._document(connection, "assignments", identifier(payload["assignment_id"]))
        if assignment["status"] != "active" or member["actor"] not in {assignment["actor"], assignment["integration_owner"]}:
            rejected("Only the active assignee or integration owner may initiate handoff.")
        recipient = self._member(connection, identifier(payload["to_actor"], "to_actor"))
        if recipient["role"] == "reader" or recipient["actor"] == assignment["actor"]:
            rejected("Handoff requires a different active writing member.")
        if len(assignment["handoffs"]) >= 1000:
            rejected("Assignment handoff history limit reached.")
        _, _, hashed = self._snapshot(connection, state["revision"])
        handoff = {"handoff_id": str(uuid.uuid4()), "from_actor": assignment["actor"], "to_actor": recipient["actor"],
                   "summary": text(payload["summary"], "handoff summary"), "revision": state["revision"], "files_hash": hashed}
        assignment["handoffs"].append(handoff)
        assignment.update(actor=recipient["actor"], human=recipient["human"], agent=recipient["agent"], status="pending_receipt")
        self._put(connection, "assignments", assignment["assignment_id"], assignment)
        self._event(connection, member["actor"], "handoff", handoff, state["revision"])
        return assignment

    def _receipt(self, connection, state, payload):
        _, _, hashed = self._snapshot(connection, state["revision"])
        if type(payload["revision"]) is not int or payload["revision"] != state["revision"] or payload["files_hash"] != hashed:
            rejected("Receipt must match the exact CURRENT accepted revision and content hash.")
        return hashed

    def _op_receive(self, connection, state, member, payload):
        fields(payload, {"assignment_id", "revision", "files_hash"})
        assignment = self._document(connection, "assignments", identifier(payload["assignment_id"]))
        if assignment["actor"] != member["actor"] or assignment["status"] != "pending_receipt":
            rejected("Only the intended pending recipient may receive this assignment.")
        self._receipt(connection, state, payload)
        assignment.update(status="active", receipt={"actor": member["actor"], "revision": payload["revision"], "files_hash": payload["files_hash"]})
        self._put(connection, "assignments", assignment["assignment_id"], assignment)
        self._event(connection, member["actor"], "receive", payload, state["revision"])
        return assignment

    def _op_complete(self, connection, state, member, payload):
        fields(payload, {"assignment_id", "revision", "files_hash", "evidence"})
        assignment = self._document(connection, "assignments", identifier(payload["assignment_id"]))
        if assignment["actor"] != member["actor"] or assignment["status"] != "active":
            rejected("Only the active assigned actor with received ownership may complete work.")
        self._receipt(connection, state, payload)
        proof = evidence(payload["evidence"])
        for row in connection.execute("SELECT id FROM proposals WHERE assignment_id=?", (assignment["assignment_id"],)):
            if self._proposal(connection, row[0])["status"] in {"pending", "conflict"}:
                rejected("Unresolved proposals prevent completion.")
        if any(item["assignment_id"] == assignment["assignment_id"] and item["status"] == "unresolved" for item in self._documents(connection, "conflicts")):
            rejected("Unresolved conflicts prevent completion.")
        assignment.update(status="completed", completion={"revision": payload["revision"], "files_hash": payload["files_hash"], "evidence": proof})
        self._put(connection, "assignments", assignment["assignment_id"], assignment)
        self._event(connection, member["actor"], "complete", {"assignment_id": assignment["assignment_id"], **assignment["completion"]}, state["revision"])
        return assignment
