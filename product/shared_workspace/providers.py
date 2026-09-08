"""Read-only provider capability and exact local receipt checks.

The selected provider remains responsible for delivery and access. These adapters
inspect bytes in an already-authorized local folder; they never sign in, share,
invite, install a client or infer remote receipt from a folder name.
"""
from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

from .errors import ProductError

PROVIDERS = ("local", "self-hosted", "google-drive", "onedrive", "icloud")
SOURCES = {
    "google-drive": "https://support.google.com/drive/answer/2375082",
    "onedrive": "https://support.microsoft.com/en-US/onedrive/onedrive-system-requirements",
    "icloud": "https://support.apple.com/en-us/108922",
}


def capabilities(provider, account_type="unspecified", system=None):
    if provider not in PROVIDERS:
        raise ProductError(3, "provider_unknown", "Select a documented provider route.")
    system = system or platform.system()
    local_route = provider in {"local", "self-hosted"} or system in {"Darwin", "Windows"}
    return {"provider": provider, "account_type": account_type, "os": system,
            "route": "authorized_local_folder" if local_route else "unsupported_vendor_desktop_route",
            "adapter": "read_only_snapshot_receipt",
            "implemented_local_operations": ["inspect", "verify_expected_snapshot"],
            "automatic_access_or_delivery": False,
            "provider_receipt": "not_applicable" if provider == "local" else "unverified",
            "product_support": "local_checks_only" if local_route else "blocked",
            "required_checks": [] if provider == "local" else ["account_and_policy", "client_or_mount_version", "authorized_recipient", "actual_delivery", "offline_recovery"],
            "api_adapter": "rclone_immutable_revision_development" if provider == "google-drive" else "not_implemented",
            "explicit_delivery_route": "google_drive_rclone" if provider == "google-drive" else None,
            "explicit_delivery_live_acceptance": "not_run",
            "report_scope": "existing_local_folder_inspection; explicit delivery is a separate command",
            "official_source": SOURCES.get(provider),
            "sources_checked": "2026-09-08", "mixed_os_team_gate": "not_run"}


def verify_receipt(root, snapshot, provider, account_type="unspecified"):
    """Read exact files without refresh/materialization; delivery source unproven."""
    root = Path(root).resolve()
    if not root.is_dir():
        raise ProductError(5, "provider_folder_missing", "Choose the actual existing authorized local folder.")
    files = snapshot.get("files")
    if not isinstance(files, dict):
        raise ProductError(3, "snapshot_invalid", "Expected a coordinator snapshot.")
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()
    if snapshot.get("files_hash") != digest:
        raise ProductError(3, "snapshot_invalid", "Expected snapshot hash is invalid.")
    mismatches = []
    for relative, text in files.items():
        parts = Path(relative).parts
        if (not isinstance(relative, str) or not parts or Path(relative).is_absolute()
                or ".." in parts or "\\" in relative):
            raise ProductError(3, "snapshot_invalid", "Unsafe snapshot path.")
        path = root / relative
        if any(parent.is_symlink() for parent in [path, *path.parents] if parent != root.parent):
            raise ProductError(3, "provider_path_unsafe", "Symlinks cannot establish accepted-file receipt.")
        if not path.resolve().is_relative_to(root):
            raise ProductError(3, "provider_path_unsafe", "Receipt path escapes the selected folder.")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(text.encode()).digest():
            mismatches.append(relative)
    report = capabilities(provider, account_type)
    report.update(project_id=snapshot["project_id"], revision=snapshot["revision"], files_hash=digest,
                  local_receipt="verified" if not mismatches else "mismatch", mismatches=mismatches,
                  readiness="ready" if provider == "local" and not mismatches else "partial")
    if report["product_support"] == "blocked" or mismatches:
        report["readiness"] = "blocked" if report["product_support"] == "blocked" else "partial"
    return report
