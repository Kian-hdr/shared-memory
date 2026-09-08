# Shared Memory

**A shared workspace for your team and its AI agents.**

Shared Memory is the product name. The repository remains
[`Kian-hdr/shared-obsidian-workspace`](https://github.com/Kian-hdr/shared-obsidian-workspace);
existing setup links and technical identifiers remain valid.

An independent coordination product for ordinary project folders and AI agents.
Readable Markdown holds project knowledge and instructions. The development
runtime coordinates ownership, proposals, accepted revisions and handoffs;
**Obsidian is optional** and never required to install, open or use the core.

Existing Obsidian users can share the same project folder inside their own private
vaults. You do not need a new vault or to share your private parent vault.

The repository includes a copyable `AGENTS.md`, a complete setup skill, the product
runtime and a legacy advisory Python tracker. [See the project-folder workflow](skills/setup-shared-project-workspace/references/project-folder-sharing.md).

The instructions cover navigation, ownership, evidence, synchronization checkpoints,
and handoffs. The optional Python tracker adds work records, target claims, dependency
tracking, and an Obsidian Bases dashboard.

Use your own folder, repository, storage provider, and account. Local-only work needs
no online account. The public GitHub address below is the software source; it does
not connect you to the maintainer's vault or Google Drive.

The legacy tracker uses advisory file claims. The development engine adds
authoritative proposal acceptance and recoverable file materialization. Neither
controls external editors or configures a provider’s sharing permissions.

## Try the legacy toolkit's local handoff demo

Run the [two-person demo](docs/DEMO.md) in a disposable plain-folder fixture.
An optional mode also tests a project within an existing-vault fixture. It uses actual
tracker commands to demonstrate separate work, a rejected conflicting claim,
an accepted handoff and verified completion. It uses fictional actors on one
computer and needs no cloud account. It does not launch independent AI agents.

**Maturity: early toolkit for controlled pilots.** Review the
[production-readiness roadmap](docs/READINESS.md) before adopting it for critical
or large-scale work. Published 1.2.0 has known drift-detection gaps; the local
1.3.0 candidate adds fixes and a reproducible demo pending publication.

## Authoritative product development build

The [Shared Memory operating guide](docs/PRODUCT-V1.md) describes the **0.2.0
development build**: a local SQLite authority, authenticated team protocol, atomic
revision acceptance, preserved conflicts/offline drafts, recoverable file updates,
owner/recipient setup and verified package installation/rollback. It requires Python
3.11+. Obsidian remains optional.

Local tests and a packaged TLS rehearsal do not establish cloud-provider delivery,
real recipient onboarding or mixed-OS TEAM-11. Stable V1 is not complete. The
[readiness roadmap](docs/READINESS.md) retains those gates and the deferred GitHub
launch rename. The historical advisory toolkit and 0.1.0 preview remain documented
separately; current public main may lag this local development candidate.

## Let your agent set it up

**[Copy the setup prompt into your own chat](SETUP-PROMPT.md).** No placeholders
need editing. The prompt guides a local agent through selecting your project folder, preserving
existing instructions, setting up or joining the correct project, and checking the
result. The folder can already live inside a private vault. Optional installation
and access setup depend on your chosen workflow and authorization; Obsidian setup
is only included when you request it.

## Get it

- [Download the repository ZIP](https://github.com/Kian-hdr/shared-obsidian-workspace/archive/refs/heads/main.zip).
- [Open the copyable AGENTS.md](AGENTS.md).
- [Open the complete skill folder](skills/setup-shared-project-workspace).

Or clone it outside your synchronized vault:

```bash
git clone https://github.com/Kian-hdr/shared-obsidian-workspace.git
cd shared-obsidian-workspace
```

## Legacy toolkit options

For the authoritative runtime, follow [the product guide](docs/PRODUCT-V1.md)
using an explicitly reviewed `.pyz` and its external SHA-256. The options below
install the historical advisory toolkit; they do not install the team coordinator.

| Option | What to copy | Result |
| --- | --- | --- |
| Instructions only | Root `AGENTS.md` | Navigation and shared-work rules; no tracker installed |
| Full agent skill | Entire `skills/setup-shared-project-workspace/` folder | Agent-guided bootstrap, retrofit, audit, and teammate onboarding |
| Direct setup | Run the bundled Python setup script | Same workspace files, without requiring a skill-aware agent |

### Instructions only

Copy [AGENTS.md](AGENTS.md) into the selected project folder. If that file already exists, merge
the relevant sections rather than replacing your existing rules. Keep any stricter
privacy, approval, and project-specific requirements. The instructions discover the
recipient's environment rather than assuming the source author's account or paths.

Tell your agent to read the file explicitly. Automatic discovery differs by agent.
The file alone does not install the tracker or configure sharing.

### Full skill

Copy the **whole** `skills/setup-shared-project-workspace` folder, preserving its
structure. `SKILL.md` references bundled scripts, assets, and reference documents.

For an existing Codex setup using `~/.codex/skills/`, place the folder at:

```text
~/.codex/skills/setup-shared-project-workspace/
```

Keep a backup and review differences if a skill with that name is already installed.
Start a new agent session if needed, and confirm the skill is discoverable. Other
agents can read its `SKILL.md` directly and use the scripts without automatic discovery.

Then use the same [setup prompt](SETUP-PROMPT.md). It is the single starting prompt
for both downloaded toolkits and installed skills, and discovers your actual project.

### Direct setup

See [the setup guide](docs/SETUP.md) for copyable terminal commands, Windows guidance,
existing-vault preservation, generated files, and validation.

Setup and the tracker require **Python 3.9+** and only its standard library.
The ordinary-folder workflow uses no Obsidian installation. Full desktop setup
can install Obsidian when explicitly requested. The notes are ordinary Markdown. Viewing `Workspace.base`
requires an Obsidian installation that supports Bases. Python tests additionally
require PyYAML, which is a development dependency only.

## How teammates use the legacy toolkit

1. The owner configures the actual shared project once.
2. Teammates obtain authorized access through that project's actual access method.
3. Each agent reads `AGENTS.md`, reviews current records, and uses a unique actor ID.
4. Contributors claim separate targets and check ownership before each mutation.
5. Material changes include evidence, dependency impact, and a next action.
6. The next contributor accepts a handoff and refreshes their context before editing.

Teammates do **not** need this skill installed once the project contains the generated
tracker and instructions. They need access to those project files and a compatible
Python runtime. Downloading this public repository does not grant access to anyone's
private vault, and downloading a copy of a vault does not create a synchronized workspace.

See [the collaboration guide](docs/COLLABORATION.md) for everyday use and conflict handling.

## Choose your own access method

| Your workflow | What setup needs |
| --- | --- |
| Local-only | Your chosen folder; no cloud account, client, link, or upload |
| Git | Your project's remote and checkout, using your own access |
| Shared folder | Your actual service/network share and its approved locator |
| Hybrid | A clear mapping of notes, code, and other targets to their authorities |

Google Drive is one optional provider, not a requirement. The
[access guide](skills/setup-shared-project-workspace/references/storage-access.md)
keeps provider-specific instructions separate from the generic setup. The toolkit
does not supply storage, subscriptions, accounts, or access to someone else's files.

Shared file targets and project-home references use project-relative paths so each
person can keep the project under a different local root. The portable dashboard is opened directly as a main-content Base tab; embedding
or contextual sidebar use is not supported by its relative scope. Legacy fixed-path
dashboards require a reviewed upgrade.
See [updating an existing workspace](docs/SETUP.md#updating-an-existing-workspace)
before upgrading an older tracker or transferred copy.

## Repository contents

```text
AGENTS.md                         Copyable vault instructions
SETUP-PROMPT.md                   Paste into your own agent's chat to get started
docs/SETUP.md                     Owner setup and validation
docs/COLLABORATION.md             Teammate workflow and boundaries
skills/setup-shared-project-workspace/
  SKILL.md                       Agent workflow
  agents/openai.yaml             Skill display metadata
  assets/                        Tracker and Obsidian dashboard template
  scripts/                       Setup, validation, and regression tests
  references/                    Retrofit policy, record schema, onboarding prompt
LICENSE                          MIT license
```

## Validation and development

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python skills/setup-shared-project-workspace/scripts/test_workspace.py
.venv/bin/python skills/setup-shared-project-workspace/scripts/test_doctor.py
```

On Windows, use `.venv\Scripts\python.exe` instead of `.venv/bin/python`.
The regression suite uses disposable temporary projects. It checks setup preservation,
ownership conflicts, stale dependencies, validation, and handoffs. It does not prove
cloud upload, another computer's receipt, or the Obsidian dashboard's visual behavior.

See [VALIDATION.md](VALIDATION.md) for current local checks, historical publication evidence and their limits.

## Product direction

Windows, macOS and Linux are first-class targets for the core, CLI and agent
workflow from the start. Equivalent behavior and same-project mixed-device
collaboration are required release criteria, not inferred from portable source.
Provider/account/OS support is tracked separately in the [capability matrix](docs/READINESS.md#provideraccountos-capability-and-verification-matrix).
The authenticated server and local folder receipt adapters are implemented.
Reachable hosted/self-hosted deployment, vendor API adapters and real provider
delivery still need implementation or validation; Obsidian is optional throughout.

Strengthen the independent folder/Markdown core and consistent agent interfaces
first. After real workflows are validated, a lightweight companion can expose
folder selection, work ownership, change review and handoff acceptance. A later
optional Obsidian plugin should reuse the same core, not implement a second
tracker. Neither interface is included in this candidate. See the
[roadmap](docs/READINESS.md) for evidence gates and architecture limits.

## License

[MIT](LICENSE). You may copy, adapt, and redistribute the toolkit under that license.
Keep its copyright and permission notice with copies or substantial portions.
