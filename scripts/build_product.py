#!/usr/bin/env python3
"""Build a self-contained product preview zipapp without downloads or installation."""
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
    fail("unsupported_runtime", "Product preview requires Python 3.11 or newer; use a maintained Python such as 3.13.", 2)
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


def build(output: Path) -> dict:
    if output.exists():
        raise ValueError("Refusing to replace an existing output; choose a fresh artifact path.")
    if not output.parent.is_dir():
        raise ValueError("The output parent directory must already exist.")
    modules = ROOT / "product/shared_workspace"
    skill = ROOT / "skills/setup-shared-project-workspace"
    if not (modules / "cli.py").is_file() or not (modules / "__init__.py").is_file():
        raise ValueError("Product implementation is incomplete: cli.py and __init__.py are required.")
    payload = {"__main__.py": BOOTSTRAP.encode("utf-8")}
    for source in sorted(modules.rglob("*.py")):
        if source.is_symlink():
            raise ValueError("Source symlinks are not package inputs.")
        payload["shared_workspace/" + source.relative_to(modules).as_posix()] = source.read_bytes()
    for source in sorted(skill.rglob("*")):
        if "__pycache__" in source.parts or source.suffix in {".pyc", ".pyo"}:
            continue
        if source.is_symlink():
            raise ValueError("Skill symlinks are not package inputs.")
        if source.is_file():
            payload["bundle/skills/setup-shared-project-workspace/" + source.relative_to(skill).as_posix()] = source.read_bytes()
    payload["LICENSE"] = (ROOT / "LICENSE").read_bytes()
    payload["PRODUCT-GUIDE.md"] = (ROOT / "docs/PRODUCT-V1.md").read_bytes()
    payload["KNOWLEDGE-GRAPH.md"] = (ROOT / "docs/KNOWLEDGE-GRAPH.md").read_bytes()
    payload["requirements-server.txt"] = (ROOT / "requirements-server.txt").read_bytes()
    files = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(payload.items())}
    bundle_id = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    source_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    source_dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip())
    metadata = {"product_version": PRODUCT_VERSION, "toolkit_version": TOOLKIT_VERSION,
                "source_revision": source_revision, "source_dirty": source_dirty,
                "engine_protocol": 1, "bundle_id": bundle_id, "files": files}
    payload["BUILD.json"] = (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode()
    # Exclusive creation preserves any artifact that appears after the initial check.
    with output.open("xb") as handle:
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in sorted(payload.items()):
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
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
