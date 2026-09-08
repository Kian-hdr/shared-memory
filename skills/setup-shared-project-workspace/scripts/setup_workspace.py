#!/usr/bin/env python3
"""Bootstrap, retrofit, or audit a lean shared project workspace."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"
MANAGED_START = "<!-- shared-project-workspace:start schema=1 -->"
MANAGED_END = "<!-- shared-project-workspace:end -->"
GENERATED_SIGNATURE = "generated-by: setup-shared-project-workspace"
PORTABLE_ITEMS_FILTER = 'this.file.ext == "base" && file.inFolder(this.file.folder + "/Items")'


class SetupError(RuntimeError):
    pass


def infer_project_home(target: Path, explicit: str | None) -> tuple[Path, bool]:
    def checked_home(candidate: Path) -> Path:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(target):
            raise SetupError("Project home must be inside the project root so it can be shared. Use a project-relative Markdown file.")
        if not resolved.is_file():
            raise SetupError(f"Project home is not a file: {candidate}")
        return resolved

    if explicit:
        candidate = Path(explicit.replace("\\", "/"))
        candidate = candidate if candidate.is_absolute() else target / candidate
        return checked_home(candidate), False
    readme = target / "README.md"
    for candidate in (target / "Home.md", readme):
        if candidate.exists():
            return checked_home(candidate), False
    named = target / f"{target.name}.md"
    if named.exists():
        return checked_home(named), False
    excluded = {"AGENTS.md", "CLAUDE.md"}
    for candidate in sorted(target.glob("*.md")):
        if candidate.name in excluded:
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")[:4096]
        if "type: project" in text:
            return checked_home(candidate), False
    return readme, True


def collaboration_mode(target: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    return "git" if any((root / ".git").exists() for root in (target, *target.parents)) else "shared-folder"


def detected_mode(target: Path, requested: str) -> str:
    if requested != "auto":
        return requested
    visible = [item for item in target.iterdir() if item.name not in {".DS_Store"}]
    return "retrofit" if visible else "bootstrap"


def find_vault_root(target: Path) -> Path | None:
    for candidate in (target, *target.parents):
        if (candidate / ".obsidian").is_dir():
            return candidate
    return None


def dashboard_content(items_folder: str | None = None) -> str:
    template = (ASSETS / "workspace.base").read_text(encoding="utf-8")
    if items_folder is None:
        return template
    # Retain explicit fixed-folder rendering for inspected legacy dashboards.
    expression = f"file.inFolder({json.dumps(items_folder, ensure_ascii=False)})"
    # JSON strings are YAML double-quoted scalars. Quote the whole expression as
    # well as its argument so colons, apostrophes and quotes in paths stay text.
    return template.replace(
        "'" + PORTABLE_ITEMS_FILTER + "'", json.dumps(expression, ensure_ascii=False)
    )


def managed_section(project_name: str, project_home: str, mode: str) -> str:
    return f"""{MANAGED_START}
## Shared project coordination

This project is coordinated by multiple people and AI agents. These rules apply in
addition to all project-specific instructions above. When rules conflict, preserve the
more specific scope, safety, security, approval, and evidence constraint.

Project: **{project_name}**  
Project home: `{project_home}`  
Collaboration mode: `{mode}`  
Coordination schema: `1`
Workspace skill: `setup-shared-project-workspace`
Workspace skill version: `1.3.0`

### Canonical state

- Read the project home for purpose, scope, team, systems of record, and deliverables.
- Current work lives in `Coordination/Items/WORK-*.md`.
- Immutable change, handoff, and decision records preserve history.
- Open `Coordination/Workspace.base` directly in Obsidian's main content area.
  Its scope follows this shared project's location inside each person's own vault.
  Embedding the dashboard or placing it in a sidebar changes its query context and
  is unsupported. Keep private parent-vault folders and settings outside the share.
- Git controls exact code diffs when present; coordination records control ownership,
  semantic progress, dependencies, impact, evidence, and handoff context.

### Required checkpoints

At session start, run:

```bash
python3 Coordination/project_tracker.py sync --actor <actor-id> --human <human-name> --agent <agent-name>
python3 Coordination/project_tracker.py status
```

