"""Owner/recipient CLI workflows for the authoritative engine."""
from __future__ import annotations

import hashlib
import contextlib
from contextlib import contextmanager
import json
import os
from pathlib import Path
import secrets
import sqlite3
import tempfile
import time
import uuid

from . import PRODUCT_VERSION
from .errors import ProductError
from .providers import PROVIDERS, capabilities, verify_receipt
from .transport import LocalTransport, HTTPTransport, read_token, serve

MANIFEST = ".shared-memory.json"
TEAM_COMMANDS = ("init", "attach", "refresh", "draft", "submit", "receipt", "team-status",
                 "coord", "member-add", "team-prompt", "serve", "providers", "provider-check", "promote-draft", "context")


def add_commands(commands):
    init = commands.add_parser("init", help="Initialize an authoritative project in an existing selected folder")
    init.add_argument("project")
    init.add_argument("--state-dir", required=True)
    for field in ("person", "actor", "agent", "purpose"):
        init.add_argument("--" + field, required=True)
    init.add_argument("--mode", choices=("local", "team"), default="local")
    init.add_argument("--provider", choices=PROVIDERS, default="local")
    init.add_argument("--include", action="append", help="Explicit relative UTF8 file; default all project Markdown outside protected directories")
    init.add_argument("--coordination-file", help="Explicit schema 2 person/agent identity and policy JSON; omission preserves schema 1")
    attach = commands.add_parser("attach", help="Attach a recipient to an existing authoritative project")
    attach.add_argument("project")
    attach.add_argument("--state-dir", required=True)
    attach.add_argument("--expected-project-id", required=True)
    route = attach.add_mutually_exclusive_group(required=True)
    route.add_argument("--endpoint")
    route.add_argument("--database", help="Same-machine authority only; never a network/sync database")
    attach.add_argument("--token-file", required=True)
    attach.add_argument("--ca-file")
    attach.add_argument("--provider", choices=PROVIDERS, default="local")
    for name in ("refresh", "draft", "submit", "receipt", "team-status", "coord", "member-add", "team-prompt", "provider-check", "promote-draft", "context"):
        command = commands.add_parser(name)
        command.add_argument("project")
        command.add_argument("--state-dir", required=True)
        command.add_argument("--session-token-file", help="Private credential for this running session; never substitutes a payload identity")
        if name in {"draft", "promote-draft"}:
            command.add_argument("--proposal-id", required=True)
            command.add_argument("--assignment-id", required=True)
            command.add_argument("--evidence", required=True)
            command.add_argument("--claims-file")
            command.add_argument("--coordination-file", help="Immutable session/generation/policy/input context recorded with this draft")
            if name == "promote-draft":
                command.add_argument("--preserved-id", required=True)
        if name == "context":
            command.add_argument("--query", required=True)
            command.add_argument("--limit", type=int, default=8)
        if name == "submit":
            command.add_argument("--proposal-id", required=True)
        if name == "coord":
            command.add_argument("operation")
            command.add_argument("--payload-file", help="JSON object; avoids shell interpolation and command-line secrets")
        if name == "member-add":
            for field in ("actor", "person", "agent", "token-output"):
                command.add_argument("--" + field, required=True)
            command.add_argument("--role", choices=("owner", "contributor", "reader"), default="contributor")
        if name == "team-prompt":
            command.add_argument("--package-locator")
            command.add_argument("--access-locator")
        if name == "provider-check":
            command.add_argument("--account-type", default="unspecified")
    server = commands.add_parser("serve", help="Run the optional authenticated coordinator; TLS required beyond loopback")
    server.add_argument("--database", required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    server.add_argument("--certfile")
    server.add_argument("--keyfile")
    provider = commands.add_parser("providers", help="Explicit OS/provider scope, without configuring access")
    provider.add_argument("--provider", choices=PROVIDERS)
    provider.add_argument("--account-type", default="unspecified")


def private_path(value, project=None):
    raw = Path(value).expanduser().absolute()
    # macOS system /tmp and /var aliases are resolved, but user-controlled links
    # anywhere else are not accepted for credentials or private transactional state.
    for path in (raw, *raw.parents):
        if path.is_symlink() and str(path) not in {"/tmp", "/var", "/etc"}:
            raise ProductError(3, "state_path_unsafe", "Private state cannot use symbolic links.")
    path = raw.resolve()
    lower = str(path).casefold()
    if any(marker in lower for marker in ("/cloudstorage/", "/mobile documents/", "onedrive", "googledrive", "google drive", "dropbox")) or str(path).startswith("\\\\"):
        raise ProductError(3, "state_path_unsafe", "Coordinator/client state belongs on local non-synchronized storage.")
    if project and (path == project or path.is_relative_to(project) or project.is_relative_to(path)):
        raise ProductError(3, "state_path_unsafe", "Private state and the project must be separate directory trees.")
    return path


def write_private(path, data, *, exclusive=True):
    path = Path(path)
    if path.is_symlink():
        raise ProductError(3, "state_path_unsafe", "Private files cannot be symbolic links.")
    mode = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    with os.fdopen(os.open(path, mode, 0o600), "w", encoding="utf-8") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def json_file(path):
    if not Path(path).is_file() or Path(path).is_symlink():
        raise ProductError(5, "input_missing", "A regular JSON input file is required.")
    if Path(path).stat().st_size > 128 * 1024 * 1024:
        raise ProductError(3, "input_too_large", "JSON input exceeds 128 MiB.")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def selected_root(value):
    raw = Path(value).expanduser().absolute()
    for part in (raw, *raw.parents):
        if part.is_symlink() and str(part) not in {"/tmp", "/var", "/etc"}:
            raise ProductError(3, "project_path_unsafe", "Choose the physical selected folder without symbolic links.")
    path = raw.resolve()
    if not path.is_dir():
        raise ProductError(5, "project_missing", "Choose an existing selected project folder.")
    return path


def initial_files(root, includes):
    selected = [root / name for name in includes] if includes else list(root.rglob("*.md"))
    files = {}
    for path in selected:
        if not path.is_relative_to(root):
            raise ProductError(3, "target_invalid", "Included files must remain inside the selected project.")
        relative = path.relative_to(root)
        if any(part.startswith(".") or part == "Coordination" for part in relative.parts[:-1]):
            if includes:
                raise ProductError(3, "target_invalid", "Protected hidden/legacy state cannot be imported as knowledge.")
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in path.parents if p != root.parent):
            raise ProductError(3, "target_invalid", "Included files cannot use symbolic links.")
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            raise ProductError(3, "target_invalid", "Included files must be regular UTF8 files no larger than 10 MiB.")
        files[relative.as_posix()] = path.read_bytes().decode("utf-8")
    return files


