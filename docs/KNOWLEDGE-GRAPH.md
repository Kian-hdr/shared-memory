# Knowledge graph for one shared project

Shared Memory builds a read-only graph from readable Markdown notes and their
explicit links. Use it to follow a project into its knowledge, decisions,
evidence and work records, or to find a broken reference before publishing a
change. Obsidian is optional. The core command needs neither Obsidian nor a new
vault, and does not open an application.

## Choose the shared folder

Point the command at the **selected project folder**, even when that folder lives
inside an existing private vault:

```text
Private vault/
  Home.md                       private outer home
  .obsidian/                    private application settings
  Projects/
    Shared project/             selected graph and sharing boundary
      Project Brief.md
      Knowledge/
      Decisions/
      Evidence/
      Work/
```

The analyzer does not follow links into the parent vault or search its siblings
to resolve a missing note. Hidden folders, known private runtime/credential paths,
symlinks and unsupported file formats are excluded. It never changes notes,
permissions, application settings or coordination policy. Keep coordinator and
client state outside the entire vault and its synchronization roots, as described
in the [operating guide](PRODUCT-V1.md).

## Run the command

Use the exact reviewed package and a compatible Python interpreter. Replace the
placeholders with your own paths; quote paths containing spaces.

```text
python PACKAGE.pyz graph PROJECT
```

This inspects the files currently present in the selected folder. It works before
Shared Memory initialization and includes local edits that may not be accepted.
Do not supply `--state-dir` for this mode.

For an attached project, inspect the authenticated accepted snapshot instead:

```text
python PACKAGE.pyz graph PROJECT --accepted --state-dir PRIVATE_STATE
```

Accepted mode checks the selected project against the private client binding and
coordinator identity, then analyzes accepted text. It does not refresh or write
local files. Untracked attachments absent from the accepted snapshot cannot be
resolved through that mode. Coordinator access is required; local mode can run
offline.

Both commands return JSON. The CLI's `data` contains the graph; check the outer
`ok` field before using it. To retain a report, redirect stdout to a **fresh private
output file outside the project**:

```text
python PACKAGE.pyz graph PROJECT > PRIVATE_GRAPH_REPORT.json
```

A graph is a reference map, not acceptance authority. Even accepted mode sets
`acceptance_authority` to `false`: accepted bytes do not establish that every
statement in a note is true. Its `accepted_identity` records the project UUID,
revision and files hash used for the inspection.

## Give the graph useful structure

Keep existing canonical notes. A practical arrangement links a project brief to
the knowledge it relies on, decisions it has made, supporting evidence and work
that implements or checks those decisions. Create a relationship only when the
source note actually supports it.

For example, `Decisions/Folder Boundary.md` can contain:

```markdown
---
type: decision
title: Keep the shared folder small
aliases:
  - Folder boundary
---
# Keep the shared folder small

Share the selected project folder. Keep unrelated notes and runtime state private.

- [Project brief](../Project%20Brief.md)
- [Supporting evidence](../Evidence/Boundary%20Check.md)
- [Implementation work](../Work/Apply%20Boundary.md)
```

The analyzer uses `type`, or `kind` when `type` is absent, to classify notes as
`knowledge`, `project`, `decision`, `evidence`, `work` or `note`. Other values fall
back to `note`. A title comes from `title`, the first heading, or the filename.
These properties describe documents; they do not assign ownership or grant rights.

Explicit links in the following frontmatter fields also carry a relationship
label. Plain prose values do not create inferred edges.

| Frontmatter field | Graph relationship |
| --- | --- |
| `project`, `projects` | `project` |
| `decision`, `decisions` | `decision` |
| `evidence`, `source`, `sources` | `evidence` |
| `work`, `work_records` | `work` |
| `depends_on` | `dependency` |
| `related` | `related` |
| `canonical` | `canonical` |

For example, `evidence: "[[Boundary Check]]"` records an explicit evidence link.
Keep essential navigation in the Markdown body as well: property rendering varies
by editor, and this analyzer does not implement every YAML or application feature.
A knowledge-graph `dependency` link does not create or satisfy a coordinator's
enforced work dependency.

## Resolve links without guessing

Prefer unambiguous document-relative Markdown paths for portability, especially
inside a larger private vault. Use forward slashes and encode spaces as `%20`.

| Reference | Meaning |
| --- | --- |
| `[Decision](../Decisions/Folder%20Boundary.md)` | Document-relative Markdown link |
| `[[Decisions/Folder Boundary]]` | Wikilink path relative to the analyzer's selected root |
| `[[Project Brief]]` | Exact selected-root note, then unique basename within the selected folder |
| `[[Project Brief\|Project]]` | Canonical destination with alternate display text |
| `[[Project Brief#Accepted boundary]]` | Heading in the destination note |
| `[Boundary](../Project%20Brief.md#accepted-boundary)` | Markdown heading anchor |
| `[[Project Brief#^boundary-1]]` | Explicit block identifier in the destination note |
| `![[Diagram.png]]` | Local attachment embed; its contents are not read |

Exact paths take priority. If a bare Markdown filename has no document-relative
match, the analyzer also checks for a unique basename inside the selected folder.
Treat this fallback as a reason to prefer an explicit relative path: other editors
may resolve it differently. A selected-root wikilink path is not a guarantee of
the same resolution inside a larger Obsidian vault.

