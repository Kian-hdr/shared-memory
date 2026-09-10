# Shared Memory acceptance scenarios

## Direct-folder workflow, 0.3.0

Use synthetic nonconfidential content for acceptance exercises, independently from
ordinary onboarding. These scenarios are evidence collection, not a requirement
that users create a disposable project before working in their own folder.

1. Set up one selected folder with preserved parent/settings/attachments, then join
   its delivered format-3 copy on another computer using independent private state.
2. Save useful edits directly while offline. Capture locally, reconnect the chosen
   provider and compare actual note bytes and visible history on both computers.
3. Make compatible edits to different lines and conflicting edits to the same
   content. Verify convergence only where supported, and retain every unresolved
   competing version. Ask a different authorized editor to resolve with evidence.
4. Exercise edits made outside the agent and provider-generated conflict copies.
   Preserve local-only copies before cleanup and distinguish the observer label
   from the original human author. Test the provider's actual ignore/hidden-file rules.
5. Test explicit deletion/rename, missing downloads, interrupted application and
   restart. Verify historical recovery and review backlinks separately; rename does
   not rewrite them automatically.
6. Verify local read-only refusal and actual provider read-only/revoked rights.
   A writable local file or old coordinator roster is not proof of provider access.
7. Record package/hash, client/OS versions, exact outcomes and limits. Separate local
   deterministic fixtures from real provider transport and independent human/device
   use. Do not claim recovery of bytes overwritten before they were captured.

See [commands](PRODUCT-V1.md), [provider choices](PROVIDERS.md),
[diagrams](DIAGRAMS.md) and [validation](../VALIDATION.md).

## Historical coordinator acceptance runbook

The retained procedure below applies only to the earlier coordinator/session design.
Its integration owner and approval flow are not requirements for direct-folder use.
Its dated results and unrun gates remain historical rather than being silently
converted into folder-mode evidence.

# Shared Memory real-device acceptance runbook

Prepared 2026-09-08. **The full three-participant/provider procedure has not been
executed.** Partial real Mac/Linux trials and automated cross-OS checks are recorded
in [VALIDATION.md](../VALIDATION.md). This procedure gathers remaining stable-V1
graduation evidence for the schema-2 product; it does not block an honestly labelled
experimental prerelease. Schema-1 rehearsals are historical
compatibility evidence and do not pass the session/coordination extension gates.
It does not authorize deployment, sharing, account changes,
credential delivery or publication. Use only disposable public/synthetic project
content. Do not use a production vault or backup drives as test fixtures.

## Required environment

