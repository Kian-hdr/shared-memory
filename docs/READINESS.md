# Shared Memory: readiness and development roadmap

**A shared workspace for your team and its AI agents.**

The product name is Shared Memory. Obsidian is optional. The product repository is
[Kian-hdr/shared-memory](https://github.com/Kian-hdr/shared-memory); package filenames
and protocol identifiers retain compatibility. The
name is a product decision; trademark and domain clearance are unverified.

## Independent product repository, 2026-09-08

Kian selected a separate repository for Shared Memory because its scope has grown
beyond the original Obsidian workspace toolkit. This supersedes the earlier plan
to rename the toolkit repository at first-version launch. The product uses
`Kian-hdr/shared-memory`; the original repository remains the legacy toolkit record
and is being made private. The new product repository also remains private during
development and becomes public only when version 1 is finished, as Kian specified.
Source history and attribution are preserved.

Current setup, clone and download navigation point to the product repository.
Historical CI links in the validation record retain their original provenance and
may require access to the private legacy repository. New CI and release evidence
must come from this repository. Existing installed packages and published pitch/QR
links need explicit review before replacement; a new repository creates no redirect
from the old URL. Repository separation does not establish stable V1, provider
support, trademark/domain clearance or readiness to migrate a live vault.

## Accepted product direction

The independent core operates on ordinary project folders, readable Markdown and
Python, with consistent interfaces for agents. Obsidian is optional. Existing
Obsidian users can keep the shared project inside their own private vaults; other
users need no Obsidian installation, launch or account. This choice does not
establish synchronization, concurrency or recovery guarantees.

The product is a coordination engine with readable project knowledge, consistent
agent interfaces and a thin human interface. AGENTS.md explains how to use it; the
instruction file is not the entire system. The following specification is accepted
design direction, not a description of implemented 1.3.0 capabilities.

## Short product specification

### First-class operating systems

Windows, macOS and Linux are first-class requirements from the start for the
independent core, CLI and agent workflow. This supersedes any earlier
macOS/Windows-first proposal that would defer Linux core or client support.
All three use the same portable project format and coordination protocol,
project-relative paths, platform-appropriate installation and equivalent core
functionality. Automated tests on all three OSes and real mixed-device
collaboration are required; source portability alone is insufficient evidence.

Markdown remains the readable knowledge, instruction and handoff foundation. A
small executable local CLI/core handles ownership, validation, proposals and
accepted revisions; the team coordinator supplies authoritative multi-computer
acceptance. Local-only, hosted and self-hosted operation must all work without
Obsidian. No new operating system or full desktop GUI is needed for the initial
product. Users can stay entirely in the setup-prompt/agent workflow; a GUI or
background watcher follows demonstrated needs.

Core OS support is distinct from provider support. Build storage adapters around
the common core rather than requiring every platform to run a vendor desktop
sync client. Unsupported provider/account/OS combinations must be explicit; do
not silently change providers or install unofficial clients.

### Setup and daily use

An owner or teammate pastes a setup prompt into a capable local agent. The agent
discovers create/join intent, the exact project folder and actual access method;
obtains a specific reviewed GitHub revision; installs only missing authorized
components; establishes distinct person/agent project identities; verifies access
and receipt of the expected accepted revision; and reports ready, partial or
blocked from evidence. Ask only for undiscoverable choices, required authorization
or protected human interactions. No new vault or Obsidian launch is mandatory.

Everyday work can remain in the agent. A later thin companion presents the selected
folder, current work/owners, recent changes, pending handoffs and conflicts. An
optional Obsidian plugin uses the same engine and interfaces. Neither interface is
implemented in this candidate; this direction does not request a whole app now.

### Bounded assignments and integration

Each assignment carries a human owner, acting agent, permitted targets, dependencies,
starting accepted revision, acceptance criteria, resource limits and an integration
owner. Use Git branches/worktrees for code where appropriate and isolated proposals
for notes/research. Agents return proposed changes and validation evidence; the
integration owner accepts them. Swarms are adaptive bounded execution, not a
mandatory group size or an expansion of permissions.

### Authority and atomic acceptance

| State | Proposed authority |
| --- | --- |
| Accepted code history and code merges | Git |
| Membership, work ownership, accepted knowledge revisions and proposal history | One authoritative coordinator per project |
| File delivery and large artifacts | The selected storage provider |
| Readable project files | A materialized view of accepted state, plus explicitly identified local drafts |

The robust team architecture uses one hosted or self-hosted coordinator per project.
Every proposal identifies its base revision. The coordinator atomically checks that
base and updates the accepted revision. A stale proposal must be compared/rebased;
it cannot silently replace newer accepted state. Deduplicate identical updates,
validate compatible independent combinations, and preserve conflicting proposals
for reconciliation.

Semantic disagreement requires source evidence and recorded authority rules even
when text merges cleanly. Timestamp alone does not establish truth; Git does not
arbitrate factual claims. An unresolved consequential dispute preserves the last
accepted state, flags the competing proposals and routes the decision to the
responsible person.

Direct edits from editors or sync clients enter as proposals, not silent accepted
replacements. Accepted state, materialized file updates and recovery must be designed
and tested together. A metadata service alone cannot guarantee safe file updates.

### Local, offline and storage modes

Local-only works without a server or account. Offline team contributors may draft
and queue proposals, but cannot assert globally accepted ownership or revisions
until reconciliation. A folder-only shared mode may remain with explicitly weaker
guarantees. Preserve drafts and both versions through conflicts and recovery.

Google Drive has a first explicit immutable-revision rclone adapter with local fixture
coverage. OneDrive and iCloud adapters remain planned. Each requires real
provider/device validation. Start with one provider and two people; do not claim
parity or supported folder placement/access isolation across providers. Use one sync
provider per physical shared folder. Keep Git repositories/worktrees outside
cloud-sync directories. Verify recipient receipt against expected revision/content
hashes; file existence or local tracker sync is insufficient. Sharing a selected
subfolder must not expose unrelated private parent-vault material.

Publication, accounts, permissions, billing and protected interactions retain their
existing approval boundaries. This architecture does not authorize those changes.

### Provider/account/OS capability and verification matrix

This initial matrix records scope and known gaps, not completed adapter support.
For every chosen route, add the exact account tier/policy, device/OS version,
adapter/client version, authorization method, supported operations, folder-placement
and access-isolation limits, receipt hashes, offline/recovery results, date and
primary source. Split rows when account types or policies change capabilities.

| Provider and account type | Windows | macOS | Linux | Product verification / next evidence |
| --- | --- | --- | --- | --- |
| Local filesystem; no account | Required | Required | Required | The corrected development CI passes on all three OSes; installed/operator behavior and real cross-device delivery remain separate evidence |
| Self-hosted storage; deployment-specific identity | Required integration path | Required integration path | Required integration path | Authenticated coordinator HTTPS and local folder receipt inspection are implemented and tested locally; an actual storage delivery route and reachable deployment still need selection and real receipt/recovery validation |
| Google Drive; personal Google account | Vendor desktop route documented; adapter unverified | Vendor desktop route documented; adapter unverified | Drive for desktop unavailable; explicit rclone route implemented, live account acceptance unverified | Check account-specific API/access capabilities and supported route before claiming product support |
| Google Drive; Workspace / shared drives where applicable | Vendor desktop route documented; account-policy integration unverified | Vendor desktop route documented; account-policy integration unverified | Drive for desktop unavailable; explicit rclone route implemented, live account acceptance unverified | Verify actual Workspace policy, shared-folder/drive access and recipient receipt; no personal-account equivalence assumed |
| OneDrive; personal Microsoft account | Adapter/capabilities unverified | Adapter/capabilities unverified | Adapter/capabilities unverified | Review official account/OS support and test the chosen route; no vendor-client or API parity claimed |
| OneDrive / SharePoint; work or school account | Adapter/capabilities unverified | Adapter/capabilities unverified | Adapter/capabilities unverified | Verify tenant policies and supported sharing/placement, then receipt and recovery |
| iCloud Drive; Apple Account and actual sharing arrangement | Adapter/capabilities unverified | Adapter/capabilities unverified | Adapter/capabilities unverified | No iCloud/Linux integration or parity is claimed; establish a supported route or report the combination unsupported |

Google's current requirements explicitly state that Drive for desktop is not
available on Linux. A browser route is not proof of a local agent integration.
The explicit rclone route is separate from that desktop client. Its implementation
and local fixtures do not yet establish live Google Drive account acceptance. [Google Drive system requirements](https://support.google.com/drive/answer/2375082), checked 2026-09-08.

Google Drive, OneDrive and iCloud remain priority integrations alongside local and
self-hosted storage. Priority does not imply verified support. Keep one provider
per physical shared folder and Git/worktrees outside cloud-sync directories.

## Active implementation goal, 2026-09-08

Build the complete agreed Shared Memory product and independently validate it using
a bounded implementation/review team. The 0.1.0 CLI is a completed foundation, not
the full goal. The [authoritative engine contract](../product/ENGINE-CONTRACT.md)
records the next module interfaces, ownership and executable acceptance requirements.
All local/team/provider/OS and TEAM gates below remain required.

Prepare migration plans, dry-run checks, backups and rollback only on synthetic or
isolated task-owned fixtures. After validated readiness, the owner will back up the
live Vault and copy it to a second drive, then confirm the intended working target.
No migration/restructuring or sharing change to that live Vault or backup drives is
authorized before that confirmation. Report blocked readiness precisely if actual
provider/recipient/mixed-device gates are unavailable.

## Approved autonomous coordination and graph extension, 2026-09-08

These accepted requirements extend the current implementation. They are not passed
capabilities. Keep private development until finished V1 and retain TEAM-01–TEAM-11.

Autonomy is primary: discover available setup details and ask only for essential
undiscoverable folder/execution/membership/budget/constraint choices. Routine work
within established scope proceeds without discretionary permission prompts. Task
limits, confidentiality and mandatory platform/authentication controls still apply.

### Identity, planning and safe integration

- Distinguish requester, person, agent, running session, assignment and delegated
  scope. Project owners set objectives/membership/budgets/rules; coordinating agents
  plan/schedule/replan; integration owners may be authorized agents; workers claim
  bounded work; reviewers independently verify consequential results; the service
  enforces recorded decisions. Human review is not a mandatory routine bottleneck.
- Reserve intended outcomes as well as files/resources. Record acceptance criteria,
  inputs/outputs, dependencies and integration owners. Atomically grant exclusive
  claims and detect existing equivalent outcome requests. Likely semantic duplicates
  are review signals, not proof of perfect duplicate detection.
- Extend planning to a queued/ready dependency graph with explicit input/interface
  revisions and invalidation. The current completed-dependencies-only claim rule
  does not satisfy this. Workers may proceed against agreed interfaces while
  implementation and tests develop independently.
- Isolate worktrees/proposal areas and integrate under recorded authority. Renewable
  ownership leases and generation/fencing tokens prevent reassigned old sessions
  from publishing. Offline work remains private drafts and cannot assert new global
  ownership. Preserve direct editor changes and previous accepted results/history.

### Targeted events, policies and defects

Durable inboxes/events with acknowledgements route upstream changes, defects,
ownership transfers and authenticated rule/constraint updates. Bind assignments to
relevant dependency/policy revisions and check them before submission/acceptance.
Arbitrary note text cannot become authoritative policy. Identify affected downstream
work and pause only those tasks while independent tasks continue. Stopped agents
catch up when resumed; continuous awareness requires a running consumer.

Defects retain reproducible evidence, responsible owners and downstream impact.
Replan/recover autonomously where recorded rules determine the next action. Preserve
previous results and history rather than overwriting the record of incorrect work.

### Useful knowledge graph and Obsidian acceptance

Keep the independent readable-folder core, optional Obsidian and shared-subfolder
placement inside existing private vaults. Link canonical knowledge, projects,
decisions, evidence and work records through compatible Markdown/frontmatter/
wikilinks. Provide portable link resolution, backlinks and integrity checks during
renames/moves. Runtime/session artifacts must not clutter the graph; credentials
never belong in notes. Notes and graph metadata do not silently grant policy authority.

Validate actual graph/navigation behavior in an isolated Obsidian fixture before
claiming UI compatibility. YAML/link checks alone are insufficient. This does not
require a new production vault or authorize migration of the live Vault. A bounded
read-only graph analyser is the first implementation step; safe rename/move and
native UI verification remain distinct follow-up acceptance work.

| Extension gate | Required observable result |
| --- | --- |
| COORD-01 | Simultaneous claims grant one exclusive owner; duplicate outcome requests do not create parallel accepted work |
| COORD-02 | Queued dependency work becomes ready on the required input/interface versions, without blocking unrelated ready tasks |
| COORD-03 | Worker crash, lease expiration and reassignment preserve drafts/history; an old session cannot submit or integrate with stale fencing tokens |
| COORD-04 | Same-file edits remain preserved proposals with controlled integration, including pending proposals across ownership transfer |
| COORD-05 | Authenticated policy changes invalidate affected running work before submit/accept and leave independent work progressing |
| COORD-06 | Incorrect upstream results route reproducible defects, invalidate affected downstream inputs and support reviewed autonomous replanning |
| COORD-07 | Targeted inbox entries survive consumer shutdown, resume and acknowledgement without silently missing relevant changes |
| GRAPH-01 | Portable Markdown/wikilinks/aliases/anchors resolve with deterministic backlinks and explicit missing/ambiguous diagnostics inside the selected scope |
| GRAPH-02 | Authorized isolated rename/move preserves note bytes/metadata and updates or flags every affected link without touching private parent/runtime files |
| GRAPH-03 | The isolated Obsidian fixture visibly supports useful graph and link/backlink navigation; actual UI evidence is captured separately from parser tests |

## Implementation sequence and first acceptance suite

First turn the scenarios below into executable acceptance tests against the actual
engine interface, then implement one complete owner-to-teammate workflow with one
provider as an initial implementation milestone, while retaining all three OSes
in the core design and automated tests from the start. Define the API and test adapter together. Do not satisfy concurrency tests
with a separate toy model, and do not report skipped/unimplemented tests as passes.
The 1.3.0 scripted local demo is a useful regression fixture, not this team suite.

**Status, 2026-09-08:** the authoritative engine/client, recovered owner setup,
packaged CLI and explicit revision delivery now pass **174/174 local product tests**
on Python 3.13.15 and 3.12.13. Independent review reran the 42 new focused delivery,
client and packaged command cases. Actual local rclone transfer/retry and rejection
of missing/corrupt provider fixtures passed without using coordinator bytes as a
fallback. Initial attachment still uses the coordinator. The preceding 132-case
three-OS checkpoint and 111-command same-project HTTPS trial passed at 3b648d0;
changed-source cross-OS validation is tracked separately in GitHub Actions and
[validation](../VALIDATION.md). Synthetic actors and local fixtures are bounded
engineering evidence. Real provider accounts, independent recipients and full
TEAM-11 remain unverified. Both product and legacy repositories are private;
public V1 requires completion of the retained release gates.

| ID | Scenario and observable acceptance |
| --- | --- |
| TEAM-01 | Owner setup in an ordinary folder or selected private-vault subfolder: reviewed version, correct identities, expected local files and unchanged parent/siblings/config; no mandatory app launch |
| TEAM-02 | Teammate joins on another computer and local root: independent identity and authorized access; confirms expected accepted revision and hashes; no re-bootstrap or parent-vault exposure |
| TEAM-03 | Bounded parallel agents return proposals with base revision, targets, dependencies, criteria and resource limits; only the integration owner accepts after validation |
| TEAM-04 | Recipient explicitly accepts a handoff and verifies the received revision before continuing; premature continuation fails without accepted-state mutation |
| TEAM-05 | Barrier-synchronized proposals from the same base: atomic revision check/update; stale changes cannot overwrite; identical updates deduplicate; compatible changes validate and conflicting proposals are both retained |
| TEAM-06 | Textually mergeable but contradictory facts: source/authority review is required; consequential unresolved dispute leaves the last accepted state intact and records escalation |
| TEAM-07 | Delayed/offline sync: drafts and queued proposals survive; no false global ownership/acceptance; reconnect reconciles against current accepted revision |
| TEAM-08 | External editor or sync-client modification is detected as a proposal; it cannot silently replace accepted knowledge; both versions remain available |
| TEAM-09 | Interrupt each acceptance/materialization boundary and restart: no lost accepted history or drafts, no duplicate acceptance, and a consistent recoverable revision/file state |
| TEAM-10 | Selected provider delivers the expected accepted content to the other computer; interrupted/delayed delivery is partial or blocked, never inferred ready from existence alone |
| TEAM-11 | Required first-release gate: Windows, macOS and Linux users collaborate on the SAME project under different local paths; ownership, accepted revisions, conflicting proposals and handoff acceptance remain consistent; each provider route proves revision/hash receipt and relevant offline/recovery behavior |

Capture expected and actual revisions, content hashes, proposal/acceptance IDs,
validation output, device/provider versions, fault injection points and recovery
results. Run local-only contract checks without an account, and mark real-device or
provider gates not run when their authorized environment is unavailable. Extend
providers and swarm automation only after this vertical workflow passes. The
first-release claim additionally requires TEAM-11 on actual mixed-OS devices,
not three isolated unit-test runs. This requirement is future acceptance, not
completed evidence.

Use [the real-device runbook](TEAM-ACCEPTANCE.md) and its unexecuted evidence
template to gather these results. Measure provider delivery before any recipient
refresh writes the expected bytes via the coordinator; inspect accepted deletions
explicitly. Coordinator receipt does not establish the storage transport used.

After core validation, add the thin companion and later optional Obsidian plugin.
Both call the same core. The doctor currently offers JSON diagnostics; other
commands are not yet a stable versioned engine API.

## Historical first CLI checkpoint, 2026-09-08

Product V1 is a complete-product milestone, separate from toolkit 1.3.0. Thursday,
2026-09-10, is the target; it does not waive TEAM-11 or authorize publication. The
current implementation milestone is a **local CLI preview 0.1.0**, reusing the
existing tracker behind a versioned JSON envelope, safe create/join, exact bundle
identity and project-specific teammate prompts. See [the frozen implementation
contract](../product/CONTRACT.md). This milestone does not introduce a coordinator
or claim its atomicity, membership authentication or provider behavior.

Engineering choice: retain Python and its standard library. Product CLI minimum
is Python 3.11; use the installed Python 3.13 for this development/rehearsal and
recommend a maintained runtime for new installs. Python 3.9 test results remain
legacy toolkit evidence, not new-install guidance. A self-contained `.pyz` archive
bundles reviewed runtime sources without runtime downloads, pip dependencies or
app installation. A compatible Python interpreter is still required. Sources:
[Python lifecycle](https://devguide.python.org/versions/) and
[Python executable archives](https://docs.python.org/3.13/library/zipapp.html),
checked 2026-09-08.

The next engine milestone should implement executable proposal/acceptance tests
before choosing persistence and network exposure. SQLite on coordinator-local
storage remains a proposed transactional option, never a database synchronized
between clients. Freeze server/authentication/materialization/recovery semantics
before exposing a team coordinator. Desktop GUI, watcher, billing, hosted SaaS
launch, arbitrary per-file ACLs and cross-provider bridging remain outside this
bounded two-day proposal.

Windows/Linux recipient hardware is unavailable in the current local pass, and
external recipient testing is not scheduled. The CI definition can build and execute this candidate on
Windows/macOS/Ubuntu using GitHub-hosted runners, but candidate upload/execution
requires authorization. Old public-main CI is not evidence for local changed code;
three independent OS jobs do not satisfy TEAM-11. See [GitHub-hosted runners](https://docs.github.com/en/actions/concepts/runners/github-hosted-runners).

Keep local, self-hosted and export routes viable while exploring future managed
coordination, onboarding, backups and support. Demand, willingness to pay, pricing,
costs and the open/paid boundary remain unresolved. Define that boundary before
external contributions or commercial commitments. Existing MIT licensing does not
establish demand or approve billing/publication. Enforce actual storage/project
access policies; prompt rules and hidden UI are not permissions, and revocation
cannot erase prior downloaded copies.

## Current implementation checkpoint: 0.2.0 development

The authoritative SQLite engine, authenticated ASGI/HTTPS transport and recoverable
local client are implemented. They include membership/revocation with explicit
authority transfer, atomic claims and revision acceptance, compatible rebase,
deduplication, preserved conflicts, responsible-owner factual resolutions, received
handoffs, offline drafts and process-kill/materialization recovery. Bounded status
summary pages and authenticated full proposal/conflict/assignment readers keep
large preserved histories out of routine responses; events have ordered cursors.
Full event-chain verification still grows with history length. Semantic checks
cover supplied structured claims; arbitrary prose remains a human/agent review.

The product also includes exact-package installation/rollback, consistent database
backup, read-only migration planning, isolated Git worktrees, accepted-source context
search, provider capability reporting and local expected-snapshot receipt checks.
The original folder checks do not configure provider access or transport. New
explicit delivery-publish/delivery-fetch commands add an immutable rclone revision
route with authenticated metadata checks and journaled client application. They
require an already attached client and private reviewed account configuration.
Actual Google Drive account/recipient delivery, other provider adapters and a
persistent reviewed deployment remain open. The legacy
tracker remains supported separately. See [the operating guide](PRODUCT-V1.md).

An earlier source-versioned 0.2.0 synthetic local profile of 1,000 text notes (~1.13 MB), 10 members and 50 accepted
revisions measured 34 ms p95 acceptance, 175 ms local receipt and 1.14 s unchanged
refresh; first materialization took 0.98 s. These one-Mac measurements are engineering
evidence for this profile, not a production capacity, latency SLA or cloud result.

Remaining release evidence: clean independent recipient setup, a reachable reviewed coordinator deployment, real provider/account
delivery and offline recovery, and all three OS clients on the same project under
TEAM-11. Repository separation is authorized. Public visibility must wait for completed
version 1; deployment and provider readiness remain separate requirements. Live Vault migration remains gated on validated readiness and
the owner's confirmed backup, second-drive working copy and target.

### Validated local coordination extension

The opt-in schema-2 implementation now passes 273 local product tests on both
Python 3.13 and 3.12. A real packaged 57-command rehearsal covers separate actor
sessions, fenced ownership, duplicate/overlap refusal, recipient handoff, stale
context refusal and exact revision receipt. Same-actor delegation preserves identity;
another person creates their own authenticated session. Completed outcomes retain
their keys. Migration/backup and graph/native-Obsidian evidence is recorded in
[validation](../VALIDATION.md). This does not complete real provider/recipient gates.

## Legacy toolkit decision

Use this toolkit for a controlled, reversible pilot with named owners and explicit
checkpoints. Do not rely on it as the sole coordination or audit mechanism for
critical production work. This is an engineering assessment from the implementation
and local tests, not a measured maximum team size or a production certification.

The local 1.3.0 candidate adds a repeatable demonstration, read-only diagnostics,
explicit local-only setup, portable project-folder dashboards and stronger change detection. Publication and testing on
new recipient machines remain separate steps. See [validation](../VALIDATION.md)
for the exact evidence, and [the demo](DEMO.md) for a concrete walkthrough.

## What the legacy toolkit actually does

Ordinary Markdown holds project instructions, work ownership, dependency revisions,
acceptance criteria, evidence and handoffs. The tracker checks that recorded context
before a contributor edits. An optional Obsidian Base can present those records. Your existing
storage or Git workflow carries the files between computers.

The tracker does not enforce permissions on editors, authenticate actors, deliver
files, run agents, supply an AI memory service, or acquire distributed locks. Its
completion status verifies supplied acceptance metadata and recorded file state;
it does not independently judge a deliverable's quality.

## Before presenting or sharing the current product

| Gate | Acceptance evidence | Current scope |
| --- | --- | --- |
| Reproducible workflow | Fresh demo passes, expected failures preserve records, both handoff criteria verified | Local scripted demonstration |
| Change detection | Regressions for directory children, undeclared targets, large files and completion drift | Local tests, see validation record |
| Attendee entry point | Compact prompt, diagnostic next steps, no account requirement for local-only | Implemented; fresh-machine onboarding still open |
| Optional visual rehearsal | Isolated selected-folder graph/navigation checked in native Obsidian | Synthetic fixture verified; ordinary folder setup needs no app launch |
| Stage rehearsal | Run in the presentation environment within the available speaking time; test TV connection | Presenter/venue check still needed |
| Audience download | Complete V1 release gates before any public installation promise | Product remains private; pitch has no public setup link |

Keep the five-minute pitch focused on the problem, ordinary files, one concrete
handoff and the remaining acceptance work. The 90-second demo is an optional walkthrough, not
additional time on top of the existing five-minute talk. Do not describe scripted
actors as independent AI agents or imply distributed locking from an overlap test.

## Real small-team pilot

Run TEAM-01 through TEAM-10 using a disposable project with public/synthetic inputs,
two authorized computers, two separate agent sessions and one selected provider.
Name a human integration owner and record the authority for each target. Actual
provider selection, accounts and devices remain implementation inputs to resolve.
Then execute TEAM-11 with Windows, macOS and Linux on the same project before
first-release acceptance. The initial two-person milestone does not defer Linux
core/client support. No fresh-device or provider readiness is inferred from the
local candidate tests.

## Historical advisory tracker gaps and continuing hardening gates

The legacy Markdown tracker checks and then writes ownership records. Atomic replacement
of individual files does not make claim acquisition or a multi-record command a
transaction. Two processes or disconnected machines can independently observe a
free target. Documentation and sequential tests do not resolve this race.

The 0.2.0 authority replaces that claim/acceptance path with SQLite transactions;
real local process contention and recovery tests now pass. The following gates
remain useful for the legacy tracker and for distributed/provider validation of
the current product. Prioritize further changes using demonstrated pilot failures:

| Workstream | Proposed acceptance gate |
| --- | --- |
| Same-machine concurrency | Barrier-synchronized competing processes cannot both acquire overlapping targets; exercise stale process recovery |
| Crash recovery | Interrupt every multi-record write boundary; recover to a consistent state without losing accepted work or history |
| Provider conflicts | Detect duplicated/conflicted and reordered records; explicit reconciliation retains both contributors' evidence |
| Reviewed upgrades | Dry-run migration, backups, version compatibility and rollback tested against real older workspaces |
| Scale and performance | Benchmark realistic note/record counts, directory sizes and actors; report p50/p95 command latency and memory against agreed budgets |
| Retrieval quality | A new agent answers and resumes representative tasks correctly using canonical notes; measure missing/stale context and instruction load |

Prefer narrow file/directory targets. Recursive hashing reads target contents and
can become expensive; keep bulk media and build trees outside the tracked note
scope. No tested capacity or latency guarantee exists yet. Do not add a database,
server or new provider solely to claim scale before workload measurements justify it.

## Production adoption gate

The legacy Markdown tracker retains advisory identities/history. The 0.2.0
authoritative development engine now has local membership, transaction, isolation
and recovery evidence; its private database is not protected from an administrator
who controls the host. Real hosted/provider/mixed-device operation remains unverified.
Do not promote local contract checks to deployed production guarantees.

Production adoption additionally requires a defined workload, reliability and
performance budgets, the mixed-OS TEAM-11 result, passing migration/scale tests, an operational owner and a
verified backup/restore procedure. These are future criteria, not current
capabilities or promised dates.

## Primary implementation references

Recheck these when choosing adapter behavior and writing implementation tests.
They inform integration design; they do not prove this product's behavior:

- [Git worktrees](https://git-scm.com/docs/git-worktree) and
  [Git merges](https://git-scm.com/docs/git-merge).
- [OneDrive and SharePoint restrictions](https://support.microsoft.com/en-us/onedrive/restrictions-and-limitations-in-onedrive-and-sharepoint).
- [Apple iCloud folder sharing](https://support.apple.com/en-ie/guide/mac-help/mh40780/mac).
- [Google Drive sharing](https://support.google.com/drive/answer/2565956).
