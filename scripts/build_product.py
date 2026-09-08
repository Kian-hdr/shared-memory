#!/usr/bin/env python3
"""Build a self-contained product zipapp without downloads or installation."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PRODUCT_VERSION = "0.2.0"
TOOLKIT_VERSION = "1.3.0"
BOOTSTRAP = r'''import hashlib
import json
import sys
import zipfile


def fail(code, message, exit_code):
    print(json.dumps({"schema_version": 1, "product_version": "0.2.0",
                      "command": sys.argv[1] if len(sys.argv) > 1 else "",
                      "ok": False, "code": code, "message": message,
                      "data": {}, "warnings": []}))
    raise SystemExit(exit_code)


if sys.version_info < (3, 11):
    fail("unsupported_runtime", "Shared Memory requires Python 3.11 or newer; use a maintained Python such as 3.13.", 2)
try:
    with zipfile.ZipFile(sys.argv[0]) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            fail("bundle_integrity", "Duplicate archive members.", 3)
        build = json.loads(archive.read("BUILD.json"))
        files = build["files"]
        if set(names) != set(files) | {"BUILD.json"}:
            fail("bundle_integrity", "Archive members differ from build manifest.", 3)
        identity = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if identity != build["bundle_id"]:
            fail("bundle_integrity", "Bundle identity mismatch.", 3)
        for name, digest in files.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                fail("bundle_integrity", "Bundle content mismatch: " + name, 3)
except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
    fail("bundle_integrity", "Cannot verify reviewed bundle: " + str(exc), 3)

from shared_workspace.cli import main
raise SystemExit(main())
'''


def build(output: Path, *, source_files: dict[str, bytes] | None = None,
          source_revision: str | None = None) -> dict:
    """Build working development inputs, or an explicitly verified source map.

    Release callers supply the complete immutable HEAD blob map and its revision
    after validating the checkout. That path never reads payload bytes from disk.
    """
    if output.exists():
        raise ValueError("Refusing to replace an existing output; choose a fresh artifact path.")
    if not output.parent.is_dir():
        raise ValueError("The output parent directory must already exist.")
    if (source_files is None) != (source_revision is None):
        raise ValueError("Verified source bytes and their revision must be supplied together.")
    inputs = {}
    if source_files is None:
        eligible = set(subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT).decode().split("\0"))
        modules = ROOT / "product/shared_workspace"
        skill = ROOT / "skills/setup-shared-project-workspace"
        for source in sorted(modules.rglob("*.py")):
            if source.relative_to(ROOT).as_posix() not in eligible:
                continue
            if source.is_symlink():
                raise ValueError("Source symlinks are not package inputs.")
            inputs[source.relative_to(ROOT).as_posix()] = source.read_bytes()
        for source in sorted(skill.rglob("*")):
            if source.relative_to(ROOT).as_posix() not in eligible:
                continue
            if "__pycache__" in source.parts or source.suffix in {".pyc", ".pyo"}:
                continue
            if source.is_symlink():
                raise ValueError("Skill symlinks are not package inputs.")
            if source.is_file():
                inputs[source.relative_to(ROOT).as_posix()] = source.read_bytes()
        for name in ("LICENSE", "docs/PRODUCT-V1.md", "docs/KNOWLEDGE-GRAPH.md", "requirements-server.txt"):
            inputs[name] = (ROOT / name).read_bytes()
    else:
        for name, data in source_files.items():
            if (not isinstance(name, str) or not name or name.startswith("/") or "\\" in name
                    or any(part in {"", ".", ".."} for part in name.split("/")) or not isinstance(data, bytes)):
                raise ValueError("Verified source map requires relative POSIX paths and exact bytes.")
        inputs = dict(source_files)
    if any(name not in inputs for name in ("product/shared_workspace/cli.py", "product/shared_workspace/__init__.py")):
        raise ValueError("Product implementation is incomplete: cli.py and __init__.py are required.")
    payload = {"__main__.py": BOOTSTRAP.encode("utf-8")}
    for name, data in sorted(inputs.items()):
        if name.startswith("product/shared_workspace/") and name.endswith(".py"):
            payload[name.removeprefix("product/")] = data
        elif name.startswith("skills/setup-shared-project-workspace/"):
            if "__pycache__" not in name.split("/") and Path(name).suffix not in {".pyc", ".pyo"}:
                payload["bundle/" + name] = data
    for destination, source in (("LICENSE", "LICENSE"), ("PRODUCT-GUIDE.md", "docs/PRODUCT-V1.md"),
            ("KNOWLEDGE-GRAPH.md", "docs/KNOWLEDGE-GRAPH.md"), ("requirements-server.txt", "requirements-server.txt")):
        payload[destination] = inputs[source]
    files = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    bundle_id = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if source_files is None:
        source_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        source_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
        # Development may deliberately include new nonignored work, but cannot
        # call those bytes clean. Special index flags hide modifications
        # from status; conservatively mark those inputs dirty even if unchanged.
        entries = subprocess.check_output(["git", "ls-files", "-v", "-z"], cwd=ROOT).decode().split("\0")
        tracked = {entry[2:]: entry[0] for entry in entries if entry}
        source_dirty |= any(name not in tracked or tracked[name] != "H" for name in inputs)
    else:
        source_dirty = False
    metadata = {"product_version": PRODUCT_VERSION, "toolkit_version": TOOLKIT_VERSION,
                "source_revision": source_revision, "source_dirty": source_dirty,
                "engine_protocol": 1, "bundle_id": bundle_id, "files": files}
    payload["BUILD.json"] = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode()
    # Exclusive creation preserves any artifact that appears after the initial check.
    with output.open("xb") as handle:
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                archive.writestr(info, data)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError("Package readback failed.")
        for name, digest in files.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise ValueError("Package content readback failed.")
    return {"artifact": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "bundle_id": bundle_id, "product_version": PRODUCT_VERSION,
            "toolkit_version": TOOLKIT_VERSION, "files": len(payload),
            "source_revision": source_revision, "source_dirty": source_dirty}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.output.expanduser().absolute()), indent=2))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"ok": False, "code": "build_failed", "message": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
