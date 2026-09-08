# Portable teammate onboarding

## Project-folder scope comes first

A selected shared folder inside an existing vault does not require a new vault,
app launch or changes to parent .obsidian settings. For folder-only setup, reuse
working components, configure/join only the project, and report UI checks as
unverified without blocking file setup. The full desktop installation/opening
steps below apply only when requested. Follow
[project-folder-sharing.md](project-folder-sharing.md) for different local vault
layouts, approved self-contained instructions and private-parent boundaries.


Use after workspace setup or when asked to onboard someone to an existing project.
Return the completed prompt in chat. Read [local-setup.md](local-setup.md) for local
installations and [storage-access.md](storage-access.md) for the selected access method.
The recipient does not need this skill installed: include the relevant instructions
in their final prompt rather than referencing files they cannot access.

## Gather project facts without inheriting the sender's environment

- Identify the actual workflow: a synchronized/shared folder, Git, hybrid, or local-only.
  The tracker mode describes record handling, not a storage provider or an account.
  A plain directory does not prove that sharing is configured.
- Identify the real access method and approved locator: a repository URL, folder
  invitation, network-share instruction, or no remote locator for local-only work.
  Never invent a service, account, domain, URL, folder ID, or mount path. Software
  distribution URLs identify this toolkit, not a shared vault or the recipient's identity.
- Express project and vault locations relative to the shared/checkout root. Include
  required parent instructions within the approved accessible scope. If that scope
  is incomplete, report the gap without assuming permission to share parent folders.
- Inspect the project home, instructions, current records, and tracker. Compute the
  actual tracker's SHA-256 and establish its provenance. A hash identifies bytes;
  neither a hash nor a generated-file marker is a security audit.
- Discover recipient identity, agent, OS, local paths, and account on their computer.
  Do not fill these fields with the sender's values or public repository author's name.
  Do not include the sender's absolute paths, account address, secrets, or unrelated notes.
- For shared work, resolve missing essential access information before calling the
  invitation ready. A URL is not mandatory if the real workflow uses another locator.
  For a local-only project, no account, cloud client, or share URL is required. If
  future sharing is undecided, finish local setup and label collaboration unconfigured.

## Build the recipient prompt

Replace all project fields before returning this template. Use `none (local-only)`
where applicable rather than inventing a link. This is an owner-filled invitation;
the repository's root setup prompt separately supports discovery without placeholders.
Include only the selected storage method's instructions. The recipient is the speaker.

