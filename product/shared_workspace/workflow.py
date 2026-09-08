"""Owner/recipient CLI workflows for the authoritative engine."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
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
        if name in {"draft", "promote-draft"}:
            command.add_argument("--proposal-id", required=True)
            command.add_argument("--assignment-id", required=True)
            command.add_argument("--evidence", required=True)
            command.add_argument("--claims-file")
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
        files[relative.as_posix()] = path.read_text(encoding="utf-8")
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
    with path.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(metadata, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return metadata


def connect(state):
    config = json_file(state / "connection.json")
    if not isinstance(config, dict) or config.get("protocol") != 1:
        raise ProductError(3, "connection_invalid", "Unsupported private connection configuration.")
    if config.get("transport") == "local":
        return LocalTransport(config["database"], state / "member.token")
    if config.get("transport") == "https":
        return HTTPTransport(config["endpoint"], state / "member.token", config.get("ca_file"))
    raise ProductError(3, "connection_invalid", "Unknown coordinator transport.")


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
    if args.command == "init":
        if any((root / name).exists() or (root / name).is_symlink() for name in (MANIFEST, ".workspace-project.json", "Coordination")):
            raise ProductError(4, "already_configured", "Existing project or legacy tracker requires a reviewed join/migration plan.")
        if state.exists() and any(state.iterdir()):
            raise ProductError(4, "state_exists", "Preserve existing private state; use the existing connection or choose a fresh state directory.")
        files = initial_files(root, args.include)
        files.setdefault("AGENTS.md", "# Shared Memory\n\nRead the selected project home. Refresh accepted context before work.\nClaim bounded targets, draft against the recorded base revision, and submit evidence.\nOnly the integration owner accepts proposals. Preserve conflicts and private parent files.\nNever treat provider file existence as proof of another actor's accepted receipt.\n")
        if not any(name in files for name in ("README.md", "Home.md")):
            files["README.md"] = "# Shared Memory\n\n" + args.purpose + "\n"
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        token = secrets.token_urlsafe(48)
        identifier = str(uuid.uuid4())
        Coordinator(state / "coordinator.sqlite3").initialize(identifier,
            {"actor": args.actor, "human": args.person, "agent": args.agent}, token, files)
        write_private(state / "member.token", token + "\n")
        config = {"protocol": 1, "transport": "local", "database": str(state / "coordinator.sqlite3"), "mode": args.mode}
        write_private(state / "connection.json", json.dumps(config, indent=2) + "\n")
        result = Client(root, state / "client", connect(state)).attach(identifier)
        write_manifest(root, identifier, args.provider)
        return {"project_id": identifier, "receipt": result, "mode": args.mode, "provider": capabilities(args.provider),
                "readiness": result["readiness"] if args.mode == "local" and args.provider == "local" else "partial",
                "coordinator_deployment": "same_machine_only", "next": "Claim an assignment before drafting changes."}
    if args.command == "attach":
        if (root / MANIFEST).exists():
            metadata = project_manifest(root)
            if metadata["project_id"] != args.expected_project_id or metadata["provider"] != args.provider:
                raise ProductError(3, "project_mismatch", "Owner-supplied project/provider does not match this folder.")
        if state.exists() and any(state.iterdir()):
            raise ProductError(4, "state_exists", "Existing client state must be resumed with refresh, not overwritten.")
        token = read_token(private_path(args.token_file, root))
        if args.database:
            database = private_path(args.database, root)
            request = LocalTransport(database, args.token_file)
            config = {"protocol": 1, "transport": "local", "database": str(database), "mode": "team"}
        else:
            request = HTTPTransport(args.endpoint, args.token_file, args.ca_file)
            config = {"protocol": 1, "transport": "https", "endpoint": args.endpoint, "ca_file": args.ca_file, "mode": "team"}
        observed = request("snapshot", {})
        if observed["project_id"] != args.expected_project_id:
            raise ProductError(3, "project_mismatch", "The coordinator serves a different project.")
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        write_private(state / "member.token", token + "\n")
        write_private(state / "connection.json", json.dumps(config, indent=2) + "\n")
        receipt = Client(root, state / "client", connect(state)).attach(args.expected_project_id)
        write_manifest(root, args.expected_project_id, args.provider)
        return {"receipt": receipt, "readiness": "partial", "provider_receipt": "unverified", "coordinator_membership": "verified"}
    metadata = project_manifest(root)
    transport = connect(state)
    config = json_file(state / "client/client.json")
    if config.get("project_id") != metadata["project_id"] or config.get("project_root") != str(root):
        raise ProductError(3, "project_mismatch", "Private client state belongs to a different project or local root.")
    checked = False
    def request(operation, payload):
        nonlocal checked
        if not checked:
            identity = transport("status", {})
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
        return client.draft(args.proposal_id, args.assignment_id, args.evidence, json_file(args.claims_file) if args.claims_file else None)
    if args.command == "promote-draft":
        return client.promote_preserved(args.preserved_id, args.proposal_id, args.assignment_id, args.evidence,
                                       json_file(args.claims_file) if args.claims_file else None)
    if args.command == "submit":
        return client.submit(args.proposal_id)
    if args.command == "team-status":
        return {"coordinator": request("status", {}), "local": client.receipt(), "provider": capabilities(metadata["provider"])}
    if args.command == "coord":
        if args.operation in {"initialize", "member"}:
            raise ProductError(2, "use_safe_command", "Use init or member-add so credentials stay outside shared files.")
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
