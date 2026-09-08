#!/usr/bin/env python3
# generated-by: setup-shared-project-workspace schema=1
"""Self-contained Markdown project tracker for shared human and agent workspaces."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import re
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath
from typing import Any

WORKSPACE_TRACKER_VERSION = "1.3.0"
SCHEMA_VERSION = 1
GENERATOR_SIGNATURE = "generated-by: setup-shared-project-workspace"
PORTABLE_ITEMS_FILTER = 'this.file.ext == "base" && file.inFolder(this.file.folder + "/Items")'

STATUSES = {
    "not_started",
    "claimed",
    "in_progress",
    "blocked",
    "pending_approval",
    "ready_for_review",
    "verified",
    "cancelled",
}
ACTIVE_STATUSES = {
    "claimed",
    "in_progress",
    "blocked",
    "pending_approval",
    "ready_for_review",
}
IMPACTS = {"none", "compatible", "breaking", "unknown"}
TRANSITIONS = {
    "not_started": {"claimed", "cancelled"},
    "claimed": {"in_progress", "blocked", "pending_approval", "cancelled"},
    "in_progress": {
        "in_progress",
        "blocked",
        "pending_approval",
        "ready_for_review",
        "cancelled",
    },
    "blocked": {"in_progress", "pending_approval", "cancelled"},
    "pending_approval": {"in_progress", "blocked", "cancelled"},
    "ready_for_review": {"in_progress", "blocked", "verified", "cancelled"},
    "verified": set(),
    "cancelled": set(),
}

TRACKER_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TRACKER_DIR.parent
ITEMS_DIR = TRACKER_DIR / "Items"


class TrackerError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso_utc(value: datetime | None = None) -> str:
    return (value or utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp(value: datetime | None = None) -> str:
    return (value or utc_now()).strftime("%Y%m%dT%H%M%SZ")


def slug(value: str, *, upper: bool = True) -> str:
    if "@" in value:
        raise TrackerError("Identifiers must not contain email addresses.")
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip()).strip("-")
    if not cleaned:
        raise TrackerError("Identifier must contain at least one letter or digit.")
    return cleaned.upper() if upper else cleaned.lower()


def unique_suffix() -> str:
    return uuid.uuid4().hex[:4].upper()


def parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    if raw.startswith("'") and raw.endswith("'"):
        return raw[1:-1].replace("''", "'")
    if raw in {"true", "false", "null"} or raw[:1] in {'"', "[", "{"}:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    if re.fullmatch(r"-?\d+", raw):
        return int(raw)
    return raw


def format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    return json.dumps(value, ensure_ascii=False)


def read_record(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        raise TrackerError(f"Missing or invalid frontmatter: {path.name}")
    data: dict[str, Any] = {}
    current_key = None
    for line_number, line in enumerate(match.group(1).splitlines(), start=2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("- ") and current_key:
            if data[current_key] == "":
                data[current_key] = []
            if not isinstance(data[current_key], list):
                raise TrackerError(f"Invalid list at {path.name}:{line_number}")
            data[current_key].append(parse_value(line.lstrip()[2:]))
            continue
        key, separator, raw = line.partition(":")
        if not separator or not re.fullmatch(r"[A-Za-z0-9_]+", key.strip()):
            raise TrackerError(f"Unsupported frontmatter at {path.name}:{line_number}")
        current_key = key.strip()
        data[current_key] = parse_value(raw)
    return data, match.group(2).rstrip() + "\n"


def write_record(path: Path, data: dict[str, Any], body: str, *, immutable: bool = False) -> None:
    ITEMS_DIR.mkdir(parents=True, exist_ok=True)
    if immutable and path.exists():
        raise TrackerError(f"Immutable record already exists: {path.name}")
    lines = ["---"]
    lines.extend(f"{key}: {format_value(value)}" for key, value in data.items())
    lines.extend(["---", body.rstrip(), ""])
    content = "\n".join(lines)
    if immutable:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(content)
        return
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def all_records() -> list[tuple[Path, dict[str, Any], str]]:
    if not ITEMS_DIR.exists():
        return []
    records = []
    for path in sorted(ITEMS_DIR.glob("*.md")):
        data, body = read_record(path)
        records.append((path, data, body))
    return records


def records_of(record_type: str) -> list[tuple[Path, dict[str, Any], str]]:
    return [record for record in all_records() if record[1].get("record_type") == record_type]


def find_work(work_id: str) -> tuple[Path, dict[str, Any], str]:
    normalized = slug(work_id)
    matches = [record for record in records_of("work") if record[1].get("work_id") == normalized]
    if not matches:
        raise TrackerError(f"Unknown work ID: {normalized}")
    if len(matches) > 1:
        raise TrackerError(f"Duplicate work ID: {normalized}")
    problems = stored_target_problems(matches[0][1])
    if problems:
        raise TrackerError(f"{normalized}: " + "; ".join(problems))
    return matches[0]


def find_actor(actor_id: str) -> tuple[Path, dict[str, Any], str] | None:
    normalized = slug(actor_id)
    matches = [record for record in records_of("actor") if record[1].get("actor_id") == normalized]
    if not matches:
        return None
    if len(matches) > 1:
        raise TrackerError(f"Duplicate actor ID: {normalized}")
    return matches[0]


def ensure_actor(actor_id: str, human: str | None, agent: str | None) -> tuple[Path, dict[str, Any], str]:
    if "@" in actor_id:
        raise TrackerError("Actor IDs must not contain email addresses.")
    normalized = slug(actor_id)
    existing = find_actor(normalized)
    if existing:
        path, data, body = existing
        if human and data.get("human") != human:
            raise TrackerError(f"Actor {normalized} is registered to a different human.")
        if agent and data.get("agent") != agent:
            raise TrackerError(f"Actor {normalized} is registered to a different agent.")
        return path, data, body
    if not human or not agent:
        raise TrackerError("A new actor requires --human and --agent.")
    now = iso_utc()
    data = {
        "record_type": "actor",
        "schema_version": SCHEMA_VERSION,
        "actor_id": normalized,
        "human": human,
        "agent": agent,
        "created": now,
        "updated": now,
        "last_sync": "",
        "seen_records": [],
        "active_work": [],
    }
    path = ITEMS_DIR / f"ACTOR-{normalized}.md"
    body = "# Actor state\n\nThis operational record is updated only by its named actor.\n"
    write_record(path, data, body)
    return path, data, body


def normalize_target(target: str) -> str:
    """Convert a local file input to the same portable label on every device."""
    if not isinstance(target, str):
        raise TrackerError("Targets must be strings.")
    value = target.strip().replace("\\", "/")
    if not value or value.startswith("~"):
        raise TrackerError("Use a project-relative target, not an empty value or a home shortcut.")
    if ".." in value.split("/"):
        raise TrackerError("Parent traversal is not supported in targets; use a path inside the project root.")
    if is_resource_label(value):
        return posixpath.normpath(value)
    path = Path(value)
    windows_drive = PureWindowsPath(value).drive
    if windows_drive and (os.name != "nt" or not path.is_absolute()):
        raise TrackerError("Foreign-machine or drive-relative targets are not portable; use a project-relative path.")
    if value.startswith("/") and not path.is_absolute():
        raise TrackerError("Foreign-machine absolute targets are not portable; use a project-relative path.")
    root = PROJECT_ROOT.resolve()
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root):
        raise TrackerError("Target is outside the project root; use a shared project-relative path or an agreed non-file resource label.")
    return resolved.relative_to(root).as_posix()


def is_resource_label(target: str) -> bool:
    # Non-file labels retain advisory ownership semantics on every operating system.
    return bool(re.match(r"^(branch|environment|env|artifact):[^/]+", target))


def stored_target_problems(data: dict[str, Any]) -> list[str]:
    """Diagnose old records without silently changing their historical paths."""
    problems = []
    targets = list(data.get("targets", [])) + list(data.get("changed_targets", []))
    for field in ("target_hashes", "hashes_before", "hashes_after"):
        try:
            targets.extend(unpack_hashes(data.get(field, [])).keys())
        except TrackerError as exc:
            problems.append(str(exc))
    for target in dict.fromkeys(targets):
        try:
            canonical = normalize_target(target)
            if canonical == target:
                continue
            reason = f"use project-relative {canonical!r}"
        except TrackerError as exc:
            reason = str(exc)
        problems.append(
            f"Nonportable stored target {target!r}: {reason}. Review the original-to-local mapping before an explicit migration. Immutable history is not rewritten by this tracker; adding a superseding record alone does not clear legacy-path diagnostics. No records were rewritten."
        )
    return problems


def targets_overlap(first: str, second: str) -> bool:
    a = normalize_target(first).casefold()
    b = normalize_target(second).casefold()
    return a == "." or b == "." or a == b or a.startswith(b + "/") or b.startswith(a + "/")


def active_works() -> list[tuple[Path, dict[str, Any], str]]:
    return [record for record in records_of("work") if record[1].get("status") in ACTIVE_STATUSES]


def assert_targets_available(targets: list[str], *, excluding_work: str | None = None) -> None:
    conflicts = []
    for _, data, _ in active_works():
        if excluding_work and data.get("work_id") == excluding_work:
            continue
        problems = stored_target_problems(data)
        if problems:
            raise TrackerError(f"{data.get('work_id')}: " + "; ".join(problems))
        for requested in targets:
            for claimed in data.get("targets", []):
                if targets_overlap(requested, claimed):
                    conflicts.append(f"{requested} overlaps {claimed} claimed by {data.get('work_id')}")
    if conflicts:
        raise TrackerError("Target conflict:\n- " + "\n- ".join(sorted(set(conflicts))))


def resolve_target(target: str) -> Path:
    return PROJECT_ROOT / normalize_target(target)


def sha256_directory(path: Path) -> str:
    """Fingerprint descendants without following links or hashing tracker records."""
    digest = hashlib.sha256()
    items = ITEMS_DIR.resolve()

    def visit(directory: Path) -> None:
        for child in sorted(directory.iterdir(), key=lambda entry: entry.name):
            if child == items:
                continue
            relative = child.relative_to(path).as_posix()
            if child.is_symlink():
                # Following links could leave the project or create a cycle. Require
                # explicit file claims when linked content needs drift protection.
                raise TrackerError(f"Directory target contains a symbolic link: {relative}. Use exact file targets instead.")
            if child.is_dir():
                entry = [relative, "directory"]
            elif child.is_file():
                file_digest = hashlib.sha256()
                with child.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        file_digest.update(chunk)
                entry = [relative, file_digest.hexdigest()]
            else:
                raise TrackerError(f"Directory target contains an unsupported file: {relative}. Use exact file targets instead.")
            digest.update((json.dumps(entry, ensure_ascii=True) + "\n").encode("utf-8"))
            if child.is_dir():
                visit(child)

    visit(path)
    return "directory-sha256:" + digest.hexdigest()


def sha256_target(target: str) -> str:
    if is_resource_label(normalize_target(target)):
        return "missing"
    path = resolve_target(target)
    if not path.exists():
        return "missing"
    if path.is_dir():
        return sha256_directory(path)
    if not path.is_file():
        return "unsupported"
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_targets(targets: list[str]) -> dict[str, str]:
    return {normalize_target(target): sha256_target(target) for target in targets}


def pack_hashes(values: dict[str, str]) -> list[str]:
    return [json.dumps({"path": path, "sha256": digest}, sort_keys=True) for path, digest in sorted(values.items())]


def unpack_hashes(values: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in values or []:
        try:
            parsed = json.loads(item)
            result[parsed["path"]] = parsed["sha256"]
        except (json.JSONDecodeError, KeyError, TypeError):
            raise TrackerError(f"Invalid target hash entry: {item}")
    return result


def pack_baselines(values: dict[str, int]) -> list[str]:
    return [f"{work_id}@{revision}" for work_id, revision in sorted(values.items())]


def unpack_baselines(values: list[str] | None) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in values or []:
        work_id, separator, revision = item.rpartition("@")
        if not separator or not revision.isdigit():
            raise TrackerError(f"Invalid dependency baseline: {item}")
        result[work_id] = int(revision)
    return result


def work_index() -> dict[str, tuple[Path, dict[str, Any], str]]:
    return {record[1]["work_id"]: record for record in records_of("work")}


def stale_dependencies(data: dict[str, Any], index: dict[str, tuple[Path, dict[str, Any], str]]) -> list[str]:
    baselines = unpack_baselines(data.get("dependency_baseline", []))
    stale = []
    for dependency in data.get("depends_on", []):
        upstream = index.get(dependency)
        if not upstream:
            stale.append(f"{dependency} is missing")
            continue
        current = int(upstream[1].get("revision", 0))
        known = baselines.get(dependency, -1)
        if known < current:
            stale.append(f"{dependency} changed from revision {known} to {current}")
    return stale


def claim_is_stale(data: dict[str, Any]) -> bool:
    value = data.get("claim_expires", "")
    if not value:
        return True
    try:
        expiry = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return expiry <= utc_now()
    except ValueError:
        return True


def current_dependents(work_id: str) -> list[str]:
    return sorted(
        data["work_id"]
        for _, data, _ in records_of("work")
        if work_id in data.get("depends_on", [])
    )


def build_work_body(data: dict[str, Any]) -> str:
    passed = set(data.get("passed_criteria", []))
    criteria = data.get("acceptance_criteria", [])
    checklist = "\n".join(
        f"- [{'x' if index + 1 in passed else ' '}] {index + 1}. {criterion}"
        for index, criterion in enumerate(criteria)
    )
    evidence = "\n".join(f"- `{item}`" for item in data.get("evidence", [])) or "- None recorded"
    blocker = data.get("blocker") or "None"
    return (
        f"# {data['title']}\n\n"
        f"## Objective\n\n{data.get('objective', '')}\n\n"
        f"## Acceptance criteria\n\n{checklist}\n\n"
        f"## Current state\n\n{data.get('current_state', '')}\n\n"
        f"## Evidence\n\n{evidence}\n\n"
        f"## Blocker\n\n{blocker}\n\n"
        f"## Next action\n\n{data.get('next_action', '')}\n"
    )


def immutable_record_id(data: dict[str, Any]) -> str | None:
    for key in ("event_id", "handoff_id", "decision_id"):
        if data.get(key):
            return str(data[key])
    return None


def event_body(data: dict[str, Any]) -> str:
    return (
        f"# {data['event_type'].replace('_', ' ').title()}\n\n"
        f"## Outcome\n\n{data.get('summary', '')}\n\n"
        f"## Changes\n\n{', '.join(data.get('changed_targets', [])) or 'No file target recorded.'}\n\n"
        f"## Validation\n\n{data.get('validation') or 'Not run.'}\n\n"
        f"## Evidence\n\n"
        + ("\n".join(f"- `{item}`" for item in data.get("evidence", [])) or "- None recorded")
        + f"\n\n## Limitations or blocker\n\n{data.get('limitations') or 'None recorded.'}\n\n"
        f"## Next action and owner\n\n{data.get('next_action') or 'None.'}\n"
    )


def emit_event(
    *,
    event_type: str,
    work: dict[str, Any],
    actor_id: str,
    initiated_by: str,
    performed_by: str,
    status_before: str,
    status_after: str,
    summary: str,
    changed_targets: list[str],
    hashes_before: dict[str, str],
    hashes_after: dict[str, str],
    change_kind: str,
    impact: str,
    affects: list[str],
    evidence: list[str],
    validation: str,
    limitations: str,
    next_action: str,
    supersedes: str = "",
) -> tuple[Path, dict[str, Any]]:
    timestamp = utc_now()
    event_id = f"{stamp(timestamp)}-{work['work_id']}-{unique_suffix()}"
    data = {
        "record_type": "event",
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id,
        "event_type": event_type,
        "work_id": work["work_id"],
        "work_revision": work["revision"],
        "timestamp": iso_utc(timestamp),
        "initiated_by": initiated_by,
        "performed_by": performed_by,
        "actor_id": slug(actor_id),
        "status_before": status_before,
        "status_after": status_after,
        "summary": summary,
        "changed_targets": [normalize_target(item) for item in changed_targets],
        "hashes_before": pack_hashes(hashes_before),
        "hashes_after": pack_hashes(hashes_after),
        "change_kind": change_kind,
        "impact": impact,
        "affects": sorted(set(affects)),
        "evidence": evidence,
        "validation": validation,
        "limitations": limitations,
        "next_action": next_action,
        "supersedes": supersedes,
    }
    path = ITEMS_DIR / f"EVENT-{event_id}.md"
    write_record(path, data, event_body(data), immutable=True)
    return path, data


def require_owner(data: dict[str, Any], actor_id: str) -> None:
    normalized = slug(actor_id)
    if data.get("actor_id") != normalized:
        raise TrackerError(
            f"{data.get('work_id')} is owned by actor {data.get('actor_id')}; "
            f"{normalized} must receive a recorded handoff before changing it."
        )


def update_actor_work(actor_id: str, human: str, agent: str, work_id: str, *, add: bool) -> None:
    path, data, body = ensure_actor(actor_id, human, agent)
    active = set(data.get("active_work", []))
    if add:
        active.add(work_id)
    else:
        active.discard(work_id)
    data["active_work"] = sorted(active)
    data["updated"] = iso_utc()
    write_record(path, data, body)


def command_claim(args: argparse.Namespace) -> None:
    planned = getattr(args, "plan_only", False)
    if args.claim_hours <= 0:
        raise TrackerError("Claim duration must be positive.")
    work_id = slug(args.work_id)
    if any(data.get("work_id") == work_id for _, data, _ in records_of("work")):
        raise TrackerError(f"Work ID already exists: {work_id}")
    targets = [normalize_target(item) for item in args.target]
    if not planned:
        assert_targets_available(targets)
    index = work_index()
    dependencies = [slug(item) for item in args.depends_on]
    missing = [item for item in dependencies if item not in index]
    if missing:
        raise TrackerError("Unknown dependencies: " + ", ".join(missing))
    baseline = {item: int(index[item][1].get("revision", 0)) for item in dependencies}
    target_hashes = hash_targets(targets)
    actor_id = slug(args.actor)
    ensure_actor(actor_id, args.owner, args.agent)
    now = utc_now()
    criteria = list(args.acceptance)
    data = {
        "record_type": "work",
        "schema_version": SCHEMA_VERSION,
        "work_id": work_id,
        "title": args.title,
        "status": "not_started" if planned else "claimed",
        "revision": 1,
        "owner": "Unassigned" if planned else args.owner,
        "agent": "Unassigned" if planned else args.agent,
        "actor_id": "" if planned else actor_id,
        "recorded_by": actor_id,
        "suggested_owner": getattr(args, "suggested_owner", ""),
        "source_summary": getattr(args, "source_summary", ""),
        "source_evidence": list(getattr(args, "source_evidence", [])),
        "initiated_by": args.initiated_by,
        "targets": targets,
        "outputs": list(args.output),
        "depends_on": dependencies,
        "dependency_baseline": pack_baselines(baseline),
        "context_status": "current",
        "context_checked": iso_utc(now),
        "acceptance_criteria": criteria,
        "acceptance_total": len(criteria),
        "acceptance_passed": 0,
        "passed_criteria": [],
        "created": iso_utc(now),
        "updated": iso_utc(now),
        "last_verified": "",
        "claim_expires": "" if planned else iso_utc(now + timedelta(hours=args.claim_hours)),
        "objective": args.objective,
        "current_state": ("Unclaimed backlog; not_started describes this follow-up, not the historical project. " + getattr(args, "source_summary", "")) if planned else "Claimed; implementation has not yet been recorded.",
        "evidence": list(getattr(args, "source_evidence", [])),
        "validation": "",
        "blocker": "",
        "handoff_pending": False,
        "handoff_id": "",
        "next_action": args.next_action,
        "target_hashes": pack_hashes(target_hashes),
    }
    path = ITEMS_DIR / f"WORK-{work_id}.md"
    write_record(path, data, build_work_body(data))
    emit_event(
        event_type="backlog_recorded" if planned else "claim",
        work=data,
        actor_id=actor_id,
        initiated_by=args.initiated_by,
        performed_by=args.agent,
        status_before="not_started",
        status_after=data["status"],
        summary=f"{'Recorded unclaimed backlog' if planned else 'Claimed'} {work_id}: {args.title}",
        changed_targets=[],
        hashes_before={},
        hashes_after={},
        change_kind="coordination",
        impact="none",
        affects=[],
        evidence=list(getattr(args, "source_evidence", [])),
        validation="Dependency existence checked; no target claim acquired." if planned else "Target overlap and dependency existence checked.",
        limitations="Historical context is not verified current status; suggested owner is not an assignment." if planned else "Claims are advisory across synchronized filesystems.",
        next_action=args.next_action,
    )
    if not planned:
        update_actor_work(actor_id, args.owner, args.agent, work_id, add=True)
    print(f"Recorded backlog {work_id}." if planned else f"Claimed {work_id} for {actor_id}.")


def command_start(args: argparse.Namespace) -> None:
    path, data, _ = find_work(args.work_id)
    if data.get("status") != "not_started" or data.get("actor_id"):
        raise TrackerError("Only unclaimed backlog can be started; existing ownership requires handoff.")
    if args.claim_hours <= 0:
        raise TrackerError("Claim duration must be positive.")
    index = work_index()
    if any(dep not in index for dep in data.get("depends_on", [])):
        raise TrackerError("Missing dependency; reconcile the backlog before starting.")
    assert_targets_available(data.get("targets", []), excluding_work=data["work_id"])
    actor_id = slug(args.actor)
    ensure_actor(actor_id, args.owner, args.agent)
    now = utc_now()
    data.update({
        "status": "claimed", "owner": args.owner, "agent": args.agent,
        "actor_id": actor_id, "revision": int(data["revision"]) + 1,
        "updated": iso_utc(now), "claim_expires": iso_utc(now + timedelta(hours=args.claim_hours)),
        "current_state": args.summary, "next_action": args.next_action,
        "dependency_baseline": pack_baselines({dep: int(index[dep][1]["revision"]) for dep in data.get("depends_on", [])}),
        "context_status": "current", "context_checked": iso_utc(now),
        "target_hashes": pack_hashes(hash_targets(data.get("targets", []))),
        "evidence": sorted(set(data.get("evidence", []) + args.evidence)),
    })
    write_record(path, data, build_work_body(data))
    emit_event(event_type="backlog_claimed", work=data, actor_id=actor_id,
        initiated_by=data["initiated_by"], performed_by=args.agent,
        status_before="not_started", status_after="claimed", summary=args.summary,
        changed_targets=[], hashes_before={}, hashes_after={}, change_kind="coordination",
        impact="compatible", affects=current_dependents(data["work_id"]),
        evidence=args.evidence, validation="Owner supplied review evidence; targets checked; dependency baseline refreshed.",
        limitations="A claim is not implementation or validation of historical results.", next_action=args.next_action)
    update_actor_work(actor_id, args.owner, args.agent, data["work_id"], add=True)
    print(f"Claimed backlog {data['work_id']} for {actor_id}.")


def command_change(args: argparse.Namespace) -> None:
    path, data, _ = find_work(args.work_id)
    require_owner(data, args.actor)
    if args.supersedes:
        known = {immutable_record_id(record) for _, record, _ in all_records()}
        if args.supersedes not in known:
            raise TrackerError(f"Unknown superseded record: {args.supersedes}")
    stale = stale_dependencies(data, work_index())
    if stale and args.status not in {"blocked", "pending_approval", "cancelled"}:
        raise TrackerError("Acknowledge changed dependencies before continuing: " + "; ".join(stale))
    if data.get("handoff_pending") and args.status not in {"blocked", "pending_approval", "cancelled"}:
        raise TrackerError("Accept the pending handoff before continuing.")
    if claim_is_stale(data) and args.status not in {"blocked", "pending_approval", "cancelled"}:
        raise TrackerError("The claim is stale. Renew it with heartbeat before continuing.")
    current_status = data["status"]
    new_status = args.status or ("in_progress" if current_status == "claimed" else current_status)
    if new_status not in TRANSITIONS.get(current_status, set()):
        raise TrackerError(f"Unsupported status transition: {current_status} -> {new_status}")
    changed_targets = [normalize_target(item) for item in (args.changed_target or data.get("targets", []))]
    all_targets = list(dict.fromkeys(data.get("targets", []) + changed_targets))
    assert_targets_available(all_targets, excluding_work=data["work_id"])
    before_map = unpack_hashes(data.get("target_hashes", []))
    before_changed = {target: before_map.get(target, "unrecorded") for target in changed_targets}
    after_changed = hash_targets(changed_targets)
    after_all = hash_targets(all_targets)
    undeclared = [
        target for target in data.get("targets", [])
        if before_map.get(target) != after_all[target]
        and not any(target == changed or target.startswith(changed + "/") or changed == "."
                    for changed in changed_targets)
    ]
    if undeclared:
        raise TrackerError(
            "Unrecorded changes outside the declared targets: " + ", ".join(undeclared)
            + ". Review these changes and explicitly include each affected claimed target before recording."
        )
    old_status = data["status"]
    data["targets"] = all_targets
    data["status"] = new_status
    data["revision"] = int(data["revision"]) + 1
    data["updated"] = iso_utc()
    data["current_state"] = args.summary
    data["context_status"] = "needs_sync" if stale else "current"
    data["context_checked"] = iso_utc()
    data["next_action"] = args.next_action
    data["target_hashes"] = pack_hashes(after_all)
    data["validation"] = args.validation
    data["blocker"] = args.limitations if new_status == "blocked" else ""
    passed = set(data.get("passed_criteria", []))
    for criterion in args.pass_criterion + args.fail_criterion:
        if criterion < 1 or criterion > int(data["acceptance_total"]):
            raise TrackerError("Criterion IDs must be within the acceptance checklist.")
    passed.update(args.pass_criterion)
    passed.difference_update(args.fail_criterion)
    data["passed_criteria"] = sorted(passed)
    data["acceptance_passed"] = len(passed)
    data["evidence"] = sorted(set(data.get("evidence", []) + list(args.evidence)))
    write_record(path, data, build_work_body(data))
    affects = sorted(set(current_dependents(data["work_id"]) + list(args.affects)))
    emit_event(
        event_type="change",
        work=data,
        actor_id=args.actor,
        initiated_by=data["initiated_by"],
        performed_by=data["agent"],
        status_before=old_status,
        status_after=new_status,
        summary=args.summary,
        changed_targets=changed_targets,
        hashes_before=before_changed,
        hashes_after=after_changed,
        change_kind=args.change_kind,
        impact=args.impact,
        affects=affects,
        evidence=list(args.evidence),
        validation=args.validation,
        limitations=args.limitations,
        next_action=args.next_action,
        supersedes=args.supersedes,
    )
    if new_status == "cancelled":
        update_actor_work(args.actor, data["owner"], data["agent"], data["work_id"], add=False)
    print(f"Updated {data['work_id']} to revision {data['revision']} ({new_status}).")


def command_block(args: argparse.Namespace) -> None:
    args.status = "blocked"
    args.summary = f"Blocked: {args.blocker}"
    args.limitations = args.blocker
    args.change_kind = "coordination"
    args.impact = args.impact or "unknown"
    args.changed_target = []
    args.affects = []
    args.pass_criterion = []
    args.fail_criterion = []
    args.supersedes = ""
    command_change(args)


def command_complete(args: argparse.Namespace) -> None:
    path, data, _ = find_work(args.work_id)
    require_owner(data, args.actor)
    stale = stale_dependencies(data, work_index())
    if stale:
        raise TrackerError("Acknowledge changed dependencies before verification: " + "; ".join(stale))
    if data.get("handoff_pending") or claim_is_stale(data):
        raise TrackerError("Accept the handoff and renew any stale claim before verification.")
    if data["status"] not in {"in_progress", "ready_for_review"}:
        raise TrackerError("Work can be verified only from in_progress or ready_for_review.")
    if int(data["acceptance_passed"]) != int(data["acceptance_total"]):
        raise TrackerError("All acceptance criteria must pass before verification.")
    if not args.evidence or not args.validation.strip():
        raise TrackerError("Verification requires evidence and a validation description.")
    before_status = data["status"]
    before_hashes = unpack_hashes(data.get("target_hashes", []))
    after_hashes = hash_targets(data.get("targets", []))
    drift = [target for target, digest in after_hashes.items() if before_hashes.get(target) != digest]
    if drift:
        raise TrackerError(
            "Unrecorded target changes prevent verification: " + ", ".join(drift)
            + ". Review and record the changes, then repeat the relevant validation before completing work."
        )
    data["status"] = "verified"
    data["revision"] = int(data["revision"]) + 1
    data["updated"] = iso_utc()
    data["last_verified"] = data["updated"]
    data["current_state"] = args.summary
    data["next_action"] = args.next_action
    data["validation"] = args.validation
    data["evidence"] = sorted(set(data.get("evidence", []) + list(args.evidence)))
    data["target_hashes"] = pack_hashes(after_hashes)
    write_record(path, data, build_work_body(data))
    emit_event(
        event_type="verification",
        work=data,
        actor_id=args.actor,
        initiated_by=data["initiated_by"],
        performed_by=data["agent"],
        status_before=before_status,
        status_after="verified",
        summary=args.summary,
        changed_targets=data.get("targets", []),
        hashes_before=before_hashes,
        hashes_after=after_hashes,
        change_kind="validation",
        impact=args.impact,
        affects=current_dependents(data["work_id"]),
        evidence=list(args.evidence),
        validation=args.validation,
        limitations=args.limitations,
        next_action=args.next_action,
    )
    update_actor_work(args.actor, data["owner"], data["agent"], data["work_id"], add=False)
    print(f"Verified {data['work_id']} at revision {data['revision']}.")


def command_handoff(args: argparse.Namespace) -> None:
    path, data, _ = find_work(args.work_id)
    require_owner(data, args.actor)
    if data["status"] not in ACTIVE_STATUSES:
        raise TrackerError("Only active work can be handed off.")
    from_actor = data["actor_id"]
    from_owner = data["owner"]
    from_agent = data["agent"]
    to_actor = slug(args.to_actor)
    ensure_actor(to_actor, args.to_owner, args.to_agent)
    timestamp = utc_now()
    handoff_id = f"{stamp(timestamp)}-{data['work_id']}-{unique_suffix()}"
    handoff = {
        "record_type": "handoff",
        "schema_version": SCHEMA_VERSION,
        "handoff_id": handoff_id,
        "timestamp": iso_utc(timestamp),
        "work_id": data["work_id"],
        "work_revision": int(data["revision"]) + 1,
        "from_actor": from_actor,
        "from_owner": from_owner,
        "from_agent": from_agent,
        "to_actor": to_actor,
        "to_owner": args.to_owner,
        "to_agent": args.to_agent,
        "last_verified": args.last_verified,
        "targets": data.get("targets", []),
        "evidence": list(args.evidence),
        "limitations": args.limitations,
        "next_action": args.next_action,
        "acknowledged": False,
    }
    handoff_path = ITEMS_DIR / f"HANDOFF-{handoff_id}.md"
    handoff_body = (
        f"# Handoff for {data['work_id']}\n\n"
        f"## Last verified state\n\n{args.last_verified}\n\n"
        f"## Limitations or blocker\n\n{args.limitations or 'None recorded.'}\n\n"
        f"## Next action\n\n{args.next_action}\n"
    )
    write_record(handoff_path, handoff, handoff_body, immutable=True)
    data["owner"] = args.to_owner
    data["agent"] = args.to_agent
    data["actor_id"] = to_actor
    data["status"] = "claimed"
    data["revision"] = int(data["revision"]) + 1
    data["updated"] = iso_utc(timestamp)
    data["claim_expires"] = iso_utc(timestamp + timedelta(hours=args.claim_hours))
    data["current_state"] = f"Handed off from {from_actor} to {to_actor}."
    data["next_action"] = args.next_action
    data["handoff_pending"] = True
    data["handoff_id"] = handoff_id
    write_record(path, data, build_work_body(data))
    update_actor_work(from_actor, from_owner, from_agent, data["work_id"], add=False)
    update_actor_work(to_actor, args.to_owner, args.to_agent, data["work_id"], add=True)
    print(f"Handed off {data['work_id']} from {from_actor} to {to_actor}.")


def command_acknowledge(args: argparse.Namespace) -> None:
    path, data, _ = find_work(args.work_id)
    require_owner(data, args.actor)
    dependency = slug(args.dependency)
    if dependency not in data.get("depends_on", []):
        raise TrackerError(f"{data['work_id']} does not depend on {dependency}.")
    index = work_index()
    if dependency not in index:
        raise TrackerError(f"Missing dependency: {dependency}")
    baseline = unpack_baselines(data.get("dependency_baseline", []))
    current_revision = int(index[dependency][1].get("revision", 0))
    previous_revision = baseline.get(dependency, -1)
    baseline[dependency] = current_revision
    old_status = data["status"]
    data["dependency_baseline"] = pack_baselines(baseline)
    data["revision"] = int(data["revision"]) + 1
    data["updated"] = iso_utc()
    data["current_state"] = args.summary
    data["next_action"] = args.next_action
    data["context_status"] = "current" if not stale_dependencies(data, index) else "needs_sync"
    data["context_checked"] = iso_utc()
    write_record(path, data, build_work_body(data))
    emit_event(
        event_type="dependency_acknowledgement",
        work=data,
        actor_id=args.actor,
        initiated_by=data["initiated_by"],
        performed_by=data["agent"],
        status_before=old_status,
        status_after=old_status,
        summary=f"Acknowledged {dependency} revision {current_revision}; previously {previous_revision}. {args.summary}",
        changed_targets=[],
        hashes_before={},
        hashes_after={},
        change_kind="dependency",
        impact="none",
        affects=[],
        evidence=list(args.evidence),
        validation=args.validation,
        limitations="",
        next_action=args.next_action,
    )
    print(f"Acknowledged {dependency}@{current_revision} for {data['work_id']}.")


def command_check(args: argparse.Namespace) -> None:
    _, data, _ = find_work(args.work_id)
    require_owner(data, args.actor)
    if data.get("status") not in ACTIVE_STATUSES:
        raise TrackerError("Only active work can pass mutation preflight.")
    if data.get("handoff_pending"):
        raise TrackerError("Accept the pending handoff first.")
    if claim_is_stale(data):
        raise TrackerError("Claim is stale. Renew it with heartbeat.")
    assert_targets_available(data.get("targets", []), excluding_work=data["work_id"])
    stale = stale_dependencies(data, work_index())
    drift = drift_for_work(data)
    if stale or drift:
        raise TrackerError("Mutation preflight failed: " + "; ".join(stale + drift))
    print(f"Mutation preflight passed for {data['work_id']}.")


def command_heartbeat(args: argparse.Namespace) -> None:
    path, data, body = find_work(args.work_id)
    require_owner(data, args.actor)
    if data.get("status") not in ACTIVE_STATUSES or args.claim_hours <= 0:
        raise TrackerError("Heartbeat requires active work and a positive claim duration.")
    assert_targets_available(data.get("targets", []), excluding_work=data["work_id"])
    now = utc_now()
    data["claim_expires"] = iso_utc(now + timedelta(hours=args.claim_hours))
    data["last_heartbeat"] = iso_utc(now)
    write_record(path, data, body)
    print(f"Renewed {data['work_id']} until {data['claim_expires']}.")


def command_accept_handoff(args: argparse.Namespace) -> None:
    path, data, _ = find_work(args.work_id)
    require_owner(data, args.actor)
    if not data.get("handoff_pending"):
        raise TrackerError("No pending handoff for this work item.")
    handoff_id = data.get("handoff_id", "")
    data["handoff_pending"] = False
    data["revision"] = int(data["revision"]) + 1
    data["updated"] = iso_utc()
    data["current_state"] = args.summary
    data["next_action"] = args.next_action
    write_record(path, data, build_work_body(data))
    emit_event(
        event_type="handoff_accepted", work=data, actor_id=args.actor,
        initiated_by=data["initiated_by"], performed_by=data["agent"],
        status_before=data["status"], status_after=data["status"], summary=args.summary,
        changed_targets=[], hashes_before={}, hashes_after={}, change_kind="coordination",
        impact="none", affects=[], evidence=[handoff_id],
        validation="Handoff and current target state reviewed.", limitations="",
        next_action=args.next_action,
    )
    print(f"Accepted handoff {handoff_id} for {data['work_id']}.")


def command_decision(args: argparse.Namespace) -> None:
    actor_id = slug(args.actor)
    ensure_actor(actor_id, args.owner, args.agent)
    decision_key = slug(args.decision_key)
    if any(data.get("decision_key") == decision_key for _, data, _ in records_of("decision")):
        raise TrackerError(f"Decision key already exists: {decision_key}")
    timestamp = utc_now()
    decision_id = f"{stamp(timestamp)}-{decision_key}-{unique_suffix()}"
    data = {
        "record_type": "decision",
        "schema_version": SCHEMA_VERSION,
        "decision_id": decision_id,
        "decision_key": decision_key,
        "timestamp": iso_utc(timestamp),
        "owner": args.owner,
        "agent": args.agent,
        "actor_id": actor_id,
        "initiated_by": args.initiated_by,
        "summary": args.summary,
        "rationale": args.rationale,
        "impact": args.impact,
        "affects": [slug(item) for item in args.affects],
        "evidence": list(args.evidence),
        "supersedes": args.supersedes,
    }
    path = ITEMS_DIR / f"DECISION-{decision_id}.md"
    body = (
        f"# {args.summary}\n\n"
        f"## Decision\n\n{args.summary}\n\n"
        f"## Rationale\n\n{args.rationale}\n\n"
        f"## Impact\n\n{args.impact}\n"
    )
    write_record(path, data, body, immutable=True)
    print(f"Recorded decision {decision_key}.")


def record_summary(data: dict[str, Any]) -> str:
    record_type = data.get("record_type")
    if record_type == "event":
        return f"EVENT {data.get('timestamp')} {data.get('work_id')} {data.get('summary')}"
    if record_type == "handoff":
        return f"HANDOFF {data.get('timestamp')} {data.get('work_id')} {data.get('from_actor')} -> {data.get('to_actor')}"
    if record_type == "decision":
        return f"DECISION {data.get('timestamp')} {data.get('decision_key')} {data.get('summary')}"
    return f"{record_type}: {data}"


def command_sync(args: argparse.Namespace) -> None:
    path, actor, body = ensure_actor(args.actor, args.human, args.agent)
    seen = set(actor.get("seen_records", []))
    immutable = []
    for _, data, _ in all_records():
        identifier = immutable_record_id(data)
        if identifier and identifier not in seen:
            immutable.append(data)
    immutable.sort(key=lambda item: (str(item.get("timestamp", "")), immutable_record_id(item) or ""))
    print(f"PROJECT SYNC for {actor['actor_id']}")
    print(f"{len(immutable)} new immutable record(s).")
    for data in immutable:
        print(f"- {record_summary(data)}")
    index = work_index()
    active = [data for _, data, _ in active_works()]
    print(f"\nACTIVE WORK: {len(active)}")
    for data in sorted(active, key=lambda item: item["work_id"]):
        stale = stale_dependencies(data, index)
        suffix = f" | NEEDS SYNC: {'; '.join(stale)}" if stale else ""
        print(
            f"- {data['work_id']} | {data['status']} | {data['owner']} / {data['agent']} | "
            f"{data['acceptance_passed']}/{data['acceptance_total']} | next: {data['next_action']}{suffix}"
        )
        if data.get("actor_id") == actor["actor_id"] and not args.no_ack:
            work_path, _, work_body = index[data["work_id"]]
            data["context_status"] = "needs_sync" if stale else "current"
            data["context_checked"] = iso_utc()
            write_record(work_path, data, work_body)
    if not args.no_ack:
        seen.update(identifier for data in immutable if (identifier := immutable_record_id(data)))
        actor["seen_records"] = sorted(seen)
        actor["last_sync"] = iso_utc()
        actor["updated"] = actor["last_sync"]
        write_record(path, actor, body)
        print("\nSync cursor updated.")


def drift_for_work(data: dict[str, Any]) -> list[str]:
    problems = stored_target_problems(data)
    if problems:
        return problems
    recorded = unpack_hashes(data.get("target_hashes", []))
    current = hash_targets(data.get("targets", []))
    return [
        f"{path}: recorded {recorded.get(path, 'unrecorded')}, current {digest}"
        for path, digest in current.items()
        if recorded.get(path) != digest
    ]


def command_status(_: argparse.Namespace) -> None:
    index = work_index()
    works = [data for _, data, _ in records_of("work")]
    if not works:
        print("No work records.")
        return
    for data in sorted(works, key=lambda item: item["work_id"]):
        stale = stale_dependencies(data, index)
        drift = drift_for_work(data) if data.get("status") in ACTIVE_STATUSES else []
        flags = []
        if stale:
            flags.append("NEEDS SYNC")
        if drift:
            flags.append("UNRECORDED CHANGE")
        if data.get("status") in ACTIVE_STATUSES and claim_is_stale(data):
            flags.append("STALE CLAIM")
        if data.get("handoff_pending"):
            flags.append("HANDOFF PENDING")
        flag_text = f" | {', '.join(flags)}" if flags else ""
        print(
            f"{data['work_id']} | {data['status']} | r{data['revision']} | "
            f"{data['acceptance_passed']}/{data['acceptance_total']} | "
            f"{data['owner']} / {data['agent']} | next: {data['next_action']}{flag_text}"
        )
        for detail in stale + drift:
            print(f"  - {detail}")


def command_reconcile(_: argparse.Namespace) -> None:
    problems = []
    for _, data, _ in active_works():
        for detail in drift_for_work(data):
            problems.append(f"{data['work_id']}: {detail}")
    if problems:
        print("Unrecorded target changes detected:")
        for problem in problems:
            print(f"- {problem}")
        raise TrackerError("Reconciliation failed. Record or resolve the changes before continuing.")
    print("All active target hashes match their latest work records.")


def dashboard_filter_expressions(base_text: str) -> list[str]:
    """Read generated global filter scalars, including older unquoted versions."""
    expressions = []
    for line in base_text.splitlines():
        if not line.startswith("    - "):
            continue
        expression = line[6:].strip()
        try:
            if expression.startswith('"'):
                expression = json.loads(expression)
            elif expression.startswith("'") and expression.endswith("'"):
                expression = expression[1:-1].replace("''", "'")
            elif re.search(r":(?:\s|$)|(?:^|\s)#", expression):
                # In a plain YAML scalar these introduce a mapping or comment,
                # even when they occur inside the expression's string argument.
                continue
            if not isinstance(expression, str):
                continue
            expressions.append(expression)
        except json.JSONDecodeError:
            continue
    return expressions


def configured_items_folder(base_text: str) -> str | None:
    """Read a legacy fixed-folder scope without treating it as portable."""
    for expression in dashboard_filter_expressions(base_text):
        match = re.fullmatch(r'file\.inFolder\(("(?:\\.|[^"\\])*")\)', expression)
        if match:
            return json.loads(match.group(1))
    return None


def validate_workspace() -> list[str]:
    errors: list[str] = []
    agents = PROJECT_ROOT / "AGENTS.md"
    claude = PROJECT_ROOT / "CLAUDE.md"
    base = TRACKER_DIR / "Workspace.base"
    installed_tracker = TRACKER_DIR / "project_tracker.py"
    trusted_tracker = Path(__file__).resolve()
    if not installed_tracker.exists():
        errors.append("Coordination/project_tracker.py is missing.")
    elif installed_tracker.resolve() != trusted_tracker and installed_tracker.read_bytes() != trusted_tracker.read_bytes():
        errors.append("Installed tracker differs from the trusted skill asset; review before use.")
    if not agents.exists() or "shared-project-workspace:start" not in agents.read_text(encoding="utf-8"):
        errors.append("AGENTS.md is missing the managed collaboration section.")
    else:
        home_match = re.search(r"(?m)^Project home: `([^`]+)`", agents.read_text(encoding="utf-8"))
        if home_match:
            home_label = home_match.group(1)
            try:
                portable_home = normalize_target(home_label) == home_label and not is_resource_label(home_label)
            except TrackerError:
                portable_home = False
            if not portable_home:
                errors.append("AGENTS.md has a nonportable project-home pointer. Select an existing project-relative home note and review setup --project-home <relative-note> --dry-run --upgrade-managed before updating the managed section.")
    if not claude.exists() or "AGENTS.md" not in claude.read_text(encoding="utf-8"):
        errors.append("CLAUDE.md is missing or does not point to AGENTS.md.")
    if not base.exists():
        errors.append("Coordination/Workspace.base is missing.")
    else:
        base_text = base.read_text(encoding="utf-8")
        if "__ITEMS_FOLDER__" in base_text:
            errors.append("Workspace.base still contains an unresolved folder placeholder.")
        elif PORTABLE_ITEMS_FILTER not in dashboard_filter_expressions(base_text):
            configured_folder = configured_items_folder(base_text)
            vault_root = next((root for root in (PROJECT_ROOT, *PROJECT_ROOT.parents) if (root / ".obsidian").is_dir()), PROJECT_ROOT)
            expected_folder = ITEMS_DIR.relative_to(vault_root).as_posix()
            if configured_folder != expected_folder:
                errors.append(
                    f"Workspace.base folder does not match this vault layout: expected legacy folder {expected_folder!r}, found {configured_folder!r}. Review setup --dry-run --upgrade-managed to install the portable direct-open dashboard, or preserve a legacy dashboard only when its fixed folder matches this vault."
                )
    try:
        records = all_records()
    except (TrackerError, OSError) as exc:
        return errors + [str(exc)]
    required = {
        "work": {
            "work_id", "title", "status", "revision", "owner", "agent", "actor_id",
            "initiated_by", "targets", "acceptance_total", "acceptance_passed", "created",
            "updated", "next_action", "depends_on", "dependency_baseline", "target_hashes",
        },
        "event": {
            "event_id", "event_type", "work_id", "work_revision", "timestamp", "initiated_by",
            "performed_by", "actor_id", "status_before", "status_after", "summary", "impact",
            "evidence", "validation", "next_action",
        },
        "handoff": {
            "handoff_id", "timestamp", "work_id", "from_actor", "to_actor", "to_owner",
            "to_agent", "last_verified", "targets", "next_action", "acknowledged",
        },
        "decision": {
            "decision_id", "decision_key", "timestamp", "owner", "agent", "actor_id",
            "initiated_by", "summary", "rationale", "impact",
        },
        "actor": {"actor_id", "human", "agent", "created", "updated", "seen_records", "active_work"},
    }
    ids: dict[tuple[str, str], str] = {}
    work_records: dict[str, dict[str, Any]] = {}
    active_targets: list[tuple[str, str]] = []
    for path, data, _ in records:
        record_type = data.get("record_type")
        if record_type not in required:
            errors.append(f"{path.name}: unsupported record_type {record_type!r}.")
            continue
        target_problems = stored_target_problems(data)
        errors.extend(f"{path.name}: {problem}" for problem in target_problems)
        missing = sorted(required[record_type] - set(data))
        if missing:
            errors.append(f"{path.name}: missing {', '.join(missing)}.")
        if data.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"{path.name}: unsupported schema_version {data.get('schema_version')!r}.")
        identifier = immutable_record_id(data)
        if identifier:
            key = (record_type, identifier)
            if key in ids:
                errors.append(f"Duplicate {record_type} ID {identifier}: {ids[key]} and {path.name}.")
            ids[key] = path.name
        if record_type == "work":
            work_id = data.get("work_id")
            if work_id in work_records:
                errors.append(f"Duplicate work ID: {work_id}.")
            work_records[work_id] = data
            if data.get("status") not in STATUSES:
                errors.append(f"{path.name}: unsupported status {data.get('status')!r}.")
            passed = data.get("acceptance_passed")
            total = data.get("acceptance_total")
            if not isinstance(passed, int) or not isinstance(total, int) or passed < 0 or passed > total:
                errors.append(f"{path.name}: invalid acceptance counts.")
            if passed != len(data.get("passed_criteria", [])):
                errors.append(f"{path.name}: acceptance count differs from exact passed criterion IDs.")
            if data.get("status") == "verified":
                if passed != total or not data.get("evidence") or not data.get("validation"):
                    errors.append(f"{path.name}: verified work lacks passed criteria, evidence, or validation.")
            if data.get("status") in ACTIVE_STATUSES:
                if claim_is_stale(data):
                    errors.append(f"{path.name}: stale or invalid claim expiry.")
                for target in data.get("targets", []) if not target_problems else []:
                    active_targets.append((work_id, target))
        if record_type in {"event", "decision"} and data.get("impact") not in IMPACTS:
            errors.append(f"{path.name}: unsupported impact {data.get('impact')!r}.")
        if record_type == "actor" and "@" in str(data.get("actor_id", "")):
            errors.append(f"{path.name}: actor ID appears to contain an email address.")
    for index, (work_id, target) in enumerate(active_targets):
        for other_work, other_target in active_targets[index + 1 :]:
            if work_id != other_work and targets_overlap(target, other_target):
                errors.append(f"Active target conflict: {work_id}:{target} overlaps {other_work}:{other_target}.")
    for work_id, data in work_records.items():
        for dependency in data.get("depends_on", []):
            if dependency not in work_records:
                errors.append(f"{work_id}: missing dependency {dependency}.")
        try:
            baselines = unpack_baselines(data.get("dependency_baseline", []))
            for dependency, baseline in baselines.items():
                if dependency in work_records and baseline > int(work_records[dependency].get("revision", 0)):
                    errors.append(f"{work_id}: future baseline {dependency}@{baseline}.")
        except TrackerError as exc:
            errors.append(f"{work_id}: {exc}")
        if data.get("status") in ACTIVE_STATUSES:
            for detail in drift_for_work(data):
                errors.append(f"{work_id}: unrecorded target change: {detail}")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(work_id: str, trail: list[str]) -> None:
        if work_id in visiting:
            errors.append("Dependency cycle: " + " -> ".join(trail + [work_id]))
            return
        if work_id in visited or work_id not in work_records:
            return
        visiting.add(work_id)
        for dependency in work_records[work_id].get("depends_on", []):
            visit(dependency, trail + [work_id])
        visiting.remove(work_id)
        visited.add(work_id)

    for work_id in sorted(work_records):
        visit(work_id, [])
    return errors


def command_validate(_: argparse.Namespace) -> None:
    errors = validate_workspace()
    if errors:
        print(f"Workspace validation failed with {len(errors)} error(s):")
        for error in errors:
            print(f"- {error}")
        raise TrackerError("Workspace is not valid.")
    print("Workspace is valid.")


def add_actor_arguments(parser: argparse.ArgumentParser, *, allow_registration: bool = False) -> None:
    parser.add_argument("--actor", required=True, help="Stable human-agent actor ID")
    if allow_registration:
        parser.add_argument("--human", help="Human associated with a new actor")
        parser.add_argument("--agent", help="Agent product associated with a new actor")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=WORKSPACE_TRACKER_VERSION)
    parser.add_argument("--project-root", help="Override the project root for trusted external audits")
    subparsers = parser.add_subparsers(dest="command", required=True)

    status_parser = subparsers.add_parser("status", help="Show current work and context warnings")
    status_parser.set_defaults(func=command_status)

    check_parser = subparsers.add_parser("check", help="Preflight a claimed target before mutation")
    add_actor_arguments(check_parser)
    check_parser.add_argument("--work-id", required=True)
    check_parser.set_defaults(func=command_check)

    heartbeat_parser = subparsers.add_parser("heartbeat", help="Renew an active target claim")
    add_actor_arguments(heartbeat_parser)
    heartbeat_parser.add_argument("--work-id", required=True)
    heartbeat_parser.add_argument("--claim-hours", type=int, default=8)
    heartbeat_parser.set_defaults(func=command_heartbeat)

    sync_parser = subparsers.add_parser("sync", help="Show records unseen by one actor")
    add_actor_arguments(sync_parser, allow_registration=True)
    sync_parser.add_argument("--no-ack", action="store_true", help="Do not advance the sync cursor")
    sync_parser.set_defaults(func=command_sync)

    work_arguments = argparse.ArgumentParser(add_help=False)
    claim_parser = work_arguments
    claim_parser.add_argument("--work-id", required=True)
    claim_parser.add_argument("--title", required=True)
    claim_parser.add_argument("--actor", required=True)
    claim_parser.add_argument("--owner", required=True)
    claim_parser.add_argument("--agent", required=True)
    claim_parser.add_argument("--initiated-by", required=True)
    claim_parser.add_argument("--target", action="append", required=True)
    claim_parser.add_argument("--output", action="append", default=[])
    claim_parser.add_argument("--depends-on", action="append", default=[])
    claim_parser.add_argument("--objective", required=True)
    claim_parser.add_argument("--acceptance", action="append", required=True)
    claim_parser.add_argument("--next-action", required=True)
    claim_parser.add_argument("--claim-hours", type=int, default=8)
    claim_parser.add_argument("--suggested-owner", default="")
    claim_parser.add_argument("--source-summary", default="")
    claim_parser.add_argument("--source-evidence", action="append", default=[])
    subparsers.add_parser("claim", parents=[work_arguments], help="Create and claim a new workstream").set_defaults(func=command_claim, plan_only=False)
    subparsers.add_parser("plan", parents=[work_arguments], help="Record unclaimed backlog without assigning an actor").set_defaults(func=command_claim, plan_only=True)

    start_parser = subparsers.add_parser("start", help="Claim existing backlog after reviewing its source and dependencies")
    start_parser.add_argument("--work-id", required=True)
    start_parser.add_argument("--actor", required=True)
    start_parser.add_argument("--owner", required=True)
    start_parser.add_argument("--agent", required=True)
    start_parser.add_argument("--summary", required=True)
    start_parser.add_argument("--evidence", action="append", required=True)
    start_parser.add_argument("--next-action", required=True)
    start_parser.add_argument("--claim-hours", type=int, default=8)
    start_parser.set_defaults(func=command_start)

    change_parser = subparsers.add_parser("change", help="Record a material work change")
    add_actor_arguments(change_parser)
    change_parser.add_argument("--work-id", required=True)
    change_parser.add_argument("--summary", required=True)
    change_parser.add_argument("--changed-target", action="append", default=[])
    change_parser.add_argument("--change-kind", required=True)
    change_parser.add_argument("--impact", choices=sorted(IMPACTS), required=True)
    change_parser.add_argument("--affects", action="append", default=[])
    change_parser.add_argument("--evidence", action="append", default=[])
    change_parser.add_argument("--validation", default="")
    change_parser.add_argument("--limitations", default="")
    change_parser.add_argument("--next-action", required=True)
    change_parser.add_argument("--status", choices=sorted(STATUSES))
    change_parser.add_argument("--pass-criterion", type=int, action="append", default=[])
    change_parser.add_argument("--fail-criterion", type=int, action="append", default=[])
    change_parser.add_argument("--supersedes", default="", help="Immutable record ID corrected by this event")
    change_parser.set_defaults(func=command_change)

    block_parser = subparsers.add_parser("block", help="Record a blocker")
    add_actor_arguments(block_parser)
    block_parser.add_argument("--work-id", required=True)
    block_parser.add_argument("--blocker", required=True)
    block_parser.add_argument("--impact", choices=sorted(IMPACTS), default="unknown")
    block_parser.add_argument("--evidence", action="append", default=[])
    block_parser.add_argument("--validation", default="")
    block_parser.add_argument("--next-action", required=True)
    block_parser.set_defaults(func=command_block)

    complete_parser = subparsers.add_parser("complete", help="Verify completed work")
    add_actor_arguments(complete_parser)
    complete_parser.add_argument("--work-id", required=True)
    complete_parser.add_argument("--summary", required=True)
    complete_parser.add_argument("--evidence", action="append", required=True)
    complete_parser.add_argument("--validation", required=True)
    complete_parser.add_argument("--impact", choices=sorted(IMPACTS), default="compatible")
    complete_parser.add_argument("--limitations", default="")
    complete_parser.add_argument("--next-action", default="No further action required.")
    complete_parser.set_defaults(func=command_complete)

    handoff_parser = subparsers.add_parser("handoff", help="Transfer active work")
    add_actor_arguments(handoff_parser)
    handoff_parser.add_argument("--work-id", required=True)
    handoff_parser.add_argument("--to-actor", required=True)
    handoff_parser.add_argument("--to-owner", required=True)
    handoff_parser.add_argument("--to-agent", required=True)
    handoff_parser.add_argument("--last-verified", required=True)
    handoff_parser.add_argument("--limitations", default="")
    handoff_parser.add_argument("--evidence", action="append", default=[])
    handoff_parser.add_argument("--next-action", required=True)
    handoff_parser.add_argument("--claim-hours", type=int, default=8)
    handoff_parser.set_defaults(func=command_handoff)

    accept_handoff_parser = subparsers.add_parser("accept-handoff", help="Acknowledge receipt of active work")
    add_actor_arguments(accept_handoff_parser)
    accept_handoff_parser.add_argument("--work-id", required=True)
    accept_handoff_parser.add_argument("--summary", required=True)
    accept_handoff_parser.add_argument("--next-action", required=True)
    accept_handoff_parser.set_defaults(func=command_accept_handoff)

    acknowledge_parser = subparsers.add_parser("acknowledge", help="Acknowledge an upstream revision")
    add_actor_arguments(acknowledge_parser)
    acknowledge_parser.add_argument("--work-id", required=True)
    acknowledge_parser.add_argument("--dependency", required=True)
    acknowledge_parser.add_argument("--summary", required=True)
    acknowledge_parser.add_argument("--evidence", action="append", default=[])
    acknowledge_parser.add_argument("--validation", default="Dependency revision inspected.")
    acknowledge_parser.add_argument("--next-action", required=True)
    acknowledge_parser.set_defaults(func=command_acknowledge)

    decision_parser = subparsers.add_parser("decision", help="Record an immutable project decision")
    decision_parser.add_argument("--decision-key", required=True)
    decision_parser.add_argument("--actor", required=True)
    decision_parser.add_argument("--owner", required=True)
    decision_parser.add_argument("--agent", required=True)
    decision_parser.add_argument("--initiated-by", required=True)
    decision_parser.add_argument("--summary", required=True)
    decision_parser.add_argument("--rationale", required=True)
    decision_parser.add_argument("--impact", choices=sorted(IMPACTS), required=True)
    decision_parser.add_argument("--affects", action="append", default=[])
    decision_parser.add_argument("--evidence", action="append", default=[])
    decision_parser.add_argument("--supersedes", default="")
    decision_parser.set_defaults(func=command_decision)

    reconcile_parser = subparsers.add_parser("reconcile", help="Detect unrecorded target changes")
    reconcile_parser.set_defaults(func=command_reconcile)

    validate_parser = subparsers.add_parser("validate", help="Validate the collaboration workspace")
    validate_parser.set_defaults(func=command_validate)
    return parser


def main() -> int:
    global PROJECT_ROOT, TRACKER_DIR, ITEMS_DIR
    try:
        args = build_parser().parse_args()
        if args.project_root:
            PROJECT_ROOT = Path(args.project_root).expanduser().resolve()
            TRACKER_DIR = PROJECT_ROOT / "Coordination"
            ITEMS_DIR = TRACKER_DIR / "Items"
        args.func(args)
        return 0
    except TrackerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
