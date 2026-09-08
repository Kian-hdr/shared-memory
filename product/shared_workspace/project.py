"""Selected-folder operations using only the verified bundled toolkit."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

from . import PRODUCT_VERSION
from .bundle import Bundle, digest_file
from .errors import ProductError

MANIFEST = ".workspace-project.json"
MODES = ("local-only", "shared-folder", "git", "hybrid")
TRACKER_COMMANDS = {"status", "check", "heartbeat", "sync", "claim", "plan", "start", "change",
                    "block", "complete", "handoff", "accept-handoff", "acknowledge", "decision", "reconcile", "validate"}
SHARED_WARNING = "Local validation does not verify provider propagation, another device's receipt, or an independent agent."


def concise_error_output(value: str) -> str:
    """Keep legacy error messages in JSON without leaking interpreter tracebacks."""
    marker = "Traceback (most recent call last):"
    if marker in value:
        prefix = value.split(marker, 1)[0]
        last_line = value.rstrip().splitlines()[-1]
        return prefix + "Trusted toolkit error: " + last_line + "\n"
    return value


def project_root(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ProductError(5, "environment_missing", "Choose an existing selected project directory.")
    return root


def run_tool(bundle: Bundle, script: str, arguments: list[str]) -> dict:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    result = subprocess.run([sys.executable, "-B", str(bundle.skill / script), *arguments],
                            capture_output=True, text=True, encoding="utf-8", errors="replace",
                            check=False, timeout=120, env=env)
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": concise_error_output(result.stderr)}


def tracker_run(bundle: Bundle, root: Path, arguments: list[str]) -> dict:
    return run_tool(bundle, "assets/project_tracker.py", ["--project-root", str(root), *arguments])


def require_success(result: dict, action: str, *, code: int = 4) -> None:
    if result["exit_code"] != 0:
        raise ProductError(code, "operation_rejected" if code == 4 else "project_invalid",
                           f"The trusted toolkit rejected {action}.", data={"legacy_output": result})


def require_regular(root: Path, relative: str, *, directory: bool = False) -> Path:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise ProductError(3, "project_invalid", f"Project path must remain inside the selected directory: {relative}")
    if not (path.is_dir() if directory else path.is_file()):
        raise ProductError(3, "project_invalid", f"Required project {'directory' if directory else 'file'} is missing: {relative}")
    return path


def check_metadata(bundle: Bundle, root: Path) -> dict:
    try:
        manifest_path = require_regular(root, MANIFEST)
        metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ProductError(3, "project_invalid", "Project manifest is malformed; preserve partial setup for review.") from exc
    fields = {"format_version", "project_id", "product_version", "toolkit_version", "bundle_id", "tracker_sha256", "mode"}
    if (not isinstance(metadata, dict) or set(metadata) != fields
            or type(metadata.get("format_version")) is not int or metadata["format_version"] != 1):
        raise ProductError(3, "project_invalid", "Project manifest has an unsupported format.")
    try:
        if str(uuid.UUID(metadata["project_id"])) != metadata["project_id"]:
            raise ValueError("Noncanonical project identity")
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProductError(3, "project_invalid", "Project identity is invalid.") from exc
    expected = {"product_version": PRODUCT_VERSION, "toolkit_version": bundle.build["toolkit_version"],
                "bundle_id": bundle.build["bundle_id"], "tracker_sha256": bundle.tracker_sha256}
    if any(metadata.get(key) != value for key, value in expected.items()):
        raise ProductError(3, "project_integrity", "Project metadata does not match this exact reviewed package.")
    if metadata["mode"] not in MODES:
        raise ProductError(3, "project_invalid", "Project collaboration mode is invalid.")
    tracker = require_regular(root, "Coordination/project_tracker.py")
    if digest_file(tracker) != bundle.tracker_sha256:
        raise ProductError(3, "project_integrity", "Installed tracker differs from the trusted package; no target code was executed.")
    instructions = require_regular(root, "AGENTS.md").read_text(encoding="utf-8")
    mode = re.search(r"(?m)^Collaboration mode: `([^`]+)`", instructions)
    if mode is None or mode.group(1) != metadata["mode"]:
        raise ProductError(3, "project_invalid", "Project instructions and manifest disagree about collaboration mode.")
    require_regular(root, "CLAUDE.md")
    require_regular(root, "Coordination/Workspace.base")
    items = require_regular(root, "Coordination/Items", directory=True)
    for record in items.glob("*.md"):
        require_regular(root, record.relative_to(root).as_posix())
    return metadata


def diagnostics(bundle: Bundle, root: Path, metadata: dict | None = None) -> dict:
    try:
        metadata = metadata or check_metadata(bundle, root)
    except ProductError as exc:
        exc.data = {"readiness": "blocked", "local_status": "invalid",
                    "partial_setup": (root / "Coordination").exists(),
                    "checks": [{"name": "product_metadata", "status": "fail", "detail": str(exc)}], **exc.data}
        raise
    report = bundle.load_module("scripts/doctor_workspace.py").diagnose(root)
    report.pop("project", None)
    for check in report.get("checks", []):
        if isinstance(check.get("detail"), str):
            check["detail"] = concise_error_output(check["detail"])
    report.setdefault("checks", []).insert(0, {"name": "product_metadata", "status": "pass"})
    data = {"metadata": metadata, "diagnostics": report, "local_status": report.get("local_status", "blocked"),
            "readiness": "ready" if metadata["mode"] == "local-only" else "partial",
            "remote_readiness": "not_applicable" if metadata["mode"] == "local-only" else "unverified"}
    if report.get("local_status") != "validated":
        data["readiness"] = "blocked"
        raise ProductError(3, "project_invalid", "Local project diagnostics did not pass.", data=data)
    return data


def footprint(root: Path) -> dict[str, str]:
    paths = [root / name for name in ("AGENTS.md", "CLAUDE.md", "README.md", MANIFEST,
                                     "Coordination/Workspace.base", "Coordination/project_tracker.py")]
    items = root / "Coordination/Items"
    if items.is_dir():
        paths.extend(items.glob("*.md"))
    return {path.relative_to(root).as_posix(): digest_file(path) for path in paths if path.is_file()}


def create(bundle: Bundle, args) -> dict:
    root = project_root(args.project)
    if ((root / MANIFEST).exists() or (root / MANIFEST).is_symlink()
            or (root / "Coordination/project_tracker.py").exists()
            or (root / "Coordination/Items").exists()
            or ((root / "AGENTS.md").is_file() and "shared-project-workspace:start" in (root / "AGENTS.md").read_text(encoding="utf-8"))):
        raise ProductError(4, "already_configured", "Existing or partial workspace detected. Use join for a complete project; preserve partial setup for owner review.")
    for relative in ("AGENTS.md", "CLAUDE.md", "README.md", MANIFEST, "Coordination",
                     "Coordination/Workspace.base", "Coordination/project_tracker.py", "Coordination/Items"):
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ProductError(3, "project_invalid", f"Refusing a generated path that leaves the selected directory: {relative}")
        expected_directory = relative in {"Coordination", "Coordination/Items"}
        if path.exists() and not (path.is_dir() if expected_directory else path.is_file()):
            raise ProductError(3, "project_invalid", f"Existing generated-path type is incompatible: {relative}")
    tracker = bundle.tracker(root)
    try:
        tracker.slug(args.actor)  # Validate identity before setup can write anything.
    except tracker.TrackerError as exc:
        raise ProductError(2, "usage_error", str(exc)) from exc
    setup = bundle.load_module("scripts/setup_workspace.py")
    try:
        setup.infer_project_home(root, None)  # Resolve external/home links before any write.
    except setup.SetupError as exc:
        raise ProductError(3, "project_invalid", str(exc)) from exc
    before = footprint(root)
    setup_result = run_tool(bundle, "scripts/setup_workspace.py", [str(root), "--purpose", args.purpose,
                            "--actor", args.actor, "--initiated-by", args.person, "--agent", args.agent,
                            "--collaboration-mode", args.mode])
    if setup_result["exit_code"] != 0:
        after = footprint(root)
        raise ProductError(4, "operation_rejected", "Setup did not complete. Preserve any created files and inspect diagnostics; no automatic repair was attempted.",
                           data={"legacy_output": setup_result, "partial_setup": before != after,
                                 "created_paths": sorted(set(after) - set(before)),
                                 "changed_paths": sorted(name for name in before.keys() & after.keys() if before[name] != after[name])})
    installed = require_regular(root, "Coordination/project_tracker.py")
    if digest_file(installed) != bundle.tracker_sha256:
        raise ProductError(3, "project_integrity", "Tracker changed during setup; project manifest was not written.")
    sync_result = tracker_run(bundle, root, ["sync", "--actor", args.actor, "--human", args.person, "--agent", args.agent])
    require_success(sync_result, "initial identity sync")
    require_success(tracker_run(bundle, root, ["validate"]), "initial validation", code=3)
    metadata = {"format_version": 1, "project_id": str(uuid.uuid4()), "product_version": PRODUCT_VERSION,
                "toolkit_version": bundle.build["toolkit_version"], "bundle_id": bundle.build["bundle_id"],
                "tracker_sha256": bundle.tracker_sha256, "mode": args.mode}
    with (root / MANIFEST).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    after = footprint(root)
    data = diagnostics(bundle, root, metadata)
    data.update(created_paths=sorted(set(after) - set(before)),
                changed_paths=sorted(name for name in before.keys() & after.keys() if before[name] != after[name]),
                legacy_output={"setup": setup_result, "sync": sync_result})
    return data


def join(bundle: Bundle, args) -> dict:
    root = project_root(args.project)
    metadata = check_metadata(bundle, root)
    if metadata["project_id"] != args.expected_project_id or metadata["bundle_id"] != args.expected_bundle_id:
        raise ProductError(3, "identity_mismatch", "Owner-supplied project or bundle identity does not match; no sync or setup was performed.")
    diagnostics(bundle, root, metadata)
    result = tracker_run(bundle, root, ["sync", "--actor", args.actor, "--human", args.person, "--agent", args.agent])
    require_success(result, "joining actor sync")
    data = diagnostics(bundle, root, metadata)
    data["legacy_output"] = result
    return data


def status(bundle: Bundle, args) -> dict:
    root = project_root(args.project)
    metadata = check_metadata(bundle, root)
    tracker = bundle.tracker(root)
    try:
        work = [{**record, "record_path": path.relative_to(root).as_posix()}
                for path, record, _ in tracker.records_of("work")]
    except Exception as exc:
        raise ProductError(3, "project_invalid", "Project work records could not be parsed by the trusted tracker.") from exc
    try:
        data = diagnostics(bundle, root, metadata)
    except ProductError as exc:
        exc.data["work_records"] = work
        raise
    data["work_records"] = work
    return data


def work(bundle: Bundle, args) -> dict:
    root = project_root(args.project)
    metadata = check_metadata(bundle, root)
    arguments = list(args.tracker_args)
    if arguments and arguments[0] == "--":
        arguments.pop(0)
    if not arguments or arguments[0] not in TRACKER_COMMANDS:
        raise ProductError(2, "usage_error", "work requires -- followed by an implemented tracker command.")
    if any(token.startswith("--") and "--project-root".startswith(token.split("=", 1)[0]) for token in arguments):
        raise ProductError(2, "usage_error", "work cannot override the selected project root.")
    result = tracker_run(bundle, root, arguments)
    require_success(result, "work command")
    return {"metadata": metadata, "legacy_output": result, "readiness": "not_assessed",
            "remote_readiness": "not_applicable" if metadata["mode"] == "local-only" else "unverified"}


def teammate_prompt(bundle: Bundle, args) -> dict:
    root = project_root(args.project)
    metadata = check_metadata(bundle, root)
    diagnostics(bundle, root, metadata)
    missing = []
    if not args.package_locator:
        missing.append("package_locator")
    if metadata["mode"] != "local-only" and not args.access_locator:
        missing.append("access_locator")
    package = args.package_locator or "Missing: obtain the exact reviewed preview package through an approved channel. No public release is implied."
    access = args.access_locator or ("Use my chosen local folder; no shared access is required." if metadata["mode"] == "local-only"
                                     else "Missing: obtain the owner's approved shared-project access instructions before joining.")
    prompt = f"""Join this existing Shared Workspace project inside my own chosen vault or folder.

