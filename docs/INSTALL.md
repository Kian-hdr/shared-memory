# Install or update 0.4.0

This is setup reference, not routine agent context. Preserve the selected workspace,
private state and previous runtime. Python 3.11+ is required. Download the versioned
runtime and SHA256SUMS from [v0.4.0](https://github.com/Kian-hdr/shared-memory/releases/tag/v0.4.0).
Verify the runtime SHA-256 against its external SHA256SUMS entry before execution.
If unavailable or mismatched, stop installation; do not substitute an unverified asset.

Use the verified package's `version` and `install-package --help`, then:

```text
python3 shared-memory-0.4.0.pyz install-package shared-memory-0.4.0.pyz --sha256 VERIFIED_SHA --tools-dir PRIVATE_TOOLS
```

Substitute actual discovered paths and checksum. Use the returned immutable package
for `setup PROJECT` and subsequent commands. Existing format-3 projects retain their
private state; supply `--state-dir` only when required by their existing binding.
For old formats, read the [migration guide](PRODUCT-V1.md) before proceeding.
New empty folders get Raw/Wiki/Output; populated folders are not reorganized.

The versioned source kit includes a POSIX launcher installer (macOS/Linux) and a
macOS automatic-capture installer. On native Windows, invoke the verified package
with Python directly; this release does not install a Windows command shim.

```text
python3 scripts/install_command.py --runtime INSTALLED_PACKAGE --sha256 VERIFIED_SHA
python3 scripts/install_capture.py PROJECT --state-dir PRIVATE_STATE --runtime INSTALLED_PACKAGE --sha256 VERIFIED_SHA --install
```

The second installs a macOS user LaunchAgent. Read [automatic capture](AUTOMATIC-CAPTURE.md)
for status, recovery and removal. Other systems can continue with native edits and
one manual sync; an automatic Windows/Linux service is not supplied in this release.
Use the host's existing private scheduler if separately configured and verified.

Install the skill directory from the verified skill ZIP in a supported skill path,
preserving any prior copy. Codex uses ~/.codex/skills; OpenCode also supports
~/.agents/skills. Do not duplicate the same name across its discovery paths.
The skill is for setup/repair, not a prerequisite for ordinary note edits.

The default command location is ~/.local/bin/shared-memory. Use its absolute path
if that directory is absent from PATH. From the selected workspace, `shared-memory
sync` defaults to the current folder and brief output. `--full` restores complete
sync/status diagnostics. Direct `.pyz` calls retain full output unless `--brief` is
requested. Never pass a project UUID where a folder path is expected.

Check the job's latest result and confirm a bounded edit appears in history. Report
local capture separately from remote provider delivery. Roll back with the runtime's
`rollback-package` command, then reinstall the launcher/capture job pointing at the
chosen verified package. Runtime rollback does not erase or downgrade history.
