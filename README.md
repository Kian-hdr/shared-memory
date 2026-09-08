# Shared Memory

<img src="assets/shared-memory.svg" width="96" height="96" alt="Shared Memory icon">

**A shared workspace for your team and its AI agents.**

Shared Memory coordinates work in ordinary project folders: ownership, proposals,
accepted revisions, conflicts and handoffs, with readable Markdown knowledge.
**Obsidian is optional.** Select an existing project subfolder inside your private
vault if that is how you work; your whole vault is not the shared unit.

**Experimental prerelease: `v0.2.0-alpha.1`.** The runtime reports `0.2.0`; the tag
identifies its alpha maturity. Use disposable projects or backed-up working copies
for controlled trials. This is not stable V1, a hosted service, a native app, or a
production-readiness claim. Independent recipient onboarding, real provider delivery
and operational deployment still need validation. See [validation](VALIDATION.md)
and the retained [V1 graduation gates](docs/READINESS.md).

## Get started with your own agent

**[Copy the setup prompt](SETUP-PROMPT.md)** into a capable agent running on or
connected to your computer. No placeholders need editing. It discovers your project,
checks the exact package, and distinguishes creating an authority from joining one.
It preserves existing instructions and uses your own identities and private paths.

Release page: [v0.2.0-alpha.1](https://github.com/Kian-hdr/shared-memory/releases/tag/v0.2.0-alpha.1).
Use the following assets only once they are present on that release:

- `shared-memory-0.2.0-alpha.1.zip`: complete source, documentation and runtime kit.
- `shared-memory-0.2.0-alpha.1.pyz`: executable Python archive, requiring Python 3.11+.
- `SHA256SUMS`: external checksums to compare before executing any downloaded archive.
- `SETUP-PROMPT.md`: the same agent-guided entry point.
- `shared-memory-skill-0.2.0-alpha.1.zip`: optional complete agent skill; it does not replace the runtime.
- `shared-memory-icons-0.2.0-alpha.1.zip`: optional branding assets, not an application installer.

An absent release or asset is not an invitation to run an arbitrary `main` archive.
Use a specifically reviewed source revision and build it as described in the
[operating guide](docs/PRODUCT-V1.md#obtain-and-install-the-exact-reviewed-package),
or obtain the intended package from the owner. A repository download gives no access
to anyone's project, cloud account or private vault.

## Owner or teammate?

| Situation | Next step |
| --- | --- |
| First local trial | Select your existing project folder and a fresh private state directory; use `init`. No account, server or GUI is required. |
| New session-coordinated project | Explicitly configure schema 2 during `init`, then create your own session and acquire bounded work. |
| Join an existing project | Obtain your own member credential, the expected project ID and authorized coordinator endpoint; use `attach`. Never initialize a second authority for that project. |
| Operate a team server | Provide a reachable authorized host and verified TLS. Deployment, hosting and membership administration belong to the operator. |

The local core uses Python's standard library. The optional authenticated server
uses the pinned dependencies in `requirements-server.txt`. Private local state holds
tokens, drafts, backups and coordinator SQLite. Keep it outside the shared project
and consumer-sync/network storage. Each recipient has their own state and credential.

See [product setup](docs/PRODUCT-V1.md#owner-setup),
[joining](docs/PRODUCT-V1.md#team-transport-and-joining), and
[everyday collaboration](docs/COLLABORATION.md).

## What you can try

- Review and accept proposals from bounded assignments; preserve conflicts and offline drafts.
- Use opt-in sessions, ownership generations, dependency interfaces and durable handoff/conflict inboxes.
- Inspect links, aliases, anchors and backlinks in the selected folder; propose and apply reviewed note moves through accepted revisions.
- Install an exact verified package, retain previous versions, and use explicit backup/recovery procedures.
- Test immutable revision delivery through an explicit rclone route. Local fixtures are verified; the Google Drive account route still needs live provider acceptance.

The coordinator authenticates operations and accepts revisions. It does not prevent
arbitrary external editor writes, decide the truth of all prose, configure sharing,
or supply an AI model. [The operating guide](docs/PRODUCT-V1.md) records limits and
recovery behavior; [the graph guide](docs/KNOWLEDGE-GRAPH.md) separates product graph
behavior from bounded native Obsidian evidence.

Automated Windows, macOS and Linux CI and same-project HTTPS runner rehearsals are
engineering evidence. They do not establish physical recipient onboarding, a cloud
provider receipt, continuous availability or complete TEAM-11 acceptance.

## Legacy compatibility and source

Shared Memory has its own source repository,
[Kian-hdr/shared-memory](https://github.com/Kian-hdr/shared-memory). The original
Obsidian workspace toolkit is a separate legacy repository. Source history and
attribution are preserved.

The bundled toolkit 1.3.0 remains an explicit advisory option:
[instructions and direct tracker setup](docs/SETUP.md#legacy-advisory-tracker-setup),
[local tracker demo](docs/DEMO.md), and the
[complete skill](skills/setup-shared-project-workspace). Instructions or a legacy
tracker alone do not install the authoritative product or authenticate membership.
Do not silently substitute them when a product package is unavailable.

For development, read [validation](VALIDATION.md) and the [roadmap](docs/READINESS.md).
The runtime, skill and legacy toolkit have distinct version and validation scopes.

## License

[MIT](LICENSE). Keep the copyright and permission notice with copies or substantial
portions. No cloud account, subscription or access to someone else's workspace is included.