Name an integration owner and three actual participants on Windows, macOS and
Linux. Record OS/Python/agent versions, distinct actor IDs, the exact reviewed
runtime SHA-256 and bundle ID, and different selected local paths. The latest
reviewed package/evidence is identified by the [release page](https://github.com/Kian-hdr/shared-memory/releases)
and [validation record](../VALIDATION.md). Verify its external
checksum before executing it. Keep private state outside all synchronized folders.

Use one project UUID and one reviewed reachable HTTPS coordinator for the whole
run. Record host ownership, availability and recovery responsibility. A sleeping
owner laptop cannot provide ongoing availability. Obtain separately authorized
provider access and independently issued membership tokens. Never copy private
client state or tokens as project content. Keep private locators/credentials out of
shared reports. No participants or deployment have been arranged by this runbook.

Select a provider/account/OS route explicitly and record whether bytes travel
through a vendor-synchronized folder or the explicit revision-delivery adapter. Windows/macOS vendor-folder tests
may exercise Google Drive, OneDrive or iCloud only with verified account/client
support. Vendor-desktop routes without supported Linux clients cannot establish Linux
provider acceptance. The implemented rclone Google Drive revision adapter is a
separate route requiring independently authorized private configuration and actual
account delivery evidence on each OS. Its local-backend fixtures are not Drive
proof. Do not label coordinator HTTPS alone as provider delivery. A self-hosted
storage route also needs its own actual file-delivery evidence. Coordinator
HTTPS receipt and storage-provider receipt are different observations.

## Owner setup and independent joins: TEAM-01/02

1. On each device create a disposable private parent with a private sibling and
   `.obsidian` fixture settings, plus the selected project subfolder. Hash the
   parent/sibling/settings files before setup. Obsidian need not run.
2. Owner uses `init PROJECT --state-dir PRIVATE_STATE --person PERSON --actor ACTOR
   --agent AGENT --purpose PURPOSE --mode team --provider PROVIDER
   --coordination-file PRIVATE_CONFIG`. Use the schema-2 person/agent/policy config
   in the [operating guide](COORDINATOR-WORKFLOW.md#session-based-coordination). Record the
   returned UUID, accepted revision/hash and actual package identity.
3. The authorized host exposes the actual packaged coordinator with verified TLS,
   preserving its database locally. Use the operating guide's `serve` procedure.
4. Owner issues each distinct member with `member-add` and separately approved
   private credential delivery. Every recipient chooses their own paths and runs
   `attach PROJECT --state-dir PRIVATE_STATE --expected-project-id UUID --endpoint
   HTTPS_ENDPOINT --token-file PRIVATE_TOKEN --provider PROVIDER`. Supply the actual
   provider explicitly; omitted `--provider` currently means local and an existing
   manifest with another provider is rejected. Use `--ca-file` only for the reviewed
   trust chain, never disable certificate verification.
5. Bind each member to its distinct person/agent IDs using authenticated
   `member-binding`. Each running worker independently creates its own
   `session-create` credential with explicit operation, target and lifetime grants.
   Record session IDs and grant summaries, never tokens. Other actors obtain their
   own credentials; delegation cannot authenticate as another actor. Use the returned
   private session file with `--session-token-file` for work operations.
6. Each participant independently verifies `team-status` and `receipt`. Compare
   UUID/revision/files_hash across devices and re-hash untouched parent/settings.
   Capture mismatches or partial results rather than replacing them with ready.

## Work, conflict and handoff: TEAM-03/04/05/06

Use `coord PROJECT --state-dir PRIVATE_STATE OPERATION --payload-file PRIVATE_JSON`
with the authenticated session and schema-2 payloads in the candidate's
[engine contract](../product/ENGINE-CONTRACT.md) and
[operating guide](COORDINATOR-WORKFLOW.md#session-based-coordination). Save each command's JSON
output, exit code and time without credential values.

- Plan distinct outcomes and declared note targets with criteria, an authorized
  integration actor and version-pinned dependencies. Acquire leases using current
  generation, receipt and policy revision. An exact duplicate outcome and overlapping
  lease must fail without mutation. Output consumers wait for completed output;
  interface consumers may run against the exact published interface while its
  producer remains active. Exercise both routes and record input hashes.
- Freeze acquired session/generation/policy/input context in a private JSON file.
  Supply it to `draft --coordination-file`; submission must retain that original
  context. Integration must authenticate its own context and validate the producer
  separately. Sessions/leases must cover the bounded trial or be legitimately
  renewed before expiration; expired grants cannot be resurrected by retry.
- Freeze a common accepted base. Two actual agents edit separate targets, `draft`
  evidence-bearing proposals, then `submit`. The integration owner reviews and
  accepts both. The stale independent change must rebase compatibly and retain its
  original proposal bytes/base. Record actual concurrent-start synchronization.
- For same-file contention, use two isolated private draft copies operated under
  the legitimately owning actor; never bypass ownership to fabricate two owners.
  Submit distinct same-base proposals. Concurrent acceptance must yield one accepted
  value and one preserved conflict, with the historical base and both exact versions
  available through `coord proposal` and `coord conflict`. Also retry identical
  submissions/acceptance and verify no duplicate accepted revision.
- Separate assigned actors supply contradictory structured factual claims with the
  same key but different values and real synthetic source pointers. Acceptance must
  retain the prior state until the responsible owner's authenticated `resolve`,
  followed by integration acceptance. Inspect `coord facts` and the event record.
  Arbitrary prose review is manual; do not imply automatic truth checking.
- Handoff work from macOS to Windows, then Windows to Linux. Preserve an origin
  draft with its acquired context before transfer. With accepted revision unchanged,
  attempt the old session's submission after handoff: it must fail due to fencing,
  preserve the draft and create no proposal or accepted change. Test the recipient
  before acquire and with an intentionally stale receipt. The recipient refreshes,
  acquires the new generation with its own session and exact receipt, then submits
  and completes a real continuation. Schema 2 uses `acquire`, not legacy `receive`.
- Make one relevant authenticated policy change and one unrelated role change.
  Only affected work must be fenced; restricting then restoring authority must not
  revive an old proposal. A note containing instructions must not change policy.
- Report a reproducible defect against a versioned output/interface. Check targeted
  downstream invalidation, retained prior output and responsible owner; replan with
  corrected pinned inputs, produce a replacement, then resolve with evidence.
- Stop a consumer after saving a paginated inbox cursor and acknowledgements.
  Generate targeted events while stopped, reopen it and exhaust all pages. Compare
  message IDs against expected events, retry acknowledgements idempotently, and
  verify unrelated actors cannot consume or acknowledge another actor's messages.

## Offline and external edits: TEAM-07/08

Disconnect only the disposable participant's coordinator transport using a reviewed
local method. Save an offline draft; reopen the client and verify its original base
and bytes. While offline, another permitted actor advances accepted context on an
independent target. Reconnect and submit/review the saved draft. Repeat with a
same-target competing version using the legitimate owning actor's isolated clients;
reconciliation must preserve the accepted value and conflicting draft.

Use an actual editor and, separately, the selected provider client to modify a
fixture file. Compare authority before/after: file arrival alone must not change
accepted revision. `refresh` must preserve the divergent draft before materializing
accepted content. Promote it with `promote-draft`, then explicitly `submit` for
review. Include an accepted deletion with a divergent local edit; retain that edit.

## Provider-delivery proof: TEAM-10/11

Choose exactly one of the following delivery procedures per recorded route.

### Vendor-synchronized selected folder

On the owner accept a unique fixture marker, a non-ASCII nested filename and a
known-file deletion. Materialize the accepted snapshot only on the owner. Record
expected revision, exact file hashes and the explicit deleted path.

On each recipient **do not run attach/refresh or manually copy the new files before
measuring provider delivery**. Those operations could write the expected bytes via
the coordinator and mask broken provider sync. `provider-check` fetches expected
metadata but does not materialize files; capture its result plus the provider's
observed transfer and deletion. Verify deletion explicitly: current snapshot receipt
checks do not by themselves prove absence of previously deleted files. Record any
provider conflict copies without deleting them.

Pause only the approved disposable provider route, accept a second unique marker,
observe missing/delayed delivery as partial, then resume and compare exact bytes.
Record actual account policy/client/OS versions and elapsed delivery/recovery times.
After provider proof is captured, refresh normal client state and verify exact
handoff receipts. Repeat each provider/account route claimed for release. A blocked
Linux vendor route remains a gap; another route does not establish vendor parity.

### Explicit Google Drive revision delivery

Use the [delivery procedure](COORDINATOR-WORKFLOW.md#explicit-revision-delivery-development-scope)
with an installed reviewed rclone executable, each participant's already authorized
private configuration, reviewed folder binding and `--provider google-drive`.
Record account type and adapter/rclone versions without account IDs or locators.
Do not silently substitute `--fixture-root`, which proves only local transfer.

After attachment, accept new unique marker/Unicode/deletion changes. One designated
publisher runs `delivery-publish --binding-file PRIVATE_BINDING_JSON`. Each recipient
runs `delivery-fetch --binding-file PRIVATE_BINDING_JSON` before any coordinator
refresh could supply those bytes. Capture both transfer and local receipts. Verify
exact provider-sourced bytes, deletion behavior and preserved divergent drafts;
remote historical revisions remain retained. Initial attach is coordinator delivery
and cannot count as this proof.

In disposable namespaces, test unavailable, incomplete and corrupt provider content:
fetch must refuse without falling back to coordinator bytes or losing local edits.
Resume the authorized route and retry. Also test an authority revision advancing
during transfer, lost responses, access revocation and restored access without
copying credentials between participants. Account/permission operations must stay
within the trial's separately established authority. Record unavailable scenarios
as not run, not passed. Repeat with the actual Windows/macOS/Linux participants.

## Graph and selected-folder boundary: GRAPH-01/02/03

Use a disposable selected subfolder with private parent/settings/runtime sentinels.
Capture graph diagnostics, resolved links and backlinks before and after an
explicit scoped rename/move. Verify original metadata/body, updated or precisely
flagged affected links, stale-plan refusal and retained recovery originals. Check
all sentinel bytes and absence of unexpected writes. A read-only graph result does
not prove scoped mutation. Native Obsidian can update outer-vault backlinks, so its
rename behavior alone cannot pass this boundary. Capture native graph/navigation
UI evidence separately; no production vault or new vault is required.

## Recovery and final review: TEAM-09/11

Use disposable authority/client state for interruption tests. Run the candidate's
actual acceptance-boundary and materialization fault tests on each OS, then perform
a reviewed participant disconnect/lost-response trial through the reachable service.
Recover/retry stable proposal IDs and compare accepted history, event sequence,
proposal bytes and drafts. Do not corrupt the live project or claim coverage of
unobserved OS/filesystem failure boundaries.

Store redacted evidence using [the evidence template](team-evidence-template.json). For each TEAM, COORD and GRAPH gate list
observed facts, commands/logs and exact pass/fail/partial/not-run status. An
independent reviewer compares all three participants' reports against the same
UUID and authority history. No full-release pass until all required scenarios,
provider routes and actual mixed-OS results are supported. Local unit tests and
three separate CI runs are supporting evidence only.
