# Shared Memory authoritative product route

Use this route when the user requests the Shared Memory product or supplies a
reviewed product `.pyz`, rather than the historical advisory Markdown tracker.
Do not silently substitute a legacy toolkit for an unavailable product package.

The experimental prerelease is **v0.2.0-alpha.1**, with runtime version **0.2.0**.
Use a disposable project or backed-up working copy for an initial trial. Select
`shared-memory-0.2.0-alpha.1.pyz` and its entry in external `SHA256SUMS` only when
present on the [release page](https://github.com/Kian-hdr/shared-memory/releases/tag/v0.2.0-alpha.1).
Verify downloaded bytes before execution, then run `version`, `capabilities` and
`guide`. Read the operating guide bundled with that exact artifact. If assets are
absent, ask for the intended reviewed package/source; do not run arbitrary latest
source. The package contains the engine; this skill folder alone does not.

Use Python 3.11+ for the product. `install-package` retains exact verified archives
under a private tools directory and returns the immutable installed path; use that
path for later commands. It does not install Python, add a global command or deploy
a server. The optional complete skill archive must preserve its directory structure
and any existing installation during review.

- `init` creates one authority for a new selected folder; `attach` joins an existing
  expected project with the recipient's own token and local paths. Never bootstrap
  during join. Existing private parent-vault files and `.obsidian` remain untouched.
- Private non-synced local state holds SQLite, tokens, connection settings and drafts.
  Shared files hold readable accepted text and portable `.shared-memory.json` metadata.
  Obsidian is optional. Local-only uses Python without a server/account; team serving
  needs separately authorized deployment and the package's optional server dependencies.
- `refresh`, `team-status`, `context` and `receipt` establish local accepted context.
  Claim bounded assignments, `draft` with a base revision/evidence, `submit`, then
  let the integration owner review and accept. In explicit schema 2, create your
  own session and use plan/acquire with its receipt, lease and immutable draft context.
  Existing schema-1 projects retain their claim workflow. Conflicts preserve both proposals;
  structured factual disputes need the responsible owner's authenticated decision.
  Arbitrary Markdown still requires semantic review by the human/agent.
- Offline drafts survive outages. Preserve recovery journals/history; use documented
  `promote-draft`, `recover-coordinator` and backup procedures instead of deletion.
- Generate `team-prompt` after successful owner setup; put the returned prompt in
  chat with real approved package/access locators. Clearly mark missing access details;
  local setup does not make an incomplete invitation ready. Credentials use a separate private
  channel. Do not send invitations or imply provider receipt from local checks.
- Runtime updates use exact reviewed package installation/rollback. Joining never
  silently migrates schemas or upgrades an owner's tracker. Live Vault migration
  requires explicit backup/working-copy/target confirmation and its separate scope.

Follow existing authorization for routine local setup without repeated permission
requests. Provider permissions, credentials/protected sign-in, messages, deployment,
publication and purchases remain their actual gates. Report unsupported OS/provider
combinations and incomplete live/mixed-device checks rather than calling them ready.

Experimental publication does not establish stable V1. Distinguish automated OS/HTTPS
fixtures from independent recipients, actual provider delivery and persistent operations.
The product is an independent folder runtime; no native app or hosted service is included.
