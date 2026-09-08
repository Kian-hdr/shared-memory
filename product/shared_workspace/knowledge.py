"""Bounded, read-only knowledge graph for one selected Markdown folder.

This is a documented Markdown/frontmatter subset, not a YAML interpreter or an
Obsidian renderer. Relationships come only from explicit links and link-bearing
metadata; note instructions never grant authority. No parent-folder discovery,
runtime graph, automatic rename, networking, or project writes occur.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from .engine import PROTECTED, canonical, validate_path
from .errors import ProductError

MAX_FILES = 5000
MAX_NOTE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_EDGES = 20000
MAX_DIAGNOSTICS = 20000
MAX_DEPTH = 32
MAX_LINE = 16384
MAX_FRONTMATTER = 65536
MAX_HEADINGS = 1000
MAX_BLOCKS = 1000
MAX_ALIASES = 64
MAX_LINK = 2048
MAX_CANDIDATE_REFERENCES = 20000
MAX_GRAPH_BYTES = 64 * 1024 * 1024
NOTE_EXTENSIONS = {'.md', '.markdown'}
ATTACHMENTS = {'.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif',
               '.mp3', '.wav', '.ogg', '.m4a', '.mp4', '.mov', '.webm', '.csv', '.txt'}
PRIVATE = PROTECTED | {'node_modules', '__pycache__', 'venv', 'runtime', 'sessions',
                       'credentials', 'secrets', 'tokens', 'oauth', 'backups', 'cache'}
PRIVATE_FILES = {'auth.json', 'credentials.json', 'secrets.json', 'token.json',
                 'credentials.md', 'secrets.md', 'tokens.md'}
RELATIONS = {'project': 'project', 'projects': 'project', 'decision': 'decision',
             'decisions': 'decision', 'evidence': 'evidence', 'source': 'evidence',
             'sources': 'evidence', 'work': 'work', 'work_records': 'work',
             'depends_on': 'dependency', 'related': 'related', 'canonical': 'canonical'}
KINDS = {'knowledge', 'project', 'decision', 'evidence', 'work', 'note'}


def _fail(code, message):
    raise ProductError(3, code, message) from None


def _fold(value):
    return unicodedata.normalize('NFC', value).casefold()


def _private(name):
    return any((part.startswith('.') and part not in {'.', '..'}) or part.casefold() in PRIVATE or part.casefold() in PRIVATE_FILES
               for part in name.replace('\\', '/').split('/'))


def _absolute(path):
    path = Path(os.path.abspath(path))
    if sys.platform == 'darwin':
        for alias in ('/var', '/tmp', '/etc'):
            start = Path(alias)
            if path.is_relative_to(start) and start.is_symlink() and start.resolve() == Path('/private' + alias):
                path = Path('/private' + alias) / path.relative_to(start)
                break
    for parent in (path, *path.parents):
        if parent.is_symlink():
            _fail('knowledge_root', 'The selected graph root cannot use symlinks.')
    if not path.is_dir():
        _fail('knowledge_root', 'Select an existing project folder.')
    return path


def _read_note(root, relative, expected):
    """Read bounded bytes; descriptor-relative no-follow traversal on POSIX."""
    handles = []
    try:
        if os.open in os.supports_dir_fd and hasattr(os, 'O_NOFOLLOW'):
            current = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            handles.append(current)
            parts = relative.split('/')
            for part in parts[:-1]:
                current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
                handles.append(current)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=current)
        else:
            path = root / relative
            for part in (path, *path.parents):
                if part.is_symlink():
                    _fail('knowledge_changed', 'A graph input changed during inspection.')
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
        handles.append(fd)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_size > MAX_NOTE_BYTES
                or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != expected):
            _fail('knowledge_changed', 'A graph input changed during inspection.')
        chunks, count = [], 0
        while chunk := os.read(fd, 65536):
            count += len(chunk)
            if count > MAX_NOTE_BYTES:
                _fail('knowledge_limit', 'A note exceeds the graph byte limit.')
            chunks.append(chunk)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != expected:
            _fail('knowledge_changed', 'A graph input changed during inspection.')
        return b''.join(chunks)
    except OSError:
        _fail('knowledge_read', 'A selected note could not be read safely.')
    finally:
        for fd in reversed(handles):
            os.close(fd)


def _plain(value):
    value = re.sub(r'!?(?:\[\[([^\]|]+)\|([^\]]+)\]\])', lambda m: m[2], value)
    value = re.sub(r'!?(?:\[\[([^\]]+)\]\])', lambda m: m[1], value)
    value = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', lambda m: m[1], value)
    value = re.sub(r'[`*_~]', '', value)
    value = re.sub(r'\\([\\`*{}\[\]()#+.!_>-])', r'\1', value)
    return value.strip()


def _slug(value):
    # Slugs lowercase Unicode letters; casefold would rewrite ß into ss.
    return ''.join(c for c in unicodedata.normalize('NFC', _plain(value)).lower() if c.isalnum() or c in '_- ')


def _scalar(value):
    value = value.strip()
    if not value:
        return ''
    if value.startswith('"'):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, str) else None
        except ValueError:
            return None
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            return None
        return value[1:-1].replace("''", "'")
    if (value[0] in '[{&*!|>' or ': ' in value or '\t' in value
            or re.search(r'\s#', value)):
        return None
    return value


def _values(value):
    value = value.strip()
    if value.startswith('[') and not value.startswith('[['):
        if not value.endswith(']'):
            return None
        # Only scalar inline lists; quotes may contain commas.
        items, current, quote, escaped = [], '', None, False
        for char in value[1:-1]:
            if escaped:
                current += char
                escaped = False
            elif char == '\\' and quote == '"':
                current += char
                escaped = True
            elif quote:
                current += char
                if char == quote:
                    quote = None
            elif char in "\"'":
                quote = char
                current += char
            elif char == ',':
                items.append(_scalar(current))
                current = ''
            else:
                current += char
        if quote:
            return None
        if current.strip() or items:
            items.append(_scalar(current))
        return items if all(v is not None for v in items) else None
    scalar = _scalar(value)
    return [scalar] if scalar is not None else None


def _frontmatter(lines, name, diagnostic):
    if not lines or lines[0].lstrip('\ufeff').strip() != '---':
        return {}, 0
    end, size = None, 0
    for i, line in enumerate(lines[1:], 1):
        size += len(line.encode('utf-8'))
        if size > MAX_FRONTMATTER:
            _fail('knowledge_limit', 'Frontmatter exceeds the graph byte limit.')
        if line.strip() in {'---', '...'}:
            end = i
            break
    if end is None:
        diagnostic('frontmatter_unclosed', name, 1)
        return {}, len(lines)
    values, seen, active = {}, set(), None
    for i in range(1, end):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*))?', line)
        if match:
            key, raw = match[1].casefold(), match[2] or ''
            if key in seen:
                diagnostic('frontmatter_duplicate_key', name, i + 1)
                values.pop(key, None)
                active = None
                continue
            seen.add(key)
            parsed = _values(raw)
            if parsed is None:
                diagnostic('frontmatter_unsupported', name, i + 1)
                active = None
                continue
            values[key] = [(value, i + 1) for value in parsed if value]
            active = key if not raw.strip() else None
        elif active and (item := re.fullmatch(r' {0,4}-[ \t]+(.+)', line)):
            parsed = _scalar(item[1])
            if parsed is None:
                diagnostic('frontmatter_unsupported', name, i + 1)
                values.pop(active, None)
                active = None
            else:
                values[active].append((parsed, i + 1))
        else:
            diagnostic('frontmatter_unsupported', name, i + 1)
            if active:
                values.pop(active, None)
            active = None
    return values, end + 1


def _masked_lines(lines, start, name, diagnostic):
    fence, comment = None, None
    for i, raw in enumerate(lines):
        if i < start:
            yield i + 1, ''
            continue
        if len(raw) > MAX_LINE:
            diagnostic('line_omitted_limit', name, i + 1)
            yield i + 1, ''
            continue
        marker = re.match(r'^(?: {0,3}> ?)* {0,3}(`{3,}|~{3,})(.*)$', raw)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                fence = None
            yield i + 1, ''
            continue
        if marker:
            fence = (marker[1][0], len(marker[1]))
            yield i + 1, ''
            continue
        # Indented code is excluded. Full CommonMark container parsing is not
        # claimed: list continuations indented four spaces are conservative.
        if raw.startswith(('    ', '\t')):
            yield i + 1, ''
            continue
        result, pos = '', 0
        while pos < len(raw):
            if comment:
                closing = raw.find(comment, pos)
                if closing < 0:
                    result += ' ' * (len(raw) - pos)
                    break
                result += ' ' * (closing + len(comment) - pos)
                pos = closing + len(comment)
                comment = None
            elif raw.startswith('<!--', pos) or raw.startswith('%%', pos):
                opener = '<!--' if raw.startswith('<!--', pos) else '%%'
                comment = '-->' if opener == '<!--' else '%%'
                result += ' ' * len(opener)
                pos += len(opener)
            else:
                result += raw[pos]
                pos += 1
        yield i + 1, result
    if fence:
        diagnostic('code_fence_unclosed', name, len(lines))
    if comment:
        diagnostic('comment_unclosed', name, len(lines))


def _mask_inline(value):
    result, i = list(value), 0
    while i < len(value):
        if value[i] == '\\':
            i += 2
            continue
        if value[i] != '`':
            i += 1
            continue
        end = i
        while end < len(value) and value[end] == '`':
            end += 1
        run = value[i:end]
        closing = value.find(run, end)
        while closing >= 0 and ((closing > 0 and value[closing - 1] == '`')
                               or (closing + len(run) < len(value) and value[closing + len(run)] == '`')):
            closing = value.find(run, closing + len(run))
        if closing >= 0:
            result[i:closing + len(run)] = ' ' * (closing + len(run) - i)
            i = closing + len(run)
        else:
            i = end
    return ''.join(result)


def _balanced(value, start, opening, closing):
    depth = 1
    i = start + 1
    while i < len(value) and i - start <= MAX_LINK:
        if value[i] == '\\':
            i += 2
            continue
        if value[i] == opening:
            depth += 1
        elif value[i] == closing:
            depth -= 1
            if not depth:
                return i
        i += 1
    return None


def _destination(value):
    value = value.strip()
    if value.startswith('<'):
        end = value.find('>')
        if end < 0 or (value[end + 1:].strip() and not re.fullmatch(r'\s*[\"\'].*[\"\']', value[end + 1:])):
            return None
        return value[1:end]
    # Markdown permits an optional quoted title after the destination.
    value = re.sub(r'\s+(?:"[^"\n]*"|\x27[^\x27\n]*\x27)$', '', value)
    if re.search(r'(?<!\\)\s', value):
        return None
    return re.sub(r'\\([\\()\[\]])', r'\1', value)


def _links(line, definitions):
    line = _mask_inline(line)
    result, i = [], 0
    while i < len(line):
        if line[i] == '\\':
            i += 2
            continue
        if line[i] == '<':
            closing = line.find('>', i + 1, i + MAX_LINK + 2)
            if closing >= 0:
                value = line[i + 1:closing]
                if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', value) and not re.search(r'\s', value):
                    result.append((value, 'markdown_autolink', False, i + 1, None))
                    i = closing + 1
                    continue
        embed = line.startswith('![', i)
        start = i + int(embed)
        if line.startswith('[[', start):
            end = line.find(']]', start + 2, start + MAX_LINK + 2)
            if end < 0:
                i = start + 2
                continue
            destination = line[start + 2:end].split('|', 1)[0].strip()
            result.append((destination, 'wikilink', embed, i + 1, None))
            i = end + 2
        elif start < len(line) and line[start] == '[':
            end = _balanced(line, start, '[', ']')
            if end is None:
                i += 1
                continue
            label = line[start + 1:end]
            if end + 1 < len(line) and line[end + 1] == '(':
                closing = _balanced(line, end + 1, '(', ')')
                if closing is not None:
                    target = _destination(line[end + 2:closing])
                    result.append((target, 'markdown', embed, i + 1, None))
                    i = closing + 1
                    continue
            reference = None
            if end + 1 < len(line) and line[end + 1] == '[':
                closing = line.find(']', end + 2, end + MAX_LINK + 2)
                if closing >= 0:
                    reference = line[end + 2:closing] or label
                    end = closing
            elif _fold(' '.join(label.split())) in definitions:
                reference = label
            if reference is not None:
                definition = definitions.get(_fold(' '.join(reference.split())))
                result.append((definition[0] if definition else None, 'markdown_reference', embed,
                               i + 1, definition[1] if definition else None))
            i = end + 1
        else:
            i += 1
    return result


class _Graph:
    def __init__(self):
        self.diagnostics, self.notes, self.inventory, self.excluded = [], {}, set(), set()
        self.edges, self.nodes, self.total = [], {}, 0
        self.counts = Counter()

    def diagnostic(self, code, path=None, line=None):
        if len(self.diagnostics) >= MAX_DIAGNOSTICS:
            _fail('knowledge_limit', 'Graph diagnostics exceed the configured limit.')
        value = {'code': code}
        if path is not None:
            value['path'] = path
        if line is not None:
            value['line'] = line
        self.diagnostics.append(value)

    def select(self, name, count=True):
        if not isinstance(name, str):
            _fail('knowledge_input', 'File inventory paths must be strings.')
        self.counts['inspected_entries'] += int(count)
        if self.counts['inspected_entries'] > MAX_FILES:
            _fail('knowledge_limit', 'Selected folder inventory exceeds the file limit.')
        if _private(name):
            self.counts['excluded_private'] += 1
            self.excluded.add(name)
            return False
        try:
            normalized = unicodedata.normalize('NFC', name)
            validate_path(normalized)
        except ProductError:
            self.counts['excluded_unsafe'] += 1
            self.diagnostic('unsafe_path_omitted')
            self.excluded.add(name)
            return False
        if len(name.split('/')) > MAX_DEPTH:
            self.diagnostic('depth_omitted', name)
            self.excluded.add(name)
            return False
        if name != normalized:
            self.diagnostic('nonportable_unicode_path', name)
        if PurePosixPath(name).suffix.casefold() not in NOTE_EXTENSIONS | ATTACHMENTS:
            self.counts['excluded_format'] += 1
            self.excluded.add(name)
            return False
        self.inventory.add(name)
        return True

    def add(self, name, raw):
        if PurePosixPath(name).suffix.casefold() not in NOTE_EXTENSIONS:
            return
        if len(raw) > MAX_NOTE_BYTES:
            _fail('knowledge_limit', 'A note exceeds the graph byte limit.')
        self.total += len(raw)
        if self.total > MAX_TOTAL_BYTES:
            _fail('knowledge_limit', 'Selected notes exceed the total graph byte limit.')
        try:
            self.notes[name] = raw.decode('utf-8')
        except UnicodeError:
            self.diagnostic('non_utf8_note_omitted', name)
            self.inventory.remove(name)
            self.excluded.add(name)

    def collect(self, root, files):
        if files is not None:
            if not isinstance(files, dict):
                _fail('knowledge_input', 'Pass an accepted file map, not a snapshot envelope.')
            if not all(isinstance(name, str) for name in files):
                _fail('knowledge_input', 'File inventory paths must be strings.')
            for name in sorted(files):
                if self.select(name) and PurePosixPath(name).suffix.casefold() in NOTE_EXTENSIONS:
                    if not isinstance(files[name], str):
                        _fail('knowledge_input', 'Accepted note contents must be UTF-8 text.')
                    if len(files[name]) > MAX_NOTE_BYTES:
                        _fail('knowledge_limit', 'A note exceeds the graph byte limit.')
                    try:
                        raw = files[name].encode('utf-8')
                    except UnicodeError:
                        _fail('knowledge_input', 'Accepted note contents must be UTF-8 text.')
                    self.add(name, raw)
            return
        pending = [('', root)]
        while pending:
            relative, directory = pending.pop()
            for ancestor in (directory, *directory.parents):
                if ancestor.is_symlink():
                    _fail('knowledge_changed', 'A graph directory changed during inspection.')
            try:
                with os.scandir(directory) as iterator:
                    entries = []
                    for entry in iterator:
                        entries.append(entry)
                        if len(entries) + self.counts['inspected_entries'] > MAX_FILES:
                            _fail('knowledge_limit', 'Selected folder inventory exceeds the file limit.')
            except OSError:
                _fail('knowledge_read', 'Selected folder inventory could not be read.')
            if len(entries) + self.counts['inspected_entries'] > MAX_FILES:
                _fail('knowledge_limit', 'Selected folder inventory exceeds the file limit.')
            for entry in sorted(entries, key=lambda e: e.name):
                self.counts['inspected_entries'] += 1
                name = relative + entry.name
                if _private(name):
                    self.counts['excluded_private'] += 1
                    self.excluded.add(name)
                    continue
                try:
                    if entry.is_symlink():
                        self.diagnostic('symlink_omitted', name)
                        self.excluded.add(name)
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        try:
                            validate_path(unicodedata.normalize('NFC', name))
                        except ProductError:
                            self.diagnostic('unsafe_path_omitted')
                            self.excluded.add(name)
                            continue
                        if len(name.split('/')) >= MAX_DEPTH:
                            self.diagnostic('depth_omitted', name)
                            self.excluded.add(name)
                        else:
                            pending.append((name + '/', Path(entry.path)))
                    elif entry.is_file(follow_symlinks=False):
                        if self.select(name, count=False) and PurePosixPath(name).suffix.casefold() in NOTE_EXTENSIONS:
                            info = entry.stat(follow_symlinks=False)
                            if info.st_size > MAX_NOTE_BYTES:
                                _fail('knowledge_limit', 'A note exceeds the graph byte limit.')
                            self.add(name, _read_note(root, name, (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)))
                    else:
                        self.diagnostic('special_file_omitted', name)
                        self.excluded.add(name)
                except OSError:
                    _fail('knowledge_read', 'Selected folder inventory changed during inspection.')

    def parse(self):
        pending = []
        for name, text in sorted(self.notes.items()):
            lines = text.splitlines()
            metadata, start = _frontmatter(lines, name, self.diagnostic)
            aliases = [v for key in ('aliases', 'alias') for v, _ in metadata.get(key, [])]
            if len(aliases) > MAX_ALIASES or any(len(v) > 256 for v in aliases):
                _fail('knowledge_limit', 'Note aliases exceed the graph limit.')
            if 'alias' in metadata:
                self.diagnostic('legacy_alias_property', name, metadata['alias'][0][1] if metadata['alias'] else 1)
            kind_value = metadata.get('type', metadata.get('kind', [('note', 1)]))
            kind = kind_value[0][0].casefold() if len(kind_value) == 1 else 'note'
            if kind not in KINDS:
                kind = 'note'
            title = metadata.get('title', [])
            node = {'id': name, 'path': name, 'title': title[0][0][:256] if len(title) == 1 else PurePosixPath(name).stem,
                    'kind': kind, 'aliases': sorted(set(aliases)), 'headings': [], 'blocks': [], 'backlinks': [],
                    'content_sha256': hashlib.sha256(text.encode()).hexdigest()}
            visible = list(_masked_lines(lines, start, name, self.diagnostic))
            definitions, definition_lines, previous, slugs = {}, set(), None, Counter()
            hierarchy = []
            for line_number, line in visible:
                heading = re.match(r'^ {0,3}(#{1,6})[ \t]+(.+?)\s*#*\s*$', line)
                setext = re.fullmatch(r' {0,3}(=+|-+)[ \t]*', line)
                if heading:
                    level, content, location = len(heading[1]), _plain(heading[2]), line_number
                elif setext and previous and previous[1].strip():
                    level, content, location = 1 if setext[1][0] == '=' else 2, _plain(previous[1]), previous[0]
                else:
                    level = None
                if level:
                    if len(node['headings']) >= MAX_HEADINGS:
                        _fail('knowledge_limit', 'Note headings exceed the graph limit.')
                    base_slug = re.sub(r'\s+', '-', _slug(content))
                    slug = base_slug + (f'-{slugs[base_slug]}' if slugs[base_slug] else '')
                    slugs[base_slug] += 1
                    while hierarchy and hierarchy[-1][0] >= level:
                        hierarchy.pop()
                    hierarchy.append((level, content))
                    node['headings'].append({'text': content, 'slug': slug, 'line': location, 'level': level,
                                             'ancestry': [part[1] for part in hierarchy]})
                    if not title and len(node['headings']) == 1:
                        node['title'] = content[:256]
                safe = _mask_inline(line)
                block = re.search(r'(?:^|\s)\^([A-Za-z0-9-]+)\s*$', safe)
                if block:
                    if len(node['blocks']) >= MAX_BLOCKS:
                        _fail('knowledge_limit', 'Note block references exceed the graph limit.')
                    node['blocks'].append({'id': block[1], 'line': line_number})
                definition = re.fullmatch(r' {0,3}\[([^\]]+)\]:\s*(.+)', safe)
                if definition:
                    key = _fold(' '.join(definition[1].split()))
                    target = _destination(definition[2])
                    if key in definitions:
                        self.diagnostic('duplicate_reference_definition', name, line_number)
                        definitions[key] = (None, line_number)
                    else:
                        definitions[key] = (target, line_number)
                    definition_lines.add(line_number)
                previous = (line_number, line) if line.strip() else None
            self.nodes[name] = node
            for key in sorted(RELATIONS):
                for value, location in metadata.get(key, []):
                    for target, syntax, embed, column, definition in _links(value, definitions):
                        pending.append((name, location, column, target, syntax, embed, RELATIONS[key], key, definition))
            for line_number, line in visible:
                if line_number in definition_lines:
                    continue
                for target, syntax, embed, column, definition in _links(line, definitions):
                    pending.append((name, line_number, column, target, syntax, embed,
                                    'embed' if embed else 'link', None, definition))
                if len(pending) > MAX_EDGES:
                    _fail('knowledge_limit', 'Explicit links exceed the graph edge limit.')
        if len(pending) > MAX_EDGES:
            _fail('knowledge_limit', 'Explicit links exceed the graph edge limit.')
        return sorted(pending, key=lambda item: (item[0], item[1], item[2], item[6]))

    def resolve(self, source, raw, syntax):
        result = {'target': None, 'status': 'missing', 'resolution': None, 'anchor': None,
                  'anchor_status': 'not_requested', 'candidates': []}
        if raw is None:
            result['status'] = 'unsupported_reference'
            return result
        if len(raw) > MAX_LINK:
            result['status'] = 'unsupported_reference'
            return result
        if re.match(r'^[A-Za-z][A-Za-z0-9+.-]*:', raw) or raw.startswith('//'):
            result['status'] = 'external'
            # Never return credentials, local absolute paths, queries or URL
            # fragments. The source path/line is sufficient to inspect a link.
            result['external_scheme'] = raw.split(':', 1)[0].casefold() if ':' in raw else 'https'
            return result
        if raw.startswith('/'):
            result['status'] = 'outside_scope'
            return result
        destination, separator, anchor = raw.partition('#')
        if '?' in destination:
            result['status'] = 'unsupported_reference'
            return result
        try:
            destination = unquote(destination, errors='strict')
            anchor = unquote(anchor, errors='strict') if separator else None
        except UnicodeError:
            result['status'] = 'unsupported_reference'
            return result
        if destination.startswith('/'):
            result['status'] = 'outside_scope'
            return result
        if anchor is not None:
            result['anchor'] = anchor
            result['anchor_status'] = 'unvalidated'
        if _private(destination):
            result['status'] = 'excluded'
            result['anchor'] = None
            result['anchor_status'] = 'not_requested'
            return result
        # Wiki slash paths start at this selected folder. Markdown tries the
        # document-relative path first; native shortest links may then use an
        # unambiguous basename inside the already inventoried selected folder.
        relative = syntax != 'wikilink' or destination.startswith(('./', '../'))
        parts = list(PurePosixPath(source).parent.parts) if relative else []
        if not destination:
            candidates, method = [source], 'same_note'
        else:
            for part in destination.split('/'):
                if part in {'', '.'}:
                    continue
                if part == '..':
                    if not parts:
                        result['status'] = 'outside_scope'
                        return result
                    parts.pop()
                else:
                    parts.append(part)
            name = '/'.join(parts)
            try:
                validate_path(unicodedata.normalize('NFC', name))
            except ProductError:
                result['status'] = 'unsupported_reference'
                return result
            suffix = PurePosixPath(name).suffix.casefold()
            choices = [name] if suffix in NOTE_EXTENSIONS | ATTACHMENTS else [name, name + '.md', name + '.markdown']
            if any('/'.join(choice.split('/')[:count]) in self.excluded
                   for choice in choices for count in range(1, len(choice.split('/')) + 1)):
                result['status'] = 'excluded'
                result['anchor'] = None
                result['anchor_status'] = 'not_requested'
                return result
            candidates = [name] if name in self.inventory else [value for value in choices if value in self.inventory]
            method = 'exact_path'
            if not candidates:
                candidates = sorted({value for choice in choices for value in self.path_fold.get(_fold(choice), [])})
                if candidates:
                    result.update(status='nonportable_match', resolution='case_or_unicode', candidates=sorted(candidates))
                    return result
            if not candidates and syntax in {'wikilink', 'markdown', 'markdown_reference'} and '/' not in destination:
                candidates = self.basename.get(destination, [])
                method = 'basename'
                if not candidates:
                    candidates = self.basename_fold.get(_fold(destination), [])
                    if candidates:
                        result.update(status='nonportable_match', resolution='case_or_unicode', candidates=sorted(candidates))
                        return result
                if not candidates and syntax == 'wikilink':
                    aliases = self.alias_fold.get(_fold(destination), [])
                    if aliases:
                        result.update(status='alias_only' if len(aliases) == 1 else 'ambiguous',
                                      resolution='alias', candidates=sorted(aliases))
                        return result
        if len(candidates) > 1:
            result.update(status='ambiguous', resolution=method, candidates=sorted(candidates))
            return result
        if not candidates:
            return result
        target = candidates[0]
        result.update(target=target, status='resolved', resolution=method)
        if anchor is not None:
            node = self.nodes.get(target)
            if not node:
                result['anchor_status'] = 'unsupported_attachment_anchor'
            elif anchor.startswith('^'):
                matches = [block for block in node['blocks'] if block['id'] == anchor[1:]]
                result['anchor_status'] = 'resolved' if len(matches) == 1 else ('ambiguous' if matches else 'missing')
            elif not anchor or anchor.startswith('#'):
                result['anchor_status'] = 'unsupported'
            elif syntax != 'wikilink':
                matches = [heading for heading in node['headings'] if heading['slug'] == anchor]
                if not matches:
                    # Obsidian Markdown destinations can contain the heading's
                    # URL-encoded text as well as conventional generated slugs.
                    # resolve() has already decoded the fragment exactly once.
                    matches = [heading for heading in node['headings']
                               if _fold(heading['text']) == _fold(anchor)]
                result['anchor_status'] = 'resolved' if len(matches) == 1 else ('ambiguous' if matches else 'missing')
            else:
                requested = [_fold(value) for value in anchor.split('#')]
                matches = [heading for heading in node['headings'] if
                           (len(requested) == 1 and _fold(heading['text']) == requested[0]) or
                           (len(requested) > 1 and [_fold(v) for v in heading['ancestry'][-len(requested):]] == requested)]
                result['anchor_status'] = 'resolved' if len(matches) == 1 else ('ambiguous' if matches else 'missing')
        return result

    def finish(self, mode):
        links = self.parse()
        self.path_fold, self.basename, self.basename_fold, self.alias_fold = (defaultdict(list) for _ in range(4))
        for path in sorted(self.inventory):
            self.path_fold[_fold(path)].append(path)
            names = {PurePosixPath(path).name}
            if PurePosixPath(path).suffix.casefold() in NOTE_EXTENSIONS:
                names.add(PurePosixPath(path).stem)
            for name in names:
                self.basename[name].append(path)
                self.basename_fold[_fold(name)].append(path)
        for path, node in sorted(self.nodes.items()):
            for alias in {_fold(a) for a in node['aliases']}:
                self.alias_fold[alias].append(path)
        for paths in self.path_fold.values():
            if len(paths) > 1:
                for path in sorted(paths):
                    self.diagnostic('nonportable_path_collision', path)
        candidate_count = 0
        for index, (source, line, column, raw, syntax, embed, relation, field, definition) in enumerate(links):
            resolved = self.resolve(source, raw, syntax)
            candidate_count += len(resolved['candidates'])
            if candidate_count > MAX_CANDIDATE_REFERENCES:
                _fail('knowledge_limit', 'Ambiguous candidate references exceed the graph limit.')
            edge = {'id': hashlib.sha256(canonical([source, line, column, index]).encode()).hexdigest()[:24],
                    'source': source, 'line': line, 'column': column, 'syntax': syntax,
                    'relation': relation, 'embed': embed, 'metadata_field': field,
                    'definition_line': definition, **resolved}
            self.edges.append(edge)
            if resolved['status'] != 'resolved':
                self.diagnostic('link_' + resolved['status'], source, line)
            elif resolved['anchor_status'] not in {'resolved', 'not_requested'}:
                self.diagnostic('anchor_' + resolved['anchor_status'], source, line)
            if resolved['target']:
                target = resolved['target']
                if target not in self.nodes:
                    self.nodes[target] = {'id': target, 'path': target, 'title': PurePosixPath(target).name,
                                          'kind': 'attachment', 'aliases': [], 'headings': [], 'blocks': [],
                                          'backlinks': [], 'content_sha256': None}
                self.nodes[target]['backlinks'].append({'source': source, 'edge_id': edge['id'], 'line': line})
        self.diagnostics.sort(key=lambda d: (d.get('path', ''), d.get('line', 0), d['code']))
        summary = {'notes': len(self.notes), 'nodes': len(self.nodes), 'edges': len(self.edges),
                   'resolved_links': sum(e['status'] == 'resolved' for e in self.edges),
                   'validated_anchors': sum(e['anchor_status'] == 'resolved' for e in self.edges),
                   'diagnostics': len(self.diagnostics), 'note_bytes': self.total, **dict(sorted(self.counts.items()))}
        graph = {'schema_version': 1, 'scope': 'selected_project', 'nodes': [self.nodes[k] for k in sorted(self.nodes)],
                'edges': self.edges, 'diagnostics': self.diagnostics, 'summary': summary,
                'evidence': {'input': mode, 'parser': 'bounded_markdown', 'obsidian_ui': 'not_run',
                             'mutations': 'none', 'semantic_inference': 'none',
                             'attachment_content': 'not_read', 'external_requests': 'none'},
                'limits': {'files': MAX_FILES, 'nodes': MAX_FILES, 'note_bytes': MAX_NOTE_BYTES, 'total_note_bytes': MAX_TOTAL_BYTES,
                           'edges': MAX_EDGES, 'diagnostics': MAX_DIAGNOSTICS, 'depth': MAX_DEPTH,
                           'line_characters': MAX_LINE, 'frontmatter_bytes': MAX_FRONTMATTER,
                           'headings_per_note': MAX_HEADINGS, 'blocks_per_note': MAX_BLOCKS,
                           'aliases_per_note': MAX_ALIASES, 'link_characters': MAX_LINK,
                           'candidate_references': MAX_CANDIDATE_REFERENCES, 'graph_bytes': MAX_GRAPH_BYTES},
                'coverage': {'frontmatter': 'top_level_scalars_and_scalar_lists',
                             'markdown_paths': 'document_relative_then_selected_basename', 'wikilink_paths': 'selected_root_relative',
                             'aliases': 'candidates_require_canonical_links',
                             'unsupported': ['full_yaml', 'html_links', 'Obsidian_query_search_links',
                                             'indented_list_continuations', 'plugin_syntax', 'rendering']}}
        if len(canonical(graph).encode('utf-8')) > MAX_GRAPH_BYTES:
            _fail('knowledge_limit', 'Serialized graph exceeds its byte limit.')
        return graph


def analyze(*, root=None, files=None):
    """Analyze exactly one selected folder or accepted file map without mutation.

    Root mode inventories supported attachment names but never reads attachment
    contents. It omits hidden/private/runtime trees before traversal. Snapshot
    mode expects ``snapshot['files']`` and applies the same exclusions. Returned
    paths are relative to this selected folder; no absolute path or raw external
    URL is exported. Hard limits fail rather than returning a falsely complete
    graph; explicitly unsupported parser coverage is reported in the result.
    """
    if (root is None) == (files is None):
        _fail('knowledge_input', 'Provide exactly one selected root or accepted file map.')
    graph = _Graph()
    graph.collect(_absolute(root) if root is not None else None, files)
    return graph.finish('selected_folder' if root is not None else 'accepted_files')
