"""Read-only graph evidence. No live Vault, Obsidian UI or rename claims."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1]
if str(PRODUCT) not in sys.path:
    sys.path.insert(0, str(PRODUCT))
from shared_workspace import knowledge
from shared_workspace.errors import ProductError
from shared_workspace.knowledge import analyze


def nodes(graph):
    return {node['id']: node for node in graph['nodes']}


def fingerprint(root):
    result = {}
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        result[relative] = ('symlink' if path.is_symlink() else 'directory' if path.is_dir()
                            else hashlib.sha256(path.read_bytes()).hexdigest())
    return result


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shared-memory-graph-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_selected_nested_private_vault_untouched_and_attachments_never_read(self):
        vault = self.root / 'Private vault'
        project = vault / 'Projects' / 'Shared project'
        project.mkdir(parents=True)
        (vault / '.obsidian').mkdir()
        (vault / '.obsidian' / 'private.json').write_bytes(b'{"private":true}')
        (vault / 'Private.md').write_bytes(b'SENTINEL-PRIVATE-PARENT')
        (project / 'Home.md').write_text('# Shared project\n[[Notes/Decision]] ![[Assets/Diagram.png]]\n'
                                         '[[../../Private]] [[.obsidian/private]] [[sessions/private]]\n', encoding='utf-8')
        (project / 'Notes').mkdir()
        (project / 'Notes' / 'Decision.md').write_text('---\ntype: decision\n---\n# Decision\n', encoding='utf-8')
        (project / 'Assets').mkdir()
        attachment = project / 'Assets' / 'Diagram.png'
        attachment.write_bytes(b'\x89PNG\xff\x00SYNTHETIC-ATTACHMENT')
        for folder in ('.obsidian', 'sessions', 'client-state', 'credentials'):
            (project / folder).mkdir()
            (project / folder / 'private.md').write_text('SECRET-RUNTIME-NOTE')
        before = fingerprint(vault)
        real_read = knowledge._read_note
        read_paths = []
        def record_read(root, relative, expected):
            read_paths.append(relative)
            self.assertTrue(relative.endswith('.md'))
            return real_read(root, relative, expected)
        with patch.object(knowledge, '_read_note', side_effect=record_read):
            graph = analyze(root=project)
        self.assertEqual(read_paths, ['Home.md', 'Notes/Decision.md'])
        self.assertEqual(set(nodes(graph)), {'Home.md', 'Notes/Decision.md', 'Assets/Diagram.png'})
        self.assertEqual(nodes(graph)['Notes/Decision.md']['kind'], 'decision')
        self.assertEqual(nodes(graph)['Assets/Diagram.png']['content_sha256'], None)
        self.assertEqual([edge['status'] for edge in graph['edges']],
                         ['resolved', 'resolved', 'outside_scope', 'excluded', 'excluded'])
        serialized = json.dumps(graph)
        for secret in ('SENTINEL-PRIVATE-PARENT', 'SECRET-RUNTIME-NOTE', str(vault), 'SYNTHETIC-ATTACHMENT'):
            self.assertNotIn(secret, serialized)
        self.assertEqual(fingerprint(vault), before)
        self.assertEqual(graph['evidence']['obsidian_ui'], 'not_run')
        self.assertEqual(graph['evidence']['mutations'], 'none')

    def test_explicit_metadata_relationships_and_backlinks_have_real_provenance(self):
        files = {'Home.md': '# Home\n[[Projects/Project]]\n',
                 'Projects/Project.md': '---\ntype: project\ntitle: "Shared project"\n'
                     'decisions: ["[[Decisions/Choice]]"]\nevidence:\n  - "[[Evidence/Test]]"\n'
                     'work_records: "[[Work/Review]]"\nowner: someone\napi_key: DO-NOT-EXPORT\n---\n# Project\n',
                 'Decisions/Choice.md': '---\ntype: decision\n---\n# Choice\n',
                 'Evidence/Test.md': '---\ntype: evidence\n---\n# Test\n',
                 'Work/Review.md': '---\ntype: work\n---\n# Review\n'}
        graph = analyze(files=files)
        project = nodes(graph)['Projects/Project.md']
        self.assertEqual((project['title'], project['kind']), ('Shared project', 'project'))
        edges = [edge for edge in graph['edges'] if edge['source'] == 'Projects/Project.md']
        self.assertEqual([(e['relation'], e['line'], e['metadata_field'], e['target']) for e in edges],
                         [('decision', 4, 'decisions', 'Decisions/Choice.md'),
                          ('evidence', 6, 'evidence', 'Evidence/Test.md'),
                          ('work', 7, 'work_records', 'Work/Review.md')])
        self.assertTrue(all(e['status'] == 'resolved' for e in edges))
        backlink = nodes(graph)['Evidence/Test.md']['backlinks'][0]
        self.assertEqual(backlink['source'], 'Projects/Project.md')
        self.assertEqual(backlink['line'], 6)
        self.assertIn(backlink['edge_id'], {edge['id'] for edge in edges})
        self.assertNotIn('DO-NOT-EXPORT', json.dumps(graph))
        self.assertEqual(graph['evidence']['semantic_inference'], 'none')

    def test_portable_markdown_relative_paths_and_wiki_selected_root_paths(self):
        files = {'Home.md': '# Home', 'Notes/Child.md': '[Home](../Home.md)\n[[Home]]\n'
                 '[Sibling](Sibling.md)\n[[Notes/Sibling]]\n[[./Sibling]]\n'
                 '[Outside](../../private.md)\n[Encoded outside](%2Fprivate.md)\n',
                 'Notes/Sibling.md': '# Sibling'}
        graph = analyze(files=files)
        links = [e for e in graph['edges'] if e['source'] == 'Notes/Child.md']
        self.assertEqual([e['target'] for e in links[:5]],
                         ['Home.md', 'Home.md', 'Notes/Sibling.md', 'Notes/Sibling.md', 'Notes/Sibling.md'])
        self.assertEqual([e['status'] for e in links[5:]], ['outside_scope', 'outside_scope'])

    def test_exact_path_precedes_basename_but_ambiguous_basename_is_not_selected(self):
        graph = analyze(files={'Home.md': '[[Note]] [[A/Note]] [[Other]]', 'A/Note.md': '# A',
                               'B/Note.md': '# B', 'Other.md': '# Root', 'A/Other.md': '# Nested'})
        ambiguous, exact, root = graph['edges']
        self.assertEqual(ambiguous['status'], 'ambiguous')
        self.assertIsNone(ambiguous['target'])
        self.assertEqual(ambiguous['candidates'], ['A/Note.md', 'B/Note.md'])
        self.assertEqual(exact['target'], 'A/Note.md')
        self.assertEqual(root['target'], 'Other.md')

    def test_native_shortest_markdown_basename_links_after_rename_resolve_in_selected_scope(self):
        graph = analyze(files={
            'Shared Memory.md': '# Shared Memory\n## Accepted boundary\n',
            'Decisions/ADR-001 Folder Boundary.md': '[Project](Shared%20Memory.md#Accepted%20boundary)\n',
            'Knowledge/Coordination Principles.md': '[Project](Shared%20Memory.md)\n',
            'Work/Validate Graph.md': '[Project](Shared%20Memory.md) [[Shared Memory]]\n',
        })
        self.assertEqual(len(graph['edges']), 4)
        self.assertEqual([edge['target'] for edge in graph['edges']], ['Shared Memory.md'] * 4)
        self.assertEqual([edge['status'] for edge in graph['edges']], ['resolved'] * 4)
        self.assertEqual(graph['edges'][0]['anchor_status'], 'resolved')
        self.assertEqual(graph['diagnostics'], [])

    def test_markdown_basename_fallback_preserves_relative_priority_ambiguity_and_boundaries(self):
        graph = analyze(files={
            'Notes/Source.md': '[Relative](Exact.md)\n[Ambiguous](Duplicate.md)\n'
                '[Reference][unique]\n[Explicit relative](./Unique.md)\n'
                '[Missing slash](Missing/Unique.md)\n[Outside](../../Unique.md)\n'
                '[Private](credentials.md)\n[Case](UNIQUE.md)\n'
                '[unique]: Unique.md\n',
            'Notes/Exact.md': '# Exact local\n', 'Exact.md': '# Exact root\n',
            'A/Duplicate.md': '# First\n', 'B/Duplicate.md': '# Second\n',
            'Elsewhere/Unique.md': '# Unique\n', 'credentials.md': '# PRIVATE-SENTINEL\n',
        })
        edges = graph['edges']
        self.assertEqual(edges[0]['target'], 'Notes/Exact.md')
        self.assertEqual(edges[0]['resolution'], 'exact_path')
        self.assertEqual(edges[1]['status'], 'ambiguous')
        self.assertEqual(edges[1]['candidates'], ['A/Duplicate.md', 'B/Duplicate.md'])
        self.assertIsNone(edges[1]['target'])
        self.assertEqual(edges[2]['target'], 'Elsewhere/Unique.md')
        self.assertEqual(edges[2]['syntax'], 'markdown_reference')
        self.assertEqual([edge['status'] for edge in edges[3:]],
                         ['missing', 'missing', 'outside_scope', 'excluded', 'nonportable_match'])
        self.assertNotIn('PRIVATE-SENTINEL', json.dumps(graph))

    def test_alias_candidates_are_explicit_not_false_obsidian_resolutions(self):
        files = {'Home.md': '[[AI]] [[Common]] [[Canonical|AI]]',
                 'Canonical.md': '---\naliases:\n - AI\n - Common\n---\n# Canonical',
                 'Second.md': '---\naliases: [Common, "Second, alias"]\n---\n# Second'}
        graph = analyze(files=files)
        links = [e for e in graph['edges'] if e['source'] == 'Home.md']
        self.assertEqual(links[0]['status'], 'alias_only')
        self.assertEqual(links[0]['candidates'], ['Canonical.md'])
        self.assertEqual(links[1]['status'], 'ambiguous')
        self.assertEqual(links[1]['candidates'], ['Canonical.md', 'Second.md'])
        self.assertEqual(links[2]['target'], 'Canonical.md')
        self.assertIn('Second, alias', nodes(graph)['Second.md']['aliases'])

    def test_case_and_unicode_collisions_never_choose_nonexact_match(self):
        files = {'Home.md': '[[NOTE]] [[Café]] [[CAFÉ]] [[Note]]',
                 'Note.md': '# First', 'note.md': '# Second',
                 'A/Café.md': '# Composed', 'B/Café.md': '# Decomposed'}
        graph = analyze(files=files)
        links = [e for e in graph['edges'] if e['source'] == 'Home.md']
        self.assertEqual(links[0]['status'], 'nonportable_match')
        self.assertEqual(links[0]['candidates'], ['Note.md', 'note.md'])
        self.assertEqual(links[1]['target'], 'A/Café.md')
        self.assertEqual(links[2]['status'], 'nonportable_match')
        self.assertEqual(links[2]['candidates'], ['A/Café.md', 'B/Café.md'])
        self.assertEqual(links[3]['target'], 'Note.md')
        self.assertIn('nonportable_path_collision', [d['code'] for d in graph['diagnostics']])
        self.assertIn('nonportable_unicode_path', [d['code'] for d in graph['diagnostics']])

    def test_heading_block_validation_is_separate_from_file_resolution(self):
        files = {'Home.md': '[[Target#Introduction]] [[Target#Parent#Child]] [[Target#^block-1]]\n'
                 '[Slug](Target.md#grüße-world) [[Target#Missing]] [[Target#Repeated]]\n'
                 '[[Target#^duplicate]] [[Target#^absent]] ![[Diagram.pdf#page=2]]\n',
                 'Target.md': '# Introduction\n## Parent\n### Child\n# Grüße, World!\n'
                 '# Repeated\n# Repeated\nText ^block-1\nOne ^duplicate\nTwo ^duplicate\n',
                 'Diagram.pdf': 'attachment placeholder'}
        graph = analyze(files=files)
        links = [e for e in graph['edges'] if e['source'] == 'Home.md']
        self.assertTrue(all(e['status'] == 'resolved' for e in links))
        self.assertEqual([e['anchor_status'] for e in links],
                         ['resolved', 'resolved', 'resolved', 'resolved', 'missing', 'ambiguous',
                          'ambiguous', 'missing', 'unsupported_attachment_anchor'])
        self.assertEqual([h['slug'] for h in nodes(graph)['Target.md']['headings']][-2:], ['repeated', 'repeated-1'])
        self.assertEqual(graph['summary']['validated_anchors'], 4)

    def test_same_note_setext_and_encoded_heading_anchors(self):
        graph = analyze(files={'Note.md': 'Title\n=====\n\n[[#Title]] [Here](#title)\n'
                               '## Café Topic\n[[#Caf%C3%A9%20Topic]]\n'})
        self.assertEqual([e['target'] for e in graph['edges']], ['Note.md'] * 3)
        self.assertEqual([e['anchor_status'] for e in graph['edges']], ['resolved'] * 3)
        self.assertEqual(nodes(graph)['Note.md']['headings'][0]['line'], 1)

    def test_markdown_encoded_heading_text_preserves_slug_and_single_decode_behavior(self):
        graph = analyze(files={
            'Decisions/Boundary.md': '[Inline](../Shared%20Project.md#Accepted%20boundary)\n'
                '[Reference][boundary]\n[Unicode](../Shared%20Project.md#Caf%C3%A9%20Topic)\n'
                '[Slug](../Shared%20Project.md#accepted-boundary)\n'
                '[Twice](../Shared%20Project.md#Accepted%2520boundary)\n'
                '[Plus](../Shared%20Project.md#Accepted+boundary)\n'
                '[Duplicate](../Shared%20Project.md#Repeated%20heading)\n'
                '[Second slug](../Shared%20Project.md#repeated-heading-1)\n'
                '[boundary]: ../Shared%20Project.md#Accepted%20boundary\n',
            'Shared Project.md': '# Shared Project\n## Accepted boundary\n## Café Topic\n'
                '## Repeated heading\n## Repeated heading\n[Same note](#Accepted%20boundary)\n',
        })
        links = [edge for edge in graph['edges'] if edge['source'] == 'Decisions/Boundary.md']
        self.assertEqual([edge['target'] for edge in links], ['Shared Project.md'] * 8)
        self.assertEqual([edge['anchor_status'] for edge in links],
                         ['resolved', 'resolved', 'resolved', 'resolved', 'missing', 'missing',
                          'ambiguous', 'resolved'])
        self.assertEqual(links[0]['anchor'], 'Accepted boundary')
        self.assertEqual(links[1]['syntax'], 'markdown_reference')
        self.assertEqual(links[2]['anchor'], 'Café Topic')
        self.assertEqual(links[4]['anchor'], 'Accepted%20boundary')
        same_note = [edge for edge in graph['edges'] if edge['source'] == 'Shared Project.md']
        self.assertEqual(same_note[0]['anchor_status'], 'resolved')
        self.assertEqual(graph['evidence']['obsidian_ui'], 'not_run')

    def test_code_comments_escaped_links_and_code_headings_excluded(self):
        text = '# Real\n[[Target]] `[[InlineSecret]]`\n```markdown\n# Not heading\n[[FenceSecret]]\n```\n'
        text += '~~~\n[[TildeSecret]]\n~~~\n    [[IndentedSecret]]\n'
        text += '<!-- [[CommentSecret]]\n[[CommentSecret2]] -->\n%% [[ObsidianSecret]] %%\n'
        text += '\\[[EscapedSecret]]\n> ```\n> [[QuoteFenceSecret]]\n> ```\n'
        graph = analyze(files={'Home.md': text, 'Target.md': '# Target'})
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['edges'][0]['target'], 'Target.md')
        self.assertEqual([h['text'] for h in nodes(graph)['Home.md']['headings']], ['Real'])
        self.assertNotIn('Secret', json.dumps(graph))

    def test_markdown_reference_links_titles_balanced_parentheses_and_embeds(self):
        files = {'Home.md': '[One][ref] ![Picture][img] [ref] [Missing][absent]\n'
                 '[Paren](Notes/A(B).md "Optional title")\n'
                 '[ref]: <Notes/A%28B%29.md> "Reference title"\n'
                 '[img]: Assets/figure.png\n',
                 'Notes/A(B).md': '# Balanced', 'Assets/figure.png': ''}
        graph = analyze(files=files)
        edges = [e for e in graph['edges'] if e['source'] == 'Home.md']
        self.assertEqual(len(edges), 5)
        self.assertEqual(edges[0]['target'], 'Notes/A(B).md')
        self.assertEqual(edges[0]['definition_line'], 3)
        self.assertEqual(edges[1]['relation'], 'embed')
        self.assertEqual(edges[2]['target'], 'Notes/A(B).md')
        self.assertEqual(edges[3]['status'], 'unsupported_reference')
        self.assertEqual(edges[4]['target'], 'Notes/A(B).md')

    def test_external_references_do_not_export_credentials_or_fetch_urls(self):
        graph = analyze(files={'Home.md': '[External](https://user:SECRET@example.invalid/private/TOKEN?q=KEY#FRAGMENT)\n'
                               '[Local](file:///private/SECRET.txt) [Mail](mailto:private@example.invalid)\n'
                               '<https://example.invalid/SECRET?q=KEY>\n'})
        self.assertEqual([e['status'] for e in graph['edges']], ['external'] * 4)
        self.assertEqual([e['external_scheme'] for e in graph['edges']], ['https', 'file', 'mailto', 'https'])
        serialized = json.dumps(graph)
        for private in ('SECRET', 'TOKEN', 'KEY', 'FRAGMENT', 'example.invalid'):
            self.assertNotIn(private, serialized)
        self.assertEqual(graph['evidence']['external_requests'], 'none')

    def test_unsupported_and_duplicate_frontmatter_do_not_create_false_relations(self):
        graph = analyze(files={'Home.md': '---\ntype: project\ntype: decision\n'
            'evidence:\n  nested: "[[Secret]]"\nrelated: &anchor "[[Secret]]"\n'
            'aliases: [Good, {complex: value}]\n---\n# Home\n[[Target]]', 'Target.md': '# Target'})
        self.assertEqual(nodes(graph)['Home.md']['kind'], 'note')
        self.assertEqual(nodes(graph)['Home.md']['aliases'], [])
        self.assertEqual(len(graph['edges']), 1)
        self.assertEqual(graph['edges'][0]['target'], 'Target.md')
        codes = [d['code'] for d in graph['diagnostics']]
        self.assertIn('frontmatter_duplicate_key', codes)
        self.assertIn('frontmatter_unsupported', codes)
        self.assertNotIn('Secret', json.dumps(graph))

    def test_symlinks_never_read_outside_or_become_graph_nodes(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'Home.md').write_text('[[Outside]] [[linked-folder/Private]]')
        outside = self.root / 'Private.md'
        outside.write_text('DO-NOT-READ-OUTSIDE')
        try:
            (project / 'Outside.md').symlink_to(outside)
            (project / 'linked-folder').symlink_to(self.root, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f'Symlink capability unavailable: {exc.errno}')
        before = fingerprint(self.root)
        graph = analyze(root=project)
        self.assertEqual(set(nodes(graph)), {'Home.md'})
        self.assertEqual([e['status'] for e in graph['edges']], ['excluded', 'excluded'])
        self.assertNotIn('DO-NOT-READ-OUTSIDE', json.dumps(graph))
        self.assertEqual(fingerprint(self.root), before)
        with self.assertRaises(ProductError):
            analyze(root=project / 'linked-folder')

    def test_snapshot_and_filesystem_graphs_have_matching_relationships(self):
        project = self.root / 'project'
        project.mkdir()
        files = {'Home.md': '# Home\n[[Nested/Note]]', 'Nested/Note.md': '# Note\n[[Home]]'}
        for name, text in files.items():
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode('utf-8'))
        before = fingerprint(project)
        snapshot = analyze(files=files)
        filesystem = analyze(root=project)
        self.assertEqual(snapshot['nodes'], filesystem['nodes'])
        self.assertEqual(snapshot['edges'], filesystem['edges'])
        self.assertEqual(fingerprint(project), before)
        self.assertEqual(analyze(files=dict(reversed(list(files.items())))), snapshot)

    def test_limits_fail_explicitly_and_unsupported_coverage_is_reported(self):
        for constant, limit, files in [('MAX_FILES', 1, {'One.md': '', 'Two.md': ''}),
                ('MAX_NOTE_BYTES', 2, {'One.md': 'Long'}),
                ('MAX_TOTAL_BYTES', 4, {'One.md': 'One', 'Two.md': 'Two'}),
                ('MAX_EDGES', 1, {'One.md': '[[A]] [[B]]'}),
                ('MAX_HEADINGS', 1, {'One.md': '# A\n# B'}),
                ('MAX_BLOCKS', 1, {'One.md': 'One ^a\nTwo ^b'}),
                ('MAX_ALIASES', 1, {'One.md': '---\naliases: [A, B]\n---'}),
                ('MAX_FRONTMATTER', 4, {'One.md': '---\ntitle: Oversized\n---'}),
                ('MAX_CANDIDATE_REFERENCES', 1, {'One.md': '[[Two]]', 'A/Two.md': '', 'B/Two.md': ''}),
                ('MAX_GRAPH_BYTES', 8, {'One.md': '# Content'})]:
            with self.subTest(limit=constant), patch.object(knowledge, constant, limit):
                with self.assertRaises(ProductError) as caught:
                    analyze(files=files)
                self.assertEqual(caught.exception.code, 'knowledge_limit')
        with patch.object(knowledge, 'MAX_LINE', 10):
            graph = analyze(files={'Home.md': '[[AReallyLongLink]]'})
            self.assertEqual(graph['edges'], [])
            self.assertIn('line_omitted_limit', [d['code'] for d in graph['diagnostics']])
        self.assertIn('full_yaml', graph['coverage']['unsupported'])

    def test_malformed_inputs_do_not_mutate_or_produce_falsely_complete_graph(self):
        for kwargs in ({}, {'root': self.root, 'files': {}}, {'files': []}, {'files': {1: 'bad'}},
                       {'files': {'Home.md': b'binary'}}):
            with self.subTest(kwargs=repr(kwargs)), self.assertRaises(ProductError):
                analyze(**kwargs)
        graph = analyze(files={'../outside.md': 'OUTSIDE', '.hidden/private.md': 'HIDDEN',
                               'client-state/private.json': 'RUNTIME', 'script.py': 'CODE', 'Home.md': '# Home'})
        self.assertEqual(set(nodes(graph)), {'Home.md'})
        self.assertIn('unsafe_path_omitted', [d['code'] for d in graph['diagnostics']])
        self.assertNotIn('OUTSIDE', json.dumps(graph))

    def test_private_link_anchor_is_not_exported_and_missing_anchor_never_resolves(self):
        graph = analyze(files={'Home.md': '[[.obsidian/settings#SECRET-FRAGMENT]] [[Missing#Missing]]\n'})
        excluded, missing = graph['edges']
        self.assertEqual(excluded['status'], 'excluded')
        self.assertIsNone(excluded['anchor'])
        self.assertEqual(missing['status'], 'missing')
        self.assertEqual(missing['anchor_status'], 'unvalidated')
        self.assertNotIn('SECRET-FRAGMENT', json.dumps(graph))

    def test_empty_and_depth_omitted_inputs_have_explicit_coverage(self):
        self.assertEqual(analyze(files={})['summary']['nodes'], 0)
        with patch.object(knowledge, 'MAX_DEPTH', 2):
            graph = analyze(files={'Home.md': '[[A/B/Deep]]', 'A/B/Deep.md': '# Too deep'})
        self.assertEqual(set(nodes(graph)), {'Home.md'})
        self.assertEqual(graph['edges'][0]['status'], 'excluded')
        self.assertIn('depth_omitted', [d['code'] for d in graph['diagnostics']])

    def test_non_utf8_note_is_not_read_as_graph_content(self):
        project = self.root / 'project'
        project.mkdir()
        (project / 'Home.md').write_bytes(b'[[Binary]]')
        (project / 'Binary.md').write_bytes(b'\xff\xfeSECRET')
        graph = analyze(root=project)
        self.assertEqual(set(nodes(graph)), {'Home.md'})
        self.assertEqual(graph['edges'][0]['status'], 'excluded')
        self.assertIn('non_utf8_note_omitted', [d['code'] for d in graph['diagnostics']])
        self.assertNotIn('SECRET', json.dumps(graph))

    def test_dotted_note_names_keep_optional_markdown_extension(self):
        graph = analyze(files={'Home.md': '[[Notes/Meeting 2026.09.08]] [[Notes/Meeting 2026.09.08.md]]',
                               'Notes/Meeting 2026.09.08.md': '# Meeting'})
        self.assertEqual([e['target'] for e in graph['edges']], ['Notes/Meeting 2026.09.08.md'] * 2)


if __name__ == '__main__':
    unittest.main()
