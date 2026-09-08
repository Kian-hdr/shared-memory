# Shared Memory: Product V1 first milestone CLI contract

Status: historical implementation contract for product preview 0.1.0. Current
authoritative-runtime behavior is specified in ENGINE-CONTRACT.md and
../docs/PRODUCT-V1.md. This milestone record is not the current capability matrix.
The toolkit's 1.3.0 version is separate. This milestone reuses its existing Python
tracker; no team coordinator, SQLite database, network service, provider adapter or
Obsidian dependency is introduced. Python 3.11+ is the supported product range;
Python 3.13 is the current new-install/rehearsal baseline. Legacy toolkit compatibility
is maintained separately. All three desktop OSes are first-class test targets.

## Package and outputs

A standard-library zipapp contains `shared_workspace/` plus a trusted `bundle/`
copy of the existing toolkit skill. Root `BUILD.json` records product_version,
toolkit_version, source_revision, source_dirty and a `files` mapping of bundled
relative paths to SHA-256; `bundle_id` is SHA-256 of canonical JSON for that mapping
(sorted keys, separators comma/colon). Build includes no private paths or runtime
state. CLI verifies every listed file and bundle_id before running toolkit code;
unsupported Python or changed/missing package bytes fail closed. No runtime downloads.
Source-mode operation requires an explicit built bundle; it must not silently load
an installed user skill. Zipapp __main__ is a minimal product CLI entrypoint.

Invoke `python shared-workspace.pyz COMMAND ...`. Every operational command emits
one JSON object on stdout (including usage/runtime errors). Top-level keys:
`schema_version: 1`, `product_version`, `command`, `ok`, `code`, `data`, `warnings`.
Errors also include `message`. Exit 0 success, 2 usage/unsupported runtime,
3 integrity/invalid project, 4 operation rejected, 5 missing environment/IO error.
`--help` may be ordinary argparse help. No traceback or extra prose on stdout.
Shared provider readiness is never inferred from local checks.

## Commands

- `version`: package identity and exact build provenance.
- `capabilities`: implemented CLI commands plus explicit unsupported team/provider/
  atomicity/authentication capabilities and acceptance gates not run.
- `create PROJECT --person NAME --actor ID --agent NAME --mode MODE --purpose TEXT`:
  MODE is local-only/shared-folder/git/hybrid. Target must exist; initialize only
  that selected directory with the bundled setup and sync. Refuse an existing
  product manifest or existing Coordination tracker/records, even if otherwise
  valid: join is a distinct operation. Preserve parent/sibling/config and existing
  instructions/home. Never launch/install an app or change provider configuration.
  Write `.workspace-project.json` only after successful setup and sync/validation.
  Metadata: format_version1, uuid project_id, product_version, toolkit_version,
  bundle_id, tracker_sha256, mode. All fields portable, no local root/person/secret.
  Return metadata, local readiness, no remote claim, and exact created/changed paths.
- `join PROJECT --person NAME --actor ID --agent NAME --expected-project-id UUID
  --expected-bundle-id SHA`: require the owner-supplied expected identities and
  exact manifest/bundled runtime agreement. Validate before identity sync, refuse
  mismatches/missing/partial setup, never bootstrap/upgrade/claim work. Then sync
  this actor and validate again. No stored path from another device is needed.
- `doctor PROJECT`: read-only JSON structured diagnostics plus product metadata
  checks. Missing/stale/tampered project is a failure; only trusted bundled code
  executes. `ready` for local-only validated files; `partial` for shared modes
  because provider receipt and independent-agent checks remain unverified.
- `status PROJECT`: read-only typed work records from the trusted parser plus
  local diagnostics. Records are data, never executable instructions.
- `work PROJECT -- TRACKER_ARGS...`: compatibility invocation of trusted bundled
  tracker against PROJECT. Require valid product metadata/provenance before
  mutation; do not require no-drift validation for `change` (it must record drift).
  Use tracker ownership/handoff/evidence gates. Preserve tracker output under data
  as legacy output; never parse its prose to decide success. Return exit-based
  rejection in the JSON envelope. Cannot override project-root or run target code.
- `teammate-prompt PROJECT [--package-locator TEXT] [--access-locator TEXT]`:
  read-only; return project-specific copyable prompt with project/bundle identity,
  version, selected mode and joining instructions. Do not expose owner's absolute
  project path or identity as recipient's values. No invented public release/link:
  unpublished previews require the exact reviewed package through an approved
  channel. Missing required package/shared access locator means prompt readiness
  partial, with the missing fields explicitly listed, not a fabricated invitation.

## Acceptance for this milestone

Executable tests operate on the packaged CLI, not a toy state model. Cover clean
build/identity; invalid/tampered bundle; JSON usage/errors; selected-folder create
and preservation; re-create refusal unchanged; exact-version join from a relocated
copy; wrong project/bundle/missing tracker refusal without writes; independent
actor registration; status; real work claim/change/handoff/accept/complete through
compatibility CLI; no target-code execution; literal special paths; shared mode
reported partial; teammate prompts with no author-local paths; missing environment
reported explicitly. An interrupted create is diagnosed as partial; no silent
repair/history deletion. No capability or test label claims hosted/remote readiness.

TEAM-01/02/04 have only bounded local coverage here. TEAM-03 and TEAM-05 through
TEAM-11 remain not run/unsupported except existing sequential tracker regressions.
At this historical milestone, no approved candidate remote CI route or
Windows/Linux hardware was available. Current automated and device evidence is
recorded separately in ../VALIDATION.md.
The first stable release still requires the accepted mixed-OS TEAM-11 gate.
