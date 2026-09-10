---
name: setup-shared-project-workspace
description: Set up, retrofit, or audit a shared Markdown project folder for direct editing by people and AI agents, with offline work, recoverable synchronization and optional Obsidian use. Discover the user's existing folder and provider. Do not use merely to manage ordinary tasks in an already configured workspace.
---

# Set up Shared Memory

Default to Shared Memory 0.3.0's direct folder workflow. People and agents edit
notes normally; saving works offline, and the chosen provider transports files on
reconnect. Reviews are optional after edits. Do not introduce a mandatory coordinator,
proposal queue, integrator or hidden automatic approval for normal folder work.

Read [product runtime routing](references/product-runtime.md) for package verification,
format detection, setup and migration. This skill alone is not the runtime. Use the
exact installed package's `guide` and command help for actual supported operations.

## Discover and finish the selected folder

Read existing instructions, project home and current metadata. Identify the user's
selected project folder, not the download directory or entire containing vault.
Reuse existing configuration. A project subfolder inside a private vault is valid;
[folder boundaries](references/project-folder-sharing.md) explains placement and access.
Do not open Obsidian or register a vault merely to configure Markdown files.

Use compatible Python 3.11+ and the externally verified package. Complete missing
local prerequisites within the task's authorization; do not add discretionary
permission round trips. Actual sign-in/MFA, OS consent, provider ACLs, confidentiality
and explicit task limits still apply. Read [local setup](references/local-setup.md)
only when prerequisites or filesystem readiness need work.

Run normal `setup` for a new or existing folder-format project. Keep each computer's
baseline/recovery state private and the portable event history with the shared
folder. Do not ask for coordinator tokens, endpoints, session leases or an online
integrator unless the discovered project explicitly uses the older workflow.
A format-1/2 project requires the documented backed-up migration to change workflows;
never reset its authority or silently reinterpret its pending work.

For one chosen provider, read [storage and access](references/storage-access.md).
Keep offline bytes available and verify that shared history is included in sync.
Local-only needs no account. Do not bridge multiple providers or provision an
unrequested service. Provider receipt and local history/status are separate checks.

After direct changes, run `sync` to capture edits and reconcile visible history;
repeat after provider files arrive. Preserve conflict copies before cleanup, including
provider copies that have not uploaded. A clean text merge is not proof of factual
agreement. Authorized editors may explicitly resolve conflicts with evidence; respect
read-only configuration and provider permissions. Use deletion/rename operations
when intended and validate links. Do not claim that a one-shot command is an
always-running watcher or that a remote recipient has received unseen work.

Finish setup with a concise [teammate prompt](references/teammate-onboarding.md) in
chat when sharing is relevant. Include actual access/package details, no credentials
or sender's private paths, and mark missing access explicitly. Do not send it unless
that action is requested. Report what works locally and which external checks ran.

## Explicit historical routes

- Existing or explicitly requested coordinator workflow: use `setup --workflow coordinator`
  and the exact historical guide; its tokens, leases and review rules remain specific
  to that mode until a reviewed migration changes it.
- Explicit advisory toolkit: bundled `scripts/` still describe the separate tracker.
  Read [retrofit policy](references/retrofit-policy.md) and
  [record schema](references/record-schema.md) for that route. Do not use it as a
  fallback when the requested current runtime is unavailable.

This skill does not grant another person's access or widen the selected share.
Keep credentials, session transcripts, cookies and private keys outside shared
notes/history. Name-based exclusions do not classify arbitrary Markdown for you.
