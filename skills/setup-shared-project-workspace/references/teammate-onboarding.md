# Teammate onboarding prompt

After normal folder setup, provide a short prompt in chat when the task involves
sharing. Fill it with observed compatible package source, project identity and the
actual chosen provider/folder access route. Do not include credentials or sender-only
private paths. Mark missing access as missing; a prompt does not grant permissions.

The recipient's agent should verify the package, locate that recipient's own local
copy, inspect existing metadata, retain private local state and run ordinary setup.
It should not initialize a second project, request a coordinator token for folder
mode or create another cloud service. Direct edits persist offline; run sync after
edits and after reconnect, preserving conflict copies and recording resolution evidence.

Use language like the following, replacing only details that have been verified:

```text
Set up the existing Shared Memory project available through the folder access
instructions supplied with this message. Verify the specified compatible runtime
and its external checksum, then locate my own local copy and inspect its metadata.
Use the normal direct-edit folder workflow, preserving existing notes, permissions
and private parent folders. Keep my baseline/recovery state private and preserve
shared history. After changes or reconnect, sync and report any unresolved conflicts.
Do not copy another user's private state or create an unrequested coordinator.
```

Add the verified package and access details above this block. If either is missing,
state that explicitly. Existing coordinator formats follow their historical guide
until migrated with backup. Send no invitation or message automatically merely because
the prompt is ready.
