# Local dependencies and app setup

## Project-folder scope comes first

Ordinary project folders require no Obsidian app. A selected shared folder inside
an existing vault does not require a new vault,
app launch or changes to parent .obsidian settings. For folder-only setup, reuse
working components, configure/join only the project, and report UI checks as
unverified without blocking file setup. The full desktop installation/opening
steps below apply only when requested. Follow
[project-folder-sharing.md](project-folder-sharing.md) for different local vault
layouts, approved self-contained instructions and private-parent boundaries.


Use when the recipient requests computer readiness or full workspace setup. A request
to audit a project or write an onboarding prompt does not itself request installations.
Apply the recipient's existing authorization to the necessary local steps below.

## Authorization and continuation

The full setup prompt authorizes required local installs, their prerequisites,
minimal PATH configuration, app launch, and opening the chosen vault. Install missing
Obsidian only for explicitly requested Obsidian desktop setup, a compatible Python, and only the components needed
by the actual access method in [storage-access.md](storage-access.md). Local-only
work needs no cloud account/client; Git and some sharing methods use different tools.
If the recipient chooses Homebrew, that choice includes
installing and configuring Homebrew when missing. Do not ask for the same permission
again at each package, installer, or configuration step.

Honor the recipient's actual approval settings, tool policy, administrator policy,
and governing instructions. Do not weaken them to make setup unattended. Stop for
missing information that changes the target, an enforced approval gate, an action
outside scope, or an interaction only the recipient can perform. Explain the exact
gate once and continue automatically after it is resolved. Passwords, MFA, protected
OS dialogs, and account consent stay in the normal user interface, never in chat.
Routine installer confirmations may be handled under existing authorization when
the environment permits. Use documented unattended options only when applicable;
they do not grant privileges or bypass authentication.

## Discover and choose the installation route

- Inspect OS/architecture, available disk space, local tools, installed apps,
  interpreters, package managers, and the relevant existing shell configuration.
- Reuse working installations. Preserve the user's explicit installer preference.
  If no preference is stated, use an existing suitable package manager or an official
  installer. Do not introduce Homebrew merely because it is mentioned in the guide.
- If Homebrew is chosen and absent, install it. If the chosen route is unsupported,
  explain why and select a compatible official route within scope; ask only when a
  material user preference remains unresolved. Do not add WSL just to install native
  Windows desktop apps, or assume a Linux runtime can configure the host desktop.
- Use current official sources and inspect the selected installer before execution.
  Install only missing prerequisites needed by this route. For toolkit retrieval,
  a ZIP avoids installing Git when Git is otherwise unnecessary.

## Homebrew, when chosen

Follow the current [Homebrew installer](https://brew.sh/) and
[installation documentation](https://docs.brew.sh/Installation). Check the actual
platform and install prerequisites, including Apple Command Line Tools when required.
Reuse an existing installation even when it is missing from PATH. Use the appropriate
official prefix; do not create a second architecture installation by accident.

Complete the installer's `brew shellenv` instructions for the actual shell. Back up
any existing startup file before a minimal, idempotent edit. Activate the same
environment for the running agent and verify that a fresh shell finds the intended
`brew`, with the expected `brew --prefix` and `brew --version`.

Homebrew documents `NONINTERACTIVE=1`; use it only when the authorized installation
can run with available privileges. If authentication is required, hand over that
interaction and resume. Do not run package operations as root or change security
settings to overcome an installation error.

Check current package metadata and platform support before installation:

| Needed component | Homebrew route, when supported |
| --- | --- |
| Obsidian | `brew install --cask obsidian` |
| Python | Install the current suitable Python formula; verify its interpreter path |

The [Obsidian cask](https://formulae.brew.sh/cask/obsidian) publishes its current
platform requirements. Check a selected storage client's metadata separately.
Package-manager support does not imply every app supports
the same OS. Do not force incompatible casks or upgrade unrelated packages.

## Python and other required dependencies

The tracker supports Python 3.9+. For a new installation, choose a currently
maintained stable release from [Python](https://www.python.org/downloads/) or the
chosen supported package manager, rather than installing the oldest accepted version.
Use the interpreter actually installed, such as `python3`, `py -3`, or an absolute
path. Check its version and run the trusted setup/tracker `--help` with it. If PATH
configuration is needed, preserve existing interpreters and shell settings.

Setup and tracking use only the Python standard library. PyYAML and a development
environment are needed only when running the repository's tests. Install any further
platform prerequisite only when a real installer or launch error establishes the need.
Do not install full development suites or unrelated browsers by default.

## Install, launch, and open Obsidian

For an Obsidian workspace, install Obsidian if missing, then launch it and open the
correct vault. Skip it only for an explicitly Markdown-only workflow or when the
recipient declines it. Use the selected compatible Homebrew route or
[Obsidian's official downloads](https://obsidian.md/download), following the current
[installation instructions](https://help.obsidian.md/install).

After installation, verify the app is usable from the user's normal desktop
environment. Use [Open folder as vault](https://help.obsidian.md/manage-vaults) for
the existing vault. Create a vault only at the recipient's chosen new location.
Do not create a nested vault, duplicate shared notes, or overwrite existing `.obsidian`
configuration. An application bundle or package receipt alone does not prove launch.

Open the project home and, after workspace setup, `Coordination/Workspace.base`.
Verify the dashboard renders when UI tools are available. Enable the built-in Bases
feature only if required and the target's configuration rules permit that bounded
change. Preserve unrelated settings. Do not install community plugins, purchase Sync,
or enable another sync service as an implicit dependency. If shared configuration
requires owner approval, report that specific gate. Never report UI verification
when no UI inspection was possible.

## Only the selected access method

Identify the method before installing anything for storage. Follow
[storage-access.md](storage-access.md); no provider is the default. If the method
requires a desktop client, install and launch that client under setup authorization.
Reuse existing accounts and sync configuration, then open the official sign-in flow
only if that method needs it. Have the recipient complete authentication and consent,
then resume. Local-only work needs neither sign-in nor upload; a Git checkout uses
its own remote/access workflow, not a cloud desktop sync client.

If the official client cannot run on this platform or organization policy blocks it,
report the exact blocker and available supported path. Do not install an unofficial
sync client, change providers, mirror an entire drive, or treat a download as the
shared working directory. Access requests and permission changes follow existing
authorization and the recipient's policy; this local setup alone does not grant them.

## Completion evidence

Report installations and versions, any required prerequisites, shell/PATH changes,
app launch, correct vault opening, tracker validation, actor record, and provider
propagation where applicable separately. Recheck validation after actor creation.
Report local-only readiness without inventing a remote dependency. An unavailable UI or
authentication step means that part is unfinished; complete independent work and
provide the precise continuation step. Do not declare the requested setup complete
while a required installation, configuration, launch, or validation step remains.

Official installation sources checked on 2026-09-04. Refresh compatibility and
installer behavior at execution time. This guide has been reviewed as instructions;
it is not evidence of an unattended install on a recipient's computer.
