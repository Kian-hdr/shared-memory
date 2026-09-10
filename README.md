# Shared Memory

<img src="assets/shared-memory.svg" width="96" height="96" alt="Shared Memory icon">

**Shared notes for people and AI agents. Edit them normally.**

Shared Memory 0.3.0 works in an ordinary Markdown folder. People and agents save
changes directly, including offline. Your chosen folder provider transports the
files when connected; Shared Memory records changes and reconciles the history it
can see. Optional reviews happen after editing. A designated integrator, approval
queue or always-online reviewer is not required.

Obsidian is optional. One shared project subfolder can live inside an existing
private vault. The enclosing vault, private notes and settings stay outside that
project's boundary.

<!-- BEGIN GENERATED MERMAID: 01-shared-folder.mmd -->
```mermaid
flowchart LR
  accTitle: One shared project, separate local copies
  accDescr: People and agents edit selected project copies. A chosen provider exchanges only the project files. Private parent notes, settings and local baselines are not shared.
  subgraph A["COMPUTER A"]
    direction TB
    AE["Person + agent"] -->|"read / edit / save"| AF["Selected project copy<br/>Optional vault subfolder<br/>Markdown + shared history"]
    AF ~~~ AP
    AP["Private parent notes / settings<br/>Private baseline outside sync"]
  end
  A <-->|"selected project files only"| P["ONE chosen provider<br/>Account-backed delivery unverified"]
  subgraph B["COMPUTER B"]
    direction TB
    BE["Person + agent"] -->|"read / edit / save"| BF["Selected project copy<br/>Optional vault subfolder<br/>Markdown + shared history"]
    BF ~~~ BP
    BP["Private parent notes / settings<br/>Private baseline outside sync"]
  end
  P <-->|"selected project files only"| B
```
<!-- END GENERATED MERMAID: 01-shared-folder.mmd -->

Only the selected project files travel between copies. Private parent notes and
settings stay outside the exchange; there is no approval queue between agents.

[Workflow, offline conflicts and provider diagrams](docs/DIAGRAMS.md)

## Get started

1. [Paste the v0.3.0 setup / upgrade prompt](SETUP-PROMPT.md) into an agent connected to your computer.
2. Select the folder and use its existing sharing provider, if any.
3. Let the agent finish setup, then edit your notes normally.

Local use needs Python 3.11+ and the verified runtime; no account or server is
required. For another person, grant the intended folder access through your chosen
provider and have their agent set up that local copy. Each computer keeps its own
private baseline. Do not copy another person's private state.

