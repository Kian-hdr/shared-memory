# Direct-folder contract for Shared Memory 0.3.0

This is the current default workflow. `ENGINE-CONTRACT.md` describes the explicitly
retained historical coordinator, not the rules for ordinary folder editing.

## Interfaces and storage

`folder.py` implements `Folder(root, state)`, `initialize`, `attach`, `sync`, `status`,
`history(path=None)`, `resolve(path, text, evidence)`, `delete(path, evidence)` and
`rename(source, destination, evidence)`. `folder_merge.py` reconstructs per-path
history and merges compatible text. `folder_workflow.py` exposes the CLI, while
`folder_migration.py` handles the separate backed-up coordinator conversion.

The selected project's `.shared-memory.json` uses `format_version: 3` and
`workflow: folder`, with its project UUID and one provider. `.shared-memory/` holds
shared immutable events and conflict observations. Private device state holds
`folder.json`, baseline, cached history and recovery material; it is not shared.
No SQLite, session credential or designated integration owner is required in this
workflow. Older formats must be retained or explicitly migrated, never silently
reinterpreted by new setup.

An event contains format, project ID, kind, self-asserted author labels, per-path
parent heads/base text, changes, evidence and an optional rename descriptor. Supported
kinds are initial, edit, resolve, delete and rename. Content-derived event identifiers
and validation detect malformed or changed records; they do not authenticate a human
or make history resistant to every hostile actor with direct folder access.

## Capture and reconciliation

People and agents edit ordinary Markdown directly. A save persists a local file;
calling sync captures the currently observed bytes against the prior private causal
baseline before reconciliation. Bytes may have arrived through a provider, so the
capture author is not necessarily the originating writer. No edit event means
approved, reviewed or factually correct.

Per-path heads describe known ancestry rather than a single coordinator revision.
Duplicate/idempotent event delivery must not duplicate logical history. Unknown or
missing parents and invalid events remain explicit; incomplete delivery does not
justify replacing them with a guessed latest version. The baseline/history and
journal support restarting after interrupted local materialization without discarding
raced edits.

Identical versions converge. Independent line edits with one usable common base may
merge. Overlap, conflicting creation/deletion or ambiguous ancestry preserves a
conflict. Semantic contradictions can exist even in a conflict-free text merge;
this core does not interpret all prose or require a reviewer before a save.

An authorized writable editor can resolve with supplied text and evidence. Explicit
read-only bindings forbid shared writes; provider/OS ACLs remain the access boundary.
There is no hidden automatic acceptance or permanently appointed resolver.

Missing files alone are not deletions. Delete records explicit intent and keeps old
history. Rename records source deletion and destination creation in one event;
its filesystem application is recoverable, not a multi-file atomic transaction.
It does not rewrite Markdown/wiki backlinks. Destination collisions and raced changes
must remain visible rather than overwritten to complete the command.

## Boundaries and limits

Discovery is Markdown-focused with private/hidden/runtime and nested coordination
exclusions. Previously managed required paths remain managed. Name filters are not
a general secret classifier. Shared historical versions can retain deleted text.

Current limits include 10 MiB per UTF-8 file, 100 MiB per validated file map,
10,000 files/changes, 20,000 visible events, 512 MiB loaded history, 128 MiB per event,
256 parent heads per changed path and 16 KiB nonempty evidence. Hitting a limit
must not trigger automatic history deletion. Archive/compaction and hostile-writer
consensus are not promised by this version.

A provider can overwrite bytes before a local sync captures them. The engine cannot
recover a never-captured version from nothing; retain provider history/backups and
capture before reconnect where practical. Provider conflict-copy detection is a
filename heuristic, not proof every copy is found or uploaded. The runtime does not
provision a provider, bridge clouds, watch forever, or prove independent receipt.

## Migration and acceptance

`migrate-folder` plans by default and changes workflow only with `--apply`. It uses
the complete local old authority, verifies a fresh private backup, preserves old
metadata/history/current notes and retains identity. Missing files, changed source
or incomplete recovery cannot be silently replaced. Pending coordinator proposals
remain historical records, not newly approved work. Provider ACLs are not created
from an archived membership roster.

See [the operating guide](../docs/PRODUCT-V1.md), [acceptance scenarios](../docs/TEAM-ACCEPTANCE.md)
and [validation](../VALIDATION.md). Existing coordinator test counts do not establish
folder/provider acceptance; exact completed results must be recorded separately.

## Concurrent rename intent

Concurrent same-source moves to distinct destinations retain both copies. Status
reports `rename_divergences` and a `rename_intent_divergence` warning; readiness can
still be ready for converged bytes. This does not establish agreed intent. An
editing member can acknowledge the retained copies with evidence through existing
resolution or deletion of the original source, without an approval role.

## Interrupted pre-cutover planning

Explicit `migrate-folder --replan` may replace a superseded pre-cutover intent only
with a fresh private backup directory, unchanged project identity and an editing
historical member. Applying it preserves the old intent and backup. Once the
format changes or new folder state exists, only the original recovery path can
resume; replan cannot reset that history.