Ambiguous basenames or aliases remain unresolved. Case or Unicode normalization
matches without an exact spelling are reported as `nonportable_match`, with
candidates rather than a silently selected destination. Use consistent casing and
Unicode NFC names across devices.

An alias is an alternate label, not a reliable replacement for a canonical link
destination. A bare alias such as `[[Folder boundary]]` can produce `alias_only`;
use the actual filename and optional display label instead. Obsidian's documented
alias insertion also uses the canonical filename plus display text. See
[Obsidian aliases](https://obsidian.md/help/aliases).

## Read the result

`nodes` contains Markdown notes and supported local attachments that are actually
linked. Each node has a relative path, title, kind and incoming `backlinks`.
Backlinks identify the source note, source line and edge ID, so you can inspect
why two notes are connected. Markdown nodes also include a content SHA-256.

`edges` retains source line/column, syntax, relationship and metadata-field
provenance where applicable. Repeated links remain separate occurrences.

| Field or status | What to check |
| --- | --- |
| `status: resolved` | A file was found within the selected input |
| `anchor_status: resolved` | The requested heading or block was also validated |
| `missing`, `ambiguous`, `alias_only`, `nonportable_match` | Correct or disambiguate the destination; inspect candidates and the source line |
| `outside_scope`, `excluded` | The analyzer deliberately did not enter the parent, private path or excluded input |
| `external` | An external reference was recognized, without fetching it |
| `unsupported_reference` | The syntax or reference definition could not be resolved by this parser |

File resolution and anchor validation are separate. A resolved file may still
have a missing or ambiguous heading. Heading anchors support validated slugs and
heading text; repeated headings and block IDs can be ambiguous. Attachment anchors,
such as a PDF page selector, are not validated.

Inspect `diagnostics`, `coverage` and `limits` along with `summary`. Raw external
URLs, credentials in those URLs and absolute host paths are not exported. This
does not make the report public: note titles, paths, links and metadata can still
contain project information. Keep reports within the project's disclosure rules.

## Optional Obsidian graph and rename checks

In an existing Obsidian vault, use Graph view's search filter to select the project
path, or open the local graph for a note. Graph nodes open notes; backlinks provide
navigation back to their sources. A graph filter controls what is displayed. It
does **not** turn the selected folder into a permissions or rename boundary. See
[Obsidian Graph view](https://obsidian.md/help/plugins/graph).

On **2026-09-08**, an isolated synthetic project in an existing registered test
vault was checked in **Obsidian 1.12.7**. The native graph showed **five notes and
twelve selected links**; node and backlink navigation were exercised. After a
native note rename, the renamed note retained its exact bytes, original application
configuration bytes were restored, and the corrected analyzer report resolved all
twelve links with one validated anchor and zero diagnostics. Private fixture notes
and runtime data were preserved. No new vault registration or live-vault migration
was performed for that check.

The native rename also updated a known backlink in the synthetic **outer Home
note**, outside the selected shared folder. This is a material boundary distinction:
Obsidian can update known backlinks across its vault. The read-only analyzer does
not scan the private parent to discover them, and cannot certify their absence.

Before a rename or move, review affected references and ownership, preserve the
original files, and decide whether any outer-vault edits are authorized. Do not
assume a filtered native graph confines automatic link updates. After the change,
rerun the graph, compare intended content changes and check navigation in the
chosen editor. The graph command itself provides no rename/move operation, rollback
or mutation boundary enforcement.

This native fixture is evidence for the exercised version and paths. It does not
establish universal Obsidian compatibility, every plugin or link syntax,
independent-user onboarding, provider synchronization or mixed-OS native behavior.
The analyzer's own `evidence.obsidian_ui` remains `not_run`; executing the command
is not a native application test.

## Bounds and parser limits

| Bound | Limit |
| --- | --- |
| Inspected inventory entries / graph nodes | 5,000 each; folder inventory counts directories too |
| Markdown note bytes | 2 MiB per note; 32 MiB total |
| Serialized graph | 64 MiB |
| Edges / diagnostics / candidate references | 20,000 each |
| Path depth | 32 components |
| Frontmatter | 64 KiB per note |
| Headings / block IDs | 1,000 each per note |
| Aliases | 64 per note; 256 characters per alias |
| Parsed line / link length | 16,384 / 2,048 characters |

Resource limits fail explicitly rather than returning a falsely complete graph.
Depth and overlong-line omissions are reported as diagnostics. Unrecognized or
overlong link syntax may not produce an edge; zero diagnostics is not proof of
complete rendering compatibility.

Frontmatter support is limited to top-level scalar values and scalar lists.
Unsupported or duplicate properties are diagnosed and never rewritten. Code fences,
recognized code spans, indented code and comments are excluded from link extraction.
Full YAML, HTML links, plugin syntax, query/search links, indented list continuations
and editor rendering are outside the declared coverage.

Local attachment inventory supports PDF, common image/audio/video formats, CSV
and text files. Only supported linked attachments become nodes, and their content
is never read. Non-UTF-8 Markdown, unsafe paths, symlinks and private/hidden inputs
are omitted or refused with the corresponding boundary diagnostics. The graph
does not infer semantic equivalence, validate claims from prose, or convert notes
into session credentials, policy or executable instructions.
