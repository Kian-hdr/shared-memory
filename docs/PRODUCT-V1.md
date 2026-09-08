# Shared Memory: operating the development build

**A shared workspace for your team and its AI agents.**

Product **0.2.0 development** contains the authoritative engine and local client.
Obsidian is optional. This is not a completed stable V1 release: actual cloud-provider
receipt, independent recipient onboarding and mixed-OS TEAM-11 remain unverified.
The existing repository URL and executable identifiers stay unchanged until the
reviewed launch rebrand. Toolkit 1.3.0 and historical CLI 0.1.0 are separate versions.

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
development source is published on the development branch; public main remains the historical toolkit and must not be substituted silently.

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

## Daily agent workflow

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