def project_manifest(root):
    data = json_file(root / MANIFEST)
    if (not isinstance(data, dict) or data.get("format_version") != 1 or data.get("protocol") != 1
            or data.get("provider") not in PROVIDERS):
        raise ProductError(3, "project_invalid", "Unsupported Shared Memory project metadata.")
    return data


def write_manifest(root, project_id, provider):
    metadata = {"format_version": 1, "protocol": 1, "project_id": project_id,
                "product_version": PRODUCT_VERSION, "provider": provider}
    path = root / MANIFEST
    if path.exists() or path.is_symlink():
        current = project_manifest(root)
        if current["project_id"] != project_id or current["provider"] != provider:
            raise ProductError(3, "project_mismatch", "Existing project identity/provider cannot be replaced while joining.")
        return current
    try:
        _publish_setup_json(path, metadata)
    except FileExistsError:
        current = project_manifest(root)
        if current["project_id"] != project_id or current["provider"] != provider:
            raise ProductError(3, "project_mismatch", "Another setup reserved this selected folder for a different project.")
        return current
    return metadata


def connect(state, token_file=None):
    if token_file is not None and not str(token_file).strip():
        raise ProductError(2, "usage_error", "An explicit credential path must not be empty.")
    credential = state / "member.token" if token_file is None else token_file
    config = json_file(state / "connection.json")
    if not isinstance(config, dict) or config.get("protocol") != 1:
        raise ProductError(3, "connection_invalid", "Unsupported private connection configuration.")
    if config.get("transport") == "local":
        return LocalTransport(config["database"], credential)
    if config.get("transport") == "https":
        return HTTPTransport(config["endpoint"], credential, config.get("ca_file"))
    raise ProductError(3, "connection_invalid", "Unknown coordinator transport.")


