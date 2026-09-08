#!/usr/bin/env python3
"""Real packaged CLI proof of an accepted, recoverable selected-folder rename.

One synthetic actor, one computer, no Obsidian UI or provider actions. The fresh
output contains private credentials and recovery state. Share only report.json.
Requires Python 3.11+ and an explicitly reviewed development .pyz package.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


class Failure(Exception):
    pass


def require(condition, label):
    if not condition:
        raise Failure(label)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p.read_bytes()) if p.is_file() else 'directory'
            for p in sorted(root.rglob('*'))}


def rehearse(package, root, project_parent=None):
    started = time.monotonic()
    parent = project_parent or root / 'Private parent'
    project = parent / 'Projects' / 'Shared project'
    state = root / 'private-state'
    project.mkdir(parents=True)
    source, destination = 'Notes/Café.md', 'Archive/世界/Renamed.md'
    home = ('# Shared project\r\n[[Notes/Café#Plan|Friendly label]]\n'
            '[Markdown](Notes/Caf%C3%A9.md#Plan)\r\n[[Project alias#Plan]]\n')
    note = ('---\r\naliases: ["Project alias"]\r\ntype: decision\r\n---\r\n'
            '# Plan\r\nCafé 世界.\n[Evidence](../Evidence.md#Proof)\r\n'
            '[[Evidence#Proof|Evidence]]\n[Self](#Plan)\r\n'
            '```md\r\n[[Notes/Café]]\r\n```\n')
    evidence = '# Proof\nFixture evidence.\r\n'
    encoded_destination = 'Archive/%E4%B8%96%E7%95%8C/Renamed.md'
    expected_home = home.replace('Notes/Café#', destination + '#').replace(
        'Notes/Caf%C3%A9.md#', encoded_destination + '#').replace(
        '[[Project alias#Plan]]', '[[' + destination + '#Plan|Project alias]]')
    expected_note = note.replace('../Evidence.md#Proof', '../../Evidence.md#Proof').replace(
        '[[Evidence#Proof|Evidence]]', '[[Evidence.md#Proof|Evidence]]')
    originals = {'Home.md': home, source: note, 'Evidence.md': evidence,
                 'AGENTS.md': '# Fixture instructions\nPreserve private parent content.\r\n'}
    sentinels = {parent / 'Private.md': b'PRIVATE PARENT\r\n',
        parent / 'Home.md': b'# Outer home\n[[Projects/Shared project/Notes/Caf\xc3\xa9]]\n',
        parent / 'Parent.md': b'# Private parent backlink\n'
            b'[Original selected note](Projects/Shared%20project/Notes/Caf%C3%A9.md)\n',
        parent / 'runtime.json': b'{"private":"synthetic runtime outside project"}\n',
        project / '.obsidian/app.json': b'{"fixture_only":true}\r\n',
        project / '.shared-memory/session-private.json': b'{"fixture":"not a real credential"}\n',
        project / 'Assets/attachment.bin': b'\x00\xffSYNTHETIC PRIVATE BINARY\r\n'}
    for path, content in {**{project / name: value.encode() for name, value in originals.items()}, **sentinels}.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    report = {'schema_version': 1, 'status': 'running', 'coordination_schema': 2,
        'package_sha256': sha(package.read_bytes()), 'commands': [], 'checks': {},
        'limitations': ['One synthetic local actor; no independent human or AI-model recipient.',
            'No provider delivery, network service, Obsidian UI, or native rename validation.',
            'The product resolves unique exact frontmatter aliases; renamed links use canonical paths with preserved display labels.',
            'Product alias resolution does not establish native Obsidian alias-link compatibility.',
            'Only selected-folder backlinks are rewritten. Known outer backlink remains unchanged.',
            'Materialization uses a recoverable journal; multiple filesystem writes are not one atomic rename.',
            'Private credentials, plans and backups remain in this fixture. Only report.json is sanitized.']}
    counter, phase = 0, 'initialize'
    session_token = state / 'sessions/demo-run/session.token'

    def payload(value):
        nonlocal counter
        counter += 1
        path = root / f'private-input-{counter:03d}.json'
        path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        return path

    def cli(label, command, *options, bound=True, expected=0, code=None):
        nonlocal phase
        phase = label
        remaining = 180 - (time.monotonic() - started)
        require(remaining > 0, 'deadline')
        arguments = [sys.executable, str(package), command]
        if bound:
            arguments += [str(project), '--state-dir', str(state)]
        arguments += list(map(str, options))
        result = subprocess.run(arguments, cwd=root, capture_output=True, timeout=min(30, remaining))
        require(len(result.stdout) + len(result.stderr) <= 2 * 1024 * 1024, 'output_limit')
        item = {'step': label, 'command': command, 'expected_exit': expected, 'actual_exit': result.returncode}
        report['commands'].append(item)
        require(result.returncode == expected and not result.stderr, label)
        response = json.loads(result.stdout)
        require(response['ok'] is (expected == 0), label)
        item['code'] = response['code']
        if code:
            require(response['code'] == code, label)
        return response['data']

    def coord(label, operation, value=None, session=True):
        options = ['--session-token-file', session_token] if session else []
        return cli(label, 'coord', operation, '--payload-file', payload(value or {}), *options)

    def graph(label):
        before = inventory(project)
        value = cli(label, 'graph', project, bound=False)
        require(inventory(project) == before, 'graph_mutated_project')
        return value

    try:
        metadata = cli('package_identity', 'version', bound=False)
        report['build'] = {key: metadata[key] for key in ('product_version', 'bundle_id', 'source_revision', 'source_dirty')}
        report['package_evidence'] = 'dirty-development-build' if metadata['source_dirty'] else 'clean-recorded-source-build'
        config = payload({'person_id': 'person-demo', 'agent_id': 'agent-demo', 'policy': {}})
        initialized = cli('schema2_init', 'init', '--person', 'Synthetic reviewer', '--actor', 'demo',
            '--agent', 'Local packaged CLI rehearsal', '--purpose', 'Reviewed selected-folder rename',
            '--coordination-file', config)
        policy = coord('policy', 'policy', session=False)
        grants = payload({'ttl_seconds': 600, 'scopes': policy['policy']['session_scopes']['owner'], 'targets': ['.']})
        opened = cli('own_session', 'session-create', '--session-id', 'demo-run', '--grants-file', grants)
        require(opened['session']['actor'] == 'demo' and opened['credential_saved'], 'own_session_identity')
        coord('plan_work', 'plan', {'assignment_id': 'rename-note', 'outcome_key': 'reviewed-note-move',
            'summary': 'Move a selected note and preserve link identities', 'targets': ['.'],
            'criteria': ['Exact reviewed bytes and validated links'], 'dependencies': [], 'interface_paths': [],
            'resource_limits': {'max_files': 4, 'max_bytes': 8192, 'max_proposals': 2},
            'integration_owner': 'demo', 'policy_revision': policy['policy_revision']})
        receipt0 = cli('initial_receipt', 'receipt')
        lease = coord('acquire_work', 'acquire', {'assignment_id': 'rename-note', 'expected_generation': 0,
            'ttl_seconds': 240, 'revision': receipt0['revision'], 'files_hash': receipt0['files_hash'],
            'policy_revision': policy['policy_revision']})
        context = {'session_id': 'demo-run', 'generation': lease['generation'],
                   'input_hash': lease['input_hash'], 'policy_revision': policy['policy_revision']}
        baseline = inventory(project)
        before_graph = graph('graph_before')
        require(before_graph['diagnostics'] == [
            {'code': 'alias_requires_canonical_link', 'path': 'Home.md', 'line': 4}],
            'expected_alias_portability_notice')
        alias_edges = [edge for edge in before_graph['edges'] if edge['source'] == 'Home.md' and edge['line'] == 4]
        require(len(alias_edges) == 1, 'one_bare_alias_edge')
        alias_edge = alias_edges[0]
        require(alias_edge['target'] == source and alias_edge['status'] == 'resolved'
                and alias_edge['anchor'] == 'Plan' and alias_edge['anchor_status'] == 'resolved',
                'bare_alias_target_and_anchor')
        original_node = next(node for node in before_graph['nodes'] if node['id'] == source)
        require(original_node['aliases'] == ['Project alias'] and any(
            backlink['source'] == 'Home.md' and backlink['edge_id'] == alias_edge['id']
            and backlink['line'] == 4 for backlink in original_node['backlinks']), 'bare_alias_backlink')
        planned = cli('rename_plan', 'graph-rename-plan', '--source', source, '--destination', destination,
                      '--session-token-file', session_token)
        require(inventory(project) == baseline, 'plan_mutated_project')
        expected_changes = {source: None, destination: expected_note, 'Home.md': expected_home}
        require(planned['changes'] == expected_changes, 'reviewed_exact_rename_changes')
        require(planned['originals'][source] == note and planned['originals']['Home.md'] == home,
                'plan_originals_preserved')
        rename_options = ['--plan-id', planned['plan_id'], '--proposal-id', 'rename-proposal',
            '--assignment-id', 'rename-note', '--evidence', 'Compared exact Unicode, mixed newline and link destination bytes',
            '--coordination-file', payload(context), '--session-token-file', session_token]
        snapshot0 = coord('accepted_before_stale_probe', 'snapshot')
        stale_bytes = (evidence + 'Unsubmitted synthetic edit.\n').encode()
        (project / 'Evidence.md').write_bytes(stale_bytes)
        stale_inventory = inventory(project)
        cli('stale_local_plan_refused', 'graph-rename-draft', *rename_options, expected=4, code='rename_stale')
        require(inventory(project) == stale_inventory, 'stale_refusal_changed_local_edit')
        require(not (state / 'client/drafts/rename-proposal.json').exists(), 'stale_proposal_created')
        require(coord('accepted_after_stale_probe', 'snapshot') == snapshot0, 'stale_refusal_changed_accepted_state')
        # This temporary edit is owned by the rehearsal. Preserve its exact bytes
        # privately before restoring the accepted fixture for the successful flow.
        (root / 'preserved-stale-input.md').write_bytes(stale_bytes)
        (project / 'Evidence.md').write_bytes(evidence.encode())
        drafted = cli('rename_draft', 'graph-rename-draft', *rename_options)
        require(drafted['proposal']['changes'] == expected_changes and not drafted['project_files_changed'],
                'draft_exact_changes')
        require(inventory(project) == baseline, 'draft_mutated_project')
        cli('unaccepted_apply_refused', 'graph-rename-apply', '--plan-id', planned['plan_id'],
            '--session-token-file', session_token, expected=4, code='rename_not_accepted')
        require(inventory(project) == baseline, 'unaccepted_apply_mutated_project')
        submitted = cli('submit', 'submit', '--proposal-id', 'rename-proposal', '--session-token-file', session_token)
        require(submitted['changes'] == expected_changes, 'submitted_changes_differ')
        accepted = coord('accept_reviewed_rename', 'accept', {'proposal_id': 'rename-proposal',
            'validation': 'Independent exact content and parsed link checks', 'reason': 'Synthetic reviewed move',
            'coordination': context})
        require(accepted['accepted'] and accepted['revision'] == receipt0['revision'] + 1,
                'accepted_revision')
        require(inventory(project) == baseline, 'accept_mutated_local_project')
        applied = cli('apply_accepted', 'graph-rename-apply', '--plan-id', planned['plan_id'],
                      '--session-token-file', session_token)
        receipt = cli('exact_receipt', 'receipt')
        require(applied['byte_source'] == 'authenticated_coordinator_snapshot', 'apply_source_claim')
        require(receipt['readiness'] == 'ready' and receipt['revision'] == accepted['revision']
                and receipt['files_hash'] == accepted['files_hash'] == planned['result_files_hash'], 'exact_accepted_receipt')
        require(not (project / source).exists(), 'accepted_source_not_deleted')
        require((project / destination).read_bytes() == expected_note.encode()
                and (project / 'Home.md').read_bytes() == expected_home.encode(), 'accepted_exact_bytes')
        for content in (home, note):
            require((state / 'client/backups' / sha(content.encode())).read_bytes() == content.encode(),
                    'original_backup_not_recoverable')
        require(all(path.read_bytes() == value for path, value in sentinels.items()), 'private_sentinel_changed')
        require((project / 'Evidence.md').read_bytes() == evidence.encode()
                and (project / 'AGENTS.md').read_bytes() == originals['AGENTS.md'].encode(), 'unaffected_note_changed')
        after_graph = graph('graph_after')
        require(not after_graph['diagnostics'] and len(before_graph['edges']) == len(after_graph['edges']),
                'unexpected_final_graph_coverage')
        require(all(edge['status'] == 'resolved' and edge['anchor_status'] == 'resolved'
                    for edge in after_graph['edges']), 'unresolved_final_link_or_anchor')
        canonical_edges = [edge for edge in after_graph['edges'] if edge['source'] == 'Home.md' and edge['line'] == 4]
        require(len(canonical_edges) == 1 and canonical_edges[0]['target'] == destination,
                'alias_canonical_destination')
        moved_node = next(node for node in after_graph['nodes'] if node['id'] == destination)
        require(moved_node['aliases'] == ['Project alias'] and any(
            backlink['source'] == 'Home.md' and backlink['edge_id'] == canonical_edges[0]['id']
            and backlink['line'] == 4 for backlink in moved_node['backlinks']), 'canonical_alias_backlink')
        completed = coord('complete_work', 'complete', {'assignment_id': 'rename-note',
            'revision': receipt['revision'], 'files_hash': receipt['files_hash'],
            'evidence': 'Exact receipts, link anchors and immutable original backups checked', 'coordination': context})
        require(completed['status'] == 'completed', 'work_incomplete')
        require(sha(package.read_bytes()) == report['package_sha256'], 'package_changed')
        report.update(status='passed', project_id=initialized['project_id'], revision=receipt['revision'],
            files_hash=receipt['files_hash'], source=source, destination=destination,
            graph_before=before_graph['summary'], graph_after=after_graph['summary'],
            original_sha256={source: sha(note.encode()), 'Home.md': sha(home.encode())},
            resulting_sha256={destination: sha(expected_note.encode()), 'Home.md': sha(expected_home.encode())},
            sentinel_sha256={'selected-parent/' + path.relative_to(parent).as_posix(): sha(value)
                            for path, value in sentinels.items()},
            checks={'plan_and_draft_preserve_project': True, 'stale_local_plan_refused': True,
                'unaccepted_apply_refused': True, 'accepted_source_deleted': True,
                'bare_alias_target_anchor_backlink_resolved': True, 'alias_canonicalized_with_display_label': True,
                'destination_and_backlinks_exact': True, 'originals_recoverable_in_private_backups': True,
                'private_parent_config_runtime_attachment_preserved': True, 'links_and_anchors_resolved': True})
    except Exception:
        report.update(status='failed', failed_step=phase)
        raise Failure(phase) from None
    finally:
        report['commands_checked'] = len(report['commands'])
        report['expected_refusals'] = sum(item['expected_exit'] != 0 for item in report['commands'])
        report['elapsed_seconds'] = round(time.monotonic() - started, 3)
        serialized = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
        require(all(str(path) not in serialized for path in (root, parent, package)), 'private_path_in_report')
        for path in root.rglob('*.token'):
            require(path.read_text().strip() not in serialized, 'credential_in_report')
        (root / 'report.json').write_text(serialized, encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--project-parent', type=Path,
        help='Optional fresh synthetic parent outside output; private state and report remain in output')
    args = parser.parse_args()
    try:
        require(sys.version_info >= (3, 11), 'python_311_required')
        package = args.package.expanduser().resolve(strict=True)
        require(package.is_file() and package.suffix == '.pyz' and package.stat().st_size <= 32 * 1024 * 1024,
                'explicit_package_required')
        requested = args.output.expanduser().absolute()
        require(not os.path.lexists(requested), 'output_already_exists')
        root = requested.parent.resolve(strict=True) / requested.name
        project_parent = None
        if args.project_parent:
            selected = args.project_parent.expanduser().absolute()
            require(not os.path.lexists(selected), 'project_parent_already_exists')
            project_parent = selected.parent.resolve(strict=True) / selected.name
            require(root != project_parent and root not in project_parent.parents
                    and project_parent not in root.parents, 'separate_private_output_required')
        root.mkdir(mode=0o700)
        result = rehearse(package, root, project_parent)
        print(json.dumps({key: result[key] for key in ('status', 'commands_checked', 'expected_refusals', 'revision')}))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        label = str(error) if isinstance(error, Failure) else 'rehearsal_unavailable'
        print(json.dumps({'status': 'failed', 'reason': label}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    os.umask(0o077)
    raise SystemExit(main())
