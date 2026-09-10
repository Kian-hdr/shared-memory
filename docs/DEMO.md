> **Version scope:** Historical advisory-toolkit demo. This synthetic fixture does not demonstrate the current direct-folder engine or real provider receipt. Use [the current guide](PRODUCT-V1.md) for normal work.

# Shared Memory: one shared project folder

A shared workspace for your team and its AI agents.

The core is **one independent Markdown project folder**. Obsidian is optional.
People who already use it can place the same shared folder inside their existing
private vaults, while keeping broader notes and configuration outside the shared scope.

By default this demo creates an ordinary synthetic folder, with no `.obsidian`
directory anywhere in its output. An explicit `--layout existing-vault` option models
a folder inside an existing vault. Both layouts retrofit only the selected project.
The script does not open Obsidian, register a vault, configure sharing, or touch your
real project or vault.

The script invokes this checkout's actual setup and tracker through the same Python
interpreter, then preserves the notes, records, evidence, and a machine-readable
report. It requires Python 3.9+ and its standard library. No network, API key, agent
product, or Obsidian installation is needed to run it.

## Rehearse

From the downloaded or cloned repository root, choose a **nonexistent output folder
under an existing parent**, outside any synchronized folder. On macOS or Linux:

```bash
python3 scripts/demo_workspace.py --output /tmp/shared-workspace-rehearsal-01
```

On Windows PowerShell:

```powershell
python scripts/demo_workspace.py --output "$env:TEMP\shared-workspace-rehearsal-01"
```

The default is `--layout plain`. To demonstrate the optional existing-vault layout:

```bash
python3 scripts/demo_workspace.py --output /tmp/shared-workspace-vault-01 --layout existing-vault
```

For a stage run, use a different fresh name and pause before each of six stages:

```bash
python3 scripts/demo_workspace.py --output /tmp/shared-workspace-stage-01 --step
```

`--step` requires an interactive terminal. Press Enter to run each stage. Ctrl-C
stops the run and preserves its partial output. The script refuses **any existing
output path, even an empty directory**. Change the name for another run; it does not
delete or reset old demos. It creates no parent directories. Interrupted or failed
runs retain a report with the failure state when initialization has completed.

The commands themselves do not synchronize files. Choosing a folder already managed
by a storage client could still cause that client to upload them; use an ordinary
local temporary directory for this demonstration.

## What happens

1. The script builds a synthetic parent folder with private notes and an existing
   `Projects/Shared Demo/Home.md`. Only `--layout existing-vault` adds an empty
   `.obsidian` fixture to the parent. Setup retrofits only `Projects/Shared Demo`
   in `local-only` mode. Every command checks that parent notes, parent layout,
   and the existing home remain unchanged. Alex and Sam are fictional identities.
2. Alex claims `Brief.md`; Sam claims `Checklist.md`. Each also owns its separate
   content-validation evidence file.
3. Sam attempts another claim on `Brief.md`. The tracker rejects the overlap. The
   script checks both the expected error and unchanged workspace file hashes.
4. After a real ownership check, the script writes the brief. A separate Python
   process compares its actual content and saves a SHA-256 digest. Alex records the
   result against an acceptance criterion.
5. Alex hands the brief to Sam. Both preflight and recording a change are rejected
   until Sam accepts. Sam refreshes records, accepts, checks ownership, reruns the
   content validation, records both passed criteria, and completes the work.
6. Sam creates and validates the checklist. The tracker validates the generated
   records, and a final check confirms both items are `verified`, have 2/2 criteria,
   belong to Sam, and have no pending handoff.

A `PASS` next to a rejection means the expected guard worked. Every subprocess exit
code and output is retained in `report.json`; a different error, a changed workspace
following an expected rejection, or a failed validation stops the demo with failure.

## About 90 seconds of narration

