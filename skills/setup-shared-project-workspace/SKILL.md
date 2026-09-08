---
name: setup-shared-project-workspace
description: Set up, retrofit, or audit an independent Markdown project folder for people and AI agents, with optional Obsidian integration, with ownership, dependencies, handoffs, validation, and a recipient-specific onboarding prompt. Discover the user's actual storage method and local environment; support local-only, Git, shared-folder, and hybrid workflows without requiring a particular account or provider. Do not use merely to manage ordinary tasks in an already configured workspace.
---

# Set up a shared project workspace

Create an independent collaboration layer in an ordinary project folder. Python
and Markdown are sufficient; Obsidian is optional. Do not install/open it or
require a vault for normal folder setup. A selected folder inside an
existing Obsidian vault can be the entire shared project; the parent vault stays
private. For this workflow read [references/project-folder-sharing.md](references/project-folder-sharing.md).
Configure the selected project root only. Do not open Obsidian, create/register a
vault, or modify parent settings merely to set up a project folder. Keep substantive instructions in
`AGENTS.md`; do not generate parallel explanation files.

The legacy setup and tracker require Python 3.9 or newer and use only its standard library.
Resolve `scripts/` paths relative to this skill directory, not the target project.
Run `--help` for the setup or tracker command when its required inputs are unclear.
For requested computer readiness or full setup, read
[references/local-setup.md](references/local-setup.md). Complete missing dependencies,
Obsidian launch/vault setup only when explicitly requested, and Homebrew installation/configuration when chosen.
Existing authorization covers necessary local steps; do not ask again per package.
Honor the recipient's enforced approval policies and required human interactions.

## Select product or legacy toolkit

For the **Shared Memory product**, a reviewed `.pyz` package, or a project containing
`.shared-memory.json`, read [references/product-runtime.md](references/product-runtime.md)
and follow the authoritative product commands. This skill folder alone contains
the legacy advisory tracker, not the new engine. Preserve the existing mode; never
silently replace unavailable product capabilities with advisory setup. The remaining
workflow below applies to the legacy toolkit.

## Choose the mode

- `bootstrap`: configure a new or effectively empty project.
- `retrofit`: preserve and extend an existing project without replacing its files.
- `audit`: inspect the collaboration layer without changing anything.
- `auto`: choose `retrofit` when the target contains project material, otherwise
  choose `bootstrap`.

Before retrofitting, read [references/retrofit-policy.md](references/retrofit-policy.md).
Read [references/record-schema.md](references/record-schema.md) only when changing the
tracking model, repairing records, or explaining its fields in detail.

## Workflow

1. Resolve the recipient's exact project/vault roots and inspect existing `AGENTS.md`,
   `CLAUDE.md`, project homes, `.obsidian`, the enclosing Git root, and `Coordination/`.
   Identify the actual storage/access method using
   [references/storage-access.md](references/storage-access.md). Never infer an account,
   provider, or shared location from this toolkit's author or download URL. Local-only
   work needs no cloud account, client, URL, or upload. A plain folder is not proof of sync.
2. Follow all instructions already governing the target. Do not weaken or replace
   project-specific scope, security, approval, or evidence rules.
3. Use `scripts/doctor_workspace.py /absolute/project/path` for read-only onboarding
   diagnostics (`--json` for structured output). It executes only the bundled trusted
   validator, reports tracker mismatch and local errors, and leaves app/access/receipt
   checks explicitly unverified. For explicitly local work, select
   `--collaboration-mode local-only`. The doctor is not proof of shared readiness.
   For a retrofit, run the audit first:

   ```bash
   python3 scripts/setup_workspace.py /absolute/project/path --mode audit
   ```

4. Run `setup_workspace.py` with the inferred or user-supplied project name,
   collaboration mode, and actor identity. Use `--dry-run` when the target is
   consequential or the proposed merge needs review.
5. The generated project footprint is limited to:
   - one managed collaboration section in `AGENTS.md`;
   - a minimal `CLAUDE.md` adapter pointing to `AGENTS.md`;
   - `README.md` only when no suitable project home already exists;
   - `Coordination/Workspace.base`;
   - `Coordination/project_tracker.py`;
   - `Coordination/Items/` for operational records.
6. Validate the installed workspace:

   ```bash
   python3 scripts/validate_workspace.py /absolute/project/path
   ```

7. Report what was reused, created, merged, skipped, and validated. Do not call the
   project multi-user-ready if validation fails.
8. After every successful bootstrap or retrofit, include a **Teammate setup prompt**
   directly in the final chat response, in one copyable fenced block. Read
   [references/teammate-onboarding.md](references/teammate-onboarding.md) and fill its
   template with verified project details. This is a required setup deliverable, not
   an offer to write it later. It must let another agent join the existing workspace
   without needing this skill installed. Do not create another onboarding file in
   the project or send the prompt to anyone unless requested.

For a prompt-only request, inspect the existing workspace and use that reference;
do not rerun setup. Audits and dry runs do not require a prompt unless requested.
If setup fails, report the failure; label any requested preview as provisional.
For shared work, if essential access details are missing, complete independent local
work and ask only for the locator required by that workflow. This may be a repository
URL, folder invitation, or network-share instruction; it is not always a folder URL.
No remote locator is required for local-only setup. Do not invent a provider or call
an incomplete shared invitation ready. Report local and shared readiness separately.

## Operating invariants

- Current state lives in one `work` record per workstream. Immutable `event`,
  `handoff`, and `decision` records preserve history.
- Record human initiator, human owner, agent, actor ID, UTC timestamp, exact targets,
  status, evidence, limitation, and next action where applicable.
- Progress is acceptance-based. Do not use an unsupported percentage.
- One active owner may mutate an exact target at a time. A directory claim conflicts
  with claims on descendants. Claims are advisory across synchronized filesystems;
  validate before every mutation and integration.
- Work revisions and dependency baselines make downstream work visibly stale after an
  upstream change. Every material change declares `none`, `compatible`, `breaking`,
  or `unknown` impact.
- Log material state changes, not every read or shell command.
- `verified` requires all acceptance criteria plus recorded validation and evidence.
- Never rewrite or delete immutable records. Correct them with a superseding record.
- Git remains authoritative for code diffs and commits. The coordination records hold
  semantic state, ownership, impact, and handoff context.
- Keep shared file targets and project-home references project-relative. Each
  contributor resolves their own root. Do not store an owner's home-directory path,
  account mount path, or unrelated external file location in operational records.
- Synchronized folders do not provide transactional locking. Do not promise continuous
  real-time awareness; require sync checkpoints at session start, before mutation,
  after material changes, before integration, and at handoff.

## Boundaries

Ordinary project setup creates local project files and a chat onboarding prompt.
When full local setup is requested, also install and configure required dependencies
under the recipient's authorization, following `references/local-setup.md`.
Generating a prompt alone does not install apps, log in, or request access on anyone else's behalf.
The recipient's agent must act under that recipient's permissions and tools, using
the authentication, access-request, and readiness boundaries in the template.
Workspace setup does not authorize invitations,
sharing-permission changes, external messages, publication, deployment, purchases,
account changes, destructive cleanup, or migration of historical content.

Do not store credentials, cookies, tokens, access codes, payment data, personal email
addresses as actor IDs, private live endpoints, or large artifacts in coordination
records. Link or hash approved external artifacts instead.

Do not retrofit a live project merely because the skill was selected. The user must
have asked to set up, change, repair, or audit that project.
