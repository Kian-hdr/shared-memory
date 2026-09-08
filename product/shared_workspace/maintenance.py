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
        if current.is_symlink():
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
    package = Path(package)
    if package.is_symlink() or not package.is_file() or sha(package) != expected:
        raise ProductError(3, "package_mismatch", "Package bytes do not match the reviewed external SHA-256.")
    tools = private_path(tools)
    version = inspect_package(package)["product_version"]
    tools.mkdir(mode=0o700, parents=True, exist_ok=True)
    versions = private_path(tools / "versions")
    versions.mkdir(mode=0o700, exist_ok=True)
    target = versions / (expected + ".pyz")
    if target.exists():
        if target.is_symlink() or sha(target) != expected:
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
                if target.is_symlink() or sha(target) != expected:
                    raise ProductError(3, "installed_integrity", "Concurrent install target has unexpected bytes.")
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return activate(tools, expected, version)


def migration_plan(source, destination):
    source = selected_root(source)
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink() or destination.resolve().is_relative_to(source):
        raise ProductError(3, "migration_target_invalid", "Plan a fresh destination outside the selected source tree.")
    files, warnings, links, names = {}, [], [], {}
    from .engine import PROTECTED
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source).as_posix()
        if path.is_symlink():
            warnings.append({"path": relative, "issue": "symlink_requires_manual_review"})
            continue
        if not path.is_file():
            continue
        # Never copy/read private runtime databases, credentials or repository internals.
        if any(part.startswith(".") for part in path.relative_to(source).parts):
            warnings.append({"path": relative, "issue": "private_or_hidden_file_excluded"})
            continue
        if (any(part.casefold() in PROTECTED | {"connection.json", "member.token"} for part in path.relative_to(source).parts)
                or path.suffix.casefold() in {".sqlite", ".sqlite3", ".db", ".key", ".pem", ".token"}
                or path.name.casefold().endswith((".sqlite-wal", ".sqlite-shm", ".sqlite-journal", ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal", ".db-wal", ".db-shm", ".db-journal"))):
            warnings.append({"path": relative, "issue": "private_state_or_credential_excluded"})
            continue
        files[relative] = {"sha256": sha(path), "bytes": path.stat().st_size}
        if path.suffix.casefold() == ".md" and path.stat().st_size <= 10 * 1024 * 1024:
            names.setdefault(path.stem, []).append(relative)
            for target in re.findall(r"\[\[([^\]]+)\]\]", path.read_text(encoding="utf-8")):
                links.append((relative, target.replace("\\|", "|").split("|")[0].split("#")[0]))
    missing = []
    for path, target in links:
        if not target:
            continue
        if "/" in target:
            candidate = target if target.endswith(".md") else target + ".md"
            resolved = candidate in files or (Path(path).parent / candidate).as_posix() in files
        else:
            resolved = len(names.get(Path(target).stem, [])) == 1
        if not resolved:
            missing.append({"path": path, "target": target})
    plan = {"schema_version": 1, "source": str(source), "destination": str(destination), "files": files,
            "warnings": warnings, "external_or_unresolved_wikilinks": missing,
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


def backup_coordinator(database, destination):
    database, destination = private_path(database), private_path(destination)
    if not database.is_file() or destination.exists() or not destination.parent.is_dir():
        raise ProductError(3, "backup_target_invalid", "Choose an existing coordinator and a fresh private local backup destination.")
    # SQLite backup API captures a consistent snapshot while the authority operates.
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        with os.fdopen(os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb"):
            pass
        with closing(sqlite3.connect(destination)) as target:
            source.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ProductError(5, "backup_invalid", "Backup integrity check failed; original authority is unchanged.")
    return {"backup_sha256": sha(destination), "integrity_check": "ok", "source_changed": False,
            "restore": "Stop the authority and verify project identity/history before selecting a restored private database; never overwrite active state automatically."}


def dispatch(bundle, args):
    if args.command == "install-package":
        return install(args.package, args.sha256, args.tools_dir)
    if args.command == "rollback-package":
        tools = private_path(args.tools_dir)
        path = tools / "versions" / (digest_string(args.sha256) + ".pyz")
        if path.is_symlink() or not path.is_file() or sha(path) != args.sha256:
            raise ProductError(3, "rollback_invalid", "Requested previously installed package is missing or modified.")
        reviewed = inspect_package(path)
        return activate(tools, args.sha256, reviewed["product_version"])
    if args.command == "migration-plan":
        return migration_plan(args.source, args.destination)
    if args.command == "git-isolate":
        return git_isolate(args)
    if args.command == "backup-coordinator":
        return backup_coordinator(args.database, args.destination)
    if args.command == "recover-coordinator":
        from .engine import Coordinator
        return Coordinator(private_path(args.database)).recover()
    raise ProductError(2, "usage_error", "Unknown maintenance command.")
