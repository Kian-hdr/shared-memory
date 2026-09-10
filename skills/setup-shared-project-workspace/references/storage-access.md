# Discover actual folder access

Use the existing provider and the user's actual local copy. Choose one provider per
folder; do not bridge Google Drive, iCloud, OneDrive and Nextcloud or infer account
access from a repository download. Local-only requires no account. Check read/write
rights separately from whether a local file is writable. Never override read-only
configuration merely to complete synchronization.

For offline work, retain real local files using the chosen provider's documented
option. Google Shared Drives stream rather than mirror; streamed files need explicit
offline availability. Apple and Microsoft expose keep-downloaded/always-available
controls. Nextcloud is the first self-hosted alternative to evaluate when none is
already chosen, with server maintenance owned by the operator.

- [Google desktop modes](https://support.google.com/drive/answer/13401938?hl=en)
- [iCloud offline files on Mac](https://support.apple.com/en-gb/guide/mac-help/mchl1a02d711/mac)
- [OneDrive local synchronization](https://support.microsoft.com/en-US/onedrive/sync-your-computer-s-files-and-folders-with-onedrive)
- [Nextcloud desktop folder connections](https://docs.nextcloud.com/server/stable/user_manual/en/desktop/usage.html)

Nextcloud's conflict copies are not uploaded by default. Preserve and capture them
locally before cleanup; a remote copy may not contain the edit yet.
[Nextcloud conflicts](https://docs.nextcloud.com/server/stable/user_manual/en/desktop/conflicts.html).

Verify that the complete shared metadata/history arrives on the recipient, including
any hidden names. A local `sync` result or green provider icon alone is not an
independent recipient receipt. Record what was actually transferred and which
provider/device checks remain unrun. Do not deploy a server during an unrelated
folder setup; use an existing service or the user's explicit deployment scope.
