> **Historical advisory toolkit reference.** This applies only when that older tracker is explicitly selected. Normal Shared Memory 0.3.0 uses direct folder editing; see [product runtime routing](product-runtime.md).

# Retrofit policy

Retrofitting must preserve the target project's existing authority and history.

## Inspect first

Read the target's governing instructions and inventory root-level Markdown, existing
status or work logs, coordination folders, `.obsidian`, `.git`, and linked external
systems. Select one existing project home in this order: an explicit path, `Home.md`,
`README.md`, a root note matching the directory name, then a root note with
`type: project`. The resolved home must be a file inside the project root; its shared
pointer is stored relative to that root using forward slashes.

## Managed sections

The setup script owns only content between its explicit markers in `AGENTS.md` and
`CLAUDE.md`. On repeat runs it replaces that section in place. It appends the section to
an existing file when no marker exists and never rewrites the surrounding content.

Generated `Workspace.base` and `project_tracker.py` include generator signatures. A
changed generated file or managed instruction section is treated as drift. Review the
diff, then use `--upgrade-managed` only when replacement is authorized. Preserve an
unsigned conflicting file and stop rather than treating it as generated content.

Audit runs the trusted tracker bundled with the skill against the target root. It does
not execute the target project's tracker. It also reports drift in the installed tracker.

## Legacy material

Do not automatically import, rewrite, split, archive, or delete old logs, memory notes,
decision notes, task systems, or historical status documents. Link them as legacy
sources only after their authority and mapping are clear. A plan, checklist, or old log
is not current state without reconciliation.

When the user authorizes reconciliation, use `project_tracker.py plan` to record
source-linked follow-ups without taking claims on other contributors' targets.
`--owner` identifies the recording human; `--suggested-owner` is advisory only.
Preserve original status and date in `--source-summary`, with `--source-evidence`.
The real owner later uses `start` after reviewing that evidence and dependencies.
Do not import historical percentages as passed criteria for a new follow-up.

## Idempotence

A second setup run with the same inputs must not duplicate managed sections, create a
second project home, or create a second workspace-setup decision. Audit and validation
must distinguish a valid installed workspace from a partially configured one.

## Collaboration mode

- `local-only`: explicitly record local work with no remote propagation requirement.
- `shared-folder`: use target hashes and reconciliation records for non-Git files.
- `git`: store branch and commit evidence; Git controls exact diffs.
- `hybrid`: use both and record which system controls each target.

Automatic mode selects Git when the target or an enclosing directory contains `.git`;
otherwise it selects shared-folder. This is a tracker mode, not a provider choice.
For new explicitly local work, choose local-only. Older local projects may still
record shared-folder; review their actual access method rather than silently
changing an existing managed section.
Select hybrid explicitly when documentation and implementation have different homes.

## Portability upgrades

Audit existing records and the actual vault layout before upgrading the tracker.
Version 1.2.0 stores in-project file targets as relative POSIX paths, rejects external
or home-relative paths, and diagnoses nonportable stored targets rather than silently
rewriting them. A generated-file upgrade is not a record migration. Existing legacy
records may need an explicitly reviewed mapping and migration before validation can
pass; preserve immutable history and do not remove another contributor's claims.
There is no automatic record migration. Superseding a record alone does not clear
legacy-path diagnostics in retained historical records.

Version 1.3.0 generates a location-independent dashboard for direct main-content
opening. Do not embed it or treat a contextual sidebar as the same query context.
Legacy fixed-path dashboards still report layout mismatches; upgrading their
managed generated content requires review. See [project-folder-sharing.md](project-folder-sharing.md).

Version 1.3.0 also replaces the old `directory` and `too-large` fingerprint
sentinels with content hashes. Existing active work using those sentinels will
correctly report drift until its owner reviews the actual target content and
records a change to establish the new baseline, with evidence and validation.
Keep historical events unchanged. Review all changed claimed targets explicitly;
`complete` now refuses unrecorded target drift. Prefer bounded targets because
recursive hashing reads descendant files. Directory claims reject symbolic links;
use reviewed exact file targets where appropriate.
