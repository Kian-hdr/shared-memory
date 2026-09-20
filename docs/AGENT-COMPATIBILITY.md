# Agent compatibility and context budget

Shared Memory stores ordinary Markdown. Use native search/read/edit tools and a
small INDEX; runtime setup, history and recovery are separate operations. Automatic
capture runs outside the model. It removes sync tool calls, not tokens spent reading
notes, reasoning or editing. `--brief` bounds routine output; full diagnostics remain
available without it. Byte/word reductions do not establish a GLM token count.

## Host integration

- OpenCode supports on-demand [skills](https://opencode.ai/docs/skills/) including
  ~/.agents/skills, and [plugins](https://opencode.ai/docs/plugins/) with host events.
  The OS capture job needs neither model-generated commands nor host-specific hooks.
- [MCP tools consume context](https://opencode.ai/docs/mcp-servers/). No MCP is
  required here; avoid duplicating native file tools with a memory tool catalog.
- Other agents need access to the selected files. Their permissions and provider
  protocols still apply. File-format compatibility is not proof that every model
  generates valid tool calls.

## GLM diagnosis

Separate process launch, runtime path rejection, invalid model arguments and provider
protocol failures. A runtime error after a successful command launch is not evidence
that GLM cannot use memory. A model may also confuse a project UUID with its folder
path; automatic capture binds the real folder once instead of asking it each turn.

Z.ai's [function calling](https://docs.z.ai/guides/capabilities/function-calling)
supports auto tool choice; its [thinking protocol](https://docs.z.ai/guides/capabilities/thinking-mode)
requires preserving reasoning across tool turns. [Coding Plan setup](https://docs.z.ai/devpack/tool/opencode)
is distinct from standard API access. [OpenRouter provider routing](https://openrouter.ai/docs/guides/routing/provider-selection)
can vary provider capabilities. Shared Memory does not replace these host adapters.

For live acceptance, use a synthetic nonprivate workspace: native read, targeted
edit, capture, then a fresh-session recall. Record client/model/provider, filesystem
result and usage separately. Never infer live provider success from unit tests.

## Skill comparison (2026-09-20)

The existing setup skill was retained and shortened after inspecting full candidate
skills. Anthropic's [memory-management](https://github.com/anthropics/knowledge-work-plugins/blob/main/productivity/skills/memory-management/SKILL.md)
has useful tiered lookup but introduces a separate CLAUDE.md/memory store. ArcticZvan's
[project-memory](https://github.com/ArcticZvan/project-memory/blob/main/SKILL.md)
uses .cursor/memory and daily startup reads. Basic Memory's
[memory-notes](https://github.com/basicmachines-co/basic-memory-skills/blob/main/memory-notes/SKILL.md)
requires another MCP service and conventions. These were not installed or copied:
targeted retrieval fits here without a second memory system or extra tools.

## Measured validation, 2026-09-20

Using `tiktoken 0.14.0` / `o200k_base` as a reproducible reference tokenizer:
setup prompt 1,066 → 307 tokens (71.2% reduction); setup skill 821 → 342 (58.3%).
A synthetic status with 5,000 note heads and 5,000 exclusions drops from 128,022
reference tokens to 32 with brief output. These are text measurements, not GLM
billing savings or a before/after measurement of complete agent sessions.

OpenCode 1.18.30 with both `zai-coding-plan/glm-5.3` and
`openrouter/z-ai/glm-5.3` passed a synthetic native-tool workflow: read INDEX, read
one Wiki note, append the required decision, then recall it in a fresh session.
Actual file bytes and fresh-session answers were verified. Tests used isolated
configuration and native read/edit tools, without shell or external-directory access.
This proves the tested native workflow, not arbitrary global configurations or
cross-device synchronization. Runtime/capture validation is separate.

## Selective reuse rather than another memory stack

We retained deterministic capture outside the LLM, keyword-first targeted retrieval,
progressive fetching, and bounded source-linked excerpts. When identical excerpts
repeat, return their text once with all source paths. These patterns need no second
canonical store, extraction/reflection model call, or copied third-party component.

A bounded synthetic comparison (2,000 files, 6.71 MB, 50 exact queries) found native
rg at 33.14 ms median and persistent SQLite FTS5 at 0.045 ms, both 50/50 correct.
However FTS returned 153 bytes per result versus 83 for bounded rg. Full indexing
cost 106.20 ms; a known-path update 2.73 ms; change-discovery stat scanning 21.49 ms;
the derived index occupied 9.58 MB. No model calls were used. Warm-cache conditions
and SQLite's persistent process favor its latency result. This does not measure
semantic recall or production workloads. An index is deferred: this evidence does
not justify extra lifecycle/staleness complexity for improved speed AND tokens.
A 20-copy constructed excerpt example shrank 1,810 to 350 bytes by deduplicating
text while keeping every source path; that is illustrative, not production savings.

No Hindsight, Basic Memory or Graphiti code was incorporated. Future component reuse
must inspect pinned code, dependencies and license, preserve source provenance and
invalidate changed/deleted inputs. Markdown stays authoritative; any future index
must remain private and rebuildable. Include creation/indexing/background costs in
comparisons, not only foreground query time or vendor headline benchmarks.
