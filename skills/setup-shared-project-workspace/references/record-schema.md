> **Historical advisory toolkit reference.** This applies only when that older tracker is explicitly selected. Normal Shared Memory 0.3.0 uses direct folder editing; see [product runtime routing](product-runtime.md).

# Coordination record schema

Schema version `1` uses Markdown notes with flat YAML frontmatter so Obsidian Bases,
plain-text tools, and the bundled Python tracker can read the same state without an
additional database.

## Record types

### Work

One mutable record represents the current state of one bounded workstream. Its owner is
the only actor allowed to update it until a recorded handoff.

Unclaimed backlog is created with `plan`: `status: not_started`, empty `actor_id`
and `claim_expires`, and `owner: Unassigned`. `recorded_by` attributes the importer;
`suggested_owner`, `source_summary`, and `source_evidence` do not assign or resume
another contributor. `start` acquires a claim only after explicit source/dependency
review, fresh target-overlap checks, and a recorded actor identity. It cannot steal an
existing claim. Historical progress is not counted as passed criteria for the follow-up.

Required properties include `work_id`, `title`, `status`, `revision`, `owner`, `agent`,
`actor_id`, `initiated_by`, `targets`, acceptance counts, dependencies, dependency
baselines, timestamps, evidence, target hashes, and `next_action`. `passed_criteria`
contains exact one-based checklist IDs; `acceptance_passed` is derived from that list.

Statuses are `not_started`, `claimed`, `in_progress`, `blocked`, `pending_approval`,
`ready_for_review`, `verified`, and `cancelled`.

Dependencies use work IDs. Baselines are serialized as `WORK-ID@revision` strings. A
dependent work item needs review whenever its baseline is below the upstream revision.

### Portable targets

Version 1.2.0 stores file `targets` and hash-map keys as project-relative POSIX paths.
An absolute input inside the current project is normalized to the same identifier
as its relative form. Inputs outside the project, home shortcuts, and parent traversal
are rejected. Contributors resolve their own local project roots; the shared records
must not require an original owner's absolute machine path.

Non-file labels beginning with `branch:`, `environment:`, `env:`, or `artifact:` are
advisory names, not proof of the resource's live state. They are not resolved or
hashed as local files; their hash field uses the `missing` sentinel.
Existing nonportable stored paths are diagnosed before use. Updating the
tracker does not migrate records or change historical ownership; follow the
[retrofit policy](retrofit-policy.md) for reviewed upgrades and record mapping.

### Content fingerprints in tracker 1.3.0

Files are hashed with streaming SHA-256, including files larger than 20 MiB.
Directory hashes use `directory-sha256:` plus a digest of sorted descendant paths,
file contents and directories. The tracker's own Coordination/Items subtree is
excluded to avoid claims invalidating themselves. Directory symbolic links are
rejected; choose exact file targets when appropriate. Narrow claims limit cost.

When explicitly declaring changed targets, `change` rejects drift in other claimed
targets instead of silently absorbing it. A child edit under a directory claim
requires acknowledging the claimed directory after reviewing its other contents.
`complete` rejects unrecorded drift before recording verification. Old `directory`
and `too-large` baselines need owner review and a recorded change, not rewritten
historical records. Neither hashing nor declared evidence authenticates an actor.

### Event

Events are immutable. They capture a material state change, including before and after
status, work revision, changed targets, file hashes, impact, affected work, evidence,
validation, limitation, and next action.

Material events include claims, deliverable or interface changes, blockers, approval
waits, validation outcomes, dependency acknowledgements, review readiness, completion,
cancellation, and corrections. Ordinary reads and low-signal command attempts are not
events unless they reveal a material blocker or result.

### Handoff

Handoffs are immutable and record the previous actor, intended next actor, last verified
state, exact continuation step, limitations, evidence, and affected work. The associated
work record changes owner only through the same operation. Its `handoff_pending` field
stays true until the receiving actor uses `accept-handoff`, which emits a new immutable
acceptance event rather than editing the handoff record.

### Decision

Decisions are immutable and include a stable key, owner, agent, rationale, impact,
affected work, evidence, and any decision they supersede.

### Actor

One actor record belongs to one human-agent combination or agent instance. It stores the
events that actor has acknowledged and its active work IDs. Only that actor updates the
record. Identity is declarative rather than cryptographically authenticated.

## Impact values

- `none`: no downstream effect.
- `compatible`: downstream owners should read the update, but existing assumptions stay
  valid.
- `breaking`: downstream assumptions, interfaces, or outputs require review.
- `unknown`: impact has not been determined and downstream work must fail closed.

## Evidence rule

`verified` work requires at least one evidence pointer and one validation description.
File hashes prove byte identity only; they do not prove correctness. Git commit IDs prove
repository state only; they do not prove runtime, UI, deployment, or physical behavior.

## Naming

The tracker creates machine-sortable files:

```text
WORK-ARCH-001.md
EVENT-20260830T181000Z-ARCH-001-A31F.md
HANDOFF-20260830T182000Z-ARCH-001-B72C.md
DECISION-20260830T183000Z-INTERFACE-FREEZE-C91D.md
ACTOR-TAYLOR-CODEX-PRIMARY.md
```

UTC timestamps plus random suffixes avoid a shared global sequence file and reduce
write contention. They do not provide a cryptographically trusted global clock.
