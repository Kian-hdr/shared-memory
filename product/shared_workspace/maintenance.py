"""Reviewed package installation, isolated Git work, and read-only migration plans."""
from __future__ import annotations

import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import zipfile

from .bundle import open_bundle
from .errors import ProductError
from .workflow import private_path, selected_root, write_private, json_file
from .path_safety import absolute_path, is_link_or_reparse, unsafe_ancestor

COMMANDS = ("install-package", "rollback-package", "migration-plan", "git-isolate", "backup-coordinator", "recover-coordinator")


def add_commands(commands):
    install = commands.add_parser("install-package", help="Install only an exact externally verified local package; preserve earlier versions")
    install.add_argument("package")
    install.add_argument("--sha256", required=True)
    install.add_argument("--tools-dir", required=True)
    rollback = commands.add_parser("rollback-package", help="Select a previously verified installed runtime; never migrate projects")
    rollback.add_argument("--tools-dir", required=True)
    rollback.add_argument("--sha256", required=True)
    migration = commands.add_parser("migration-plan", help="Read-only selected-folder inventory and link/preservation plan; no migration")
    migration.add_argument("source")
    migration.add_argument("--destination", required=True)
    isolate = commands.add_parser("git-isolate", help="Prepare or create a code worktree outside synchronized folders")
    isolate.add_argument("repository")
    isolate.add_argument("--worktree", required=True)
    isolate.add_argument("--branch", required=True)
    isolate.add_argument("--base", default="HEAD")
    isolate.add_argument("--apply", action="store_true")
    backup = commands.add_parser("backup-coordinator", help="Create an isolated transaction-consistent coordinator backup")
    backup.add_argument("--database", required=True)
    backup.add_argument("--destination", required=True)
    backup.add_argument("--expected-project-id", help="Reject an authority belonging to another project before creating backup")
    recover = commands.add_parser("recover-coordinator", help="Recover a private coordinator hot journal without changing accepted history")
    recover.add_argument("--database", required=True)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


