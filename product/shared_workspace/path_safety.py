"""Dependency-free filesystem link checks, before canonical path resolution.

These preflights reject existing symlinks and Windows reparse points. They do not
provide an OS lock against hostile concurrent replacement of path components.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


def _raw_absolute(value):
    # Path.absolute retains '..', unlike os.path.abspath. Inspect every original
    # component before lexical normalization could hide an alias/../ sequence.
    path = Path(value).absolute()
    # Preserve the established, exact macOS system aliases only. Never resolve a
    # user-selected alias before checking its raw components.
    if sys.platform == 'darwin':
        for alias in ('/var', '/tmp', '/etc'):
            prefix = Path(alias)
            if path.is_relative_to(prefix) and prefix.is_symlink() and prefix.resolve() == Path('/private' + alias):
                return Path('/private' + alias) / path.relative_to(prefix)
    return path


def absolute_path(value):
    return Path(os.path.abspath(_raw_absolute(value)))


def is_link_or_reparse(path):
    try:
        info = os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return False
    return (stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0)
            & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400)))


def unsafe_ancestor(value):
    path = _raw_absolute(value)
    # Check from root to leaf so even metadata inspection does not pass through a
    # discovered junction to inspect descendants outside the intended tree.
    for component in reversed((path, *path.parents)):
        if is_link_or_reparse(component):
            return component
    return None
