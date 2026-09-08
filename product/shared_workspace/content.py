"""Explicit content selection; absent metadata retains the legacy behavior."""
from pathlib import PurePosixPath

from .errors import ProductError

CONTENT_MODES = ('legacy', 'markdown')


def content_mode(value=None):
    mode = 'legacy' if value is None else value
    if mode not in CONTENT_MODES:
        raise ProductError(3, 'content_mode_invalid', 'Unsupported project content mode.')
    return mode


def markdown_path(name):
    return PurePosixPath(name).suffix.casefold() in {'.md', '.markdown'}


def manifest_mode(data):
    version = data.get('format_version')
    if type(version) is int and version == 1 and data.get('content_mode', 'legacy') == 'legacy':
        return 'legacy'
    if type(version) is int and version == 2 and data.get('content_mode') == 'markdown':
        return 'markdown'
    raise ProductError(3, 'project_invalid', 'Unsupported Shared Memory content format; use a compatible reviewed runtime.')


def client_mode(config):
    version = config.get('schema_version')
    if type(version) is int and version == 1 and config.get('content_mode', 'legacy') == 'legacy':
        return 'legacy'
    if type(version) is int and version == 2 and config.get('content_mode') == 'markdown':
        return 'markdown'
    raise ProductError(3, 'client_state', 'Unsupported private client content format.')