Before mutation, claim a bounded work ID and every exact file, directory, branch,
environment, or artifact target. One active owner may mutate a target at a time. A
directory claim conflicts with descendants. Synchronize again immediately before
integration or when the target changed since the claim.

Store file targets and the project-home pointer relative to the project root, using
forward slashes. Absolute local file inputs inside the project are converted to this
form. Home shortcuts, paths outside the project, and parent traversal are rejected.
Use agreed portable labels for non-file resources; these labels are advisory and are
not live branch, environment, or artifact checks.

Use `plan` for unclaimed backlog; its actor/owner identify the recorder, while
`--suggested-owner` is not an assignment. Preserve historical context with
`--source-summary` and `--source-evidence`. `not_started` refers to the follow-up,
not the entire historical project. The actual owner uses `start` with review evidence
to claim existing backlog. Neither command resumes paused work or grants approval.

Run `python3 Coordination/project_tracker.py check --actor <actor-id> --work-id <work-id>`
immediately before mutation. Renew an active claim with `heartbeat` when needed. Accept
a received handoff with `accept-handoff` before continuing. Use `--pass-criterion N`
and `--fail-criterion N` on `change` to update exact acceptance-criterion IDs.

After each material state change, record it with `project_tracker.py change`. Material
changes include deliverable or interface changes, status or ownership changes,
decisions, blockers, approval waits, validation outcomes, handoffs, and completion. Do
not record every read or low-signal command.

Before stopping, update acceptance state, validation, evidence, limitation, exact next
action, and owner. Create a handoff when another actor must continue. Never rewrite or
delete immutable records; supersede an incorrect record with a correction.

### Status and evidence

Allowed statuses are `not_started`, `claimed`, `in_progress`, `blocked`,
`pending_approval`, `ready_for_review`, `verified`, and `cancelled`. Progress is the
number of passed acceptance criteria, not an unsupported percentage. `verified`
requires every acceptance criterion plus recorded validation and evidence.

Every material change declares impact as `none`, `compatible`, `breaking`, or
`unknown`. Work revisions and dependency baselines determine whether downstream work
needs synchronization. Breaking or unknown upstream changes must be reviewed before
dependent work continues.

### Attribution and boundaries

Record human initiator, owner, agent, stable actor ID, UTC timestamp, exact targets,
status, evidence, limitations, and next action. Actor identity is declarative, not
cryptographically authenticated.

Do not store credentials, tokens, cookies, access codes, payment data, email addresses
as actor IDs, private live endpoints, or large artifacts in coordination records. This
workspace does not authorize invitations, permission changes, publication, deployment,
purchases, account changes, destructive actions, or external messages.

Synchronized folders do not provide transactional locking. Context becomes current at
the required checkpoints, not continuously in real time.
{MANAGED_END}"""


def claude_section() -> str:
    return f"""{MANAGED_START}
Read and follow `AGENTS.md` completely before performing any work in this project.

