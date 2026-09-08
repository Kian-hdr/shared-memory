# Shared Memory: operating the development build

**A shared workspace for your team and its AI agents.**

Product **0.2.0 development** contains the authoritative engine and local client.
Obsidian is optional. This is not a completed stable V1 release: actual cloud-provider
receipt, independent recipient onboarding and mixed-OS TEAM-11 remain unverified.
The product source is [Kian-hdr/shared-memory](https://github.com/Kian-hdr/shared-memory).
Executable/protocol identifiers retain compatibility. Toolkit 1.3.0 and historical
CLI 0.1.0 are separate versions.

## What is installed and shared

| Location | Contents and authority |
| --- | --- |
| Private local tools directory | Verified `.pyz` executable; Python is installed separately |
| Private local coordinator state | SQLite accepted revisions, membership, assignments, proposals, decisions and event history; never a consumer-sync/network database |
| Each recipient's private local state | Token, immutable setup intent, connection settings, received snapshot, offline drafts, backups and recovery journal; never shared with the project |
| Selected project folder | Human-readable accepted text and `.shared-memory.json` portable identity/protocol/provider metadata |
| Existing large artifacts | Preserved outside accepted text coverage; use the chosen storage authority and record their links/hashes separately |

The coordinator transfers accepted text over authenticated HTTPS. A provider's
folder client can separately deliver files and large artifacts. `provider-check`
only reads local bytes against the expected snapshot; it does not configure access,
upload or prove which transport delivered them. Use one storage authority per
project. Google Drive, OneDrive and iCloud routes require separate account/client/
OS testing; vendor-folder routes on Linux are not claimed supported.

Anyone holding a member token has that member's rights. Tokens prove membership,
not the real-world identity or factual correctness of the person using them. Keep
tokens outside shared files and send them only through a separately approved private
channel. Access revocation stops future coordinator operations, not prior copies.

## Obtain and install the exact reviewed package

Use compatible Python 3.11+, with maintained Python 3.13 as the development baseline.
Local operation uses the standard library. Serving additionally needs the pinned
optional dependencies in `requirements-server.txt`, installed in a dedicated local
environment. No interpreter, OS client or cloud account is bundled.

A local agent should discover the recipient's actual folder, Python and provider.
A cloud-only agent needs a connection to the recipient's computer before claiming
local setup. Routine authorized installations/configuration can proceed without
repeated permission requests; protected sign-in/MFA/OS consent and actual sharing
permission changes remain their own gates.

Obtain a specific reviewed package and its expected SHA-256 from the approved
source. A package's self-reported hashes do not authenticate its publisher. This
development source lives in this independent repository. Select its exact reviewed
revision and package; do not substitute the separate historical toolkit.

Verify the downloaded bytes without executing the package. Compare against the
external SHA-256 supplied through the approved source; stop on a mismatch:

```text
python -c "import hashlib,pathlib,sys; actual=hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest(); print(actual); sys.exit(0 if actual == sys.argv[2].lower() else 1)" PACKAGE.pyz EXPECTED_SHA256
```

Only after that comparison succeeds:

```text
python PACKAGE.pyz version
python PACKAGE.pyz capabilities
python PACKAGE.pyz guide
python PACKAGE.pyz install-package PACKAGE.pyz --sha256 EXPECTED_SHA256 --tools-dir PRIVATE_TOOLS
```

Replace placeholders using the actual local OS paths, quoting paths with spaces.
Windows can use `py -3.13`; macOS/Linux use their installed compatible interpreter.
Installation keeps immutable `versions/<sha256>.pyz` files and a private activation
pointer. Interrupted copies cannot occupy the final package path. Rollback selects
a previously verified runtime with `rollback-package --tools-dir ... --sha256 ...`.
It never migrates a project's schema or replaces another owner's tracker. Source
builds use `python scripts/build_product.py --output FRESH_OUTPUT.pyz` in a Git checkout.

## Owner setup

Choose one existing project folder. It can live inside a private vault; its parent,
siblings and `.obsidian` settings are not the shared unit. Choose a fresh private
state directory on local, non-synchronized storage outside that project.

```text
python PACKAGE.pyz init PROJECT --state-dir PRIVATE_STATE --person "Owner name" --actor owner-1 --agent "Local agent" --purpose "Project purpose"
```

This defaults to local-only operation without a server/account. `--mode team`
prepares the same authority for team transport, and `--provider google-drive`,
`onedrive`, `icloud` or `self-hosted` records the intended storage route. Choosing a
provider grants no access. Team mode reports partial until its external checks pass.
Initial import defaults to Markdown; repeated `--include RELATIVE_FILE` selects
explicit UTF8 files. Existing instructions/home are preserved; missing ones are
created. Legacy `Coordination/` or `.workspace-project.json` causes a refusal and
requires reviewed migration, rather than silent replacement.

If `init` or `attach` is interrupted, rerun the original command with the same
selected folder, private state and setup arguments. The private setup intent retains
the original credential, identity and source snapshot before authority creation or
materialization. A retry verifies that binding and resumes the existing journal;
it does not recreate accepted history or replace a different connection. Keep the
original recipient token file available for an interrupted attach retry. Changed
inputs or unrelated private state are rejected. Once setup finishes, use `refresh`
for ordinary work. Never share `setup-intent.json`, tokens or `setup-recovery/`.

Setup and exact-package installation require local filesystem support for atomic
same-directory hard-link publication. Unsupported filesystems fail without
replacing existing target files. This capability still needs validation on each
chosen provider folder/client; core OS CI does not establish provider compatibility.

The old `create/join/doctor/status/work/teammate-prompt` commands remain the advisory
tracker compatibility interface. Use `init/attach/refresh/team-status` for the new
authoritative workflow. Do not confuse their guarantees.

## Team transport and joining

The authority must remain reachable. A server on a sleeping/disconnected laptop
cannot provide team availability. Deployment is not created by a setup prompt.
For a reviewed self-hosted environment, install `requirements-server.txt` and run:

```text
python PACKAGE.pyz serve --database PRIVATE_STATE/coordinator.sqlite3 --host HOST --port PORT --certfile CERTIFICATE --keyfile PRIVATE_KEY
```

Non-loopback serving requires TLS. Certificate/hostname verification stays enabled;
redirects and environment proxies cannot forward bearer tokens elsewhere. Serving
uses Uvicorn. The packaged server has local TLS evidence and a successful
concurrent Windows/macOS/Linux HTTPS rehearsal through a temporary testing tunnel.
That completed fixture is not a persistent hosting service, availability SLA or
unattended deployment.

An owner explicitly adds a member and saves their credential privately:

```text
python PACKAGE.pyz member-add PROJECT --state-dir PRIVATE_STATE --actor teammate-1 --person "Teammate name" --agent "Their local agent" --token-output PRIVATE_TOKEN_FILE
python PACKAGE.pyz team-prompt PROJECT --state-dir PRIVATE_STATE --package-locator "Reviewed package location and SHA-256" --access-locator "Approved access instructions"
```

The user copies/sends the prompt. It contains portable project/protocol/revision
identity and actual approved locators, not a token or sender-local path. Missing
locators remain explicit. Prompt completeness is not team readiness.

The recipient uses their own token, selected folder and private state directory:

```text
python PACKAGE.pyz attach MY_PROJECT --state-dir MY_PRIVATE_STATE --endpoint https://COORDINATOR --token-file MY_PRIVATE_TOKEN --expected-project-id OWNER_PROJECT_ID --provider PROVIDER
```

Use the actual provider selected for this folder. Omitting `--provider` means
`local`; an existing manifest with another provider is rejected before writes.
A private CA can be supplied with `--ca-file`. `--database` is for same-machine
local tests/operation only; do not point it at a shared/network SQLite file. Joining
checks project identity and membership before materialization, and preserves local
conflicting bytes as drafts. `refresh` resumes an existing client; an interrupted
`attach` can be retried with its original arguments and immutable setup intent.
It never overwrites a different private connection.

## Session-based coordination

New projects can explicitly enable schema 2 with `init --coordination-file CONFIG.json`.
Keep that file in private local storage. Its bounded configuration is:

```json
{"person_id":"person-1","agent_id":"agent-1","policy":{}}
```

An empty policy selects documented engine defaults; it does not remove permission
checks. Omitting the option preserves schema 1. Existing authorities never upgrade
implicitly. Person and agent IDs are project bindings, not independently verified
real-world identities. A member credential can register another member, then use
`coord member-binding` with `actor`, `person_id` and `agent_id` before that member
opens a session. Session credentials cannot mint unrestricted member credentials.

Inspect `coord policy` to obtain current allowed operations and revision. Prepare a
private grants JSON with `ttl_seconds`, an explicit `scopes` operation list, and
project-relative `targets`. Create one distinct session for each running worker:

```text
python PACKAGE.pyz session-create PROJECT --state-dir STATE --session-id run-1 --grants-file GRANTS.json
```

The result identifies a private credential file. Use that exact file with
`--session-token-file` on subsequent `coord`, `draft`, `submit` and other supported
work commands. The durable private intent preserves the credential across retries;
repeating the same command does not extend its lifetime. Changed grants require a
different session identity. Do not share the intent or token in project notes.
Delegation adds `--delegate-to SAME_ACTOR --session-token-file PARENT_TOKEN`; child
operations, targets and lifetime cannot exceed the parent's current grants.
It cannot mint credentials for another actor, including another project owner.
Assign another actor work through planning or handoff; that actor opens its own
authenticated session. Those steps can run autonomously within existing authority.
Revoking a parent also fences its descendants. There is no background renewal loop.

Schema 2 uses `plan` followed by `acquire`, rather than the legacy `claim` route.
A plan includes:

```json
{
  "assignment_id":"notes-1", "outcome_key":"review-project-notes",
  "summary":"Review the project notes",
  "targets":["Research/"], "criteria":["Validate sources and links"],
  "dependencies":[], "interface_paths":[], "resource_limits":{"max_files":20},
  "integration_owner":"owner-1", "policy_revision":1
}
```

Use the current policy revision, never assume it remains 1. Plans reserve exact
outcome keys and report likely duplicates using advisory word overlap. Acquiring
work additionally requires `assignment_id`, `expected_generation`, `ttl_seconds`,
the current accepted `revision` and `files_hash`, and `policy_revision`. Only one
live lease can own overlapping targets. A replacement session receives a new
generation; retaining old files or a payload session ID grants no authority.

Pin the acquired context in a private JSON file with `session_id`, `generation`,
`policy_revision` and `input_hash`. Supply it to `draft --coordination-file` or
`promote-draft --coordination-file`. The draft preserves its original bytes, base
revision and context. Submission never silently refreshes a stale policy or lease.
An unrelated role's policy change can leave this context valid. The engine compares
every intervening rule revision for the worker and its delegation ancestors. A
restriction followed by restoration cannot revive an old proposal, and acceptance
checks the producer and integrator separately. After reassignment or relevant
policy/input changes, preserve the old draft and prepare a new
proposal with evidence and the new acquired context. `renew` extends a still-valid
lease within policy and session lifetime; it cannot revive expired ownership.

Integration is performed by the recorded integration actor, which can be an
authorized agent. `accept` adds that actor's authenticated session context to the
ordinary proposal ID, validation and reason. The engine checks both integrator
authority and the original proposing session, generation, policy and inputs.
Evidence is still an assertion that the actor must substantiate; the coordinator
does not run arbitrary tests or establish factual truth. Human review is not a
mandatory routine step when an agent already holds the required authority.

An output dependency pins `assignment_id`, `output_revision` and `interface_hash`
and waits for producer completion. An interface dependency uses `kind:"interface"`,
`interface_revision` and `interface_hash`; it can run while implementation remains
active after the producer publishes its agreed contract through `interface-publish`.
Contract publication records bounded text and evidence, not completed implementation.
`outputs` returns paginated metadata (`assignment_id`, optional `offset` and `limit`);
use `output` with `assignment_id` and `output_revision` for one complete preserved
version. Requester identity is recorded from the authenticated planning session and
survives acquisition by another worker.

For disputed structured facts, `resolve` requires the responsible owner's session,
proposal ID, resolutions and current coordination context; integration still follows
through `accept`. `reject` and `supersede` also require current integration context
and retain original requests. Responsibility can be deliberately transferred:
`transfer-integration` takes `assignment_id`, `to_actor`, `reason` and `coordination`;
`transfer-authority` takes `key`, `to_actor`, `evidence`, `reason`, `policy_revision`,
`revision` and `files_hash` through a project-wide scoped responsible-owner session.
Transfer responsibilities before revocation, which cannot orphan them.

Authenticated `policy-update`, `defect-report`, `replan` and `defect-resolve` record
changed rules, version-specific problems and recovery evidence. Affected work is
invalidated transitively; unrelated work can continue. Read paginated `inbox` entries
and `ack` their message IDs. Consumers catch up when they run; no always-on worker
or automatic notification service is bundled. Arbitrary note text never becomes
policy. Inspect actual command results and the extension acceptance record before
claiming production or provider readiness.

## Explicit coordinator upgrade and backup

For an existing local schema-1 authority, prepare the same private coordination
configuration and obtain a read-only full-history checkpoint:

```text
python PACKAGE.pyz coordination-plan-upgrade --database DATABASE --token-file OWNER_TOKEN --expected-project-id PROJECT_ID --coordination-file CONFIG.json
python PACKAGE.pyz coordination-upgrade --database DATABASE --token-file OWNER_TOKEN --expected-project-id PROJECT_ID --coordination-file CONFIG.json --expected-checkpoint CHECKPOINT --backup-destination FRESH_PRIVATE_BACKUP --migration-id upgrade-1
```

The upgrade authenticates an active owner, writes and verifies a private backup
before its exclusive transaction, and refuses intervening authority changes. Schema,
history and the upgrade event commit together. A retry after a committed lost response
requires the exact original configuration, checkpoint, migration ID and retained
backup. A pre-commit failure preserves its backup and needs a fresh destination for
another attempt. No automatic restore or downgrade occurs.

Legacy assignments require explicit `rebind` under the authenticated integration
actor. It records reviewed outcome/dependencies, current receipt/policy and evidence;
old proposal request bytes remain unchanged. Old pending proposals are retained as
legacy-blocked history and cannot be submitted as new session-fenced work.
This command upgrades a coordinator, not a live vault's folder structure or notes.

`backup-coordinator --database DATABASE --destination FRESH_PRIVATE_BACKUP
--expected-project-id PROJECT_ID` separately captures and verifies complete schema-1
or schema-2 history. It checks every stored snapshot, proposal, document and event
chain, then compares the backup with the pinned source checkpoint and flushes it
to local storage. Preserve the authority and partial backup after a failure.

## Knowledge graph

`graph PROJECT` reads only the selected folder without changing it or requiring
configuration. `graph PROJECT --accepted --state-dir STATE` analyzes the current
authenticated accepted snapshot, independently of local drafts. Both return typed
nodes, links, backlinks and explicit diagnostics; neither grants policy authority.
See [the knowledge graph guide](KNOWLEDGE-GRAPH.md) for supported Markdown, privacy
bounds and the separate native Obsidian rename/navigation validation.

For a reviewed move of one selected Markdown note, `graph-rename-plan` records
exact original bytes, hashes and affected links in private state; `graph-rename-draft`
saves an ordinary assignment proposal without editing notes. Submit and accept it
through the same authenticated ownership/integration rules as other work, then use
`graph-rename-apply` to materialize only when the accepted snapshot exactly matches
the plan. Originals and interrupted writes use the existing private backup/journal.
Unsupported or ambiguous links and stale plans are refused. Parent-vault backlinks
remain unknown and untouched; filesystem writes are recoverable, not one atomic
multi-file rename. See the knowledge graph guide for exact arguments and limits.

## Legacy schema-1 daily agent workflow

1. Run `refresh PROJECT --state-dir STATE`, then `team-status` and `context --query
   "relevant question"`. Status returns summaries; use authenticated `coord proposal`/`coord conflict` to
   retrieve preserved details, `coord assignment` for full work criteria, `coord facts`
   for accepted factual authority, and `coord events` for paginated history.
   Context returns accepted-revision file excerpts and hashes;
   lexical matches are not factual verification and omit pending drafts.
2. Claim a bounded assignment. The engine requires targets, dependencies, acceptance
   criteria, resource limits and an integration owner. Only active assignment owners
   submit changes. Enforced limits are proposal count, changed-file count and bytes;
   other limits are recorded as unenforced, not promised runtime/cost enforcement.
3. Edit selected files. Run `draft --proposal-id ID --assignment-id WORK --evidence
   "checked evidence"`; this saves original base revision and bytes locally, even offline.
   `submit --proposal-id ID` queues the exact proposal at the authority; retries are
   idempotent and never delete drafts after a timeout.
4. The integration owner reviews evidence, content and semantic claims before `accept`.
   Compatible changes can rebase only when touched paths are unchanged. Conflicts
   preserve both versions and the accepted snapshot. Acceptance evidence is the
   reviewer's assertion; the engine does not run arbitrary tests or judge all prose.
5. Refresh and verify `receipt` before taking over a handoff. Recipient `receive`
   requires the current revision/hash. Completion requires owned work, exact current
   receipt, evidence and no unresolved assignment proposals/conflicts.

Authenticated operations use `coord PROJECT --state-dir STATE OPERATION
--payload-file JSON_FILE`. JSON files avoid shell interpolation and command-line
secrets. Example claim payload:

```json
{
  "assignment_id": "notes-1",
  "targets": ["Research/"],
  "criteria": ["Review sources and validate changed links"],
  "dependencies": [],
  "resource_limits": {"max_proposals": 10, "max_files": 20, "max_bytes": 1000000},
  "integration_owner": "owner-1"
}
```

Accept payload: `{"proposal_id":"proposal-1","validation":"Recorded review evidence",
"reason":"Acceptance decision"}`. See [the engine contract](../product/ENGINE-CONTRACT.md)
for payloads for semantic `resolve`, `reject`, `supersede`, `handoff`, `receive`,
`complete`, `transfer-authority`, `transfer-integration` and `revoke`.

Structured factual claims carry key/value/source/responsible owner. Contradictions
require that responsible owner's authenticated resolution, followed by integration
owner acceptance. Arbitrary prose still requires human/agent semantic review; no
automatic universal contradiction detector is claimed. Authority transfers are
explicit and audited; revocation cannot orphan active factual/integration authority.

## Conflict, offline and crash recovery

External editor/provider changes never become accepted merely by appearing in the
folder. Refresh preserves drafts before materializing the accepted snapshot. Use
`promote-draft --preserved-id ID --proposal-id NEW_ID --assignment-id WORK --evidence
"Reviewed preserved change"` to prepare a local proposal against its original base.
Then run `submit --proposal-id NEW_ID` with the same project and state directory
to send it for integration review.
Do not erase history or manually edit private state to clear a conflict.

Filesystems cannot atomically replace a whole project. A private durable journal
and immutable backups recover interrupted materialization; mixed files report
partial receipt. Divergent accepted deletions preserve local bytes. Untracked binary/
large attachments stay untouched and are listed outside accepted-text coverage.

For a directory-to-file conversion, first accept deletion of its tracked files,
then accept the replacement file as a separate revision. One proposal containing
both parent-file and child-deletion paths is conservatively rejected. Recipients
may catch up over both revisions in one refresh. The client performs eligible
tracked deletions before writes and removes only empty obsolete directories needed
for that replacement. Modified tracked children and private/untracked descendants
are preserved and can block the conversion until deliberately reconciled.

`recover-coordinator --database PRIVATE_DB` recovers a killed writer's SQLite hot
journal and validates accepted history. The server runs this at startup. Read-only
commands never silently repair state. `backup-coordinator --database PRIVATE_DB
--destination FRESH_PRIVATE_BACKUP` uses SQLite's consistent backup API. Validate the
backup and stop the authority before a reviewed restore; never overwrite active state.

`git-isolate REPOSITORY --worktree FRESH_LOCAL_PATH --branch BRANCH [--base REF]`
previews code isolation; `--apply` creates the worktree while preserving original
tracked/untracked bytes and disabling checkout hooks for this operation. Worktrees
start from a commit and omit uncommitted changes. Coordinator assignment and code
integration are separate. Keep repositories/worktrees outside consumer sync folders.

## Explicit revision delivery, development scope

`delivery-publish` and `delivery-fetch` transfer accepted text revisions through an
explicit installed rclone driver. This first adapter supports already attached
projects. Initial `attach` still obtains its initial snapshot from the coordinator;
it is not evidence of provider delivery. Obsidian is optional throughout.

For a local transfer rehearsal, use an existing disposable directory separate from
both the selected project and private state. This exercises the actual rclone local
backend and always reports `local_fixture`, never a Google Drive receipt:

```text
python PACKAGE.pyz delivery-publish PROJECT --state-dir PRIVATE_STATE --rclone ABSOLUTE_RCLONE_EXECUTABLE --fixture-root DISPOSABLE_LOCAL_TRANSFER
python PACKAGE.pyz delivery-fetch PROJECT --state-dir RECIPIENT_PRIVATE_STATE --rclone ABSOLUTE_RCLONE_EXECUTABLE --fixture-root DISPOSABLE_LOCAL_TRANSFER
```

The Google Drive route requires the project to have been explicitly initialized or
attached with `--provider google-drive`, and an already authorized private rclone
config plus reviewed folder/account binding. The command never signs in, invites
people, changes permissions, or configures an account. Keep both config and binding
outside the shared project and sync storage. On POSIX they must be owned by the
current user with no group/other access. Review equivalent private access on Windows.
Example binding shape, with recipient-specific placeholders:

```json
{
  "config": "ABSOLUTE_PRIVATE_CONFIG_PATH",
  "remote": "REVIEWED_NAMED_REMOTE",
  "root_folder_id": "REVIEWED_FOLDER_ID",
  "account_type": "workspace_my_drive",
  "reviewed": true
}
```

Account types are `personal`, `workspace_my_drive`, or `workspace_shared_drive`;
the last also requires `team_drive_id`. Use `--binding-file PRIVATE_BINDING_JSON`
instead of `--fixture-root` in either command. These IDs and config contents belong
only in private local configuration, not in shared notes or reports. A root folder
bounds this adapter's operations; it does not narrow an OAuth token's authority.
See [rclone's Drive setup and scope requirements](https://rclone.org/drive/) and
[Google's API scope guidance](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

Publication uses `PROJECT_UUID/revisions/REVISION-HASH/` with exact UTF-8 bytes and
a final manifest completion marker. Matching retries are idempotent. Conflicting,
extra, duplicate, unsafe or incomplete content fails validation; it is not repaired
by overwriting history. Native Google documents and shortcuts are unsupported. This
is not a Drive transaction or multi-writer compare-and-swap protocol. Assign one
approved publisher to each revision namespace. Existing
accepted remote revisions remain retained; no sync/bisync, trash or remote deletion
operation is used.

Fetch authenticates the expected current project/revision/hash through coordinator
metadata, obtains bytes only from the selected delivery backend, and verifies them
in private staging. Client application rechecks authenticated metadata and reuses
the existing journal/draft/conflict protections. Missing or corrupt provider content
never falls back to coordinator snapshot bytes. If the authority advances during
transfer, a stale download is rejected and may be retried. An unavailable authority
does not permit an unverified offline application.

The transfer receipt's `deleted_paths` compares the saved accepted baseline with the
new accepted snapshot. Its `local_deletions: not_applied` describes transfer only;
inspect the separate `local` receipt and preserved drafts after application.
Locally modified removed files remain protected. Remote historical revisions are
retained, so a removed local file does not imply remote erasure.

Actual Google Drive account delivery, independent recipients, provider revocation,
offline reconciliation and mixed-device TEAM acceptance remain unexecuted gates.
Local rclone fixtures and synthetic cross-OS tests do not establish those results.

## Migration and release gates

`migration-plan SOURCE --destination FRESH_TARGET` is read-only. It inventories
hashes, excluded private state and unresolved/ambiguous links. It does not move files,
change sharing or authorize migration. For the existing live Vault, first establish
validated product readiness; its owner then backs it up, copies it to a second drive
and explicitly identifies/confirms the intended working target before migration.

The development build has local transaction, recovery, package and TLS evidence.
Limits: 10 MiB per accepted text file, 100 MiB accepted snapshot, 10,000 files,
128 MiB protocol envelope. These bounds are not a tested production capacity.
Windows/Linux execution, actual provider/account routes, real independent-recipient
use and same-project mixed-OS TEAM-11 remain release gates. See
[validation](../VALIDATION.md) and [the readiness roadmap](READINESS.md).
