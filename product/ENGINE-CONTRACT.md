# Shared Memory authoritative engine contract

Implementation target: product 0.2.0 development, not a stable release. This extends
CONTRACT.md's historical 0.1.0 CLI preview; all TEAM requirements in docs/READINESS.md
remain in force. The live Exlumina Vault is never a test or migration target.

## Ownership and interfaces

- Engine owner: `product/shared_workspace/engine.py` only.
- Client owner: `product/shared_workspace/client.py` only.
- Independent acceptance owner: `product/tests/test_engine.py`, `test_client.py`,
  `test_team_cli.py` only; may add fixtures under product/tests.
- Primary: integration, CLI, HTTP transport, provider capability adapters,
  installation/update/migration preparation, docs/build and Vault handoff.

Use Python 3.11+ stdlib. Local coordinator SQLite lives OUTSIDE shared/project
storage; one authority per project. Readable files materialize accepted snapshots.
No SQLite over consumer sync, no direct edits silently becoming accepted. External
editors cannot be prevented from editing ordinary files; detect and preserve drafts.

## Engine Python API

`Coordinator(db_path)` has `initialize(project_id, owner, token, files)` returning
status, and `request(token, operation, payload)` returning a JSON-serializable dict.
Initialize accepts canonical UUID, owner {actor, human, agent}, a generated secret
supplied by caller, and {portable_relative_path: UTF8_text}. Reject existing state.
Tokens are caller-generated random secrets stored as hashes in DB, never synced.
All authenticated operations check active membership. Fail using ProductError
(exit3 malformed,4 operation rejection,5 environment); all DB changes per request
are atomic with BEGIN IMMEDIATE, rollback on exceptions. Read methods never write.
State schema version1; refuse unknown versions. Full historical snapshots, proposal
bytes, decisions and events retained, with hash verification on export/read.

Operations (payload fields; fields marked ? optional):

- `status {offset?,limit?}` -> {project_id, revision, files_hash, members, assignments, proposals,
  conflicts}; bounded summaries, no full proposal/conflict file contents or tokens.
  `proposal {proposal_id}`, `conflict {conflict_id}` and `assignment {assignment_id}`
  retrieve preserved full details for authorized members. `facts {offset?,limit?}`
  exposes accepted structured facts and their responsible authority. Status/facts
  defaults are 100 entries. Status returns per-collection paging.next_offsets; facts
  returns next_offset. Pass the desired offset to retrieve the next page.
