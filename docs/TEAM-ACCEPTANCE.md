# Shared Memory real-device acceptance runbook

Prepared 2026-09-08. **Not executed.** This procedure gathers the missing TEAM
release evidence. It does not authorize deployment, sharing, account changes,
credential delivery or publication. Use only disposable public/synthetic project
content. Do not use the live Exlumina Vault or backup drives.

## Required environment

Name an integration owner and three actual participants on Windows, macOS and
Linux. Record OS/Python/agent versions, distinct actor IDs, the exact reviewed
runtime SHA-256 and bundle ID, and different selected local paths. The latest
reviewed package/evidence is identified by the delivery README. Verify its external
checksum before executing it. Keep private state outside all synchronized folders.

Use one project UUID and one reviewed reachable HTTPS coordinator for the whole
run. Record host ownership, availability and recovery responsibility. A sleeping
owner laptop cannot provide ongoing availability. Obtain separately authorized
provider access and independently issued membership tokens. Never copy private
client state or tokens as project content. Keep private locators/credentials out of
shared reports. No participants or deployment have been arranged by this runbook.

Select a provider/account/OS route explicitly. Windows/macOS vendor-folder tests
may exercise Google Drive, OneDrive or iCloud only with verified account/client
support. The current vendor-desktop routes are blocked on Linux; do not label an
HTTPS-only Linux run as a passed vendor-provider integration. A separately supported
self-hosted storage route needs its own actual file-delivery evidence. Coordinator
HTTPS receipt and storage-provider receipt are different observations.

## Owner setup and independent joins: TEAM-01/02

1. On each device create a disposable private parent with a private sibling and
   `.obsidian` fixture settings, plus the selected project subfolder. Hash the
   parent/sibling/settings files before setup. Obsidian need not run.
2. Owner uses `init PROJECT --state-dir PRIVATE_STATE --person PERSON --actor ACTOR
   --agent AGENT --purpose PURPOSE --mode team --provider PROVIDER`. Record the
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
5. Each participant independently verifies `team-status` and `receipt`. Compare
   UUID/revision/files_hash across devices and re-hash untouched parent/settings.
   Capture mismatches or partial results rather than replacing them with ready.

## Work, conflict and handoff: TEAM-03/04/05/06

Use `coord PROJECT --state-dir PRIVATE_STATE OPERATION --payload-file PRIVATE_JSON`
with the payloads in the candidate's engine contract. Save each command's JSON
output, exit code and time without credential values.

- Each distinct actor claims different declared note targets. Include acceptance
  criteria, an integration owner and a real dependency. Attempt continuation before
  dependency completion and an overlapping claim; both must fail without mutation.
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
- Handoff work from macOS to Windows, then Windows to Linux. Before `receive`,
  attempt a proposal as the recipient and confirm rejection. Recipient verifies
  current receipt, supplies exact revision/hash to `receive`, then continues and
  completes with evidence. Attempt stale receipt/completion and record rejection.

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

## Recovery and final review: TEAM-09/11

Use disposable authority/client state for interruption tests. Run the candidate's
actual acceptance-boundary and materialization fault tests on each OS, then perform
a reviewed participant disconnect/lost-response trial through the reachable service.
Recover/retry stable proposal IDs and compare accepted history, event sequence,
proposal bytes and drafts. Do not corrupt the live project or claim coverage of
unobserved OS/filesystem failure boundaries.

Store redacted evidence using [the evidence template](team-evidence-template.json). For each TEAM gate list
observed facts, commands/logs and exact pass/fail/partial/not-run status. An
independent reviewer compares all three participants' reports against the same
UUID and authority history. No full-release pass until all required scenarios,
provider routes and actual mixed-OS results are supported. Local unit tests and
three separate CI runs are supporting evidence only.
