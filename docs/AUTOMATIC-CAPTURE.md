# Automatic local history capture on macOS

A selected existing format-3 folder workspace can capture edits every 60 seconds
without calling a model or asking an agent to construct a shell command. Editors
continue saving ordinary files. Capture records observed changes and reconciles
history; it does not extract knowledge from conversations, upload provider files,
prove remote receipt, or establish factual agreement.

The installer uses a per-user LaunchAgent with absolute Python and runtime paths,
a `ProgramArguments` array, `StartInterval`, and no shell or persistent AI process.
The script is copied into private Application Support so moving the checkout does
not break the service. The installed Python interpreter and `.pyz` must remain at
the configured paths. Install once per selected workspace on each editing Mac.

## Prepare and install

Use the actual physical paths of the installed compatible runtime, Python 3, the
selected workspace and its existing private state. No setup, migration or new
identity is performed. The state argument is the same one used successfully by
`sync`; a legacy connection wrapper's `folder/` binding is detected.

```sh
python3 scripts/install_capture.py '/absolute/selected workspace' \
  --state-dir '/absolute/private state' \
  --runtime '/absolute/installed/shared-memory.pyz' \
  --python '/absolute/python3' \
  --sha256 '<independently verified runtime digest>'
```

Without flags this prints a plan and makes no changes. Repeat with `--install` to
install and load it. `--interval 30` through `--interval 3600` changes the cadence;
60 seconds is the default. Installation requires macOS and a logged-in GUI session.
The expected digest must come from a verified build/release record; merely hashing
an untrusted download does not establish authenticity. Every run checks the
runtime SHA-256 and refuses unexpected replacement. The installer also verifies the runtime's `folder-status --brief` response before
changing configuration. Read-only bindings, wrong identities, symlink paths and
private state inside the selected workspace are refused. Private state must also
stay outside other cloud-provider roots; known CloudStorage, iCloud, OneDrive, Google Drive, Dropbox, Nextcloud
and Box path names are rejected, but arbitrary provider locations cannot be inferred automatically.

The LaunchAgent plist lives in `~/Library/LaunchAgents`. Its private configuration,
runner and latest result live under
`~/Library/Application Support/Shared Memory/Capture/<workspace-path-hash>/`.
Configuration and results are owner-readable/writable; the capture directory is
owner-only. No credentials or file contents are included in the configuration.
Previous changed configuration/runner/plist versions are retained in that private
directory. Repeating installation uses the same label, rather than creating a
second job. History and the underlying private device state remain untouched.

## Inspect, repair and stop

Run `python3 scripts/install_capture.py '/absolute/selected workspace' --status` to inspect whether launchd has loaded the job
and read the latest result. A loaded job does not prove the last sync succeeded;
check `last_result.ok`, its timestamp, and readiness. Status exits zero only when
the job is loaded and the latest capture is successful, ready, and recent. It exits
2 when missing, stale, failed, unloaded, or requiring attention. A missing result means no
completed run has been recorded. Errors are stored in `last-result.json`, whose
error details are bounded and replaced on the next run, not appended indefinitely.
Missing interpreter/runner failures can prevent that result from updating; inspect
`launchctl print gui/$(id -u)/<label>` using the exact label returned by the plan.

Use the same project-only command with `--uninstall` to unload the selected job and move its plist into private
recovery. This preserves shared history, private baselines, the runner and the last
result. Other jobs are not touched. Status and uninstall read the saved private configuration, so they remain available
even if the runtime, workspace or state files have disappeared. Keep the original
workspace path argument to identify its installation.

A run holds a nonblocking private lock in addition to launchd's per-job scheduling;
the runtime still applies its normal folder locks. Runs time out after five minutes
and report failure. A nonzero runtime exit, malformed JSON, or `ok: false` cannot
be reported as successful capture. A successful runtime response with partial
readiness retains `ok: true` (the command completed), sets `attention_required`,
and makes the runner exit 2. Installation success means the job was loaded; it does
not certify that a capture has finished. When the Mac sleeps or the user logs out,
capture is not continuous. After the next successful run, inspect readiness when
conflicts or provider arrivals need attention. On non-macOS systems this installer
only prepares a plan; use the ordinary compatible sync command or a separately
configured platform scheduler.

Design references: Apple's [Creating Launch Daemons and Agents](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)
and [Scheduling Timed Jobs](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html).
