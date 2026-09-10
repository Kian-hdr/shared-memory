# Everyday collaboration

Edit the selected project's notes directly with your existing editor or agent.
Saving works offline. Optional reviews happen afterward; no permanent integrator,
proposal acceptance or hidden approval step is part of normal folder mode.

1. Read the relevant instructions and notes. Inspect `folder-status` and any provider
   warnings. Coordinate overlapping work with other active editors when practical.
2. Make the intended edits, preserving unrelated content and links. Run `sync` to
   capture observed bytes and reconcile delivered history.
3. After reconnect or provider delivery, sync again. Keep local provider conflict
   copies until the edits are recorded and their resolution is checked.
4. Review factual disagreements deliberately. Compatible line merges do not prove
   semantic consistency. An authorized editor can record a resolution with evidence.
5. Report actual local results and any outstanding conflict, missing delivery or
   review need. A local ready status is not a receipt from every other computer.

See [exact commands](PRODUCT-V1.md), [provider guidance](PROVIDERS.md), and the
[workflow diagrams](DIAGRAMS.md). `watch` is an optional bounded capture loop, not an
always-online AI or review service. Capture labels identify the observer, not
necessarily the human who originated a provider-delivered edit.

Use explicit delete/rename operations when intended. Rename preserves history but
does not rewrite backlinks; review those links and sync corrections separately.
Keep private baselines and credentials outside the shared folder, while transporting
its complete portable event history through one chosen provider. Preserve provider
ACLs and explicit read-only bindings.

A project may be one selected subfolder inside each contributor's private Obsidian
vault. Do not share its parent or configure a new vault merely to collaborate.
Nested trackers retain their own existing authority; folder editing does not acquire
claims in an independent project tracker.

## Historical projects

A format-1/2 coordinator project retains its own claim/session/proposal rules until
explicit backed-up migration. Consult the [coordinator manual](COORDINATOR-WORKFLOW.md)
for that route. The advisory toolkit is separately documented under
[legacy setup](SETUP.md#legacy-advisory-tracker-setup). Those rules are not mandatory
steps for a format-3 direct-edit project.
