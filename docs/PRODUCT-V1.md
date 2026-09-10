# Shared Memory 0.3.0 operating guide

Shared Memory now defaults to **direct editing in a shared Markdown folder**.
Save notes in your normal editor, including offline. Run `sync` to capture the bytes
this computer observes and reconcile visible history. The selected provider handles
transport on reconnect. There is no mandatory proposal, integrator, coordinator
server or hidden automatic approval. Reviews are optional after edits.

Obsidian is optional. Choose an ordinary project folder or one shared subfolder
inside an existing private vault. The selected folder is the boundary; setup does
not register a vault or grant access to its parent. [Diagrams](DIAGRAMS.md) show
people, agents, files, history and recovery.

## Agent-guided setup

[Paste the setup prompt](../SETUP-PROMPT.md) into an agent connected to your computer,
select the folder and let it complete local setup. Normal use does not require a
disposable trial. Python 3.11+ and the verified package are required; the local
folder engine uses the standard library. The optional historical coordinator's
server dependencies are not needed for folder mode.

Use the exact release at [v0.3.0](https://github.com/Kian-hdr/shared-memory/releases/tag/v0.3.0)
only when its assets are present. The expected executable is
`shared-memory-0.3.0.pyz`, with external `SHA256SUMS`; an explicitly supplied reviewed
candidate is also usable. Internal package hashes do not independently authenticate
the publisher. Compare the external SHA before executing a download:

```text
python -c "import hashlib,pathlib,sys; actual=hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(); print(actual); sys.exit(0 if actual == sys.argv[2].lower() else 1)" PACKAGE.pyz EXPECTED_SHA256
python PACKAGE.pyz version
python PACKAGE.pyz capabilities
python PACKAGE.pyz guide
python PACKAGE.pyz install-package PACKAGE.pyz --sha256 EXPECTED_SHA256 --tools-dir PRIVATE_TOOLS
```

Replace terminal placeholders with actual recipient paths, quoting spaces. On Windows
use the installed compatible Python launcher; on macOS/Linux use the discovered
interpreter. `install-package` returns the immutable installed package path under
`versions/<sha256>.pyz`. Use that exact file for subsequent commands. It does not
install an interpreter, globally alter PATH, provision a provider or deploy a service.

## Set up and join

```text
python PACKAGE.pyz setup PROJECT
```

The selected folder must already exist; the agent may create the ordinary new folder
the user chose. Setup defaults to `--workflow folder` and Markdown discovery. It
creates a new project only when no existing project/history indicates joining or
migration. A delivered format-3 folder is joined using the recipient's own device
identity and private baseline. No member token or coordinator endpoint is needed.
If you expect a particular project, supply `--expected-project-id` so missing or
mismatched metadata cannot silently become a new project.

Optional setup inputs are `--state-dir`, `--actor`, `--person`, `--agent`,
`--expected-project-id`, `--provider` and `--read-only`. Providers are `local`,
`google-drive`, `icloud`, `onedrive`, `nextcloud` and `self-hosted`. The choice records
one intended route; it does not log in or prove delivery. Identity defaults are
stored once. Explicit conflicting identity/provider inputs are refused on resume.
Actor/person labels record capture provenance, not verified human authorship.

Each device's default state is beneath its private application-data location:
`Shared Memory/projects/<hash-of-selected-root>/folder`. macOS uses
`~/Library/Application Support`, Windows uses `LOCALAPPDATA`, and Linux uses
`XDG_STATE_HOME` or `~/.local/state`. A supplied state path overrides discovery.
The returned `state_dir` is the actual folder-state path. When an old coordinator
state base is supplied after migration, discovery uses its `folder` child.
Keep this state outside consumer-sync storage and the shared project.

Use `--read-only` when attaching a reader. The binding forbids Shared Memory writes;
provider and OS rights remain authoritative too. Omitting the flag on a later setup
does not silently widen a saved read-only binding. Requesting it for an existing
writable binding is refused rather than silently changing or ignoring access intent.
Creating a new project requires a writable editor.

## What is shared

| Location | Contents |
| --- | --- |
| Selected folder | Live Markdown notes, preserved unrelated artifacts, portable `.shared-memory.json` format-3 identity |
| Shared `.shared-memory/` | Immutable event history and conflict observations, deliberately transported with the folder |
| Private device state | `folder.json` binding, baseline, cached history and recovery journal/copies |
| Old coordinator state after migration | Preserved SQLite/history and private migration inputs, outside the share |

Normal discovery includes `.md` and `.markdown`, with hidden/private runtime paths
and nested legacy `Coordination` excluded. Already managed historical paths remain
subject to their validation, even if non-Markdown. Arbitrary Markdown may contain
sensitive information: exclusions do not classify content or create permissions.
All shared history can retain earlier note content, including text later removed
from the live note. Share it only with the intended audience.

Use actual downloaded files and safe physical paths. A provider placeholder, unsafe
link or unsupported filename is not fixed by calling it a synchronized file. The
provider must transport the metadata and event history as well as live notes.
See [provider routes and limitations](PROVIDERS.md).

## Edit, capture and reconnect

```text
python PACKAGE.pyz folder-status PROJECT
python PACKAGE.pyz sync PROJECT
python PACKAGE.pyz history PROJECT
python PACKAGE.pyz history PROJECT --path Notes/Plan.md
```

People and agents edit live notes directly. Saving persists the file immediately;
`sync` then records observed changes against this device's previous baseline before
reconciling incoming history. Observed changes may have come from a local editor or
a provider download. The capture actor is not proof of who originally authored them.

The provider uploads/downloads on its own schedule. Capture local edits before
reconnect when practical: a provider overwrite before capture can destroy a version
that Shared Memory has never recorded, so provider history/backups remain useful. Run sync again after reconnection
or delivered files arrive. The command is one-shot, not a background AI service.
An optional bounded loop is available:

```text
python PACKAGE.pyz watch PROJECT --interval 5 --cycles 12
```

This repeats sync for the stated cycles and stops. It does not wake an AI, perform
semantic review, install an autostart service or guarantee future provider receipt.
A read-only binding can inspect status/history but cannot run sync or other writes.

`folder-status` reports readiness, visible history hash/event count, per-path heads,
conflicts, deferred/invalid events, missing or partial files and uncaptured local
changes. Inspect these fields even when a command executes successfully. `ready`
means the local view is consistent with currently visible history, not that every
remote device is online, current or semantically correct. Do not clean up incomplete
history to remove a warning; allow delivery to finish and preserve the evidence.

## Merge, review and resolve

Independent non-overlapping line edits with a usable common base can merge. Overlaps,
competing creation/deletion and ambiguous ancestry preserve competing versions.
Conflict observations live under `.shared-memory/conflicts/`; an older report may
remain after resolution, so check current status rather than deleting history.

No general semantic agreement is inferred. Two changes on different lines may still
contradict each other. A person or agent may review after the work and record the
reason and evidence for a correction. Any editor with the folder's actual editing
rights may resolve; no designated integrator must be online:

```text
python PACKAGE.pyz resolve PROJECT --path Notes/Plan.md --text-file REVIEWED_TEXT.md --evidence "Compared both versions and checked the supporting source"
```

The supplied file contains the intended UTF-8 result, not instructions for automatic
approval. Keep all competing versions until the recorded resolution is verified.
Provider conflict-copy recognition is only a filename heuristic. Inspect originals
and unrecognized copies too, especially when the provider kept a conflict locally
without uploading it. A textual merge is not proof that a fact is correct.

## Delete and rename deliberately

```text
python PACKAGE.pyz delete PROJECT --path Notes/Old.md --evidence "This obsolete note was superseded by the current record"
python PACKAGE.pyz rename PROJECT --source Notes/Old.md --destination Notes/New.md --evidence "Move the note to its maintained location"
```

Missing files alone are not interpreted as intentional deletion; they may be delayed
provider content. Explicit delete preserves the historical version. Rename records
source deletion and destination creation together and preserves raced edits.
**Rename does not rewrite Markdown or wiki backlinks.** Review and correct affected
links separately, then sync those edits. `graph PROJECT` is a bounded read-only aid;
it does not supply universal vault coverage or a native Obsidian guarantee.

The older `graph-rename-*` proposal/acceptance commands belong to the coordinator
workflow; they are not the normal folder rename interface.

Concurrent renames of one source to different destinations retain both copies.
`rename_divergences` and a `rename_intent_divergence` warning identify the competing
intents even when the file view is ready. Review the destinations against evidence;
an editing member may deliberately keep both by recording `delete` of the already
removed source with an explanation, or reconcile the destination files. No special
reviewer is assigned. Repeated sync does not create another rename event.

## Migrate an existing coordinator project

Formats 1 and 2 remain historical coordinator projects. Normal setup reports that a
migration is required rather than creating a replacement project. To keep that route,
use `setup PROJECT --workflow coordinator` and its [historical guide](COORDINATOR-WORKFLOW.md).
To change it deliberately, use the old private coordinator state and a fresh private
backup directory:

```text
python PACKAGE.pyz migrate-folder PROJECT --state-dir OLD_STATE --backup-dir FRESH_PRIVATE_BACKUP
python PACKAGE.pyz migrate-folder PROJECT --state-dir OLD_STATE --backup-dir FRESH_PRIVATE_BACKUP --apply
python PACKAGE.pyz setup PROJECT --state-dir OLD_STATE
```

The first command reports the plan. Apply requires locally accessible full authority
history, verifies a private backup, preserves old metadata/history and current notes,
and retains project identity. Remote client credentials alone cannot supply the full
history backup. Missing previously accepted files, changed source/history or a wrong
binding require reconciliation, not an empty replacement authority. Retry an interrupted
migration with its original state and backup path.

New private folder state lives in `OLD_STATE/folder`; the old authority remains intact
outside the share. Legacy membership records are preserved as evidence. They do not
automatically become provider ACLs. Read-only local bindings and provider rights must
remain correct. Pending old proposals are retained historically, not silently approved.

If newer notes or authority history invalidate a saved plan before cutover, use a
fresh different backup directory with `migrate-folder --replan`, inspect that plan,
then repeat with `--apply`. Replanning preserves the previous intent and backup.
It is refused after format-3 cutover begins or new folder state exists; resume the
original migration in that case. A read-only replan does not change private state.

## Scope and validation

The local implementation is bounded: ordinary UTF-8 text/path validation applies,
and event/history limits can require an explicit future archival strategy. Shared
history is not a hostile-writer-proof ledger or a cloud permission service. Keep
provider backups and task-appropriate recovery copies; do not erase history casually.

[Validation](../VALIDATION.md) separates current folder checks from previous coordinator
fixtures. [Acceptance scenarios](TEAM-ACCEPTANCE.md) and [readiness](READINESS.md)
record missing provider/device evidence without making an online review queue part
of ordinary editing. [The folder contract](../product/FOLDER-CONTRACT.md) documents
the implementation boundary.
