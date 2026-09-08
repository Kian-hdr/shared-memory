"""Verify a reviewed, self-contained bundle before executing toolkit code."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from . import PRODUCT_VERSION
from .errors import ProductError

SKILL_PATH = "bundle/skills/setup-shared-project-workspace"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def checked_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not name or not path.parts or "\\" in name or path.is_absolute() or ".." in path.parts
            or str(path) != name or ":" in path.parts[0]):
        raise ProductError(3, "bundle_integrity", "Bundle contains an unsafe file path.")
    return name


class Bundle:
    def __init__(self, root: Path, build: dict):
        self.root = root
        self.build = build
        self.skill = root / SKILL_PATH
        self.tracker_path = self.skill / "assets/project_tracker.py"
        self.tracker_sha256 = digest_file(self.tracker_path)

    def load_module(self, relative: str):
        path = self.skill / relative
        spec = importlib.util.spec_from_file_location("_shared_workspace_" + path.stem, path)
        if spec is None or spec.loader is None:
            raise ProductError(3, "bundle_integrity", "Trusted toolkit module cannot be loaded.")
        module = importlib.util.module_from_spec(spec)
        previous = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = previous
        return module

    def tracker(self, project: Path):
        module = self.load_module("assets/project_tracker.py")
        module.PROJECT_ROOT = project
        module.TRACKER_DIR = project / "Coordination"
        module.ITEMS_DIR = project / "Coordination/Items"
        return module


def validate_build(build: dict) -> dict[str, str]:
    if not isinstance(build, dict):
        raise ProductError(3, "bundle_integrity", "BUILD.json must contain an object.")
    files = build.get("files")
    if not isinstance(files, dict) or not files:
        raise ProductError(3, "bundle_integrity", "BUILD.json lacks the file manifest.")
    for name, digest in files.items():
        if not isinstance(name, str):
            raise ProductError(3, "bundle_integrity", "Invalid bundle file name.")
        checked_name(name)
        if name == "BUILD.json" or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ProductError(3, "bundle_integrity", "Invalid bundle file digest.")
    calculated = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if build.get("bundle_id") != calculated:
        raise ProductError(3, "bundle_integrity", "Bundle identity does not match its file manifest.")
    if (build.get("product_version") != PRODUCT_VERSION
            or not isinstance(build.get("toolkit_version"), str)
            or not isinstance(build.get("source_revision"), str)
            or not isinstance(build.get("source_dirty"), bool)):
        raise ProductError(3, "bundle_integrity", "Build provenance or product version is unsupported.")
    required = {f"{SKILL_PATH}/assets/project_tracker.py", f"{SKILL_PATH}/assets/workspace.base",
                f"{SKILL_PATH}/scripts/setup_workspace.py", f"{SKILL_PATH}/scripts/doctor_workspace.py"}
    if not required.issubset(files):
        raise ProductError(3, "bundle_integrity", "Bundle lacks required trusted toolkit files.")
    return files


@contextmanager
def open_bundle(explicit: str | None = None):
    source = Path(explicit).expanduser() if explicit else Path(sys.argv[0])
    if not source.exists():
        raise ProductError(5, "environment_missing", "The reviewed package or built bundle is unavailable.")
    if explicit is None and not zipfile.is_zipfile(source):
        raise ProductError(5, "environment_missing", "Source mode requires an explicit built package or directory via --bundle.")
    with tempfile.TemporaryDirectory(prefix="shared-workspace-runtime-") as temporary:
        root = Path(temporary)
        try:
            if source.is_dir():
                build_path = source / "BUILD.json"
                if not build_path.is_file() or build_path.is_symlink():
                    raise ProductError(3, "bundle_integrity", "The built directory has no regular BUILD.json.")
                build = json.loads(build_path.read_text(encoding="utf-8"))
                files = validate_build(build)
                actual = set()
                for path in source.rglob("*"):
                    if path.is_symlink():
                        raise ProductError(3, "bundle_integrity", "Symbolic links are not accepted in a built bundle.")
                    if path.is_file() and path != build_path:
                        actual.add(path.relative_to(source).as_posix())
                if actual != set(files):
                    raise ProductError(3, "bundle_integrity", "Bundle file inventory does not match BUILD.json.")
                for name, digest in files.items():
                    output = root / name
                    output.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source / name, output)
                    if digest_file(output) != digest:
                        raise ProductError(3, "bundle_integrity", f"Bundled file failed integrity verification: {name}")
            else:
                with zipfile.ZipFile(source) as archive:
                    members = archive.infolist()
                    names = [entry.filename for entry in members if not entry.is_dir()]
                    if len(names) != len(set(names)) or "BUILD.json" not in names:
                        raise ProductError(3, "bundle_integrity", "Archive has duplicate entries or no BUILD.json.")
                    build = json.loads(archive.read("BUILD.json"))
                    files = validate_build(build)
                    if set(names) - {"BUILD.json"} != set(files):
                        raise ProductError(3, "bundle_integrity", "Archive file inventory does not match BUILD.json.")
                    for entry in members:
                        if stat.S_ISLNK(entry.external_attr >> 16):
                            raise ProductError(3, "bundle_integrity", "Archive symbolic links are not accepted.")
                        if entry.is_dir():
                            checked_name(entry.filename.rstrip("/"))
                            continue
                        checked_name(entry.filename)
                        if entry.filename == "BUILD.json":
                            continue
                        output = root / entry.filename
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with archive.open(entry) as incoming, output.open("wb") as outgoing:
                            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
                        if digest_file(output) != files[entry.filename]:
                            raise ProductError(3, "bundle_integrity", f"Bundled file failed integrity verification: {entry.filename}")
            bundle = Bundle(root, build)
            if bundle.load_module("assets/project_tracker.py").WORKSPACE_TRACKER_VERSION != build["toolkit_version"]:
                raise ProductError(3, "bundle_integrity", "Toolkit version differs from the build manifest.")
        except (json.JSONDecodeError, UnicodeError, zipfile.BadZipFile, KeyError) as exc:
            raise ProductError(3, "bundle_integrity", "Built package is malformed or incomplete.") from exc
        yield bundle