- `snapshot {revision?}` -> {project_id, revision, files, files_hash}; canonical
  files_hash = sha256(JSON(files, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()).
- `member {actor,human,agent,role,token}` owner-only, role owner/contributor/reader;
  token supplied by caller, reject duplicate identity. `revoke {actor}` owner-only;
  no last owner removal. Revocation stops future operations, not prior copies.
- `claim {assignment_id,targets,criteria,dependencies,resource_limits,integration_owner}`
  actor from token; all targets portable, prefix overlap rejected against active
  assignments. Dependencies refer to completed assignments. Store base_revision.
  Integration owner must be active owner. Reader cannot claim/propose/mutate.
- `propose {proposal_id,base_revision,changes,evidence,assignment_id,claims?}`:
  changes map portable path to text or null(deletion); require nonempty evidence,
  active assignment owned by actor, within declared targets. Unknown/future base
  refused; preserve stale proposals for reconciliation. Stable proposal_id makes
  exact retry idempotent, changed reuse rejected. claims list optional semantic
  facts {key,value,source,authority}; values strings, authority actor ID. Store bytes.
- `accept {proposal_id,validation,reason,resolutions?}`: only assignment's integration
  owner (active owner) may accept. validation nonempty evidence string. Atomic
  compare base/current: deduplicate identical result; independent changes rebase
  only if touched paths unchanged since base, otherwise mark conflict and preserve
  accepted snapshot and BOTH versions. Structured facts with same key and unequal
  value produce semantic conflict even if files differ. Never infer truth from
  timestamps/text merge. resolutions list {key,value,source,reason,authority} requires
  matching active responsible owner and evidence; record decision. Explicit review
  evidence authorizes compatible merge, not blanket automatic text merging.
- `resolve {proposal_id,resolutions}`: active responsible owner authenticates and
  records evidence-bearing semantic decisions; integration owner accepts later.
- `transfer-authority {key,to_actor,evidence,reason}`: current responsible owner
  explicitly transfers a fact to an active owner, preserving value/source and recording
  the revision. `transfer-integration {assignment_id,to_actor,reason}` transfers
  acceptance responsibility. Revocation cannot orphan active facts/integration roles.
- `reject {proposal_id,reason}` or `supersede {proposal_id,replacement_id,reason}`:
  integration owner resolves pending/conflicted records without deleting bytes;
  supersede requires an accepted replacement in the same assignment.
- `handoff {assignment_id,to_actor,summary}` owner of active assignment or integration
  owner; persist pending receipt at current revision/hash. Source loses write rights;
  recipient cannot propose until `receive {assignment_id,revision,files_hash}` verifies
  exact CURRENT accepted snapshot and actor. Retain handoff history.
- `complete {assignment_id,revision,files_hash,evidence}` assigned actor only, received
  ownership/current snapshot checked, no unresolved proposals/conflicts for assignment;
  preserve completed history. `events {after_seq?,limit?}` reads chronological
  decision pages (default 100, maximum 1,000), no secrets; follow next_after_seq
  while has_more is true. Pages target 4 MiB; one larger historical event remains
  readable under the protocol envelope. Every request still verifies the full chain,
  so history length affects latency; this is not an unbounded-scale claim.

Portable paths reject absolute/traversal/backslash/drive/control chars, reserved
Windows names/trailing dot/space and casefold collisions. Reject `.git`, `.obsidian`,
`.workspace-project.json`, `.shared-memory.json` and coordinator/client state names.
Directory claims use `path/` prefixes (normalized); files use exact targets; `.` may
claim whole selected project, never its private parent. Reject invalid IDs before
writing. No semantic claim automatically extracted/trusted from arbitrary Markdown;
required human/agent review remains explicit.

Local host method `Coordinator.recover()` performs writable hot-journal recovery
and verifies accepted state/history without a new logical revision/event. Server
startup invokes it; no unauthenticated remote recovery operation exists.

## Client Python API

`Client(project_root, state_dir, request)` where request is a callable
`request(operation, payload)->dict` authenticated by the transport. State is private
outside project/root, never under a known consumer sync root. Constructor performs
no mutation. Client methods:

- `attach(expected_project_id)` loads snapshot, validates identities, initializes
  local state, preserves parent/siblings/settings. Existing local files differing
  from accepted state become preserved drafts before materialization; only explicit
  selected paths may be written. Never reads/overwrites symlinks. Return receipt.
- `refresh()` -> export latest snapshot, detect edits relative to last receipt,
  preserve them as immutable queued drafts, materialize current accepted state and
  verify exact content; {revision,files_hash,readiness,drafts}. No claim of provider
  delivery from direct coordinator transport. No network -> keep files/drafts.
- `draft(proposal_id, assignment_id, evidence, claims=None)` detects local changes
  against saved base and saves immutable proposal (base_revision,changes,evidence,
  assignment_id,claims). No network required, no automatic global claim.
- `submit(proposal_id)` sends saved proposal through request; keep local queue on
  timeout/rejection, stable IDs allow retry. Never deletes drafts/history.
- `promote_preserved(preserved_id, proposal_id, assignment_id, evidence, claims=None)`
  creates a reviewable immutable proposal with preserved original base/bytes.
- `receipt()` validates materialized bytes against saved snapshot, returns
  {project_id,revision,files_hash,readiness}; drift means partial. A receipt proves
  local bytes only; provider/different-device verification is separately recorded.

Use durable private journal + same-directory os.replace, fsync where supported.
Before any write build a plan; back up touched existing bytes in private immutable
recovery storage. A crash may leave mixed materialized files but not false readiness:
retry resumes idempotently, preserving edits made after interruption. Never erase
untracked files; accepted deletions preserve prior bytes and require exact baseline.
No shell execution or project-supplied Python code. Size limits explicit, not hidden
truncation. File safety checked again before writes. Validate snapshot files_hash.

## Acceptance and release boundary

Independent tests must use actual engine/client with concurrent processes and
failure injection, persistent reopen/retry, stale compatible and conflicting
proposals, semantic conflicts, auth/revocation, ownership/handoff, offline draft
survival and external edit preservation. CLI + loopback HTTP must integrate these
same modules. A test fixture or loopback service is not a real cloud/provider run.
Windows/Linux and actual mixed-OS/provider TEAM-10/11 remain explicit external gates.

Migration is preparation only: after validated readiness, Kian backs up the live
Vault and copies it to a second drive, then explicitly identifies and confirms the
working target. No live Vault restructuring/sharing or backup-drive writes now.