Project ID: {metadata['project_id']}
Bundle ID: {metadata['bundle_id']}
Product version: {metadata['product_version']} (preview)
Toolkit version: {metadata['toolkit_version']}
Mode: {metadata['mode']}
Reviewed package locator: {package}
Project access instructions: {access}

Discover my own local project folder, name, unique actor ID, and agent. Keep my private parent vault, sibling folders and .obsidian settings outside the shared project. Do not use the owner's machine paths or identity. Obtain missing package/access information before claiming readiness. Use Python 3.11 or newer; Python 3.13 is the rehearsal baseline.

Inspect the existing project AGENTS.md and project home. Verify the package and project identities above. Run the reviewed package's doctor, then join using my identity:

python <reviewed-package.pyz> join <my-local-project-folder> --person <my-name> --actor <my-unique-actor-id> --agent <my-agent> --expected-project-id {metadata['project_id']} --expected-bundle-id {metadata['bundle_id']}

Never bootstrap, upgrade, replace the tracker, delete history, or take over claims to fix a joining failure. Stop and report any mismatch or incomplete setup. Open Coordination/Workspace.base directly in Obsidian's main content area when using Obsidian. Local checks do not prove provider propagation, receipt on another device, or independent-agent readiness. Preserve my tool approvals and existing project restrictions; do not send invitations, change permissions, enter credentials, install applications or publish anything without authorization.
"""
    return {"metadata": metadata, "prompt": prompt, "readiness": "partial" if missing else "ready",
            "missing_fields": missing, "remote_readiness": "not_applicable" if metadata["mode"] == "local-only" else "unverified"}
