# Share a project folder inside an existing vault

Use the selected project folder as the collaboration and access boundary. An
Obsidian vault is the contributor's containing workspace; it does not have to be
the shared unit. A plain Markdown project can use the same coordination files.

```text
Owner's existing vault/                 Teammate's existing vault/
  Private/                               Personal notes/
  Projects/Client Alpha/  <same share>    Collaboration/Client Alpha/
    Home.md                                Home.md
    AGENTS.md                              AGENTS.md
    Coordination/                          Coordination/
```

This diagram describes a possible layout, not a configured synchronization route.
The actual provider must support the intended local placement and folder access.
An independent copy is not a synchronized project.

## Configure only the selected folder

- Discover the exact project root separately from the existing vault root. Run
  setup on that project root, never silently promote the target to its parent vault.
- Read governing parent instructions locally, but do not copy confidential parent
  material into the share. Include the approved project-specific rules and required
  context within the shared project so teammates do not need the owner's private
  parent vault. If essential context cannot be shared, identify that blocker.
- Reuse the project's existing home and files. Add or merge only its AGENTS.md,
  pointer adapter and Coordination files. Leave parent notes, parent AGENTS.md,
  .obsidian settings and sibling projects unchanged.
- Setting up a project folder does not require launching Obsidian, registering a
  vault, creating a nested .obsidian folder or installing apps that already work.
  Do not open the GUI just to prove file setup. Desktop installation/opening is a
  separate requested full-computer or visual-verification scope.
- Use a distinct project folder/Coordination directory for each unrelated team or
  access boundary. Copy the toolkit when needed, not another project's live actor
  records and claims. Do not re-bootstrap a project a teammate is joining.

## Reuse across different local vault layouts

Store targets and the home pointer relative to the project. The 1.3.0 dashboard
finds Items relative to Workspace.base when opened directly as a main-content tab.
The same shared Base therefore needs no author-specific vault path.

Obsidian changes the meaning of `this` for embedded or sidebar Bases. The generated
filter includes a Base-file context guard; open Coordination/Workspace.base
directly, rather than embedding it or placing it in a contextual sidebar. A view
with an empty result is not evidence that there are no work items. Use tracker
status if the context is uncertain. Legacy fixed-path dashboards still require a
reviewed generated-file upgrade; do not rewrite them automatically while joining.
Sources: [Bases syntax](https://obsidian.md/help/bases/syntax) and
[file functions](https://obsidian.md/help/bases/functions), checked 2026-09-08.

## Configure the real sharing method separately

Share only the approved project folder through the existing authorized provider
or repository. Verify access and actual receipt with the intended contributor.
Do not grant access, send invitations, move live folders, add a provider, introduce
symlinks or expand the share to the parent vault merely to make a layout fit.
Those changes require the user's specific scope and the provider's supported route.
Some providers or device combinations cannot place a shared folder at an arbitrary
path; report that limitation instead of claiming this toolkit fixes synchronization.

Review outgoing links, attachments and necessary parent rules for the selected
share boundary. A link to a private sibling does not give the recipient access
and may reveal a private title. Keep reusable project context self-contained with
approved relative links or authorized external references.

## Report the actual outcome

Distinguish configured project files, authenticated editing access, provider
propagation and other-device receipt. For a folder-only request, app launch and
visual dashboard checks can remain unverified without blocking file setup.
A full computer-setup or explicit visual-verification request retains those checks.
No mode grants distributed locking or proves agent behavior merely from valid files.
