# Shared Memory diagrams

These figures explain the developing **0.3.0 folder workflow**, not the older
format-1/2 coordinator. They are design and operating illustrations, not evidence
of provider delivery, independent-device acceptance or a published release. Read
the [operating guide](PRODUCT-V1.md) and [provider guidance](PROVIDERS.md) for current
commands and limits.

The `.mmd` files are the editable source of truth. The Mermaid blocks below and
SVG fallbacks are generated from those same files. GitHub and Mermaid-enabled
Obsidian views can render the fenced blocks directly; other readers can use the
SVGs. Edit the `.mmd` source and regenerate, rather than editing a generated block.
The README also uses generated Mermaid blocks, with fixed color classes omitted
so GitHub can choose light or dark presentation. The checker verifies both the
README and this guide against the same `.mmd` sources. SVGs remain optional image
fallbacks; do not maintain independent copies of the diagrams.

## 1. Separate local copies, one selected project

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
  classDef private fill:#f1f5f9,stroke:#94a3b8,color:#475569;
  classDef shared fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
  classDef route fill:#ecfdf5,stroke:#059669,color:#064e3b;
  class AP,BP private;
  class AF,BF shared;
  class P route;
```
<!-- END GENERATED MERMAID: 01-shared-folder.mmd -->

<details>
<summary>SVG fallback</summary>

![People and agents edit selected project copies, with private parent content outside the exchange.](../assets/diagrams/01-shared-folder.svg)

</details>

[Editable Mermaid](../assets/diagrams/01-shared-folder.mmd)

Each computer has its own selected project copy and private baseline. An optional
private Obsidian vault can surround that folder. Arrows through the provider carry
only selected project files and portable history; disconnected private boxes have
no delivery arrow. Provider permissions still determine access. Folder selection
does not create sharing permissions or prove that arbitrary note content is safe
to share. No database, login credential or agent transcript belongs in the exchange.

## 2. Direct editing and history exchange

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
  classDef local fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
  classDef caution fill:#fff7ed,stroke:#c2410c,color:#7c2d12;
  class E,S,H,R local;
  class W,C caution;
```
<!-- END GENERATED MERMAID: 02-edit-and-deliver.mmd -->

<details>
<summary>SVG fallback</summary>

![Saving is local; sync captures history and reconciles provider arrivals, deferring incomplete history.](../assets/diagrams/02-edit-and-deliver.svg)

</details>

[Editable Mermaid](../assets/diagrams/02-edit-and-deliver.mmd)

People and agents save directly without an approval queue or designated integrator.
Saving persists local bytes; history capture happens when `sync` runs. Local edits
are captured against the private baseline before incoming history is reconciled. The chosen
provider delivers files separately. Run `sync` again after arrivals. An inactive
agent does not automatically wake, renew ownership or notice changes. Missing
parent events defer the whole affected event, including multi-path changes; absence
alone is not an intentional deletion.
Use the explicit deletion and rename operations to record those intentions.

## 3. Offline work and conflicts

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
  classDef state fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
  classDef merge fill:#ecfdf5,stroke:#059669,color:#064e3b;
  classDef conflict fill:#fff7ed,stroke:#c2410c,color:#7c2d12;
  class B,A,C,J state;
  class M merge;
  class K,R conflict;
```
<!-- END GENERATED MERMAID: 03-offline-and-conflicts.mmd -->

<details>
<summary>SVG fallback</summary>

![Offline changes keep their causal parents, merge when compatible, and retain conflicting versions for explicit resolution.](../assets/diagrams/03-offline-and-conflicts.svg)

</details>

[Editable Mermaid](../assets/diagrams/03-offline-and-conflicts.mmd)

The two branches share a known parent, not a clock-based winner. After complete
history arrives, compatible text can merge. Competing versions remain recoverable
in immutable history, with readable `.shared-memory/conflicts/` reports, until an
authorized editor records an explicit resolution and its evidence.
No special integrator role is required in normal folder mode. Read-only settings
and provider access restrictions still apply. A clean text merge does not prove
factual agreement; people and agents must check consequential claims against sources.
History hashes establish content integrity, not independently authenticated human
identity. Preserve provider conflict copies and unrelated edits.

## 4. Provider alternatives

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
  classDef state fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e;
  classDef route fill:#f8fafc,stroke:#64748b,color:#0f172a;
  classDef selfhost fill:#ecfdf5,stroke:#059669,color:#064e3b;
  class P,D state;
  class G,I,O route;
  class N selfhost;
```
<!-- END GENERATED MERMAID: 04-provider-options.mmd -->

<details>
<summary>SVG fallback</summary>

![Google Drive, iCloud Drive, OneDrive and operator-managed Nextcloud are alternative routes for a selected project.](../assets/diagrams/04-provider-options.svg)

</details>

[Editable Mermaid](../assets/diagrams/04-provider-options.mmd)

The four branches are alternatives: choose **one provider for each physical project
folder**. They are not bridges between providers. Nextcloud is the recommended first
self-hosted option in this design; no service is provisioned by this diagram or by
ordinary local setup. Account type, client, OS, offline availability and provider
conflict behavior need their own validation. Account-backed delivery tests for this
folder workflow are not yet available. No identical provider/OS support is claimed.
Local-only use remains possible without any provider or server.

## Regenerate and review

Check or regenerate the fenced Markdown blocks with standard-library Python only:

```sh
python3 scripts/render_diagrams.py --check-markdown
python3 scripts/render_diagrams.py --update-markdown
```

The check exits nonzero if any generated block differs from its source or its
markers are missing/duplicated. It does not run Node, launch a browser or write files.
The update changes only the marked regions, preserving captions and SVG fallbacks.

Rendering is a documentation-development step, not a runtime dependency. Use
Mermaid CLI **11.17.0**, Node.js and an existing compatible Chrome/Chromium:

```sh
# Install development-only tooling in a private temporary directory.
PUPPETEER_SKIP_DOWNLOAD=true npm install --prefix /tmp/shared-memory-diagram-tools --no-audit --no-fund @mermaid-js/mermaid-cli@11.17.0

# Run from this repository. Replace the browser path for the actual computer.
python3 scripts/render_diagrams.py \
  --mmdc /tmp/shared-memory-diagram-tools/node_modules/.bin/mmdc \
  --chrome "/path/to/Chrome-or-Chromium" \
  --png-dir /tmp/shared-memory-diagram-previews
```

The renderer processes each `.mmd` with Mermaid, rejecting syntax/render failures,
and writes the matching SVG. After successful rendering it also updates the generated
Markdown blocks. `--output-dir` can target a fresh SVG comparison directory.
PNG previews are optional and stay outside the repository. Inspect all figures for
readable text, clipping, arrow direction and faithful boundaries after changing a
source. Font/browser differences can affect layout; generated output is reviewed
artwork, not a promise of identical bytes on every renderer host.

For a surface that needs an image fallback, use the existing export:

```markdown
![Shared project copies for people and agents](assets/diagrams/01-shared-folder.svg)

[Workflow, offline conflicts and provider diagrams](docs/DIAGRAMS.md)
```

Each SVG includes a title and description from Mermaid's accessibility fields. The
captions above supply the meaning and limitations without relying on color alone.
