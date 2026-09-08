# Everyday collaboration with Shared Memory

Start with the actual project's `AGENTS.md` and the exact installed runtime's guide.
The experimental 0.2.0 product and legacy advisory tracker use different commands.
Do not run the legacy examples against a product project as a substitute for its authority.

The shared unit may be one project folder inside each person's existing vault.
Keep parent vaults private and configure only that folder. Follow the
[project-folder guide](../skills/setup-shared-project-workspace/references/project-folder-sharing.md)
for access boundaries and different local layouts; there is no need to open or
create an Obsidian vault just to join a configured folder.

## Experimental product workflow

Use your own private member credential and local client state. Refresh accepted
context and inspect `team-status`, `context` and `receipt` before work. A current
local receipt establishes which accepted bytes you have; it is not a provider receipt.

For schema 2, create your own session, plan bounded assignments and acquire a live
lease using a current receipt. Keep the acquired session, ownership generation,
policy revision and input hash with every draft. Submit it for the integration
owner's review and acceptance, then refresh the accepted result. Claiming an identity
in prose does not authenticate it. Another actor creates their own session; delegation
cannot impersonate them. Existing schema-1 projects keep their documented `claim`
workflow until an explicitly reviewed upgrade.

On handoff, the old worker stops its work. The recipient inspects their own durable
inbox, acknowledges addressed notices, refreshes and acquires with their own session
and current receipt. Stale ownership or receipts must not be worked around by deleting
history. Offline edits remain drafts until the authority accepts them. Structured
factual conflicts require the responsible owner's decision; arbitrary prose still
needs semantic review.

See [exact session and handoff commands](PRODUCT-V1.md#session-based-coordination),
[graph and reviewed rename operations](KNOWLEDGE-GRAPH.md), and
[experimental limits](READINESS.md). None of these steps deploys a server or configures
sharing. Automated fixtures do not prove independent-person or provider acceptance.

## Legacy advisory tracker workflow

The examples below apply only after legacy tracker setup, with the terminal in that
selected project. They do not use the product's member tokens or authenticated engine.

### Start a session

Review the tracker before its first execution and verify its provenance with the
project owner. Choose an actor ID unique to your human/agent/session and do not use
an email address. Use your own identity; the test suite's example people are fixtures.
Run validation/status first, then use `sync --help` for required identity arguments:

```bash
python3 Coordination/project_tracker.py --help
python3 Coordination/project_tracker.py validate
python3 Coordination/project_tracker.py status
python3 Coordination/project_tracker.py sync --help
```

`sync` records what this actor has reviewed locally. It does not trigger or verify
provider propagation or Git operations. Check your actual access method separately;
remote synchronization is not applicable to local-only work.

### Own a bounded task

Use the installed command's help to supply its required fields:

```bash
python3 Coordination/project_tracker.py claim --help
python3 Coordination/project_tracker.py start --help
python3 Coordination/project_tracker.py change --help
python3 Coordination/project_tracker.py handoff --help
```

- `plan` records an unclaimed follow-up; a suggested owner is not an assignment.
- `start` lets an owner claim existing backlog after reviewing its evidence.
- `claim` establishes a new bounded work item and its exact targets.
- `check` verifies ownership, freshness, and dependencies immediately before editing.
- `heartbeat` renews an active claim when necessary.
- `change` records a material result, evidence, acceptance state, and dependency impact.
- `handoff` proposes transfer; the recipient uses `accept-handoff` before continuing.
- `complete` requires acceptance and validation evidence.

After claiming a real work item, replace the values in this example:

```text
python3 Coordination/project_tracker.py check --actor <your-actor-id> --work-id <your-work-id>
```

Inspect the [record schema](../skills/setup-shared-project-workspace/references/record-schema.md)
when diagnosing records. Use the tracker rather than hand-editing its operational state.

### Work in parallel

Divide work by exact files, directories, branches, environments, or artifacts. Two
agents must not edit the same target concurrently. A directory claim includes its
children. Agree on an integration owner and declare dependencies before work diverges.
Use project-relative paths for file targets. Each person's project may have a different
local root; a sender's absolute home or mount path is not a shared target identifier.

Claims are advisory on synchronized filesystems. Two disconnected computers can both
see an apparently free target. Do not continue affected edits offline when ownership
cannot be established. Coordinate directly with the owner through an authorized channel.
Never assume an expired claim means a contributor has stopped.

### Handle changes and handoffs

In 1.3.0, directory descendants and large files participate in drift checks.
`complete` refuses unrecorded changes. If using `change --changed-target`, include
all affected claimed targets after reviewing their actual contents. Prefer narrow
claims; directory hashing reads descendants and rejects symbolic links.

Record what changed, who owns it, validation and evidence, limitations, and the next
action. Mark impact `none`, `compatible`, `breaking`, or `unknown`. Review stale
dependencies before continuing downstream work. Preserve historical events; correct
them through a superseding record.

At handoff, confirm provider synchronization, update acceptance criteria, and identify
the next owner. The recipient must refresh their own context and accept the handoff.
Local validation, cloud upload, another device's receipt, and visual verification are
different checks. Report only the ones actually performed.

### Keep the vault portable and private

Prefer relative links. Use Obsidian for note moves where available and verify links.
Keep credentials, private endpoints, large artifacts, and machine-specific runtime
state out of shared notes. Do not change shared `.obsidian` configuration casually.
Agent rules and actor IDs are not authentication, authorization, or tamper-proof auditing.
