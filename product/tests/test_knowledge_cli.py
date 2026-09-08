"""Packaged read-only graph commands on disposable selected folders/authorities."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
import test_team_cli as fixtures


def fingerprint(root):
    return {path.relative_to(root).as_posix():
            ('directory' if path.is_dir() else hashlib.sha256(path.read_bytes()).hexdigest())
            for path in root.rglob('*')}


class KnowledgeCLITests(unittest.TestCase):
    # Reuse the actual package builder and setup helpers, without inheriting tests.
    setUpClass = classmethod(fixtures.TeamCLITests.setUpClass.__func__)
    setUp = fixtures.TeamCLITests.setUp
    cli = fixtures.TeamCLITests.cli
    initialize = fixtures.TeamCLITests.initialize
    coord = fixtures.TeamCLITests.coord

    def graph(self, project=None, *, accepted=False, state=None, expected=0):
        command = [sys.executable, str(self.archive), 'graph', str(project or self.project)]
        if accepted:
            command.append('--accepted')
        if state is not None:
            command.extend(['--state-dir', str(state)])
        before = fingerprint(self.root)
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertEqual(result.stderr, '', result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output['schema_version'], 1)
        self.assertEqual(output['command'], 'graph')
        self.assertEqual(output['ok'], expected == 0)
        self.assertEqual(fingerprint(self.root), before, 'Graph command changed project, private state or directory inventory')
        for token in self.root.rglob('*.token'):
            self.assertNotIn(token.read_text().strip(), result.stdout)
        self.outputs.append(output)
        return output

    def test_unconfigured_selected_subfolder_is_read_only_and_excludes_private_parent_and_runtime(self):
        (self.project / 'Home.md').write_text('# Shared\n[[Notes/Decision]] [[../Private]]\n'
            '[[credentials/private]] [[.obsidian/private]] ![[Assets/preview.png]]\n', encoding='utf-8')
        (self.project / 'Notes').mkdir()
        (self.project / 'Notes/Decision.md').write_text('---\ntype: decision\n---\n# Decision\n', encoding='utf-8')
        (self.project / 'Assets').mkdir()
        (self.project / 'Assets/preview.png').write_bytes(b'\x89PNG\x00PRIVATE-ATTACHMENT-BYTES')
        for name in ('credentials', '.obsidian', 'sessions'):
            (self.project / name).mkdir()
            (self.project / name / 'private.md').write_text('# SECRET-LOCAL-RUNTIME\n')
        graph = self.graph()['data']
        self.assertEqual(graph['source'], 'local_selected_folder')
        self.assertFalse(graph['acceptance_authority'])
        self.assertEqual({node['id'] for node in graph['nodes']},
                         {'Home.md', 'Notes/Decision.md', 'Assets/preview.png'})
        self.assertEqual([edge['status'] for edge in graph['edges']],
                         ['resolved', 'outside_scope', 'excluded', 'excluded', 'resolved'])
        self.assertFalse(self.state.exists())
        self.assertFalse((self.project / '.shared-memory.json').exists())
        serialized = json.dumps(graph)
        for private in ('PRIVATE-PARENT', 'SECRET-LOCAL-RUNTIME', 'PRIVATE-ATTACHMENT-BYTES',
                        str(self.project.parent), str(self.state)):
            self.assertNotIn(private, serialized)
        self.assertEqual(graph['evidence']['obsidian_ui'], 'not_run')
        self.assertEqual(graph['evidence']['mutations'], 'none')

    def test_accepted_graph_uses_current_authenticated_snapshot_not_local_notes_or_saved_baseline(self):
        (self.project / 'Home.md').write_text('# Original\n[[Old]]\n', encoding='utf-8')
        (self.project / 'Old.md').write_text('# Old\n', encoding='utf-8')
        initialized = self.initialize()
        self.coord('claim', {'assignment_id': 'graph-update', 'targets': ['.'],
            'criteria': ['Exact graph fixture'], 'dependencies': [], 'resource_limits': {},
            'integration_owner': 'alex'})
        accepted_home = '# Accepted heading\n[[Accepted]]\n'
        self.coord('propose', {'proposal_id': 'accepted-links', 'assignment_id': 'graph-update',
            'base_revision': 0, 'changes': {'Home.md': accepted_home, 'Old.md': None,
            'Accepted.md': '# Accepted\n'}, 'evidence': 'New accepted fixture graph'})
        accepted = self.coord('accept', {'proposal_id': 'accepted-links',
            'validation': 'Compared fixture link destinations', 'reason': 'Explicit acceptance'})
        (self.project / 'Home.md').write_text('# Divergent draft\n[[DraftOnly]]\n', encoding='utf-8')
        (self.project / 'DraftOnly.md').write_text('# Local draft only\n', encoding='utf-8')
        self.assertEqual(json.loads((self.state / 'client/snapshot.json').read_text())['revision'], 0)
        graph = self.graph(accepted=True, state=self.state)['data']
        self.assertEqual(graph['source'], 'accepted_coordinator_snapshot')
        self.assertEqual(graph['accepted_identity'], {'project_id': initialized['project_id'],
                         'revision': accepted['revision'], 'files_hash': accepted['files_hash']})
        nodes = {node['id']: node for node in graph['nodes']}
        self.assertIn('Accepted.md', nodes)
        self.assertNotIn('Old.md', nodes)
        self.assertNotIn('DraftOnly.md', nodes)
        self.assertEqual(nodes['Home.md']['content_sha256'], hashlib.sha256(accepted_home.encode()).hexdigest())
        self.assertTrue(any(edge['source'] == 'Home.md' and edge['target'] == 'Accepted.md' for edge in graph['edges']))
        self.assertFalse(graph['acceptance_authority'])
        self.assertEqual(graph['evidence']['obsidian_ui'], 'not_run')
        local = self.graph()['data']
        self.assertEqual(local['source'], 'local_selected_folder')
        self.assertIn('DraftOnly.md', {node['id'] for node in local['nodes']})
        self.assertNotIn('accepted_identity', local)

    def test_accepted_missing_state_and_local_unused_state_are_json_usage_errors_without_setup(self):
        output = self.graph(accepted=True, expected=2)
        self.assertEqual(output['code'], 'usage_error')
        output = self.graph(state=self.state, expected=2)
        self.assertEqual(output['code'], 'usage_error')
        self.assertFalse(self.state.exists())
        self.assertFalse((self.project / '.shared-memory.json').exists())

    def test_linked_root_and_ancestor_rejected_before_local_or_accepted_reads(self):
        outside = self.root / 'private-outside'; outside.mkdir()
        (outside / 'nested').mkdir()
        private = outside / 'nested' / 'Private.md'
        private.write_bytes(b'# PRIVATE-JUNCTION-TARGET\n')
        before = fingerprint(outside)
        link = self.project / 'linked'
        if os.name == 'nt':
            created = subprocess.run(['cmd', '/d', '/c', 'mklink', '/J', str(link), str(outside)],
                                     capture_output=True, text=True, timeout=15)
            self.assertEqual(created.returncode, 0, created.stdout + created.stderr)
            self.assertFalse(link.is_symlink(), 'Exercise an actual non-symlink Windows junction')
            self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        else:
            link.symlink_to(outside, target_is_directory=True)
            self.addCleanup(lambda: link.unlink() if link.is_symlink() else None)
        for selected in (link, link / 'nested', link / '..'):
            for accepted in (False, True):
                with self.subTest(root=selected.name, accepted=accepted):
                    command = [sys.executable, str(self.archive), 'graph', str(selected)]
                    if accepted:
                        command.append('--accepted')
                    # No state is provided: unsafe input must be rejected before
                    # private binding reads or the accepted-mode missing-state error.
                    result = subprocess.run(command, cwd=self.root, capture_output=True,
                                            text=True, timeout=60)
                    self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
                    self.assertEqual(result.stderr, '')
                    output = json.loads(result.stdout)
                    self.assertFalse(output['ok'])
                    self.assertEqual(output['command'], 'graph')
                    self.assertEqual(output['code'], 'knowledge_root')
                    self.assertNotIn('nodes', output['data'])
                    self.assertNotIn('PRIVATE-JUNCTION-TARGET', result.stdout)
                    self.assertNotIn(str(outside), result.stdout)
                    self.assertEqual(fingerprint(outside), before)
                    self.assertFalse(self.state.exists())

    def test_selected_root_and_private_state_project_mismatch_is_refused(self):
        self.initialize()
        other = self.root / 'Other selected project'; other.mkdir()
        other_state = self.root / 'other-private-state'
        self.initialize(other, other_state)
        output = self.graph(other, accepted=True, state=self.state, expected=3)
        self.assertEqual(output['code'], 'project_mismatch')
        # Even an identical manifest does not authorize another local root path.
        (other / '.shared-memory.json').write_bytes((self.project / '.shared-memory.json').read_bytes())
        output = self.graph(other, accepted=True, state=self.state, expected=3)
        self.assertEqual(output['code'], 'project_mismatch')

    def test_valid_foreign_coordinator_credential_cannot_export_as_selected_project(self):
        self.initialize()
        other = self.root / 'Other project'; other.mkdir()
        (other / 'Foreign.md').write_text('# FOREIGN-COORDINATOR-HEADING\n')
        other_state = self.root / 'other-state'
        self.initialize(other, other_state)
        (self.state / 'connection.json').write_bytes((other_state / 'connection.json').read_bytes())
        (self.state / 'member.token').write_bytes((other_state / 'member.token').read_bytes())
        output = self.graph(accepted=True, state=self.state, expected=3)
        self.assertEqual(output['code'], 'project_mismatch')
        self.assertNotIn('FOREIGN-COORDINATOR-HEADING', json.dumps(output))
        self.assertNotIn('nodes', output['data'])

    def test_private_state_cannot_be_nested_in_selected_project(self):
        self.initialize()
        output = self.graph(accepted=True, state=self.project / 'client-state', expected=3)
        self.assertEqual(output['code'], 'state_path_unsafe')
        self.assertFalse((self.project / 'client-state').exists())

    def test_revoked_authenticated_reader_cannot_fall_back_to_local_graph(self):
        initialized = self.initialize()
        token = self.root / 'reader.token'
        self.cli('member-add', None, None, '--actor', 'reader', '--person', 'Synthetic reader',
                 '--agent', 'Graph test', '--role', 'reader', '--token-output', token)
        recipient = self.root / 'Recipient vault' / 'Shared'; recipient.mkdir(parents=True)
        state = self.root / 'reader-private-state'
        self.cli('attach', recipient, state, '--database', self.state / 'coordinator.sqlite3',
                 '--token-file', token, '--expected-project-id', initialized['project_id'])
        graph = self.graph(recipient, accepted=True, state=state)['data']
        self.assertEqual(graph['accepted_identity']['project_id'], initialized['project_id'])
        self.coord('revoke', {'actor': 'reader'})
        output = self.graph(recipient, accepted=True, state=state, expected=4)
        self.assertNotIn('nodes', output['data'])
        self.assertNotIn('accepted_identity', output['data'])

    def test_missing_authority_cannot_fall_back_to_saved_snapshot_or_local_graph(self):
        self.initialize()
        config_path = self.state / 'connection.json'
        config = json.loads(config_path.read_text())
        config['database'] = str(self.root / 'missing-authority.sqlite3')
        config_path.write_text(json.dumps(config))
        output = self.graph(accepted=True, state=self.state, expected=5)
        self.assertNotIn('nodes', output['data'])
        self.assertFalse((self.root / 'missing-authority.sqlite3').exists())


if __name__ == '__main__':
    unittest.main()