```text
Set up this computer and my agent for the project below. Carry out the work with
available local tools, reuse working components, and resume after required user
handoffs. Do not just return a checklist.

Project: {{PROJECT_NAME}}
Setup scope: {{FOLDER_ONLY_OR_FULL_COMPUTER_SETUP}}
Workflow and actual storage/access method: {{WORKFLOW_AND_ACCESS_METHOD}}
Approved access locator or local-only status: {{ACCESS_LOCATOR_OR_NONE}}
Project path relative to accessible root: {{PROJECT_RELATIVE_PATH}}
Project home relative to project: {{PROJECT_HOME}}
Obsidian mode and vault path relative to accessible root: {{OBSIDIAN_MODE_AND_VAULT_PATH}}
Tracker mode: {{TRACKER_MODE}}
Expected SHA-256 of Coordination/project_tracker.py: {{TRACKER_SHA256}}
Storage-specific instructions: {{SELECTED_ACCESS_INSTRUCTIONS}}

These describe the project, not my account or local mount paths. Discover my own
identity and paths; ask only when required information cannot be found. The public
toolkit repository is a software source, not an invitation to its author's workspace.

I authorize necessary local installation and configuration for this project:
a maintained compatible Python, Obsidian for an Obsidian workflow, and only the
client/prerequisites required by the selected access method. If I choose Homebrew,
install and configure it when missing. This includes minimal PATH configuration,
app launch, and opening the correct vault. Do not ask permission again for each
already-authorized step. Preserve existing files, accounts, and unrelated settings.
Honor my actual tool/OS/admin approval rules and required authentication/consent.
Do not weaken those controls. Do not send messages, change sharing permissions,
buy anything, publish, or take over existing work without authorization for that action.

1. Inspect this computer and acquire the correct project.
Check OS/architecture and whether you can operate on my real local files, terminal,
and desktop. Explain any capability gap instead of claiming remote-container work
configured my computer. Follow only the specified access method. Use my own account
when one is needed; do not infer it from a sender, URL namespace, or folder name.
Hand required credentials, MFA, consent, and protected OS dialogs to me through their
normal interfaces, then resume. Never request or store secrets in chat or project notes.
An access request is not access granted. Do not send repeated requests while waiting.

For a shared folder, resolve its actual local path and inspect synchronization and
editing access. For Git, inspect the authorized remote and obtain/reuse the intended
checkout and branch, preserving uncommitted changes. Do not put .git in a folder
synchronized by another service. For hybrid work, map each target to its authority.
For local-only work, use my chosen directory and omit cloud sign-in and upload steps.
Do not treat a download or independent copy as a live shared workspace.

2. Install and configure missing local dependencies.
Reuse my preferred install route, an existing suitable package manager, or an official
installer. If Homebrew is chosen, look for an existing installation outside PATH and
reuse its proper architecture/prefix. If absent, follow https://brew.sh/ and
https://docs.brew.sh/Installation, inspect the installer, install required prerequisites,
and complete shellenv configuration with backed-up, minimal, nonduplicated edits.
Verify brew in the current environment and a fresh shell. Use documented unattended
options only when permitted; hand off necessary administrator authentication and resume.
Do not add an unrelated provider, unofficial sync replacement, browser, or WSL setup.

The tracker supports Python 3.9+; install a maintained stable release when missing,
using the chosen supported package manager or https://www.python.org/downloads/.
Verify the actual interpreter path/version and command availability. Normal tracking
uses only the standard library; development/test packages are not required.
Install a storage client only if the selected workflow requires it. Some methods
use an OS facility, Git, or an existing app instead of a separate desktop sync client.
Verify current official platform support; report unsupported routes rather than
silently changing the team's workflow.

3. Load the selected project and connect my agent.
For folder-only scope, keep the existing vault and .obsidian settings untouched;
do not open Obsidian or create/register a vault. Treat app checks below as optional
unless full computer setup or visual verification is requested.
Read all accessible governing instructions and the existing project home. Check the
expected project files and tracker provenance before executing shared code. Verify
the supplied digest and inspect the script. If it differs, obtain the owner's reviewed
update before execution. Missing files are a blocker, not permission to regenerate
another team's coordination layer. Do not bootstrap, upgrade the tracker, rewrite
history, claim work, or resume paused tasks under an onboarding request.

Open this project in my agent and explicitly load AGENTS.md; do not assume automatic
discovery. Confirm ownership, checkpoints, evidence, and handoff rules are understood.
The sender's skill need not be installed. If a new session is needed, give the exact
local project path and a continuation prompt.

For requested full desktop setup, unless I requested Markdown-only work or declined Obsidian, install it if missing
via the selected supported Homebrew route or https://obsidian.md/download. Follow
https://help.obsidian.md/install, launch the app, and open the correct existing folder
as a vault. Preserve configuration and avoid a duplicate/nested vault. Do not install
community plugins or add another sync service. Open the project home and Workspace.base
when present; inspect the UI if tools permit. Enable built-in Bases only when required
and allowed by the project's configuration rules. Otherwise report the exact gate or
unverified UI check. A package receipt does not prove the app or correct vault opened.

4. Establish my own context and verify readiness.
Use the trusted tracker with the actual interpreter. Validate and inspect status.
Ask my name only if unknown and choose a unique actor ID without my email or another
actor's identity. Once validation and applicable editing access pass, run tracker sync
for my actor, inspect recent changes and dependencies, then validate again. Do not
claim an existing task just to prove setup works or delete history to clear failures.

Verify my actor record locally. For a synchronized/shared folder, verify propagation
through its real storage mechanism when tools permit. For Git, separately report
local state, commit, push, and receipt at the remote: local tracker sync does none of
those. Commit or push only when authorized by my request or project instructions.
Do not require a cloud upload for local-only work. For hybrid work, verify each target
against its authority. Always distinguish local validation, remote propagation, and
another contributor's actual receipt; advisory claims are not distributed locks.

5. Report the outcome and continuation.
Give the actual local paths, access method, actor ID, reused/installed dependencies,
PATH changes, app/vault checks, tracker validation, and any relevant propagation
result. State locally configured, shared collaboration ready, partially configured,
or blocked according to actual evidence. For shared readiness, required installs and
any explicitly requested app/vault checks must pass; folder-only setup does not
require those app checks, the agent must load the
rules, the tracker must validate, and the chosen workflow's access and propagation
must be verified. A local-only workspace may be fully locally configured without an
account or remote. Identify unfinished checks and the smallest next action. Complete
independent work while waiting for external access; never invent completion.
```

## Review before returning

Review the filled prompt against the selected access method, a different account,
a different local root/OS, denied access, missing or modified tracker, no UI tools,
missing Homebrew/PATH, an explicit Markdown-only workflow, and enforced approval
settings. No provider should be installed merely because it appears in an example.
No owner-local path or account should be required on the recipient's machine.
Instruction review does not prove installation, login, UI behavior, or cross-device sync.