def digest_string(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ProductError(3, "digest_invalid", "Use the exact external SHA-256 from the reviewed source.")
    return value


def activate(tools, digest, version):
    entry = {"schema_version": 1, "sha256": digest, "product_version": version,
             "package": "versions/" + digest + ".pyz"}
    current = private_path(tools / "current.json")
    if current.exists():
        prior = json_file(current)
        record = private_path(tools / "history" / (str(time.time_ns()) + ".json"))
        record.parent.mkdir(mode=0o700, exist_ok=True)
        write_private(record, json.dumps(prior, indent=2) + "\n")
    fd, temporary = tempfile.mkstemp(prefix=".activate-", dir=tools)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        if unsafe_ancestor(current) is not None:
            raise ProductError(3, "install_path_unsafe", "Active package pointer cannot be a symbolic link.")
        os.replace(temporary, current)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {"installed": entry, "project_schemas_changed": False, "rollback": "Prior runtime files and activation history are retained.",
            "run": "Run the selected versions/<sha256>.pyz with compatible Python. No global PATH or shell configuration was changed."}


def inspect_package(package):
    """Static verification for installing/rolling back another runtime version.

Unlike open_bundle, never import modules from the candidate. The expected external
digest is checked by the caller; an internally valid manifest is not authenticity.
"""
    from .bundle import checked_name
    import stat
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            if len(entries) > 10000 or sum(e.file_size for e in entries) > 128 * 1024 * 1024:
                raise ValueError("Package exceeds limits")
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise ValueError("Duplicate members")
            for entry in entries:
                checked_name(entry.filename)
                if entry.is_dir() or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError("Unsupported archive entry")
            build = json.loads(archive.read("BUILD.json"))
            files = build["files"]
            if not isinstance(files, dict) or set(names) != set(files) | {"BUILD.json"}:
                raise ValueError("Manifest mismatch")
            if build["bundle_id"] != hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest():
                raise ValueError("Bundle identity mismatch")
            for name, digest in files.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != digest_string(digest):
                    raise ValueError("Content mismatch")
            if not re.fullmatch(r"\d+\.\d+\.\d+", build.get("product_version", "")) or build.get("engine_protocol", 1) != 1:
                raise ValueError("Unsupported runtime/protocol")
            if "__main__.py" not in files or "shared_workspace/cli.py" not in files:
                raise ValueError("No executable CLI")
            return build
    except (KeyError, ValueError, TypeError, zipfile.BadZipFile, UnicodeError) as exc:
        raise ProductError(3, "package_invalid", "Candidate package failed static verification; no candidate code was executed.") from exc


def install(package, expected, tools):
    digest_string(expected)
    if unsafe_ancestor(package) is not None:
        raise ProductError(3, "package_mismatch", "Package bytes do not match the reviewed external SHA-256.")
    package = absolute_path(package)
    if not package.is_file() or sha(package) != expected:
        raise ProductError(3, "package_mismatch", "Package bytes do not match the reviewed external SHA-256.")
    tools = private_path(tools)
    version = inspect_package(package)["product_version"]
    tools.mkdir(mode=0o700, parents=True, exist_ok=True)
    versions = private_path(tools / "versions")
    versions.mkdir(mode=0o700, exist_ok=True)
    target = versions / (expected + ".pyz")
    if target.exists():
        if unsafe_ancestor(target) is not None or sha(target) != expected:
            raise ProductError(3, "installed_integrity", "Existing immutable installed package was modified.")
    else:
        fd, temporary = tempfile.mkstemp(prefix=".package-", suffix=".partial", dir=versions)
        try:
            with package.open("rb") as source, os.fdopen(fd, "wb") as destination:
                shutil.copyfileobj(source, destination)
                destination.flush()
                os.fsync(destination.fileno())
            if sha(temporary) != expected:
                raise ProductError(3, "package_mismatch", "Package changed during installation; it was not activated.")
            # Atomic publication with no replacement, including competing installs.
            # Unsupported hard-link filesystems fail safely before activation.
            try:
                os.link(temporary, target)
            except FileExistsError:
                if unsafe_ancestor(target) is not None or sha(target) != expected:
                    raise ProductError(3, "installed_integrity", "Concurrent install target has unexpected bytes.")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return activate(tools, expected, version)


def migration_plan(source, destination):
    if unsafe_ancestor(Path(source).expanduser()) is not None:
        raise ProductError(3, "project_path_unsafe", "Choose the physical selected folder without symbolic links or reparse points.")
    source = selected_root(source)
    raw_destination = Path(destination).expanduser()
    if unsafe_ancestor(raw_destination) is not None:
        raise ProductError(3, "migration_target_invalid", "Plan a fresh destination outside the selected source tree.")
    destination = absolute_path(raw_destination).resolve()
    if unsafe_ancestor(destination) is not None or destination.exists() or destination.is_relative_to(source):
        raise ProductError(3, "migration_target_invalid", "Plan a fresh destination outside the selected source tree.")
    files, warnings, observed, directories = {}, [], {}, {}

    def identity(path):
        info = path.stat()
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def changed():
        raise ProductError(3, "migration_source_changed", "Selected files changed during migration planning; retry after edits stop.")
    from .engine import PROTECTED
    from .knowledge import PRIVATE, PRIVATE_FILES, analyze
    private_names = PROTECTED | PRIVATE | PRIVATE_FILES | {"connection.json", "member.token"}
    # Prune private directories and links before enumerating any descendants.
    # A rglob inventory can cross a Windows junction even when later file reads
    # are filtered. Recheck discovered ancestors before content access as well.
    pending = [source]
    paths = []
    while pending:
        folder = pending.pop()
        if unsafe_ancestor(folder) is not None:
            warnings.append({"path": folder.relative_to(source).as_posix(), "issue": "symlink_requires_manual_review"})
            continue
        directories[folder] = identity(folder)
        with os.scandir(folder) as entries:
            children = sorted((Path(entry.path) for entry in entries), reverse=True)
        for path in children:
            relative = path.relative_to(source).as_posix()
            if is_link_or_reparse(path):
                warnings.append({"path": relative, "issue": "symlink_requires_manual_review"})
            elif path.name.startswith('.'):
                warnings.append({"path": relative, "issue": "private_or_hidden_file_excluded"})
            elif path.name.casefold() in private_names:
                warnings.append({"path": relative, "issue": "private_state_or_credential_excluded"})
            elif path.is_dir():
                pending.append(path)
            else:
                paths.append(path)
    for path in sorted(paths):
        relative = path.relative_to(source).as_posix()
        if unsafe_ancestor(path) is not None:
            warnings.append({"path": relative, "issue": "symlink_requires_manual_review"})
            continue
        if not path.is_file():
            continue
        # Never copy/read private runtime databases, credentials or repository internals.
        if any(part.startswith(".") for part in path.relative_to(source).parts):
            warnings.append({"path": relative, "issue": "private_or_hidden_file_excluded"})
            continue
        if (any(part.casefold() in private_names for part in path.relative_to(source).parts)
                or path.suffix.casefold() in {".sqlite", ".sqlite3", ".db", ".key", ".pem", ".token"}
                or path.name.casefold().endswith((".sqlite-wal", ".sqlite-shm", ".sqlite-journal", ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal", ".db-wal", ".db-shm", ".db-journal"))):
            warnings.append({"path": relative, "issue": "private_state_or_credential_excluded"})
            continue
        observed[relative] = identity(path)
        files[relative] = {"sha256": sha(path), "bytes": observed[relative][2]}
        if identity(path) != observed[relative]:
            changed()
    graph = analyze(root=source)
    # A plan must not combine an old inventory with differently parsed note
    # contents. Graph traversal retains its own no-follow reads and hard bounds.
    for folder, expected in directories.items():
        if unsafe_ancestor(folder) is not None or not folder.is_dir() or identity(folder) != expected:
            changed()
    for relative, expected in observed.items():
        path = source / relative
        if unsafe_ancestor(path) is not None or not path.is_file():
            changed()
        if identity(path) != expected:
            changed()
    for node in graph['nodes']:
        digest = node['content_sha256']
        if node['path'] not in files or (digest is not None and files[node['path']]['sha256'] != digest):
            changed()
    # Retain the original narrow field for consumers; the complete graph is the
    # authoritative link audit, including Markdown, anchors and alias warnings.
    missing = [{'path': edge['source'], 'target': edge['requested_path'] or '[inspect source link]'}
               for edge in graph['edges'] if edge['syntax'] == 'wikilink' and edge['status'] != 'resolved']
    warnings.sort(key=lambda item: (item['path'], item['issue']))
    plan = {"schema_version": 1, "source": str(source), "destination": str(destination), "files": files,
            "warnings": warnings, "external_or_unresolved_wikilinks": missing, "link_analysis": graph,
            "actions": ["Verify independent backup and intended working copy", "Review excluded/private files and links",
                        "Copy selected files without changing source", "Verify all hashes, links and parent-vault preservation",
                        "Initialize/join reviewed runtime only after acceptance", "Keep source and backup for rollback"],
            "apply_performed": False, "readiness": "review_required", "live_migration_authorized": False}
    plan["plan_sha256"] = hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return plan


def git_isolate(args):
    repo = private_path(args.repository)
    worktree = private_path(args.worktree)
    if not repo.is_dir() or worktree.exists() or worktree.is_relative_to(repo):
        raise ProductError(3, "worktree_invalid", "Use an existing local repository and a fresh separate local worktree path.")
    def git(*command):
        result = subprocess.run(["git", "-C", str(repo), *command], capture_output=True, text=True)
        if result.returncode:
            raise ProductError(4, "git_rejected", "Git rejected the isolated-worktree request.", data={"stderr": result.stderr})
        return result.stdout.strip()
    if args.branch.startswith("-") or args.base.startswith("-"):
        raise ProductError(3, "git_ref_invalid", "Git refs cannot be command options.")
    git("check-ref-format", "--branch", args.branch)
    commit = git("rev-parse", "--verify", args.base + "^{commit}")
    before = git("status", "--porcelain")
    def worktree_bytes():
        inventory = {}
        for name in git("ls-files", "-z", "--cached", "--others", "--exclude-standard").split("\0"):
            if not name:
                continue
            path = repo / name
            if path.is_symlink():
                inventory[name] = {"symlink": os.readlink(path)}
            elif path.is_file():
                inventory[name] = {"sha256": sha(path)}
            else:
                inventory[name] = {"kind": "directory_or_absent"}
        return inventory
    bytes_before = worktree_bytes()
    if args.apply:
        with tempfile.TemporaryDirectory(prefix="shared-memory-no-hooks-") as empty_hooks:
            git("-c", "core.hooksPath=" + empty_hooks, "worktree", "add", "-b", args.branch, str(worktree), commit)
        if git("status", "--porcelain") != before or worktree_bytes() != bytes_before:
            raise ProductError(5, "source_changed", "Original checkout changed during isolation; inspect before continuing.")
    return {"base_commit": commit, "branch": args.branch, "worktree": str(worktree),
            "applied": args.apply, "original_checkout_preserved": True,
            "uncommitted_changes_included": False, "coordinator_claim": "Must be acquired separately with bounded assignment and integration owner."}


def backup_coordinator(database, destination, expected_project_id=None):
    database, destination = private_path(database), private_path(destination)
    if not database.is_file() or destination.exists() or not destination.parent.is_dir():
        raise ProductError(3, "backup_target_invalid", "Choose an existing coordinator and a fresh private local backup destination.")
    from .engine import Coordinator
    from .coordinator_migration import verify_checkpoint, _backup_path
    from .client import _fsync_dir
    engine = Coordinator(database)
    destination = _backup_path(destination, engine)
    # One read transaction pins every historical record and its exact backup.
    # This is local-file maintenance, not a remotely callable membership operation.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute("BEGIN")
        schema = source.execute("PRAGMA user_version").fetchone()[0]
        identity = engine._schema(source)['project_id']
        checkpoint = verify_checkpoint(source, engine, expected_schema=schema,
            expected_project_id=expected_project_id or identity)
        with os.fdopen(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"):
            pass
        deadline = time.monotonic() + 60
        def progress(status, remaining, total):
            if time.monotonic() > deadline:
                raise ProductError(5, 'backup_timeout', 'Backup deadline exceeded; preserve its partial file and original authority.')
        with closing(sqlite3.connect(destination)) as target:
            target.row_factory = sqlite3.Row
            target.execute('PRAGMA synchronous=FULL')
            source.backup(target, pages=128, progress=progress, sleep=0.05)
            target.execute('BEGIN')
            verified = verify_checkpoint(target, Coordinator(destination), expected_schema=schema,
                                         expected_project_id=identity)
            if verified['checkpoint'] != checkpoint['checkpoint']:
                raise ProductError(5, "backup_invalid", "Backup history differs from the pinned authority; preserve both files.")
    # Windows requires a writable handle to flush an existing file. r+b retains
    # the verified backup bytes and does not truncate or create a missing file.
    with destination.open("r+b") as stream:
        os.fsync(stream.fileno())
    _fsync_dir(destination.parent)
    return {"backup_sha256": sha(destination), "integrity_check": "ok", "source_changed": False,
            "history_verified": True, "schema_version": schema, "project_id": identity,
            "checkpoint": checkpoint['checkpoint'],
            "restore": "Stop the authority and verify project identity/history before selecting a restored private database; never overwrite active state automatically."}


def dispatch(bundle, args):
    if args.command == "install-package":
        return install(args.package, args.sha256, args.tools_dir)
    if args.command == "rollback-package":
        tools = private_path(args.tools_dir)
        path = tools / "versions" / (digest_string(args.sha256) + ".pyz")
        if unsafe_ancestor(path) is not None or not path.is_file() or sha(path) != args.sha256:
            raise ProductError(3, "rollback_invalid", "Requested previously installed package is missing or modified.")
        reviewed = inspect_package(path)
        return activate(tools, args.sha256, reviewed["product_version"])
    if args.command == "migration-plan":
        return migration_plan(args.source, args.destination)
    if args.command == "git-isolate":
        return git_isolate(args)
    if args.command == "backup-coordinator":
        return backup_coordinator(args.database, args.destination, args.expected_project_id)
    if args.command == "recover-coordinator":
        from .engine import Coordinator
        return Coordinator(private_path(args.database)).recover()
    raise ProductError(2, "usage_error", "Unknown maintenance command.")
