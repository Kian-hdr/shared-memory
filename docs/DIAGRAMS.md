# Shared Memory diagrams

These figures explain the developing **0.3.0 folder workflow**, not the older
format-1/2 coordinator. They are design and operating illustrations, not evidence
of provider delivery, independent-device acceptance or a published release. Read
the [operating guide](PRODUCT-V1.md) and [provider guidance](PROVIDERS.md) for current
commands and limits.

The `.mmd` files are the editable source of truth. SVGs are generated from them.
README and other guides should embed those SVGs and link here, rather than keeping
another Mermaid copy that can drift.

## 1. Separate local copies, one selected project

![People and agents edit selected project copies, with private parent content outside the exchange.](../assets/diagrams/01-shared-folder.svg)

[Editable Mermaid](../assets/diagrams/01-shared-folder.mmd)

Each computer has its own selected project copy and private baseline. An optional
private Obsidian vault can surround that folder. Arrows through the provider carry
only selected project files and portable history; disconnected private boxes have
no delivery arrow. Provider permissions still determine access. Folder selection
does not create sharing permissions or prove that arbitrary note content is safe
to share. No database, login credential or agent transcript belongs in the exchange.

## 2. Direct editing and history exchange

![Saving is local; sync captures history and reconciles provider arrivals, deferring incomplete history.](../assets/diagrams/02-edit-and-deliver.svg)

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

![Offline changes keep their causal parents, merge when compatible, and retain conflicting versions for explicit resolution.](../assets/diagrams/03-offline-and-conflicts.svg)

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

![Google Drive, iCloud Drive, OneDrive and operator-managed Nextcloud are alternative routes for a selected project.](../assets/diagrams/04-provider-options.svg)

[Editable Mermaid](../assets/diagrams/04-provider-options.mmd)

The four branches are alternatives: choose **one provider for each physical project
folder**. They are not bridges between providers. Nextcloud is the recommended first
self-hosted option in this design; no service is provisioned by this diagram or by
ordinary local setup. Account type, client, OS, offline availability and provider
conflict behavior need their own validation. Account-backed delivery tests for this
folder workflow are not yet available. No identical provider/OS support is claimed.
Local-only use remains possible without any provider or server.

## Regenerate and review

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
and writes the matching SVG. `--output-dir` can target a fresh comparison directory.
PNG previews are optional and stay outside the repository. Inspect all figures for
readable text, clipping, arrow direction and faithful boundaries after changing a
source. Font/browser differences can affect layout; generated output is reviewed
artwork, not a promise of identical bytes on every renderer host.

For a README overview, use the existing source and export:

```markdown
![Shared project copies for people and agents](assets/diagrams/01-shared-folder.svg)

[Workflow, offline conflicts and provider diagrams](docs/DIAGRAMS.md)
```

Each SVG includes a title and description from Mermaid's accessibility fields. The
captions above supply the meaning and limitations without relying on color alone.
