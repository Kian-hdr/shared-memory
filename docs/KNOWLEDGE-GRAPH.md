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
symlinks, Windows junction/reparse entries and unsupported file formats are excluded.
The selected root and its ancestors must be physical folders, without these links.
It never changes notes,
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

After canonical path and basename lookup, a bare wikilink can resolve through one
exact frontmatter alias. Its `resolution: alias` target receives ordinary heading/
block validation and backlinks. Duplicate aliases remain ambiguous; case or Unicode
normalization alone does not choose an alias. Markdown destinations do not use this
alias fallback, and private/excluded notes never supply alias candidates.

This is product lookup, not a claim that bare aliases work as native Obsidian links.
The `alias_requires_canonical_link` diagnostic identifies each resolved alias for
portable correction, for example `[[Decisions/Folder Boundary.md|Folder boundary]]`.
Obsidian's documented alias insertion uses the canonical filename plus display text. See
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
| `missing`, `ambiguous`, `nonportable_match` | Correct or disambiguate the destination; inspect candidates and the source line |
| `resolution: alias`, diagnostic `alias_requires_canonical_link` | Product alias lookup found the note; use its canonical destination and alias display text for portable/native links |
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

## Reviewed selected-folder note rename

The separate `graph-rename-*` commands rename one accepted Markdown note and
update supported selected-folder references through ordinary proposals. They do
not require Obsidian. The existing `graph` command remains read-only.

```sh
python shared-workspace.pyz graph-rename-plan ./Selected-project \
  --state-dir /private/local-state --source Notes/Old.md \
  --destination Archive/New.md
python shared-workspace.pyz graph-rename-draft ./Selected-project \
  --state-dir /private/local-state --plan-id rename-HASH \
  --proposal-id rename-note --assignment-id assigned-work \
  --evidence "Reviewed source, outgoing links and backlink diff"
```

Use the returned full `plan_id`, not the placeholder above. The plan contains the
original source and affected-note bytes, exact SHA-256 hashes, proposed changes,
affected link locations, baseline identity/revision/hash and resulting file hash.
It is stored as an immutable content-addressed JSON record under the external
client state's `rename-plans/`. Plan and draft leave project files untouched.
Review the complete diff and assign all affected paths, including both names.
Schema 2 drafts also require their current `--coordination-file`; the normal
session, lease, policy and input checks apply at submission and acceptance.

Submit using the existing `submit --proposal-id rename-note` command. An
authorized integrator then uses the existing `coord accept` route with appropriate
validation and coordination context. This can be an authorized agent. The rename
commands neither accept their own proposal nor change accepted authority.

```sh
python shared-workspace.pyz graph-rename-apply ./Selected-project \
  --state-dir /private/local-state --plan-id rename-HASH
```

Apply requires the current authenticated coordinator snapshot to exactly match
the reviewed result and to be newer than the plan's baseline. It then uses the
existing client materialization journal and immutable backups outside the project.
An ordinary refresh can also materialize accepted proposals. Rename-specific
apply adds its exact-result check and reparse-point preflights. No plan authorizes
parent-vault reads or writes. Every plan and apply result states that **outer-vault
backlinks are unknown and are not updated**.

Supported changes preserve all other bytes, including mixed LF/CRLF/lone-CR line
endings and no final newline. Explicit wikilinks and inline Markdown links retain
embeds, display labels, titles and heading/block fragments. Wiki replacements use
explicit selected-root paths with ordinary Unicode/spaces; Markdown destinations
use document-relative URI-encoded paths. Moving a note updates its supported
outgoing links as well as incoming references. Same-note anchors stay local.
Uniquely identifiable links in supported top-level frontmatter relation fields
can be updated; frontmatter alias declarations remain byte-identical. Affected
bare alias links become canonical destinations with the alias as display text;
existing explicit display labels, fragments and embeds remain intact. Unsupported
alias display delimiters are refused rather than changing the link syntax.
Unrelated alias references remain precisely flagged for canonical correction.
Before/after graph
comparison checks every parsed edge's target, fragment, relation and status.

The command refuses rather than guesses when an affected reference-style link,
escaped destination, ambiguous metadata span or unsupported graph diagnostic
prevents exact rewriting. It does not rename attachments or directories. Case-only
renames, canonically equivalent/casefolded collisions, existing destinations,
reserved/private paths and link-delimiter characters in source/destination names
are refused. Full YAML, HTML and plugin links remain outside parser coverage;
the plan certifies only the explicitly supported parsed links, not every syntax
an editor might render. Code/comment examples are retained unchanged.

Planning requires accepted Markdown to match the selected local Markdown inventory,
including no additional untracked notes. New local notes, changed/deleted notes,
changed accepted authority before drafting, or a changed saved plan require a new
review. Private runtime/configuration trees are excluded without reading their
contents; a private tree that the general client cannot exclude safely causes an
explicit refusal. Symlinks and Windows reparse points in the selected tree or
private recovery paths are refused. No private parent is inventoried for backlinks.

File materialization is **recoverable, not a multi-file filesystem transaction**.
On an interruption, rerun rename apply while the exact accepted result is current.
If authority has since advanced, rename apply refuses without resuming the old
journal; use the ordinary reviewed refresh/recovery workflow. Post-plan or
post-interruption edits are retained through client backups and preserved drafts.
A divergent old source is retained, so the receipt is `partial` until reviewed.
There is no automatic rollback: recovery completes accepted materialization, while
reversing an accepted rename requires a new reviewed proposal. External editors
are not locked out, and preflight/rechecks do not atomically exclude a hostile
concurrent OS path replacement. Coordinate editing during materialization.

## Optional Obsidian graph and rename checks

In an existing Obsidian vault, use Graph view's search filter to select the project
path, or open the local graph for a note. Graph nodes open notes; backlinks provide
navigation back to their sources. A graph filter controls what is displayed. It
does **not** turn the selected folder into a permissions or rename boundary. See
[Obsidian Graph view](https://obsidian.md/help/plugins/graph).

On **2026-09-08**, an isolated synthetic project in an existing registered test
vault was checked in Obsidian. The initial record listed **1.12.7** without
distinguishing installer and running application versions. The native graph showed **five notes and
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

A later **scoped product rename** on the same date used a fresh selected folder
inside that existing test vault, with all credentials/plans/backups outside it.
The running application reported **Obsidian 1.13.7 (installer 1.12.7)**. The actual
packaged schema-2 workflow made 20 CLI calls with two expected refusals, accepted
revision 1 and preserved original note backups, mixed newlines and private sentinels.
Native metadata resolved all six selected links with no unresolved destinations;
a rendered wikilink opened the renamed Unicode-path note, and its native backlinks
pane showed the three incoming Home references. Known outer Home/Parent backlinks
and existing application configuration remained byte-identical. Only the existing
vault's workspace layout changed during navigation. This is local synthetic evidence,
not a claim about untested plugins, other OS native clients or provider delivery.

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
is never read. Non-UTF-8 Markdown, unsafe paths, symlinks/reparse points and private/hidden inputs
are omitted or refused with the corresponding boundary diagnostics. The graph
does not infer semantic equivalence, validate claims from prose, or convert notes
into session credentials, policy or executable instructions.
