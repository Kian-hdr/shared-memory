# One provider for one shared folder

Use the provider already chosen for the project. Shared Memory records and reconciles
local Markdown history; the provider moves files between authorized computers.
It does not translate accounts, bridge clouds, replace provider permissions or
provision a service automatically. The checks below were researched on 2026-09-10;
they are provider guidance, not a record of completed Shared Memory device trials.

## Supported route to evaluate

| Provider | Local files and offline work | Important boundary |
| --- | --- | --- |
| Google Drive | Use Drive for desktop's local files and explicitly retain what is needed offline. My Drive can mirror; Shared Drives stream. | A streaming placeholder is not proof the actual bytes are available. |
| iCloud Drive | Keep the project downloaded on Mac, or pin it with iCloud for Windows. | Confirm the actual folder invitation and edit/view permission; account ownership alone is not a share. |
| OneDrive | Work in the synchronized folder and retain offline files explicitly. | Online-only files and Files On-Demand need inspection before disconnected work. |
| Nextcloud | Use an existing operator-managed service with its desktop folder synchronization. | Include shared metadata/history, inspect ignore rules, and preserve local conflict copies. |

Google documents that My Drive can stream or mirror, while Shared Drives can only
stream. Mirrored files remain local; streamed items require explicit offline
availability. Discover the actual drive type rather than instructing every recipient
to mirror a shared drive. [Google Drive desktop modes](https://support.google.com/drive/answer/13401938?hl=en).

Apple provides **Keep Downloaded** on Mac and **Always keep on this device** in
iCloud for Windows. Its shared-folder permissions distinguish editing from viewing.
These are Mac/Windows routes; a generic filesystem API does not establish an
unsupported desktop client route on another OS.
[Mac offline files](https://support.apple.com/en-gb/guide/mac-help/mchl1a02d711/mac),
[Windows pinning](https://support.apple.com/en-ie/guide/icloud-windows/icw8531ad6b7/icloud),
[iCloud permissions](https://support.apple.com/guide/icloud/manage-sharing-for-files-and-folders-mm59dd13d0be/icloud).

OneDrive synchronizes changes in its folder with the service, including deletions.
Its always-available files are distinct from online-only items. Keep offline project
bytes present, and do not use a provider's remove-download operation as a Shared
Memory deletion instruction.
[OneDrive synchronization](https://support.microsoft.com/en-US/onedrive/sync-your-computer-s-files-and-folders-with-onedrive),
[offline availability indicators](https://support.microsoft.com/en-gb/office/work-with-synced-files-in-file-explorer-8d9b1c45-4a3f-4fa8-a55b-fd0635e77d4d).

## First self-hosted choice: Nextcloud

**Recommendation: evaluate Nextcloud first when the project needs a self-hosted
alternative and has no existing suitable provider.** This is a fit decision, not a
claim that it is faster, safer or already deployed. Its documented desktop clients
cover Windows, macOS and Linux, with folder sync connections, sharing controls and
visible connection/ignore status. An existing Nextcloud operator can expose one
selected project share without adding a Shared Memory coordinator.
[Desktop and server requirements](https://docs.nextcloud.com/server/stable/admin_manual/installation/system_requirements.html),
[desktop folder synchronization](https://docs.nextcloud.com/server/stable/user_manual/en/desktop/usage.html).

Operating Nextcloud still requires a maintained server, appropriate database/storage,
HTTPS, backups and updates. Those are a chosen service's operational responsibilities;
local Shared Memory setup does not silently create them. A hosted Nextcloud provider
is also a possible delivery choice. Exact account terms, capacity and support need
the selected operator's current information, not an invented free hosting promise.

Seafile is a viable alternative, especially where the team already uses its
library-based synchronization. Its client synchronizes a library with a local
folder, and it preserves competing edits as conflict files. Its read-only sync
behavior can allow a user to modify a local copy while refusing to upload that edit,
so local file writability must not be mistaken for remote write permission.
For this first route, prefer Nextcloud's documented folder connection workflow and
keep one provider; do not deploy both or add a bridge merely for comparison.
[Seafile library sync](https://help.seafile.com/syncing_client/install_sync/),
[Seafile conflicts](https://help.seafile.com/syncing_client/file_conflicts/),
[Seafile read-only sync](https://help.seafile.com/syncing_client/read-only_syncing/).

## Conflict copies must survive reconnect

Nextcloud normally keeps the locally conflicting version in a separate conflict
file and downloads the remote version to the original path. Its documentation says
that the conflict copy is **not uploaded by default**. Other recipients may therefore
be missing the only copy of someone's edit. Capture and inspect these local copies
before deleting, renaming or relying on remote receipt. Do not silently enable
experimental provider flags to make a status indicator turn green.
[Nextcloud conflict handling](https://docs.nextcloud.com/server/stable/user_manual/en/desktop/conflicts.html).

The provider may also ignore names or directories. Check that the complete Shared
Memory metadata/history is actually synchronized. Do not infer this from the parent
folder's green icon, and do not globally disable provider ignore rules: they may
protect unrelated files. Hydrated files and safe physical paths remain subject to
the runtime's actual filesystem checks.

## Evidence for a real provider route

Record the provider/client versions, operating systems and intended read/write
permissions. Verify the selected folder and history are present on each recipient;
compare actual bytes and event/history identifiers after upload and download.
Then exercise offline editing, reconnect, concurrent compatible changes, conflicting
changes, provider-generated copies, deletion/rename, permission refusal and restart
recovery. Keep exact synthetic evidence separate from private account details.

A local fixture can verify the merge, event and recovery logic. It cannot prove a
provider transported the files, included hidden metadata, retained a conflict copy,
or delivered the result to an independent physical recipient. No real Google Drive,
iCloud, OneDrive, Nextcloud or Seafile acceptance is asserted by this guide.
