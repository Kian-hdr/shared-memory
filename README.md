# Shared Memory

<img src="assets/shared-memory.svg" width="96" height="96" alt="Shared Memory icon">

**A shared workspace for your team and its AI agents.**

Shared Memory coordinates ownership, proposals, accepted revisions, conflicts and
handoffs in ordinary project folders. Knowledge stays readable Markdown.
**Obsidian is optional.** You can share a selected project folder inside an existing
private vault without making the whole vault the shared workspace.

## Get started

1. **[Copy the setup prompt](SETUP-PROMPT.md)** into your own agent running on or connected to your computer.
2. **Choose an existing folder or a new folder.** Your agent discovers the remaining local details and asks only for information it cannot determine.
3. **Let the agent complete setup.** It installs missing authorized prerequisites, verifies the release, runs setup, resumes recoverable interruptions and checks your local receipt. Then work with your agent in that folder.

Use your actual project; a trial folder is optional. Setup preserves existing notes,
instructions and settings, and keeps credentials, drafts, backups and coordination
state in private local storage outside the selected folder. Your agents keep their
own conversations and histories; Shared Memory supplies shared project context and
an explicit acceptance workflow.

**Release: [v0.2.0](https://github.com/Kian-hdr/shared-memory/releases/tag/v0.2.0)**
(runtime `0.2.0`). Download the matching executable and external checksum before
running it:

- `shared-memory-0.2.0.pyz`: executable archive for Python 3.11+.
- `SHA256SUMS`: checksums to verify downloaded assets.
- `shared-memory-0.2.0.zip`: complete source, documentation and runtime kit.
- `SETUP-PROMPT.md`: agent-guided setup instructions.
- `shared-memory-skill-0.2.0.zip`: optional complete agent skill.
- `shared-memory-icons-0.2.0.zip`: optional branding assets.

Use the exact release assets when available. If an asset is absent or its checksum
fails, your agent must identify the problem rather than execute a different build.
A software download grants no access to another person's project or cloud account.

## Work locally or join a team

Local setup needs no account, server or Obsidian installation. The `setup PROJECT`
command creates or resumes the selected local project and reports its authenticated
state and receipt. It does not install an AI model or merge agents' private histories.

To join the same authority from another computer, obtain your own member credential,
the expected project ID and a reachable authenticated TLS coordinator endpoint from
the operator. Your agent uses those inputs and your own local folder. It must never
initialize a second authority for an existing team project.

Shared Memory includes a self-hosted server interface; it does not include managed
hosting or automatically deploy a server. Successful local setup is not proof of
cross-computer availability or Google Drive, OneDrive or iCloud delivery. See the
[operating guide](docs/PRODUCT-V1.md) for joining, hosting and explicit provider routes.

## What you can do

- Assign bounded work, save offline drafts, review proposals and preserve conflicts.
- Use session coordination with leased ownership, dependency interfaces and durable inboxes.
- Inspect links, aliases, anchors and backlinks within the selected folder, and propose reviewed note moves.
- Resume interrupted setup and materialization with retained drafts, backups and accepted history.

Ordinary file editors can still change files; those changes require proposal and
acceptance before becoming shared accepted state. The coordinator checks authority
and revisions, while people or authorized agents review factual and technical evidence.

[Setup and commands](docs/PRODUCT-V1.md) · [Collaboration](docs/COLLABORATION.md) ·
[Validation evidence](VALIDATION.md) · [Full product requirements](docs/READINESS.md)

The broader TEAM, COORD and GRAPH acceptance requirements remain tracked. Tests,
independent-recipient checks and live provider checks have separate evidence; they
are not a mandatory checklist for ordinary local onboarding or automatically passed
by publishing a release.

## Legacy toolkit and license

The separate original Obsidian workspace toolkit remains available as an explicit
[advisory tracker option](docs/SETUP.md#legacy-advisory-tracker-setup). Toolkit 1.3.0
and the authoritative runtime have different roles. Do not substitute the tracker
for a missing product package.

[MIT](LICENSE). Retain the copyright and permission notice with copies or substantial
portions. No cloud account, subscription or access to someone else's workspace is included.
