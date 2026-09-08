#!/usr/bin/env python3
"""Build reviewed release assets from a clean Git checkout, without publishing.

Requires Python 3.11+ and Git. No downloads, credentials or third-party packages.
Use a fresh output directory outside the source checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
import zipfile

from build_product import build, PRODUCT_VERSION, ROOT


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(path: Path, files: dict[str, bytes]) -> None:
    with path.open("xb") as handle:
        with zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as output:
            for name, content in sorted(files.items()):
                entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                output.writestr(entry, content)
    with zipfile.ZipFile(path) as check:
        if check.testzip() is not None or set(check.namelist()) != set(files):
            raise ValueError("Release archive readback failed")
        if any(check.read(name) != content for name, content in files.items()):
            raise ValueError("Release archive content differs from source")


def committed_source() -> tuple[str, dict[str, bytes]]:
    """Read exact HEAD blobs, never index contents or recursively found files."""
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "ls-tree", "-r", "-z", "--full-tree", revision], cwd=ROOT)
    entries = []
    for record in tree.split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        name = raw_name.decode("utf-8")
        if (mode not in {b"100644", b"100755"} or kind != b"blob" or name.startswith("/")
                or "\\" in name or any(part in {"", ".", ".."} for part in name.split("/"))):
            raise ValueError("Release source requires regular committed files and relative POSIX paths")
        entries.append((name, oid))
    # Batch exact object IDs: filenames with spaces/newlines cannot alter requests.
    data = subprocess.check_output(["git", "cat-file", "--batch"], cwd=ROOT,
                                  input=b"".join(oid + b"\n" for _, oid in entries))
    offset, sources = 0, {}
    for name, oid in entries:
        newline = data.index(b"\n", offset)
        actual_oid, kind, length = data[offset:newline].split()
        size = int(length)
        start, end = newline + 1, newline + 1 + size
        if actual_oid != oid or kind != b"blob" or data[end:end + 1] != b"\n":
            raise ValueError("Committed source object readback failed")
        sources[name] = data[start:end]
        offset = end + 1
    if offset != len(data):
        raise ValueError("Unexpected trailing committed source objects")
    return revision, sources


def verify_checkout(revision: str, sources: dict[str, bytes]) -> None:
    """Status is additional evidence, never the authority for working bytes."""
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != revision:
        raise ValueError("Source revision changed during release preparation")
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("Commit and review source changes before building release assets")
    for name, expected in sources.items():
        source = ROOT
        for component in name.split("/"):
            source = source / component
            info = source.lstat()
            if (stat.S_ISLNK(info.st_mode) or
                    getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                raise ValueError("Release source cannot traverse links or reparse points: " + name)
        if not stat.S_ISREG(info.st_mode) or source.read_bytes() != expected:
            raise ValueError("Tracked working bytes differ from reviewed HEAD: " + name)


def release(output: Path, version: str) -> dict:
    """Build all assets from one reviewed byte map, without executing source payloads."""
    output = output.expanduser().resolve()
    root = ROOT.resolve()
    if output == root or root in output.parents:
        raise ValueError("Release output must be outside the source checkout")
    if not re.fullmatch(re.escape(PRODUCT_VERSION) + r"(?:-alpha\.[1-9][0-9]*)?", version):
        raise ValueError("Release version must match the runtime version, optionally with -alpha.N")
    source_revision, sources = committed_source()
    verify_checkout(source_revision, sources)
    required = {"LICENSE", "SETUP-PROMPT.md", "assets/shared-memory.svg", "assets/shared-memory.png",
                "assets/shared-memory.icns", "assets/README.md", "skills/setup-shared-project-workspace/SKILL.md",
                "product/shared_workspace/cli.py", "product/shared_workspace/__init__.py",
                "docs/PRODUCT-V1.md", "docs/KNOWLEDGE-GRAPH.md", "requirements-server.txt"}
    if not required <= sources.keys():
        raise ValueError("Release is missing required committed source inputs")
    output.mkdir(parents=True, exist_ok=False)
    package = output / f"shared-memory-{version}.pyz"
    product = build(package, source_files=sources, source_revision=source_revision)
    skill_prefix = "skills/setup-shared-project-workspace/"
    skill_files = {"setup-shared-project-workspace/" + name.removeprefix(skill_prefix): content
                   for name, content in sources.items() if name.startswith(skill_prefix)}
    skill_files["LICENSE"] = sources["LICENSE"]
    archive(output / f"shared-memory-skill-{version}.zip", skill_files)
    icons = {name: sources["assets/" + name]
             for name in ("shared-memory.svg", "shared-memory.png", "shared-memory.icns", "README.md")}
    icons["LICENSE"] = sources["LICENSE"]
    archive(output / f"shared-memory-icons-{version}.zip", icons)
    manifest = {
        "release_tag": "v" + version, "maturity": "experimental_alpha" if "-alpha." in version else "release", "stable_v1": False,
        "source_repository": "https://github.com/Kian-hdr/shared-memory",
        "source_revision": source_revision, "source_dirty": False,
        "runtime_version": PRODUCT_VERSION, "runtime_asset": package.name,
        "runtime_sha256": sha(package), "bundle_id": product["bundle_id"],
        "limits": ["physical Windows onboarding unverified", "independent-user acceptance incomplete",
                   "live storage-provider delivery unverified", "production-scale and long-running hosting unverified"],
    }
    (output / "RELEASE-MANIFEST.json").write_bytes((json.dumps(manifest, indent=2) + "\n").encode())
    (output / "SETUP-PROMPT.md").write_bytes(sources["SETUP-PROMPT.md"])
    # Complete committed source keeps relative documentation/skill links usable.
    kit = dict(sources)
    generated = {package.name, "RELEASE-MANIFEST.json", "SHA256SUMS"}
    if generated & kit.keys():
        raise ValueError("Committed source collides with generated release-kit entries")
    kit[package.name] = package.read_bytes()
    kit["RELEASE-MANIFEST.json"] = (output / "RELEASE-MANIFEST.json").read_bytes()
    kit["SHA256SUMS"] = (sha(package) + "  " + package.name + "\n").encode()
    archive(output / f"shared-memory-{version}.zip", kit)
    files = sorted(path for path in output.iterdir() if path.is_file())
    (output / "SHA256SUMS").write_bytes("".join(f"{sha(path)}  {path.name}\n" for path in files).encode())
    verify_checkout(source_revision, sources)
    return {"output": str(output), "source_revision": source_revision,
            "release_tag": "v" + version, "assets": [path.name for path in files] + ["SHA256SUMS"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--release-version", default=PRODUCT_VERSION)
    args = parser.parse_args()
    print(json.dumps(release(args.output, args.release_version), indent=2))


if __name__ == "__main__":
    main()
