import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared_workspace.folder_workflow import brief
from shared_workspace.cli import parser


class BriefTests(unittest.TestCase):
    def test_large_success_does_not_return_paths_or_heads(self):
        data = {'readiness': 'ready', 'event_count': 3, 'heads': {f'note-{i}': ['a'*64] for i in range(10000)},
                'excluded': [f'Raw/archive/{i}' for i in range(10000)]}
        result = brief(data)
        self.assertEqual(result['tracked_files'], 10000)
        self.assertEqual(result['counts']['excluded'], 10000)
        self.assertLess(len(json.dumps(result)), 200)

    def test_all_attention_counts_and_recovery_survive(self):
        data = {'readiness': 'partial', 'recovery_pending': True,
                'invalid_events': ['x'*1000]*30, 'conflicts': [{'path':'note'}]*20,
                'rename_divergences': ['rename'], 'warnings': ['intent']}
        result = brief(data)
        self.assertTrue(result['recovery_pending'])
        self.assertEqual(result['counts']['invalid_events'], 30)
        self.assertEqual(len(result['attention']['invalid_events']), 3)
        self.assertEqual(len(result['attention']['invalid_events'][0]), 240)
        self.assertIn('rename_divergences', result['attention'])
        self.assertIn('details', result)

    def test_sync_defaults_to_selected_cwd_not_uuid(self):
        args = parser().parse_args(['sync', '--brief'])
        self.assertEqual(args.project, '.')
        self.assertTrue(args.brief)
