---
name: setup-shared-project-workspace
description: Set up, update or repair Shared Memory in a selected Markdown folder. Ordinary note work uses native file tools; load this skill only for setup or troubleshooting.
---

# Shared Memory

People and agents read and edit ordinary Markdown. Obsidian is optional. Use native
file tools; routine memory work does not require generated scripts or model-specific
APIs. Read the project's INDEX and relevant notes only. Update existing canonical
notes with durable facts, decisions and progress; retain evidence and uncertainty.

## Setup or update

Read [runtime setup](references/product-runtime.md). Discover the selected folder,
existing format, installed runtime and private state. Verify release checksums before
execution. Preserve project identity, history, instructions and unrelated files.
Only an empty new workspace receives Raw/, Wiki/, Output/, AGENTS.md and INDEX.md.
Never reorganize a populated workspace automatically.

Install a stable `shared-memory` command and optional automatic capture once, outside
shared storage. [Agent integration](references/agent-integration.md) explains the
small routine contract. Automatic capture works independently of the model; host
permissions still apply. Without it, run one `sync PROJECT --brief` after edits.
On failure, preserve saved notes and report the capture gap once; do not retry or
reinstall repeatedly. Load detailed command help only for the operation needed.

Keep private state and credentials outside shared storage. One provider per folder;
local capture does not prove delivery. Preserve conflicts and read-only boundaries.
Use explicit rename/delete operations and check backlinks. Formats 1/2 require the
backed-up migration in the runtime reference; never reset their authority.
