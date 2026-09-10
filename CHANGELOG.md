# Changelog

## 0.3.0, direct-folder workflow

- Ordinary note editing is the default. Local saves and captured change history no
  longer depend on a coordinator, proposal queue or designated integrator. Reviews
  are optional after edits, without hidden automatic approval.
- Add format-3 portable history, per-device baselines, compatible text reconciliation,
  preserved conflicts and explicit evidence-backed resolution/delete/rename commands.
  Rename does not rewrite backlinks; capture provenance is self-asserted.
- Add explicit backed-up conversion from the retained coordinator workflow, keeping
  old history and project identity. Provider ACLs and local read-only bindings remain.
- Synchronization uses one chosen provider. Google Drive, iCloud, OneDrive and
  Nextcloud guidance separates offline availability from actual remote receipt;
  no bridge, managed hosting or automatic provider provisioning is introduced.
- Update setup prompt, distributed skill and four diagrams for the direct workflow.
  Exact release checks are recorded in VALIDATION.md; historical counts below do
  not establish new folder/provider acceptance.

Older entries retain their dated workflow and publication statements.

## 0.2.1, local compatibility candidate, unreleased

- Add opt-in Markdown content mode for existing Vaults: preserve untracked attachments,
  non-Markdown artifacts and nested legacy coordination files without treating them
  as root knowledge edits. Already accepted files remain managed.
- Bind the choice to setup intent and versioned folder/client metadata; preserve
  default behavior and refuse implicit conversion. Existing format2 folders require
  a compatible client. This is not an authority-wide client-version handshake.
- Public distribution remains v0.2.0 until a separate reviewed release. Whole-Vault
  filesystem graph limits, real provider delivery and hosted operations remain separate.


## 0.2.0

Normal public release with a direct agent-guided entry point: paste the setup
prompt, select a folder, and complete setup. Obsidian remains optional.

- `setup` discovers saved project binding, supplies private local defaults for new
  owners, resumes interrupted setup and preserves edits as recoverable drafts.
  Existing team projects join their original authority using their own membership.
- Missing established authority fails safely instead of recreating revision zero.
- Default imports and untracked scans exclude credential/runtime paths while
  preserving their files. Existing accepted history is not silently reclassified.
- The prompt, skill and complete normal release package use the same workflow.
  Local use requires Python; cross-computer use requires an authorized reachable
  coordinator with verified TLS and separately issued member credentials.

- Migration dry runs use the bounded graph analyser for Markdown, wikilinks,
  aliases and anchors, preserving explicit ambiguity and parser-limit diagnostics.
- Plans refuse observed file/directory changes, and exclude credential/runtime
  subtrees before traversal. They remain read-only and do not authorize migration.
- Graph edges expose only validated local requested paths for actionable missing
  references; external, private and outside-scope destinations remain redacted.

## 0.2.0-alpha.1

First public experimental release of the independent Shared Memory product.
The package reports runtime version `0.2.0`; the release tag identifies its alpha
maturity. This is suitable for disposable trials and controlled pilots, with
reviewed backups and explicit integration ownership. Stable V1 acceptance remains
open in [READINESS.md](docs/READINESS.md).

- Ordinary project folders and readable Markdown, including selected folders
  inside existing Obsidian vaults. Obsidian is optional.
- Local SQLite authority and authenticated HTTPS team coordinator, atomic
  accepted revisions, preserved proposals and factual-conflict review.
- Opt-in session coordination with bounded ownership, handoffs, dependencies,
  interfaces, policy checks, defect records and durable targeted inboxes.
- Offline drafts, external-edit preservation, recoverable materialization,
  verified backups and explicit schema upgrades.
- Read-only graph inspection and reviewed selected-folder note renames.
- Explicit immutable-revision delivery adapter with local rclone fixtures.
  Actual Google Drive account delivery remains unverified.
- Exact-byte trusted tracker installation across line endings, including Windows,
  with explicit review required for existing drift.
- Verified package installation and rollback, owner/join guidance, copyable
  setup prompt, standalone SVG/PNG/macOS icon, and separate legacy skill bundle.

Windows, macOS and Linux automated coverage and bounded real Mac/Linux agent
trials are recorded in [VALIDATION.md](VALIDATION.md). Automated participants are
not independent human operators. Physical Windows onboarding, full mixed-device
provider acceptance, production capacity and long-running hosted operation remain
unverified. No automatic agent wakeup service or native app is included.

## Historical versions

The bundled `1.3.0` advisory tracker and `0.1.0` CLI milestone are compatibility
components, not earlier stable versions of the authoritative team product. Their
implementation history and dated checks remain in Git and the validation record.