`AGENTS.md` is the canonical project instruction file. Do not duplicate or override its
instructions here.
{MANAGED_END}"""


def merge_managed(path: Path, title: str, section: str, *, dry_run: bool) -> str:
    if path.exists():
        original = path.read_text(encoding="utf-8")
        if MANAGED_START in original:
            start = original.index(MANAGED_START)
            end_index = original.find(MANAGED_END, start)
            if end_index < 0:
                raise SetupError(f"Managed section is incomplete in {path}")
            end = end_index + len(MANAGED_END)
            updated = original[:start].rstrip() + "\n\n" + section + original[end:]
            action = "updated managed section"
        else:
            updated = original.rstrip() + "\n\n" + section + "\n"
            action = "appended managed section"
    else:
        updated = f"# {title}\n\n{section}\n"
        action = "created"
    if not dry_run:
        path.write_text(updated, encoding="utf-8")
    return action


def install_generated(source: Path, destination: Path, content: str | bytes, *, dry_run: bool) -> str:
    if destination.exists():
        existing = destination.read_bytes() if isinstance(content, bytes) else destination.read_text(encoding="utf-8", errors="replace")
        signature = GENERATED_SIGNATURE.encode("utf-8") if isinstance(content, bytes) else GENERATED_SIGNATURE
        if signature not in existing:
            raise SetupError(f"Refusing to replace unsigned existing file: {destination}")
        action = "unchanged" if existing == content else "updated generated file"
    else:
        action = "created"
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            destination.write_bytes(content)
        else:
            destination.write_text(content, encoding="utf-8")
        if source.suffix == ".py":
            destination.chmod(0o755)
    return action


def audit(target: Path, project_home: Path, home_would_create: bool) -> list[str]:
    findings = []
    agents = target / "AGENTS.md"
    claude = target / "CLAUDE.md"
    coordination = target / "Coordination"
    findings.append(f"project home: {project_home.relative_to(target) if project_home.is_relative_to(target) else project_home}")
    if home_would_create:
        findings.append("missing project home: README.md would be created")
    findings.append("AGENTS.md: managed section present" if agents.exists() and MANAGED_START in agents.read_text(encoding="utf-8") else "AGENTS.md: missing managed section")
    findings.append("CLAUDE.md: canonical adapter present" if claude.exists() and "AGENTS.md" in claude.read_text(encoding="utf-8") else "CLAUDE.md: missing canonical adapter")
    findings.append("Workspace.base: present" if (coordination / "Workspace.base").exists() else "Workspace.base: missing")
    findings.append("project_tracker.py: present" if (coordination / "project_tracker.py").exists() else "project_tracker.py: missing")
    findings.append("Items directory: present" if (coordination / "Items").is_dir() else "Items directory: missing")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="Project root")
    parser.add_argument("--mode", choices=["auto", "bootstrap", "retrofit", "audit"], default="auto")
    parser.add_argument("--project-name")
    parser.add_argument("--project-home")
    parser.add_argument("--purpose", help="Required only when a new README.md project home is created")
    parser.add_argument("--collaboration-mode", choices=["auto", "local-only", "shared-folder", "git", "hybrid"], default="auto")
    parser.add_argument("--actor", help="Stable actor ID for the setup decision")
    parser.add_argument("--initiated-by", help="Human who initiated setup")
    parser.add_argument("--agent", help="Agent that performed setup")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--upgrade-managed", action="store_true", help="Allow reviewed changes to managed sections and signed generated files")
    args = parser.parse_args()

    try:
        target = Path(args.target).expanduser().resolve()
        if not target.exists() or not target.is_dir():
            raise SetupError(f"Target is not a directory: {target}")
        mode = detected_mode(target, args.mode)
        project_name = args.project_name or target.name
        project_home, home_would_create = infer_project_home(target, args.project_home)
        collab_mode = collaboration_mode(target, args.collaboration_mode)

        if mode == "audit":
            print(f"Audit: {target}")
            for finding in audit(target, project_home, home_would_create):
                print(f"- {finding}")
            tracker = target / "Coordination" / "project_tracker.py"
            if tracker.exists():
                result = subprocess.run([sys.executable, str(ASSETS / "project_tracker.py"), "--project-root", str(target), "validate"], check=False)
                return result.returncode
            return 1

        if not args.actor or not args.initiated_by or not args.agent:
            raise SetupError("Setup requires --actor, --initiated-by, and --agent for attribution.")
        if home_would_create and not args.purpose:
            raise SetupError("Creating a new project home requires --purpose.")

        home_label = project_home.relative_to(target).as_posix()
        coordination = target / "Coordination"
        items = coordination / "Items"
        planned = {
            "Coordination/Workspace.base": dashboard_content(),
            "Coordination/project_tracker.py": (ASSETS / "project_tracker.py").read_bytes(),
        }

        for relative in ("Coordination/Workspace.base", "Coordination/project_tracker.py"):
            existing = target / relative
            if existing.exists():
                expected = planned[relative]
                content = existing.read_bytes() if isinstance(expected, bytes) else existing.read_text(encoding="utf-8", errors="replace")
                signature = GENERATED_SIGNATURE.encode("utf-8") if isinstance(expected, bytes) else GENERATED_SIGNATURE
                if signature not in content:
                    raise SetupError(f"Refusing to replace unsigned existing file: {existing}")
                if content != planned[relative] and not args.upgrade_managed:
                    raise SetupError(f"Generated file has drifted: {existing}. Review the diff and use --upgrade-managed only when its replacement is authorized.")
        for name in ("AGENTS.md", "CLAUDE.md"):
            existing = target / name
            if existing.exists():
                text = existing.read_text(encoding="utf-8")
                if (MANAGED_START in text) != (MANAGED_END in text):
                    raise SetupError(f"Managed section is incomplete in {existing}")
                if MANAGED_START in text:
                    start = text.index(MANAGED_START)
                    end = text.index(MANAGED_END, start) + len(MANAGED_END)
                    expected = managed_section(project_name, home_label, collab_mode) if name == "AGENTS.md" else claude_section()
                    if text[start:end] != expected and not args.upgrade_managed:
                        raise SetupError(f"Managed section has drifted: {existing}. Review the diff before --upgrade-managed.")

        actions = []
        if home_would_create:
            vault_root = find_vault_root(target)
            frontmatter = ""
            if vault_root:
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                summary = args.purpose.strip().replace("\n", " ")
                frontmatter = (
                    f"---\ntitle: README\ntype: project\ntags: []\nstatus: active\n"
                    f"created: {today}\nupdated: {today}\nsummary: {summary!r}\n"
                    f"verified: asserted\nconfidence: medium\nchecked: {today}\n---\n"
                )
            content = (
                frontmatter + f"# {project_name}\n\n{args.purpose.strip()}\n\n"
                "## Collaboration\n\n"
                "- Agent instructions: [AGENTS.md](AGENTS.md)\n"
                "- Project dashboard: [Coordination/Workspace.base](Coordination/Workspace.base)\n"
            )
            if not args.dry_run:
                project_home.write_text(content, encoding="utf-8")
            actions.append(f"created project home {home_label}")
        else:
            actions.append(f"reused project home {home_label}")

        agents_action = merge_managed(
            target / "AGENTS.md",
            "Project agent instructions",
            managed_section(project_name, home_label, collab_mode),
            dry_run=args.dry_run,
        )
        actions.append(f"{agents_action}: AGENTS.md")
        claude_action = merge_managed(
            target / "CLAUDE.md",
            "Claude project instructions",
            claude_section(),
            dry_run=args.dry_run,
        )
        actions.append(f"{claude_action}: CLAUDE.md")

        if not args.dry_run:
            items.mkdir(parents=True, exist_ok=True)
        actions.append("ensured Coordination/Items")

        base_content = planned["Coordination/Workspace.base"]
        actions.append(
            f"{install_generated(ASSETS / 'workspace.base', coordination / 'Workspace.base', base_content, dry_run=args.dry_run)}: Coordination/Workspace.base"
        )
        tracker_content = planned["Coordination/project_tracker.py"]
        actions.append(
            f"{install_generated(ASSETS / 'project_tracker.py', coordination / 'project_tracker.py', tracker_content, dry_run=args.dry_run)}: Coordination/project_tracker.py"
        )

        print(f"Mode: {mode}")
        for action in actions:
            print(f"- {action}")
        if args.dry_run:
            print("Dry run: no files changed.")
            return 0

        decision_command = [
            sys.executable,
            str(coordination / "project_tracker.py"),
            "decision",
            "--decision-key", "workspace-setup-v1",
            "--actor", args.actor,
            "--owner", args.initiated_by,
            "--agent", args.agent,
            "--initiated-by", args.initiated_by,
            "--summary", "Established the shared project coordination workspace",
            "--rationale", "Use one canonical instruction contract and structured records for current state, changes, dependencies, decisions, and handoffs.",
            "--impact", "compatible",
            "--evidence", "AGENTS.md",
            "--evidence", "CLAUDE.md",
            "--evidence", "Coordination/Workspace.base",
            "--evidence", "Coordination/project_tracker.py",
        ]
        existing_decision = any(
            "decision_key: \"WORKSPACE-SETUP-V1\"" in path.read_text(encoding="utf-8", errors="replace")
            for path in items.glob("DECISION-*.md")
        )
        if not existing_decision:
            subprocess.run(decision_command, check=True)
        result = subprocess.run([sys.executable, str(coordination / "project_tracker.py"), "validate"], check=False)
        return result.returncode
    except (SetupError, OSError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
