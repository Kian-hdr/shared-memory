"""Deterministic conservative line merges over immutable per-path causal heads."""
from difflib import SequenceMatcher


def merge_text(base, versions):
    if len(set(versions)) == 1:
        return True, versions[0]
    if base is None or any(value is None for value in versions):
        return False, None
    original = base.splitlines(keepends=True)
    if len(original) > 2000 or any(len(value) > 2 * 1024 * 1024 for value in versions):
        return False, None  # Retain full versions rather than run an unbounded diff.
    edits = []
    for text in versions:
        lines = text.splitlines(keepends=True)
        if len(lines) > 2000:
            return False, None
        for op, start, end, left, right in SequenceMatcher(None, original, lines, autojunk=False).get_opcodes():
            if op == 'equal':
                continue
            change = (start, end, tuple(lines[left:right]))
            if change in edits:
                continue
            for old_start, old_end, _ in edits:
                overlap = max(start, old_start) < min(end, old_end)
                if start == end:
                    overlap |= old_start <= start <= old_end
                if old_start == old_end:
                    overlap |= start <= old_start <= end
                if overlap:
                    return False, None
            edits.append(change)
    for start, end, replacement in sorted(edits, reverse=True):
        original[start:end] = replacement
    return True, ''.join(original)


def views(events):
    """Events must be complete, acyclic and ordered parents before children.

    Compute ancestry only for actual concurrent heads. Long linear histories do
    not build an all-pairs ancestor matrix.
    """
    nodes, parents, heads = {}, {}, {}
    for identity, event in events.items():
        for path, text in event['changes'].items():
            key = (path, identity)
            lineage = event['parents'][path]
            parents[key] = lineage
            nodes[key] = text
            heads.setdefault(path, set()).difference_update(lineage)
            heads[path].add(identity)
    def ancestry(path, identity):
        found, pending = set(), [identity]
        while pending:
            item = pending.pop()
            if item in found:
                continue
            found.add(item)
            pending.extend(parents[(path, item)])
        return found
    result = {}
    for path, values in sorted(heads.items()):
        ids = sorted(values)
        texts = [nodes[(path, identity)] for identity in ids]
        if len(ids) == 1:
            maximal = ids
        else:
            common = set.intersection(*(ancestry(path, identity) for identity in ids))
            # Ancestors of a common node are also common. Remove its direct
            # parents to obtain the maximal common nodes without quadratic walks.
            maximal = sorted(common - {parent for item in common for parent in parents[(path, item)]})
        base_id = maximal[0] if len(maximal) == 1 else None
        base = nodes[(path, base_id)] if base_id else None
        if len(ids) == 1 or len(set(texts)) == 1:
            compatible, text = True, texts[0]
        elif len(maximal) > 1:
            compatible, text = False, None
        else:
            compatible, text = merge_text(base, texts)
        result[path] = {'heads': ids, 'text': text, 'conflict': not compatible,
                        'base_id': base_id, 'base': base,
                        'versions': [{'event': identity, 'text': nodes[(path, identity)]} for identity in ids]}
    return result