> When people use different AI assistants on one project, the next session needs
> more than a chat history. It needs to know what matters, who owns each change,
> what has been checked, and what happens next.
>
> This toolkit puts that context in one ordinary Markdown folder. Obsidian is
> optional: that folder can also live inside each person's existing private vault.
> Here I am using a synthetic local example. Alex and Sam are fictional contributors.
> No folder is being shared over a network, and no real vault is being opened.
>
> Alex claims the brief. Sam claims the checklist. They can work on separate targets.
> If Sam also tries to claim Alex's brief, the tracker rejects the overlap.
>
> Alex writes the brief, runs a small content check, and records the result with
> evidence. Then Alex hands it to Sam. The tracker requires Sam to accept that
> handoff before continuing. Sam checks ownership, reruns the validation, and
> completes the work against explicit criteria.
>
> The useful output is the shared context: ownership, decisions, evidence, and a
> clear next step, kept beside the project files.
>
> This demonstrates one computer and a tiny example. Real sharing permissions,
> cross-device synchronization, and production scale need separate validation.
> The next step is a real small-team pilot.

## Inspect the result

The default plain-layout output folder contains:

```text
report.json                                Outcomes, limitations, hashes, boundary checks
plain-folder/                              Ordinary synthetic parent, no .obsidian
  Private.md                               Synthetic private note, preserved unchanged
  AGENTS.md                                Synthetic parent rules, preserved unchanged
  Projects/Shared Demo/                    The only folder setup configures
    Home.md                                Existing project home, preserved unchanged
    AGENTS.md                              Self-contained project instructions
    CLAUDE.md                              Pointer to project instructions
    Brief.md                               Fictional sample output
    Checklist.md                           Fictional sample output
    Evidence/                              Actual content checks and SHA-256 digests
    Coordination/Items/                    Actor, work, event, handoff, decision records
    Coordination/Workspace.base            Optional Obsidian dashboard definition
    Coordination/project_tracker.py        Installed tracker used by this run
```

With `--layout existing-vault`, `existing-vault/` replaces `plain-folder/` and contains
an empty `.obsidian/` directory preserved unchanged. This is a filesystem fixture,
never an opened or registered vault. The report records `layout` and the relative
`workspace` path for either mode.

Inspect the machine-readable report or rerun validation for the default layout:

```bash
python3 -m json.tool /tmp/shared-workspace-stage-01/report.json
python3 "/tmp/shared-workspace-stage-01/plain-folder/Projects/Shared Demo/Coordination/project_tracker.py" validate
python3 "/tmp/shared-workspace-stage-01/plain-folder/Projects/Shared Demo/Coordination/project_tracker.py" status
```

Inspect the Markdown and report in your existing editor or terminal. This walkthrough
requires no app launch or vault registration. The optional `.obsidian` fixture only
exercises the nested dashboard path and remains empty. The report's `fixture_boundary`
contains before/after digests for parent files and the original project home.

For an actual team, scope the chosen storage method's sharing and permissions to the
selected project folder. Verify that private parent notes and vault configuration are
excluded. A recipient can use the folder directly with any Markdown-capable tools,
or place it within their existing vault. The current generated dashboard scopes its
items relative to the Base file; this demo checks the generated structure, not the
Obsidian rendering. Older dashboards with fixed folder paths require review when
moved. None of those real storage, permission, recipient, or UI steps is performed
by this demo.

## Evidence boundary

This proves the observed local command behavior, content checks, recorded handoff,
final record validation, and preservation of the synthetic parent/private/configuration
boundary in this run. The content checks are deliberately tiny;
passing them says nothing about the quality of a real deliverable. SHA-256 records
byte identity, not correctness. Actor identities are declared and are not authenticated.

The script runs contributors **sequentially on the same computer**. It does not prove
live agent behavior, independent review, simultaneous edits, real sharing permissions,
cloud synchronization, cross-device exclusion, UI rendering, recovery from provider conflicts, performance
at scale, or suitability for critical production workflows. Claims are advisory and
do not stop other software from editing files directly. Use the saved report as
demo evidence, not a production certification.
