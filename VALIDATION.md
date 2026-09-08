# Validation record

## Repository separation

Shared Memory now has an independent private development repository. Public
visibility is deferred until version 1 is finished. The source was transferred
from commit `c4aaedbbeb959bce8b624efe2c83c91f96c8ee0d` with its history preserved.
The separation changes repository navigation and documentation, not runtime behavior.
Historical links below identify runs in the legacy repository and may require access
after it becomes private. They are not new-repository CI results. The new repository
checkpoint below records its own completed validation separately.

## Selected-root and core path-boundary correction, 2026-09-08

The `24f1ff3` candidate is withheld. Its [matrix](https://github.com/Kian-hdr/shared-memory/actions/runs/34243071900)
passed ten jobs, but both Windows product jobs rejected valid rename plans with
`project_mismatch`: setup saved a canonical root while rename compared a lexical
path. The correction checks the original path for links/reparse points before
canonicalizing, then validates the canonical path and saved binding. Dedicated
Windows regressions cover case/short-name aliases and junction-root refusal.

An adjacent source review found that ordinary client scanning/materialization and
setup/private database paths still needed equivalent junction guards. Directory
junctions cannot be treated as harmless merely because `is_symlink()` is false.
The correction now shares original-path checks across client scanning/materialization,
setup, private files/tokens, database sidecars, delivery staging and local backend
traversal, migration previews, runtime install/rollback and retained backup hashing.
Raw `alias/../` components are checked before normalization. Protected directories
are pruned before enumeration. Canonical destination containment, backup checksums,
checkpoint verification and durability checks remain in place. This does not provide
an OS lock against hostile concurrent filesystem replacement.

Independent source/test review approved the combined changes. On each local Python
3.13 and 3.12 run, the core group collected 182 tests: 169 passed and 13 actual
Windows junction cases skipped; the adjacent group collected 62: 59 passed and
three Windows-only cases skipped. The final graph group on 3.13 collected 21:
18 passed and three Windows-only cases skipped. These groups overlap existing
regressions and must not be added together as distinct coverage. The final combined
Python 3.13 suite collected **345 tests: 324 passed and 21 Windows-only cases
skipped**, in 73.892 seconds. Actual Windows/macOS/Linux matrix and exact-source
HTTPS execution remain separate acceptance evidence.

The same candidate's [schema-2 HTTPS trial](https://github.com/Kian-hdr/shared-memory/actions/runs/34243094389)
passed all four jobs and 423 packaged calls/four expected refusals. All three OS
clients reached revision 5 with matching content, preserved private bytes and
stopped temporary processes. This separate protocol result does not override the
failed Windows rename matrix or pass provider/independent-person acceptance.

## Scoped product rename and context validation, 2026-09-08

The new graph rename plan/draft/apply workflow preserves selected-folder boundaries
and uses ordinary authenticated proposals plus the existing client journal/backups.
The independent review reproduced a supplied JSON-null coordination file being
silently treated as omitted; rename, ordinary draft and preserved-draft promotion
now validate supplied objects before mutation. Packaged regressions cover malformed
shapes, valid context and actual omission. Independent probes confirm that a new
local edit after acceptance remains preserved and yields a correctly partial receipt.

The final local Python 3.13 suite collected **299 tests: 296 passed and three
Windows-only junction tests skipped**, in 76.122 seconds. The focused rename/client/
graph suite passed 87 of 90 with three platform skips on both 3.13 and 3.12;
following generic context fixes, all ten team CLI cases passed on both, with the
two new malformed-context cases independently rerun. Actual Windows execution and
the new 20-command packaged rename fixture were included in the matrix above; Windows failed before that fixture could run, while macOS/Linux completed it.

A separate fixture ran the actual packaged schema-2 rename inside an existing
registered Obsidian test vault, with private runtime state outside it. All 20 calls
passed, including two expected refusals, at revision 1/hash
`840c483d4f03c3bef38bc1450ce2789a33b7759d01b8ba1bd0bcf33afd3f98af`.
Obsidian **1.13.7 (installer 1.12.7)** resolved all six selected links; clicking the
rendered wikilink opened the renamed note and the native backlink pane showed the
three incoming Home references. Existing notes, known outer backlinks and app
configuration were preserved; only workspace layout changed. This proof used an
explicitly labeled development package; clean committed package identity/readback
is a separate checkpoint. It does not establish provider or independent-user readiness.

## Windows portability correction, 2026-09-08

The extension at `3c8e9e90e78e4b12890e13c1dd42a03a863ecab5` passed ten
[CI jobs](https://github.com/Kian-hdr/shared-memory/actions/runs/34238239825) but
failed both Windows product jobs. The graph used directory-entry metadata whose
Windows file identity did not agree with an opened descriptor, matching the
[Python directory-entry contract](https://docs.python.org/3.13/library/os.html#os.DirEntry.stat). Backup and schema
upgrade attempted to flush read-only file descriptors, which Windows rejected.
That artifact is retained as a withheld development checkpoint.

The correction obtains uncached no-follow path identity before opening graph notes
and keeps descriptor identity/change checks. Graph traversal also rejects linked
roots/ancestors and excludes Windows junction/reparse entries, including validation
of the original CLI path before resolution can hide a junction. Backup flushes use writable,
nontruncating handles; flushing is still required, and failures still propagate.
Both local Python 3.13 and 3.12 runs collected **280 tests: 278 passed and
two real Windows-only junction fixtures were explicitly skipped**. The native-renamed
synthetic graph still resolves five notes/twelve edges without diagnostics.
Independent review approved the flush, replacement/mutation and junction boundaries.
The corrected e1d023c [matrix](https://github.com/Kian-hdr/shared-memory/actions/runs/34239839865)
passed all twelve jobs, including both actual Windows junction fixtures. Product
jobs each collected 280 tests: macOS/Windows passed 278 with two platform skips;
Ubuntu passed 277 with three. Every product job also passed the 57-call packaged
coordination rehearsal with four expected refusals.

The preceding 3c8e9e9 [HTTPS regression](https://github.com/Kian-hdr/shared-memory/actions/runs/34238278569)
passed all four jobs and **123 packaged CLI calls**. All three OS clients reached
revision 3 with identical content and preserved private parent/settings/attachment
bytes. Task-owned processes stopped. The package SHA-256 was
`0ca9413784f0f77a87c757d4730be629ce90eb6c279015f145553823b3d832de`, identical to
the independently built/read-back local package. This tests schema-1 compatibility,
not the new distributed session workflow, provider receipt or independent people.

## Distributed schema-2 rehearsal and inbox resume, 2026-09-08

The distributed script now offers explicit `--coordination-schema 2`, retaining
schema 1 by default. The workflow dispatch input selects one schema for every
participant; signed rendezvous metadata binds that selection before downloaded
package execution. Each actor creates its own authenticated session. Same-base
proposals integrate at revisions 1–3; actual Windows-role and Linux-role handoff
continuations produce revisions 4–5. An origin's preserved draft is refused after
transfer while its base is still current, before the recipient acquires. The
recipient also proves stale-receipt refusal, targeted inbox acknowledgement and
fresh fenced acquisition. Exact private parent/settings/attachment bytes survive.

One-machine loopback selfchecks against the exact reviewed e1d023c executable
passed: schema 1 made 96 packaged calls/two expected refusals at revision 3;
schema 2 made 309 calls/four refusals at revision 5 with content hash
`34bbe57a2286cd4d98343d8fadf73cc74ac7e783f1ef3ece48535722cd0da764`.
Call counts include polling, not distinct coverage. All four processes stopped.
Independent review inspected the frozen script and both complete reports. The actual
[three-OS HTTPS run](https://github.com/Kian-hdr/shared-memory/actions/runs/34241487058)
at private checkpoint `912ae9f94a050e382fa80fbffa76ae2049242331` then passed all
four jobs, with 396 packaged calls/four expected refusals, the same revision-5 hash
and preserved private fixture bytes. Each actual OS client used its own session;
temporary coordinator/tunnel processes stopped. Its package SHA-256
`5c2946d3513e6c1b07774d327830e5b1cc27557b582d6084407171051e2d1fab` matches
the independently built/read-back clean source package. Neither local role names
nor automated runners constitute independent people/provider TEAM-11.

The new inbox-resume acceptance test starts separate consumer processes against
the actual SQLite authority, persists a two-message-page cursor, resumes after new
addressed events arrive and checks all expected message IDs without omission or
duplicate processing. Acknowledgements survive reopening and are idempotent; another
actor cannot see or acknowledge those IDs. The focused coordination suite passed
44/44 on Python 3.13 and 3.12. This demonstrates the durable API, not an installed
always-on consumer or notification service.

## Coordination, graph and upgrade extension, 2026-09-08

The opt-in schema-2 extension passed **273/273 product tests**, with no skips, on
macOS/Python 3.13.15 and 3.12.13. Schema 1 remains the default. The extension adds
separate session identities, same-actor narrowed delegation, renewable fenced
leases, reserved outcome keys, versioned output/interface dependencies, targeted
policy/inbox updates, defect invalidation and explicit responsibility transfers.

Independent review reproduced an impersonation bug in development delegation before
this checkpoint. The corrected engine rejects both new cross-actor delegation and
retained cross-actor child/grandchild credentials without rewriting history. All
nine distinct-actor role combinations and the original integration bypass were
independently refused without database-byte changes. Same-actor narrowing and
ancestor revocation remain enforced. Actual packaged regressions also reject empty
or whitespace session credentials, empty delegation arguments and empty explicit
coordination configuration without database, private-session or project writes;
these inputs can never silently select owner credentials or schema 1. The independent 74-case coordination,
migration and maintenance suite passed on both runtimes. Policy revision history
prevents restrict-then-restore from resurrecting stale authority; unaffected roles
can retain valid context. Exact outcome keys remain reserved after completion.

The actual packaged CLI rehearsal passed **57 commands and four expected refusals**
on each runtime: separate owner/recipient credentials, duplicate outcomes, overlapping
leases, stale drafts and stale receipts, two accepted revisions, handoff/completion,
exact materialization and read-only graph. Private parent notes, home/instructions,
binary attachments and the immutable old draft remain unchanged. Reusing its output
directory rejects without changing the fixture. Run it with:

```sh
python scripts/rehearse_coordination.py --package /reviewed/shared-memory.pyz --output /private/fresh-rehearsal
```

The output contains synthetic credentials and private state. Only its sanitized
`report.json` is intended for inspection/sharing. The CI product matrix now runs
this rehearsal against its exact built package on each OS/runtime; remote results
must be checked separately before claiming this changed source passed there.

Upgrade tests cover seven actual process-kill boundaries, checkpoint drift, owner
authentication, exact retry and preserved legacy history. Backup verifies complete
history and rejects coordinator sidecars/shared-project destinations before writing.
Two independently inspected 73,400,320-byte immutable outputs remain retrievable;
paginated summaries measured 1,395 bytes instead of embedding the content.

The graph has 23 analyzer and eight packaged CLI tests. In a separate synthetic
existing vault, native Obsidian 1.12.7 displayed five selected notes with twelve
resolved links; graph/backlink navigation and native rename were exercised. Renamed
note bytes and original app configuration were preserved. Native rename also updated
one known outer-fixture backlink: it does not enforce the selected-folder write
boundary. The analyzer reads only its selected root and cannot certify parent links.
No live Vault migration or new vault registration occurred.

These are synthetic/local engineering results, not real provider delivery,
independent-recipient onboarding, hosted operations or completed TEAM-11. No public
release is authorized before finished V1.

## Private product repository checkpoint, 2026-09-08

At `3b648d08be8f47c698c47375e42c2ee9dc3a45c4`, the new repository's
[CI matrix](https://github.com/Kian-hdr/shared-memory/actions/runs/34181376740)
passed all twelve jobs and its
[concurrent HTTPS rehearsal](https://github.com/Kian-hdr/shared-memory/actions/runs/34181380260)
passed all four jobs with **111 packaged CLI calls**. All three OS clients used the
same downloaded package, reached revision 3 and agreed on accepted content hash
`8d721b8696ffdabe16a392582867e2dc1080131db29acfab8e166d839fd31ff7`.
Private parent notes/settings/artifacts and original mixed-newline Unicode files
remained byte-identical. Premature handoff writes were refused; server/tunnel stopped.

The exact downloaded executable SHA-256 is
`9b9068f635a5f55410b64c680fcb5039aad8872a2752939f6541b5be2f7451b7`;
the committed source ZIP SHA-256 is
`a823065728e6285b7f49b46487324976a2380b1c6c4be03c683a2925a465842f`.
All 33 package entries and all 61 source files passed independent readback.
These synthetic OS actors do not establish independent human setup, provider
delivery, complete TEAM-11 or a production service. The private internal artifacts
are preserved; no release/tag was created. Subsequent provider implementation is
not included in this checkpoint.

## Immutable revision delivery implementation, 2026-09-08

The first explicit rclone adapter adds manifest-last immutable publication, bounded
verified fetch, private reviewed Drive configuration, duplicate/unsafe/native-document
refusal, and separate deletion-base receipts. The client checks current authenticated
metadata before any recovery or project write, then uses its existing journal and
draft protections. The CLI fetch path never substitutes coordinator snapshot bytes.
Initial attachment remains through the coordinator.

**174/174 product tests passed on macOS/Python 3.13.15 and 3.12.13, no skips.** This
includes 20 delivery tests, 17 downloaded-client tests and five binding/packaged CLI
tests beyond the previous 132. Independent review reran all 42 focused tests with no
skips or blocking findings. Actual installed rclone 1.75.0 local-backend transfer,
idempotent retry, accepted deletion and refusal of missing/corrupt remote fixture
bytes passed. These are local fixtures, not Google Drive requests.

CI now stages official rclone 1.75.0 using platform-specific reviewed SHA-256 hashes
in a disposable runner directory, so its Windows/macOS/Linux product jobs exercise
the actual local driver instead of skipping for missing rclone. The staging script
was executed on macOS arm64 and verified the downloaded archive hash before extracting
only its executable. Subsequent exact source `5a6fd30` passed the
[twelve-job matrix](https://github.com/Kian-hdr/shared-memory/actions/runs/34232620856),
including real local rclone on every product OS. Its runtime-equivalent `7d88ce3`
passed the [four-job HTTPS rehearsal](https://github.com/Kian-hdr/shared-memory/actions/runs/34232511551)
with 98 packaged calls; `5a6fd30` changed only readiness documentation.
No Google Drive account authentication, publication, sharing or provider request has
been performed; actual account/recipient/mixed-device gates remain open.

## Completed c4aaedb cross-platform checkpoint, 2026-09-08

The [twelve-job matrix](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34180872359)
and its duplicate PR run both passed at
`c4aaedbbeb959bce8b624efe2c83c91f96c8ee0d`. The product suite collects 132 cases:
macOS executes all 132; Windows passes 130 with two explicit skips (POSIX hook
fixture and unavailable unsupported-Python interpreter); Ubuntu passes 131 with
one skip (unavailable unsupported-Python interpreter). Both Python 3.11 and 3.13
jobs passed on each OS; all six legacy toolkit/demo jobs also passed.

The [same-source HTTPS run](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34180872287)
passed all four concurrent jobs and 103 packaged CLI calls. All OS actors used
package SHA-256 `2c7cd1e5b3c11ddd586e24514f9b0f9f6bbfa9ab6657d90e56933e2fa89b33df`,
reached revision 3 and file hash
`8d721b8696ffdabe16a392582867e2dc1080131db29acfab8e166d839fd31ff7`,
and preserved private parent notes, settings and local attachments, including exact
mixed line endings and non-ASCII accepted text. Handoffs and premature-write
rejection passed; all task-owned processes stopped. These were synthetic automated
actors, not independent humans or real storage-provider delivery.

Terminal run metadata, all six product job logs, all four HTTPS reports, the exact
package and a verified 61-file source snapshot were captured privately before the
legacy repository became private. Both repositories are now private. No GitHub
release or public prerelease was created. The new repository retains source history;
its own validation remains distinct from these historical runs.

## Windows output correction, 2026-09-08

The corrected recovery source at `8c5c26ef6167dc3efb256ef798fb3744777af044`
passed the [four-job HTTPS run](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34180503539)
with 104 packaged calls, including exact existing mixed-line-ending and non-ASCII
content on all three OS clients. Its [full CI matrix](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34180503531)
passed ten jobs; both Windows product jobs exposed a real CLI output encoding bug
and a token-terminator assertion mistake. The downloadable candidate remained withheld.

Valid Unicode content could fail JSON output under a legacy Windows CP1252 pipe and
be mislabeled malformed project data. The CLI now emits ASCII-safe JSON escapes;
decoded Unicode values and UTF8 project bytes are unchanged. A real packaged-process
regression forces `PYTHONIOENCODING=cp1252` and `PYTHONUTF8=0`, and passed after failing
before the fix. Credential tests now deliberately use CRLF input, compare the parsed
credential value, and still require private credential bytes to remain unchanged
through interrupted and completed retries.

**132/132 product tests passed on macOS/Python 3.13.15 and 3.12.13, no skips.**
The completed remote result for the output fix is recorded above. New-repository
validation remains a separate check after the documentation/navigation transfer.

## Recovery hardening checkpoint, 2026-09-08

A subsequent bounded audit reproduced interrupted first-time setup, a skipped-revision
directory-to-file recovery failure, and first-import newline normalization. The
prepared b58ea16 downloadable prerelease was withheld; its successful earlier CI
and HTTPS run remain historical evidence for that exact source.

The corrected source adds immutable private setup intent and credential preservation,
atomic authority/manifest publication, bounded setup locking and exact retry binding.
Invalid owner inputs are rejected before creating private state, and different setup
identities reserve the selected root before materialization. Initial UTF8 import
preserves CRLF, LF, lone CR and missing final newline bytes. New setup records are
excluded from accepted content and migration output.

Directory conversion now processes eligible tracked deletions before writes, including
when a recipient skips intermediate revisions. Only empty obsolete ancestors required
for the conversion are removed; modified tracked files and private/untracked descendants
remain preserved and may block replacement. The stored journal format is unchanged.

**131/131 product tests passed with no skips on macOS/Python 3.13.15 and 3.12.13.**
New coverage comprises ten setup tests (including fifteen real subprocess hard-exit
boundaries and deterministic concurrency regressions), fourteen directory-transition
tests (including injected I/O failure/reopen), and one private-setup exclusion test.
Existing engine/client/maintenance/CLI tests also passed. Independent focused review
reproduced the original failures and verified the corrections. These boundaries do
not certify physical power loss or every filesystem. Setup, installation and directory
conversion require supported same-filesystem hard links.

The subsequent remote result and Windows output correction are recorded above.
This section preserves the earlier local 131-case checkpoint; it is not the final
release result.

## Published development branch and cross-platform CI, 2026-09-08

The reviewed source is published on
[the preserved source revision](https://github.com/Kian-hdr/shared-memory/tree/c4aaedbbeb959bce8b624efe2c83c91f96c8ee0d).
This is a development branch, not a stable V1 release or a repository rename.

The [first run](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34178714443)
passed ten of twelve jobs. Both Windows product jobs exposed a fixture newline
mismatch: Windows text-mode writes produced CRLF while the test expected LF.
The runtime correctly preserved the actual bytes. Commit
[`9214375`](https://github.com/Kian-hdr/shared-memory/commit/9214375ea778c4c650def5ecb5f253756d218f49)
uses explicit UTF8 fixture bytes and adds a mixed-line-ending roundtrip, bringing
the product suite to 106 tests. The
[corrected run](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34178908410)
passed **all 12 jobs** on that exact commit. The six product jobs use Python
3.11/3.13 across Windows, macOS and Ubuntu. macOS executes all 106 tests; Windows
skips the POSIX-only injected-hook fixture and unavailable unsupported-Python
fixture; Ubuntu skips only the unavailable unsupported-Python fixture. Skips are
not counted as passed cases. All six legacy toolkit/demo jobs also passed.

Actual provider transport, independent recipient operators and same-project
mixed-OS TEAM-11 remain distinct requirements. Automated hosted OS actors are
labeled explicitly and do not count as independent human onboarding.

## Concurrent same-project HTTPS evidence, 2026-09-08

[Run 34179509646](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34179509646)
passed all four jobs at exact source commit
`b58ea168f4c18ef16db87dc69b64a454d48673c3`: one Linux coordinator and concurrent
macOS, Windows and Linux clients. These are automated hosted OS actors with
synthetic identities, not independent humans or live storage-provider clients.

All four reports agree on project identity, revision **3**, file hash
`91ebe9250283e0a8834d1e4551264b5742842c5840483af09650b79fc51c7461`,
and exact package SHA-256
`993434e0cf3305b717c719e123502cf19fa453f211c88fcdd94285e5d1fffaf2`.
The package was built once from the clean reviewed source and distributed with a
signed run/attempt/source rendezvous; clients verified identity and bytes before
execution. This does not claim byte-identical independent builds across OSes.

The run executed **99 packaged CLI calls**. Three proposals used revision zero;
the integration owner reviewed exact content, accepted all three and verified
compatible stale rebases. All clients verified exact materialized UTF8 bytes and
accepted receipts. The macOS to Windows to Linux handoff completed, and both
premature writes were rejected. Existing instructions, parent-vault notes, Obsidian
settings and local binary attachments remained byte-identical. Every report
records its task-owned processes stopped; the temporary testing tunnel ended.

The [same-commit twelve-job CI](https://github.com/Kian-hdr/shared-obsidian-workspace/actions/runs/34179509594)
also passed, retaining the 106-case suite and documented platform skips above.
The HTTPS run uses a temporary testing tunnel, not a persistent production service.
Provider delivery, independent operator onboarding, provider offline/recovery and
the rest of TEAM-11 remain open. The fixture is in
[`scripts/rehearse_distributed.py`](scripts/rehearse_distributed.py), with the
[bounded workflow](.github/workflows/team-integration.yml).

## Local pre-upload checkpoint 0.2.0, 2026-09-08

**105/105 product tests passed on macOS/Python 3.13.15 and 3.12.13**, no skips:
29 engine, 7 assignment-limit, 7 acceptance-boundary, 14 client, 3 offline-reconciliation,
14 maintenance, 23 legacy CLI compatibility and 8 packaged team CLI/loopback tests. These exercise real modules/processes and archived CLI
bytes. Independent review found and verified fixes for interrupted installation,
private migration exclusions, cross-project binding, malformed HTTP envelopes,
Git checkout hooks, cross-owner authority transfer and database hot-journal recovery.

- Concurrent processes contend for claims and revision acceptance. Conflicts preserve
  both proposals; responsible owners authenticate semantic decisions separately.
- Seven added actual acceptance subprocess-kill boundaries cover snapshot/state/
  proposal/conflict/event writes and before/after commit. Recovery preserves the
  prior state before commit; lost post-commit responses retry without a second
  accepted revision. This is selected application-boundary coverage, not filesystem
  internals or physical power-loss certification.
- Seven dependency/budget tests verify completion gating, exact proposal/file/UTF8
  byte limits and unchanged durable state on rejection. Three offline tests advance
  accepted context while a client is disconnected, then exercise compatible rebase,
  preserved conflict and deduplication using the original saved proposal base.
- Eight materialization interruption points preserve post-crash edits. A real killed
  SQLite writer left a hot DELETE journal; recovery restored exact accepted snapshot
  and event history. This goes beyond a caught-exception rollback test.
- The actual packaged Uvicorn 0.52.4 server passed **16 CLI commands** with a fixture
  TLS certificate/verified CA, authenticated recipient, exact revision receipt,
  handoff, completion and consistent backup. The fixture server was stopped.
- Ten added pagination/detail regressions verify bounded status and chronological
  event pages, authenticated exact detail retrieval, and integrity checks outside
  the requested page. Full chain verification still scales with history length.
- An independent agent followed the owner setup in a fresh nested-vault fixture:
  nine commands passed and all eight original files remained byte-identical.
- An earlier 0.2.0 source-versioned 1,000-note/10-member/50-revision synthetic local benchmark measured ~34 ms p95
  acceptance, ~175 ms receipt, ~1.14 s unchanged refresh and ~0.98 s first materialization.
  No production workload capacity or network latency guarantee is established.

Core/client are stdlib; optional server dependency pins are recorded separately.
TLS used two synthetic clients on the same Mac, not independent users/cloud storage.
Provider adapters verify local bytes in already-authorized folders; automatic access,
vendor API adapters, real upload/receipt, Windows/Linux execution and mixed-OS TEAM-11
remain unverified. Local facts/reviewer evidence do not prove arbitrary prose correct.
A separate attempt used the unsupported system Python 3.9 by mistake; packaged
commands correctly refused it. Its failed/skipped test log is preserved separately
and is not counted as supported-runtime evidence.
The old 0.1.0 and toolkit archives remain preserved; no live Vault migration, installed
skill upgrade, public source upload or repository rename was performed.

## Product CLI preview 0.1.0, 2026-09-08

The local executable preview bundles toolkit 1.3.0. It is not a stable Product V1
release and has not been published. All checks below ran on macOS.

- **23 packaged acceptance tests passed** on Python 3.13.15 and Python 3.12.13,
  with no skips. Tests build and execute the actual `.pyz`, including the installed
  unsupported Python 3.9 rejection, JSON envelopes, identity/hash checks, relocated
  joins and the real claim/change/handoff/accept/complete flow.
- Rejection cases preserve project bytes: invalid identity, changed package or
  tracker, unsafe archive paths, generated-path symlinks/type collisions, external
  home pointers, invalid actors and attempted project-root overrides.
- Six additional commands ran against the delivered package in a saved synthetic
  existing-vault fixture and relocated recipient copy. Three private parent/settings
  files stayed byte-identical. Shared mode correctly reported partial readiness.
- Every executable archive member was hash-checked against BUILD.json. Source and
  package identities are recorded with delivery evidence. Hashes detect mismatched
  bytes, not an independently authenticated publisher or actor.

The runtime still uses advisory coordination. No coordinator service, authenticated
membership, atomic proposal acceptance, provider adapter, live receipt or background
watcher is implemented. Windows/Linux execution, a clean recipient installation,
provider delivery and mixed-OS TEAM-11 remain unverified. Configured CI jobs have
not run for this candidate. See [the product guide](docs/PRODUCT-V1.md) and
[the acceptance roadmap](docs/READINESS.md).

## Local 1.3.0 candidate, 2026-09-08

This candidate is prepared locally from public revision
`3a48bf4c52af837d8c0a98c9adaefe3816ee8ca8`. It has not been published and its updated
CI workflow has not run on GitHub. Existing installations remain unchanged.

### Passed locally

- **56 workspace regressions** on macOS/Python 3.9.6 with PyYAML 6.0.3.
- **7 diagnostic regressions**, including no-write behavior, missing tracker in an
  existing workspace, missing canonical home, explicit local-only mode, no false
  remote receipt, and never executing target-supplied tracker code.
- Full demo using actual CLI commands, two fictional sequential actors, expected
  ownership/handoff rejection and exact-content checks. See the saved run report
  for individual outcomes. Plain-folder and nested existing-vault modes use the
  same core; neither launches Obsidian or an AI agent.
- Different vault-relative layouts accept byte-identical shared project files;
  parent private notes and configuration are preserved. The portable Base filter
  scopes to its own sibling Items folder in documented direct-open semantics.
- Recursive directory changes, files over 20 MiB, undeclared target drift and
  completion drift are detected. Rejected operations under regression leave
  records unchanged. Legacy hash-baseline review preserves immutable history.
- Skill validation and Git whitespace checks passed.

The demo's acceptance checks prove only its tiny synthetic outputs. Shared-folder
claims remain advisory. Directory hashing excludes Coordination/Items and rejects
symbolic links. Exact file hashes stream bytes; hashes do not authenticate actors
or prove semantic correctness. See [the schema](skills/setup-shared-project-workspace/references/record-schema.md).

### Remaining gates

No fresh-recipient installation, live independent-agent collaboration, provider
upload/receipt, two-device conflict handling, crash-recovery campaign, scale test,
or production certification is established. The 1.3.0 relative dashboard has
structural tests and official syntax support, but native populated rendering and
embedded/sidebar behavior were not verified. Open it directly in main content;
embedded/sidebar use is unsupported. Folder-only setup requires no GUI check.

The new GitHub workflow includes diagnostics and a demo in its OS/Python matrix,
but it is only configuration until the candidate is published and those jobs pass.
For adoption criteria see [the readiness roadmap](docs/READINESS.md).

### Upgrading

Review generated-file diffs and back up existing installations. Do not automatically
upgrade a teammate's live project while onboarding. Old active `directory` or
`too-large` baselines report drift until the owner reviews the actual contents and
records the new baseline with evidence. Legacy fixed-path dashboards need a reviewed
upgrade for different vault layouts. No historical records are silently migrated.


## Portability refactor 1.2.0, 2026-09-05

All **45 regression tests** passed locally on macOS with Python 3.9.6 and
PyYAML 6.0.3. The additional cases cover:

- Copying a workspace to a different local root and checking the recipient's files.
- Normalizing absolute in-project targets to relative paths and detecting overlapping
  absolute/relative claims, including a claim on the whole project.
- Rejecting external, home-relative, and parent-traversal targets without writes.
- Diagnosing legacy machine-specific work, event hashes, and project-home pointers
  without silently rewriting records.
- Reusing `Home.md`, requiring an in-project home, and using portable separators.
- Detecting an enclosing Git repository for nested projects.
- Detecting a changed vault layout and validating a reviewed dashboard update.
- Safely serializing dashboard folders containing Unicode, apostrophes, colons, and
  quotation marks. Characters invalid in Windows filenames use serialization tests.

The source and all four pre-refactor commits were inspected for personal account
addresses, private sharing links, and author-machine paths. None were found. The
actual portability defects were Drive-specific onboarding defaults and runtime
acceptance of machine-specific paths. The GitHub source URL and MIT copyright
attribution remain public project identifiers, not account or vault configuration.

The setup and teammate prompts now distinguish local-only, Git, shared-folder, and
hybrid access. Independent review checked that local-only needs no remote/account,
recipients use their own paths and identities, dependencies follow the selected
workflow, and authorized local installation still includes missing Obsidian and
Homebrew when chosen. Skill validation and documentation link, format, YAML, and
targeted private-reference checks passed.

Consult the [workflow runs](https://github.com/Kian-hdr/shared-memory/actions/workflows/test.yml)
for Linux, macOS, and Windows results on Python 3.9 and 3.13. A workflow definition
alone does not establish a passing run.

These tests do not prove fresh-machine installation, protected authentication,
Obsidian UI rendering, another person's access, or actual multi-device synchronization.
Existing installed skills and project-local trackers need a reviewed upgrade.
Legacy absolute-path records require explicit mapping and migration; the toolkit
does not automatically migrate them or clear their diagnostics by superseding them.

## Historical initial publication, 2026-09-04

### Passed locally

- All 31 bundled regression tests on macOS with Python 3.9.6 and PyYAML 6.0.3.
- Documentation smoke test in a disposable Obsidian-shaped project: unconfigured
  audit, no-write preview, retrofit, workspace validation, and repeat-run idempotence.
- Preservation of the copyable `AGENTS.md`, existing home note, and research note
  during that retrofit.
- Relative Markdown link checks and YAML syntax checks across the distribution.
- Byte-for-byte comparison of runtime scripts and dashboard assets with the installed skill.
- Targeted distribution scan for private local paths, project identifiers, and common
  credential patterns. This is a publication check, not a comprehensive security audit.

### Scope at initial publication

The packaged runtime scripts and dashboard are copied from the existing
`setup-shared-project-workspace` skill. Personal names in test fixtures and the record
schema example were replaced with generic identities. The installed source skill
was not modified. The repository adds general vault instructions, distribution
documentation, an MIT license, development requirements, and CI configuration.

### Limits at initial publication

Local tests do not establish cross-device locking, provider upload, another person's
access, or real-time synchronization. Obsidian dashboard rendering and Windows
PowerShell instructions were not manually exercised during this publication pass.

The GitHub Actions workflow runs the bundled Python tests on Linux, macOS, and Windows
with Python 3.9 and 3.13. Consult the actual workflow run for its current result;
the existence of the workflow file is not evidence that those jobs passed.

## Historical local setup instruction update, 2026-09-04

The setup prompt, teammate prompt, skill entrypoint, and supporting documentation
now authorize required local dependencies and configuration, including missing
Homebrew when chosen, Obsidian installation/launch, and opening the correct vault.
An independent scenario review covered a fresh machine, installation preferences,
missing PATH entries, Markdown-only use, unsupported platforms, and enforced
approval/authentication gates. The skill validator and documentation link/format
checks passed. Runtime scripts and dashboard assets were unchanged.

The revised skill guidance was also synchronized to the maintainer's installed
skill after preserving its previous instruction files. No fresh-machine installer,
administrator/authentication flow, or recipient app launch was executed for this update.
