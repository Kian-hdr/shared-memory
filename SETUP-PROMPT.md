# Set up Shared Memory

Copy the block into an agent running on or connected to your computer. Select the
folder when it asks for information it cannot discover. No placeholders need editing.
This prompt targets the published **v0.3.0** release and supports new setups or
updating an existing installation while preserving its project and private state.

```text
Set up Shared Memory 0.3.0 for the folder I want to work in. Use the normal direct
folder workflow: people and agents edit notes normally, save offline, and reconcile
shared changes when the chosen provider reconnects. Reviews are optional after edits;
do not install a mandatory coordinator, proposal queue or always-online integrator,
and do not replace those gates with hidden automatic approval.

Read my existing instructions and discover the selected folder, current Shared
Memory format, available Python 3.11+ and installed runtime. A selected subfolder in
my existing private Obsidian vault is valid. Preserve existing notes, instructions,
parent folders, settings and attachments. Do not create or open a vault merely for
setup. Create a new ordinary folder only if that is the folder I selected.

Use the published release at:
https://github.com/Kian-hdr/shared-memory/releases/tag/v0.3.0
Download the runtime and external checksum file from these exact URLs:
https://github.com/Kian-hdr/shared-memory/releases/download/v0.3.0/shared-memory-0.3.0.pyz
https://github.com/Kian-hdr/shared-memory/releases/download/v0.3.0/SHA256SUMS
The runtime's expected SHA-256 is:
32f8cc4ef06050b6859d0a5236370819fc66ac0769051551e892c5801436e91d
Verify the downloaded runtime against both that value and its SHA256SUMS entry
before execution. If a download is unavailable or the checks disagree, report the
exact blocker; do not substitute a candidate or older release. Reuse working
prerequisites and install missing local components within my task authorization.

Read the verified package's version, capabilities, guide and setup --help. Confirm
version 0.3.0 and direct-folder support. Install it outside shared storage with
install-package, passing the verified package as its positional argument plus
--sha256 and --tools-dir with actual local values. Use the immutable installed path
returned by that command for subsequent operations. Reuse an already verified
identical installation. Preserve prior runtime versions and existing private device
state when upgrading; never copy another person's identity, baseline or credentials.

Inspect the project format before setup. For a new or existing format-3 folder,
run setup using the selected path and reuse its actual provider and my own local
copy. When joining a known project, check its delivered identity and use
--expected-project-id; missing metadata is not permission to create a second project.
Keep each computer's private baseline and recovery state outside shared storage.
The shared folder carries the product's portable metadata/history, not a credential
or SQLite database. Discover existing state rather than asking me for coordinator
endpoints, member tokens or session leases for normal folder use.

If the folder already uses the old coordinator format, diagnose it first. Keep its
identity and history intact. Explain the available backed-up migrate-folder operation
and perform the migration when covered by my request; do not silently initialize
a second project or discard old state. Explicitly retained coordinator projects use
the historical workflow instead of mixing the two protocols.

For sharing, use one chosen provider for the selected folder, not a bridge between
Google Drive, iCloud, OneDrive and Nextcloud. Local-only work needs no provider.
Complete the selected provider's necessary local setup; preserve its read-only and
sharing permissions. Respect unavoidable sign-in, MFA, OS controls and explicit
limits in my request. Do not infer access to someone else's folder or provision an
unrequested hosted service. Keep files needed offline actually downloaded, and
check that the product's shared history is included in provider synchronization.

After setup, run sync and folder-status with the returned private-state path.
After direct edits, run sync to capture them and reconcile visible history. Repeat
after reconnecting or receiving provider changes. Preserve conflict copies before
cleanup, including copies a provider has not uploaded. Merge only compatible text;
leave ambiguous or contradictory versions available and use an explicit resolution
with evidence. Any editor authorized for that folder may resolve a conflict; do not
invent a permanent reviewer. Textual convergence is not proof of factual correctness.
Use explicit deletion/rename operations when intended, and validate affected links.

Finish feasible local setup and report the selected project identity, saved local
state, current folder status, conflicts or preserved work, and what provider/device
receipt was actually checked. Do not require a disposable trial before normal use.
Return a concise teammate prompt with the actual folder/provider access instructions
and exact compatible package source, no credentials or sender-specific private paths.
Mark missing access clearly and do not send the prompt automatically.
```

[Operating guide](docs/PRODUCT-V1.md) · [Provider choices](docs/PROVIDERS.md)