# Setup intent contains the original credential and source snapshot. It is private,
# immutable, hash checked, and never copied into the shared project or CLI output.
SETUP_INTENT = "setup-intent.json"
SETUP_LOCK = ".setup.lock"
SETUP_LOCK_MAGIC = b"SharedMemorySetupLock1\n"


def _setup_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _publish_setup_bytes(path, data):
    """Durably publish a complete new file without replacing an existing one."""
    from .client import _fsync_dir
    path = Path(path)
    if path.is_symlink():
        raise ProductError(3, "setup_invalid", "Setup cannot replace a symbolic link.")
    fd, temporary = tempfile.mkstemp(prefix=".setup-write-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        _fsync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
        _fsync_dir(path.parent)


def _publish_setup_json(path, value):
    _publish_setup_bytes(path, (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


@contextmanager
def _setup_lock(state):
    """OS lock survives no process; competing setup waits at most five seconds."""
    from .client import _fsync_dir
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = private_path(state / SETUP_LOCK)
    # Publish complete immutable magic before the inode can be opened/locked.
    # No contender writes through a descriptor based on a stale empty-file stat.
    if not path.exists():
        try:
            _publish_setup_bytes(path, SETUP_LOCK_MAGIC)
        except FileExistsError:
            pass  # Another contender atomically published the same lock first.
    descriptor = os.open(path, os.O_RDWR | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(descriptor, "r+b") as stream:
        deadline = time.monotonic() + 5
        acquired = False
        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                if time.monotonic() >= deadline:
                    raise ProductError(4, "setup_busy", "Another setup operation owns this private state; retry after it finishes.")
                time.sleep(0.05)
        try:
            stream.seek(0)
            magic = stream.read()
            if magic != SETUP_LOCK_MAGIC:
                raise ProductError(3, "setup_invalid", "Existing lock does not belong to Shared Memory setup.")
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _setup_binding(root, args):
    binding = {"command": args.command, "project_root": str(root), "provider": args.provider}
    if args.command == "init":
        binding.update(mode=args.mode, person=args.person, actor=args.actor, agent=args.agent,
                       purpose=args.purpose, include=args.include)
        if getattr(args, "coordination_file", None) is not None:
            from .coordination import validate_configuration
            binding["coordination"] = validate_configuration(json_file(private_path(args.coordination_file, root)))
    else:
        binding.update(project_id=args.expected_project_id, token_file=str(private_path(args.token_file, root)),
                       database=str(private_path(args.database, root)) if args.database else None,
                       endpoint=args.endpoint, ca_file=str(private_path(args.ca_file)) if args.ca_file else None)
    return binding


def _setup_connection(binding, state):
    if binding["command"] == "init":
        return {"protocol": 1, "transport": "local", "database": str(state / "coordinator.sqlite3"), "mode": binding["mode"]}
    if binding["database"]:
        return {"protocol": 1, "transport": "local", "database": binding["database"], "mode": "team"}
    return {"protocol": 1, "transport": "https", "endpoint": binding["endpoint"], "ca_file": binding["ca_file"], "mode": "team"}


def _setup_transport(connection, token_file):
    if connection["transport"] == "local":
        return LocalTransport(connection["database"], token_file)
    return HTTPTransport(connection["endpoint"], token_file, connection.get("ca_file"))


def _check_setup_state(root, state, intent, binding):
    from .client import _snapshot
    unsigned = {k: v for k, v in intent.items() if k != "intent_hash"}
    if (intent.get("schema_version") != 1 or intent.get("intent_hash") != _setup_digest(unsigned)
            or intent.get("binding") != binding):
        raise ProductError(3, "setup_mismatch", "Setup intent is invalid or inputs changed; preserve state and retry the original setup inputs.")
    _snapshot(intent["snapshot"], intent["project_id"])
    token = intent["token"]
    if not isinstance(token, str) or not 32 <= len(token) <= 512 or any(c.isspace() for c in token):
        raise ProductError(3, "setup_invalid", "Private setup credential is invalid.")
    if binding["command"] == "attach" and read_token(binding["token_file"]) != token:
        raise ProductError(3, "setup_mismatch", "Joining credential changed; setup will not replace its original membership.")
    for name in (".workspace-project.json", "Coordination"):
        if (root / name).exists() or (root / name).is_symlink():
            raise ProductError(4, "already_configured", "Legacy state requires reviewed migration; setup cannot take it over.")
    if (root / MANIFEST).exists() or (root / MANIFEST).is_symlink():
        metadata = project_manifest(root)
        if metadata["project_id"] != intent["project_id"] or metadata["provider"] != binding["provider"]:
            raise ProductError(3, "project_mismatch", "Existing folder identity differs from this setup intent.")
    token_path = private_path(state / "member.token")
    if token_path.exists() and read_token(token_path) != token:
        raise ProductError(3, "setup_mismatch", "Existing credential differs; setup will not replace it.")
    connection_path = private_path(state / "connection.json")
    if connection_path.exists() and json_file(connection_path) != _setup_connection(binding, state):
        raise ProductError(3, "setup_mismatch", "Existing connection differs; setup will not redirect it.")
    client_config = private_path(state / "client" / "client.json")
    if client_config.exists():
        config = json_file(client_config)
        if config.get("project_id") != intent["project_id"] or config.get("project_root") != str(root):
            raise ProductError(3, "setup_mismatch", "Existing client belongs to a different project or local folder.")


def _initial_authority(state, intent):
    """Build revision zero privately, then publish it atomically exactly once."""
    from .client import _fsync_dir
    from .engine import Coordinator
    final = private_path(state / "coordinator.sqlite3")
    staging = private_path(state / (".setup-authority-" + intent["project_id"] + ".sqlite3"))
    token, snapshot = intent["token"], intent["snapshot"]
    binding = intent["binding"]

    def verify(path):
        authority = Coordinator(path)
        observed = authority.request(token, "snapshot", {"revision": 0})
        if observed != snapshot:
            raise ProductError(3, "setup_mismatch", "Existing authority has a different original identity or snapshot.")
        # Authentication ties the original token to its owner. Revoked/changed
        # credentials fail instead of silently regenerating membership.
        return authority

    if final.exists():
        verify(final)
        return
    if staging.exists():
        try:
            verify(staging)
        except ProductError:
            # An interrupted initial SQLite transaction has no committed tables.
            # Recover only the task-owned staging path, preserve its blank result,
            # and never reset a database containing any committed schema/history.
            with contextlib.closing(sqlite3.connect(staging)) as connection:
                tables = connection.execute("SELECT name FROM sqlite_master").fetchall()
                version = connection.execute("PRAGMA user_version").fetchone()[0]
            if tables or version:
                raise
            recovery = private_path(state / "setup-recovery")
            recovery.mkdir(mode=0o700, exist_ok=True)
            destination = recovery / (uuid.uuid4().hex + ".sqlite3")
            os.rename(staging, destination)
            _fsync_dir(state)
            _fsync_dir(recovery)
    if not staging.exists():
        Coordinator(staging).initialize(intent["project_id"],
            {"actor": binding["actor"], "human": binding["person"], "agent": binding["agent"]}, token, snapshot["files"],
            coordination=binding.get("coordination"))
    verify(staging)
    os.link(staging, final)
    _fsync_dir(state)
    # The final hardlink remains if interrupted immediately before cleanup.
    staging.unlink()
    _fsync_dir(state)


def _setup(root, state, args):
    from .client import Client, _snapshot
    from .engine import files_hash, validate_files, identifier, text
    if args.command == "init":
        # Reject uncorrectable owner/intent values before publishing an immutable
        # setup record or creating any private state.
        identifier(args.actor, "actor")
        text(args.person, "human")
        text(args.agent, "agent")
        text(args.purpose, "purpose")
    binding = _setup_binding(root, args)
    # Reject a wrong remote/project identity before creating even a private lock.
    # Resume paths still validate their immutable intent under the lock below.
    if not (state / SETUP_INTENT).exists():
        if state.exists() and any(p.name != SETUP_LOCK and not p.name.startswith(".setup-write-") for p in state.iterdir()):
            raise ProductError(4, "state_exists", "Existing private state has no matching setup intent; preserve its existing workflow.")
        if any((root / name).exists() or (root / name).is_symlink() for name in (".workspace-project.json", "Coordination")):
            raise ProductError(4, "already_configured", "Legacy project state requires a reviewed migration.")
        if args.command == "init":
            if (root / MANIFEST).exists() or (root / MANIFEST).is_symlink():
                raise ProductError(4, "already_configured", "Existing project cannot be initialized by a new setup intent.")
        else:
            if (root / MANIFEST).exists() or (root / MANIFEST).is_symlink():
                metadata = project_manifest(root)
                if metadata["project_id"] != args.expected_project_id or metadata["provider"] != args.provider:
                    raise ProductError(3, "project_mismatch", "Owner-supplied identity/provider differs from this folder.")
            read_token(binding["token_file"])
            request = _setup_transport(_setup_connection(binding, state), binding["token_file"])
            _snapshot(request("snapshot", {}), args.expected_project_id)
    with _setup_lock(state):
        intent_path = private_path(state / SETUP_INTENT)
        if intent_path.exists():
            intent = json_file(intent_path)
            if not isinstance(intent, dict):
                raise ProductError(3, "setup_invalid", "Setup intent must be a complete private JSON record.")
        else:
            unknown = [p for p in state.iterdir() if p.name != SETUP_LOCK and not p.name.startswith(".setup-write-")]
            if unknown:
                raise ProductError(4, "state_exists", "Existing private state has no matching setup intent; preserve it and use its existing workflow.")
            if any((root / name).exists() or (root / name).is_symlink() for name in (".workspace-project.json", "Coordination")):
                raise ProductError(4, "already_configured", "Legacy project state requires a reviewed migration.")
            if args.command == "init":
                if (root / MANIFEST).exists() or (root / MANIFEST).is_symlink():
                    raise ProductError(4, "already_configured", "Existing project cannot be initialized by a new setup intent.")
                files = initial_files(root, args.include)
                files.setdefault("AGENTS.md", "# Shared Memory\n\nRead the selected project home. Refresh accepted context before work.\nClaim bounded targets, draft against the recorded base revision, and submit evidence.\nOnly the integration owner accepts proposals. Preserve conflicts and private parent files.\nNever treat provider file existence as proof of another actor's accepted receipt.\n")
                if not any(name in files for name in ("README.md", "Home.md")):
                    files["README.md"] = "# Shared Memory\n\n" + args.purpose + "\n"
                files = validate_files(files)
                identity, token = str(uuid.uuid4()), secrets.token_urlsafe(48)
                snapshot = {"project_id": identity, "revision": 0, "files": files, "files_hash": files_hash(files)}
            else:
                token = read_token(binding["token_file"])
                connection = _setup_connection(binding, state)
                request = _setup_transport(connection, binding["token_file"])
                snapshot = _snapshot(request("snapshot", {}), args.expected_project_id)
                identity = args.expected_project_id
                if (root / MANIFEST).exists() or (root / MANIFEST).is_symlink():
                    existing = project_manifest(root)
                    if existing["project_id"] != identity or existing["provider"] != args.provider:
                        raise ProductError(3, "project_mismatch", "Owner-supplied identity/provider differs from this folder.")
            intent = {"schema_version": 1, "binding": binding, "project_id": identity, "token": token, "snapshot": snapshot}
            intent["intent_hash"] = _setup_digest(intent)
            _publish_setup_json(intent_path, intent)
        _check_setup_state(root, state, intent, binding)
        connection = _setup_connection(binding, state)
        # Existing authority/history must match before restoring any missing
        # private credential or connection file on a retry.
        if args.command == "init" and (state / "coordinator.sqlite3").exists():
            _initial_authority(state, intent)
        if args.command == "attach":
            observed = _snapshot(_setup_transport(connection, binding["token_file"])(
                "snapshot", {"revision": intent["snapshot"]["revision"]}), intent["project_id"])
            if observed != intent["snapshot"]:
                raise ProductError(3, "setup_mismatch", "Coordinator history differs from the verified setup snapshot.")
        # Original credential and immutable intent are durable before authority
        # creation; partial setup never strands the only credential in memory.
        token_path = private_path(state / "member.token")
        if not token_path.exists():
            _publish_setup_bytes(token_path, (intent["token"] + "\n").encode("utf-8"))
        connection_path = private_path(state / "connection.json")
        if not connection_path.exists():
            _publish_setup_json(connection_path, connection)
        if args.command == "init":
            _initial_authority(state, intent)
        request = _setup_transport(connection, token_path)
        original = _snapshot(request("snapshot", {"revision": intent["snapshot"]["revision"]}), intent["project_id"])
        if original != intent["snapshot"]:
            raise ProductError(3, "setup_mismatch", "Coordinator history differs from the verified setup snapshot.")
        # Reserve this exact root identity before materialization. Separate state
        # directories cannot initialize different identities into the same root.
        write_manifest(root, intent["project_id"], args.provider)
        receipt = Client(root, state / "client", request).attach(intent["project_id"])
        if args.command == "init":
            return {"project_id": intent["project_id"], "receipt": receipt, "mode": args.mode, "provider": capabilities(args.provider),
                    "readiness": receipt["readiness"] if args.mode == "local" and args.provider == "local" else "partial",
                    "coordinator_deployment": "same_machine_only", "next": "Claim an assignment before drafting changes."}
        return {"receipt": receipt, "readiness": "partial", "provider_receipt": "unverified", "coordinator_membership": "verified"}


def dispatch(bundle, args):
    from .client import Client
    from .engine import Coordinator
    if args.command == "providers":
        return {"providers": [capabilities(p, args.account_type) for p in ([args.provider] if args.provider else PROVIDERS)]}
    if args.command == "serve":
        serve(private_path(args.database), args.host, args.port, args.certfile, args.keyfile)
        return {"server": "stopped"}
    root = selected_root(args.project)
    state = private_path(args.state_dir, root)
    coordination_file = getattr(args, "coordination_file", None)
    if coordination_file is not None and not coordination_file.strip():
        raise ProductError(2, "usage_error", "An explicit coordination configuration path must not be empty.")
    if args.command in {"init", "attach"}:
        return _setup(root, state, args)
    metadata = project_manifest(root)
    credential = getattr(args, "session_token_file", None)
    if credential is not None and not credential.strip():
        raise ProductError(2, "usage_error", "An explicit session credential path must not be empty.")
    transport = connect(state, private_path(credential, root) if credential is not None else None)
    # Identity verification is a read-only membership operation. A bounded session
    # need not have permission to read the whole project status; actual requested
    # operations always retain its credential and never fall back to membership.
    identity_transport = connect(state) if credential is not None else transport
    config = json_file(state / "client/client.json")
    if config.get("project_id") != metadata["project_id"] or config.get("project_root") != str(root):
        raise ProductError(3, "project_mismatch", "Private client state belongs to a different project or local root.")
    checked = False
    def request(operation, payload):
        nonlocal checked
        if not checked:
            identity = identity_transport("status", {})
            if identity["project_id"] != metadata["project_id"]:
                raise ProductError(3, "project_mismatch", "Connection points to a different project's authority.")
            checked = True
        return transport(operation, payload)
    client = Client(root, state / "client", request)
    if args.command == "receipt":
        return client.receipt()
    if args.command == "refresh":
        return client.refresh()
    if args.command == "draft":
        return client.draft(args.proposal_id, args.assignment_id, args.evidence, json_file(args.claims_file) if args.claims_file else None,
                            coordination=json_file(args.coordination_file) if args.coordination_file is not None else None)
    if args.command == "promote-draft":
        return client.promote_preserved(args.preserved_id, args.proposal_id, args.assignment_id, args.evidence,
                                       json_file(args.claims_file) if args.claims_file else None,
                                       coordination=json_file(args.coordination_file) if args.coordination_file is not None else None)
    if args.command == "submit":
        return client.submit(args.proposal_id)
    if args.command == "team-status":
        return {"coordinator": request("status", {}), "local": client.receipt(), "provider": capabilities(metadata["provider"])}
    if args.command == "coord":
        if args.operation in {"initialize", "member", "session-open", "session-delegate"}:
            raise ProductError(2, "use_safe_command", "Use init, member-add or session-create so credentials stay in private files.")
        payload = json_file(args.payload_file) if args.payload_file else {}
        return request(args.operation, payload)
    if args.command == "member-add":
        target = private_path(args.token_output, root)
        if not target.parent.is_dir() or target.exists():
            raise ProductError(5, "token_output_invalid", "Select a fresh token path in an existing private local directory.")
        token = secrets.token_urlsafe(48)
        # Write first so a successful membership response lost in transit does not
        # lose its only credential. A failed request leaves a private pending token.
        write_private(target, token + "\n")
        result = request("member", {"actor": args.actor, "human": args.person, "agent": args.agent,
                                    "role": args.role, "token": token})
        return {"membership": result, "credential_saved": True, "credential_delivery": "Separate approved private channel required; not sent."}
    if args.command == "provider-check":
        return verify_receipt(root, request("snapshot", {}), metadata["provider"], args.account_type)
    if args.command == "context":
        import re
        if not 1 <= args.limit <= 50:
            raise ProductError(2, "usage_error", "Context limit must be 1–50 files.")
        terms = set(re.findall(r"\w+", args.query.casefold()))
        if not terms:
            raise ProductError(2, "usage_error", "Context query needs at least one search term.")
        snapshot = request("snapshot", {})
        matches = []
        for name, content in snapshot["files"].items():
            score = sum(content.casefold().count(term) + 3 * name.casefold().count(term) for term in terms)
            if score:
                lines = [{"line": i, "text": line[:500]} for i, line in enumerate(content.splitlines(), 1)
                         if any(term in line.casefold() for term in terms)][:8]
                matches.append({"path": name, "score": score, "sha256": hashlib.sha256(content.encode()).hexdigest(), "matches": lines})
        matches.sort(key=lambda m: (-m["score"], m["path"]))
        return {"project_id": snapshot["project_id"], "revision": snapshot["revision"], "files_hash": snapshot["files_hash"],
                "results": matches[:args.limit], "source": "accepted_coordinator_snapshot", "drafts_included": False,
                "retrieval": "literal lexical matching; source excerpts, not semantic verification"}
    if args.command == "team-prompt":
        status = request("status", {})
        missing = [name for name, value in (("package_locator", args.package_locator), ("access_locator", args.access_locator)) if not value]
        prompt = f"""Set up Shared Memory: a shared workspace for your team and its AI agents.
Use a local agent connected to my actual computer. Obsidian is optional.
Project ID: {metadata['project_id']}
Engine protocol: 1. Expected accepted revision: {status['revision']}.
Expected files hash: {status['files_hash']}.
Reviewed package: {args.package_locator or 'MISSING: obtain the exact reviewed package and external SHA-256.'}
Authorized project/coordinator access: {args.access_locator or 'MISSING: obtain actual access instructions.'}
Provider: {metadata['provider']}. Verify actual account/client/OS support and sharing separately.
Use my own unique actor and a private membership token issued for me through an approved separate channel.
Do not copy the sender's identity or paths. Discover my selected project folder and local non-synced private state directory.
Verify the package's external SHA-256 before execution. Install compatible Python only within setup authorization.
Run attach with expected project ID, verified coordinator endpoint and my private token file. Never initialize an existing team project.
Verify receipt against the expected/current accepted revision. Inspect conflicts and preserve offline drafts; no silent history repair.
Do not migrate a live Vault, change permissions, send invitations or publish without the required authorization.
Report local receipt, coordinator membership, provider delivery and unavailable mixed-device checks separately.
"""
        return {"prompt": prompt, "readiness": "partial" if missing else "prompt_complete", "missing_fields": missing,
                "remote_readiness": "unverified", "project_id": metadata["project_id"]}
    raise ProductError(2, "usage_error", "Unknown authoritative workflow command.")
