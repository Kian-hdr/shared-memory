# Optional Markdown content mode

This compatibility extension is a local development candidate. The published
v0.2.0 package does not support it. Use only a reviewed package whose command help
lists `--content-mode`; release packaging and its version are checked separately.

Normal setup retains its existing discovery behavior. To choose Markdown-only
discovery for a **new** selected project, explicitly use:

```text
python PACKAGE.pyz setup PROJECT --content-mode markdown
```

`PROJECT` is the selected existing folder, not implicitly its containing vault.
Advanced `init` accepts the same option alongside its normal identity/state flags.
Obsidian installation, app launch, vault registration, provider setup and changes
to parent folders or settings are not required.

In Markdown mode, initial import and discovery of new local files include `.md`
and `.markdown` case-insensitively. Untracked hidden/private paths retain their
existing exclusions. Untracked nested directories named `Coordination` are pruned,
and untracked non-Markdown files are skipped before path validation or content
reads. This leaves nested legacy tracker bytes and unrelated binaries/configuration
untouched. The selected root's own `Coordination` or `.workspace-project.json`
still requires separate reviewed legacy migration; this option does not take it over.

**Already accepted paths remain managed**, including non-Markdown files or files
under a nested `Coordination` directory. Accepted revisions, journal recovery,
drafts, delivery application and reviewed note moves retain those bytes and their
normal validation. The mode governs discovery, not authority permissions or file
access control. It does not make unsafe Markdown names, Markdown symlinks, malformed
notes or arbitrary history safe. Initial explicit `--include` in Markdown mode
must still select permitted Markdown files.

The choice is saved in the immutable setup intent, portable project manifest and
private client configuration. Re-run `setup PROJECT` with the same private state
to resume without restating it. Existing projects cannot switch modes through
`setup`, `init`, `attach`, or by overwriting metadata. No automatic conversion is
provided. The CLI spelling `legacy` means the previous discovery behavior; it does
not select or install the separate advisory tracker.

Markdown projects use manifest `format_version: 2` and private client
`schema_version: 2`, both with `content_mode: markdown`. Compatible readers retain
support for existing format-1 projects. Published v0.2.0 clients reject a format-2
folder instead of silently treating it as the earlier format. Do not remove or
downgrade these markers to make an older runtime accept the folder.

For a recipient, retain the owner's portable format-2 manifest in the selected
folder, or explicitly pass `--content-mode markdown` when attaching a new empty
local copy with its expected project ID, authorized endpoint and the recipient's
own credential. The authenticated coordinator protocol does **not** negotiate
content mode: access to an authority alone does not establish the owner's folder
configuration or prevent an older client from creating a separate format-1 copy.
Compatible client versions and matching folder configuration must be supplied in
the handoff. This is not an authority-wide minimum-client-version guarantee.

The `graph` command remains a separate bounded read-only analysis. Its raw-folder
entry and byte limits are unchanged and can include more inventory than the
Markdown client. Reviewed graph rename uses the selected client's mode and still
checks accepted note/link coverage and destination collisions. This extension
does not establish whole-vault graph coverage or native Obsidian compatibility.
