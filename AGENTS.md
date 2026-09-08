# Shared Memory: Agent Instructions

This is a reusable contract for a project folder shared by people and AI agents.
Obsidian is optional; an existing vault may contain the selected shared folder.
Preserve existing knowledge, make ownership clear, and leave enough context for
another contributor to continue. Resolve the user's intended project before setup;
a downloaded toolkit is not automatically the project to configure.

## 1. Start here

1. Read this file and the existing vault home or index, usually `Home.md` or `README.md`.
2. Identify the relevant project and canonical notes.
3. Read the nearest project-level `AGENTS.md`, if present.
4. Review current work, recent changes, decisions, and handoffs.
5. Confirm the local files are synchronized before editing shared material.

Read only what the task needs. Do not crawl the whole vault by default. Follow the
user's explicit scope and approvals. Preserve project-specific confidentiality,
safety, and evidence requirements. Resolve material instruction conflicts before acting.

## 2. Navigate the vault

- Use the existing folder structure and naming conventions.
- Start with an index or Map of Content when the exact source is unclear.
- Search filenames first, then relevant note contents.
- Follow wikilinks to canonical notes and evidence; resolve ambiguous names by path.
- Inspect frontmatter and dates before relying on a note.
- Treat meeting notes, plans, and old status reports as dated evidence.
- Use the designated live system for changing state when one is recorded.
- Discover the actual structure; do not assume folders or integrations exist.
- Discover the user's own storage method, account when required, and local root.
  Do not inherit a toolkit author's or teammate's account, machine paths, or provider.
  Local-only work requires no cloud service or sharing URL.

## 3. Maintain one canonical source

- Update existing canonical notes instead of creating duplicate summaries.
- Keep substantive agent instructions in `AGENTS.md`; compatibility files should
  point to it where supported. Project instructions hold project-specific rules.
- Keep code history in Git when a repository exists.
- Keep ownership, progress, decisions, and handoffs in established coordination records.
- Link large artifacts and external sources instead of duplicating them in notes.

## 4. Coordinate multiple people and agents

Before editing, identify the human requester, work owner, agent, and stable actor ID.
Review active work, define exact targets and acceptance criteria, claim the targets
through the installed workflow, and re-read them immediately before mutation.

Only one active owner may edit a target at a time. Directory claims cover descendants.
Parallel work needs separate targets, agreed dependencies, and an integration owner.
Do not overwrite another contributor's changes or take over active claims. An expired
claim is not proof that its owner has stopped; resolve ownership conflicts first.

Use subagents only when authorized by the user or applicable project instructions.
Give each agent bounded targets and clear acceptance criteria.

## 5. Use the tracker when installed

If `Coordination/project_tracker.py` exists, inspect its provenance and help before
first execution, then follow the project's tracker instructions. Typical commands
below use placeholders: replace identity and work values before running them.

```text
python3 Coordination/project_tracker.py sync --actor <actor-id> --human <human-name> --agent <agent-name>
python3 Coordination/project_tracker.py status
python3 Coordination/project_tracker.py check --actor <actor-id> --work-id <work-id>
```

Use installed commands to claim work, renew claims, record material changes, accept
handoffs, and complete work. Current records live in `Coordination/Items/`.
`Coordination/Workspace.base`, when present, is the Obsidian dashboard.

Do not bypass validation or rewrite immutable history. Supersede incorrect records.
If no tracker exists, use the established ownership process. If none exists, agree
on exclusive ownership before shared edits. Do not claim automated coordination is active.

## 6. Synchronization and conflicts

Shared-folder synchronization is not a transactional lock. Check synchronization at
session start, before mutation, after material changes, before integration, and at handoff.
A tracker checkpoint does not prove the storage provider has synchronized all devices.

If files conflict, change unexpectedly, or are unavailable locally, pause affected
edits. Preserve both versions, establish ownership, and reconcile deliberately.
Do not promise continuous awareness of another contributor's work.

## 7. Edit safely in Obsidian

- Preserve frontmatter, links, embeds, and existing formatting.
- Follow established metadata and tag conventions.
- Link new notes from an appropriate index or canonical note.
- Prefer vault-relative links over machine-specific absolute paths.
- Keep tracked file targets and the project home within the project and store their
  relative paths. Resolve each contributor's root locally. If a project is copied into
  a different vault layout, verify its dashboard scope before calling it portable.
- Rename or move notes through Obsidian when available so links can update.
  Validate affected links after an authorized direct-file move.
- Change `.obsidian` settings, plugins, themes, or sync configuration only when
  required and authorized. Do not introduce another sync provider implicitly.
- Keep deletion recoverable and preserve unrelated changes.

## 8. Record evidence and progress

Distinguish verified results, historical information, inferences, assumptions, and
unresolved questions. Record material outcomes with what changed and why, human
owner, agent, UTC timestamp, targets, validation, evidence, limitations, and next action.

Declare dependency impact as `none`, `compatible`, `breaking`, or `unknown`.
Review breaking or unknown upstream changes before continuing dependent work.
Measure progress against acceptance criteria. Do not invent completion percentages
or claim checks that were not run. Log material outcomes, not every read or command.

## 9. Privacy and approval boundaries

Keep credentials, tokens, cookies, private keys, payment data, and sensitive live
endpoints out of the vault. Respect disclosure restrictions in notes and projects.
Do not include confidential content in external drafts without authorization.

Reading, reversible in-scope edits, and already-authorized local installations and
configuration do not require repeated approval. A full setup request covers its
necessary prerequisites, app launch, vault opening, and minimal PATH configuration;
choosing Homebrew includes installing it when missing. Respect the recipient's
actual tool/OS/admin approval rules and required human interactions. Do not weaken
those rules or add a new permission question for each authorized step. Obtain
explicit authorization before external messages, publication, permission changes,
purchases, deployment, or destructive actions. Existing authorization remains valid
within its stated scope. Sharing a vault grants no authority to act for another person.

## 10. Finish with a useful handoff

1. Save and validate changed files, metadata, links, and index coverage.
2. Update the existing work record with the material outcome and acceptance state.
3. Record blockers, limitations, next action, and next owner.
4. Create a handoff when another contributor must continue.
5. Report the result concisely with relevant note links.

Do not call work complete while required steps remain. Do not create redundant logs
merely to record that a session occurred.