[Release v0.3.0](https://github.com/Kian-hdr/shared-memory/releases/tag/v0.3.0) is the
version-specific download location. The setup prompt includes direct asset links
and the runtime SHA-256; verify the download against the release
`SHA256SUMS` before execution. The runtime is `shared-memory-0.3.0.pyz`; the matching full kit,
setup prompt, optional skill and icons are separate assets. A download does not grant
access to another person's folders.

## Save, reconnect, reconcile

<!-- BEGIN GENERATED MERMAID: 02-edit-and-deliver.mmd -->
```mermaid
flowchart TB
  accTitle: Save locally, capture history, reconcile arrivals
  accDescr: Direct editing requires no approval queue. Saving is local. Sync records history; the separately configured provider delivers files. Received history is reconciled only when parents are present, with conflicts retained.
  E["Read → edit → save<br/>Person or agent · offline is allowed"] -->|"local bytes saved"| S["Run sync<br/>Capture changes + reconcile visible history"]
  S -->|"immutable JSON events"| H["Portable project history<br/>.shared-memory/events/"]
  H -->|"configured provider delivers"| R["Other copy: run sync after arrival"]
  R -->|"parents available"| C["Compatible changes merge<br/>Competing versions remain for resolution"]
  R -->|"parent events missing"| W["Defer reconciliation<br/>Keep history; wait for missing parents"]
```
<!-- END GENERATED MERMAID: 02-edit-and-deliver.mmd -->

Saving is local. The provider transports files; `sync` captures and reconciles the
history available on each computer.

- Edit Markdown with your existing editor or agent. Saving persists locally.
- Run `sync` after edits and again when provider files arrive. The agent can do this
  as part of its work; the command itself is not a permanently running watcher.
- Compatible text changes can merge. Conflicting versions remain recoverable and
  need an explicit resolution with evidence from an authorized editor.
- A clean textual merge does not prove factual agreement. Review contradictions
  in meaning when they matter; record corrections without pretending software
  approved them.
- Deletions and renames need their explicit history operations, so temporary
  provider absence is not silently treated as intentional deletion.

Capture before reconnect when practical. A provider can overwrite a version before
Shared Memory records it; such uncaptured work needs provider history or backups.

## When people work offline

<!-- BEGIN GENERATED MERMAID: 03-offline-and-conflicts.mmd -->
```mermaid
flowchart TB
  accTitle: Offline branches retain their causal history
  accDescr: Two edits descend from a common version. On reconnect, complete history supports a compatible merge or a retained conflict. Any authorized editor can resolve with evidence. A clean text merge does not establish factual truth.
  B["Shared earlier version"] --> A["Copy A: edit offline<br/>Save; sync records parent + change"]
  B --> C["Copy B: edit independently<br/>Save; sync records parent + change"]
  A --> J["Reconnect · provider delivers<br/>Sync checks complete parent history"]
  C --> J
  J -->|"compatible text"| M["Merge + record history<br/>Keep ancestry; review factual meaning"]
  J -->|"conflicting edits"| K["Retain competing versions<br/>Do not silently choose a winner"]
  K --> R["Any authorized editor resolves<br/>Record chosen result + source evidence"]
```
<!-- END GENERATED MERMAID: 03-offline-and-conflicts.mmd -->

Agents can work at different times. After reconnecting, compatible text can merge;
genuine conflicts keep both versions for an authorized editor to resolve.
Synchronization does not decide which factual claim is correct.

Shared history contains readable project content and immutable event records,
not SQLite or login credentials. Provider permissions and explicit read-only
configuration still apply. History hashes are integrity checks, not independent
proof of an editor's real-world identity or the truth of a note.

## Choose your storage

Choose **one provider per folder**: Google Drive, iCloud Drive, OneDrive, or an
operator-managed Nextcloud service. Shared Memory does not bridge these services
or provision a server automatically. [Provider guidance](docs/PROVIDERS.md) covers
offline files, conflict copies and the recommended first self-hosted option.

<!-- BEGIN GENERATED MERMAID: 04-provider-options.mmd -->
```mermaid
flowchart LR
  accTitle: Choose one provider route for each physical project
  accDescr: Google Drive, iCloud Drive, OneDrive and operator-managed Nextcloud are alternative routes, not interconnected bridges. Nextcloud is the recommended first self-hosted option, not provisioned. Account-backed Shared Memory delivery is unverified for these routes.
  P["Selected physical project<br/>Choose ONE route"] --> G["Google Drive<br/>Account / OS route must be verified"]
  P --> I["iCloud Drive<br/>Account / OS route must be verified"]
  P --> O["OneDrive<br/>Account / OS route must be verified"]
  P --> N["Nextcloud · operator managed<br/>Recommended first self-hosted option<br/>Not provisioned"]
  G --> D["Other authorized local copies<br/>Verify delivered history + content<br/>Account-backed delivery unverified"]
  I --> D
  O --> D
  N --> D
```
<!-- END GENERATED MERMAID: 04-provider-options.mmd -->

These routes are alternatives, not bridges. The arrows describe file delivery;
local filesystem checks do not prove that another device received the files.

## Existing projects and evidence

Formats 1 and 2 belong to the older coordinator workflow. Keep that workflow
explicitly, or use the documented migration with a fresh private backup. Setup
never silently deletes its database/history or converts it into folder mode.
See [the operating guide](docs/PRODUCT-V1.md), [everyday work](docs/COLLABORATION.md),
and [the historical coordinator manual](docs/COORDINATOR-WORKFLOW.md).

[Validation](VALIDATION.md) distinguishes local fixtures and earlier coordinator CI
from actual provider and independent-device acceptance. A local sync result is not
a receipt from every remote recipient. The package is not a hosted service, native
app, editor lock, permission bypass or universal semantic conflict detector.

## License

[MIT](LICENSE). The [legacy toolkit](docs/SETUP.md#legacy-advisory-tracker-setup)
remains available explicitly; it is not the normal folder workflow.
