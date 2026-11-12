"""Native Backups Verify request (KM-P1-038): typed, read-only helper IPC over the KM-010 verifier."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_management as managed
import test_verify_runs as verify_runs

base = managed.base
m = base.migration
ROOT = Path(__file__).resolve().parents[1]


class DesktopVerifyTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices
    execute = managed.ManagedWorkflowTests.execute
    latest = managed.ManagedWorkflowTests.latest
    make_runs = verify_runs.VerifyRunsTests.make_runs
    corrupt_source_payload = verify_runs.VerifyRunsTests.corrupt_source_payload

    def setUp(self):
        super().setUp()
        # The helper refuses workspaces below symbolic links (macOS temp folders use one).
        self.project = self.root.resolve() / 'project'

    def call(self, **fields):
        request = {'version': 1, 'id': 'verify-test', 'operation': 'verify', 'workspace': str(self.project), **fields}
        proc = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'bridge_desktop_helper.py')],
                              input=json.dumps(request) + '\n', capture_output=True, text=True, timeout=60)
        packets = [json.loads(line) for line in proc.stdout.splitlines()]
        self.assertTrue(packets and packets[-1]['event'] == 'result', proc.stderr[-2000:])
        self.assertTrue(all(p['version'] == 1 and p['id'] == 'verify-test' for p in packets))
        self.assertTrue(all(p['event'] in {'log', 'result'} for p in packets))
        return packets[-1], packets[:-1], proc.stdout

    def test_dependencies_are_verified_with_localized_progress_and_nothing_changes(self):
        self.make_runs()
        before = base.tree_contents(self.project)
        result, logs, raw = self.call(runID=self.reuse.name, withDependencies=True, locale='zh-Hant')
        self.assertTrue(result['ok'], result)
        data = result['data']
        self.assertTrue(data['passed'])
        self.assertEqual((data['runID'], data['withDependencies'], data['exitCode']), (self.reuse.name, True, 0))
        runs = {row['id']: row for row in data['runs']}
        self.assertEqual(set(runs), {self.full.name, self.reuse.name})
        self.assertTrue(runs[self.reuse.name]['requested'])
        self.assertEqual(runs[self.full.name]['dependencyOf'], [self.reuse.name])
        self.assertEqual(runs[self.full.name]['result'], 'verified')
        self.assertTrue(runs[self.full.name]['artifacts'])
        self.assertTrue(all(a['status'] == 'verified' and a['detail'] == '' for a in runs[self.full.name]['artifacts']))
        self.assertEqual(data['summary']['runs'], 2)
        self.assertEqual(data['summary']['failed'] + data['summary']['missing'], 0)
        self.assertTrue(any('唯讀' in packet['text'] for packet in logs))
        self.assertNotIn(str(self.root.resolve()), raw)
        self.assertEqual(base.tree_contents(self.project), before)

    def test_single_batch_without_dependencies_only_checks_that_batch(self):
        self.make_runs()
        result, _, _ = self.call(runID=self.reuse.name)
        self.assertTrue(result['ok'], result)
        self.assertEqual([row['id'] for row in result['data']['runs']], [self.reuse.name])
        self.assertFalse(result['data']['withDependencies'])

    def test_corrupted_archive_is_reported_as_failure_without_repair(self):
        self.make_runs()
        name = self.corrupt_source_payload(self.full)
        before = base.tree_contents(self.project)
        result, _, raw = self.call(runID=self.reuse.name, withDependencies=True)
        self.assertTrue(result['ok'], result)
        data = result['data']
        self.assertFalse(data['passed'])
        self.assertEqual(data['exitCode'], 1)
        full = next(row for row in data['runs'] if row['id'] == self.full.name)
        self.assertEqual(full['result'], 'failed')
        failed = [a for a in full['artifacts'] if a['status'] == 'failed']
        self.assertEqual([a['name'] for a in failed], [name])
        self.assertTrue(failed[0]['detail'])
        self.assertGreaterEqual(data['summary']['failed'], 1)
        self.assertNotIn(str(self.root.resolve()), raw)
        self.assertEqual(base.tree_contents(self.project), before)

    def test_missing_dependency_is_reported_as_missing(self):
        self.make_runs()
        self.full.rename(self.root.resolve() / 'moved-away')
        result, _, _ = self.call(runID=self.reuse.name, withDependencies=True)
        self.assertTrue(result['ok'], result)
        self.assertFalse(result['data']['passed'])
        self.assertEqual(result['data']['summary']['missing'], 1)
        missing = next(row for row in result['data']['runs'] if row['id'] == self.full.name)
        self.assertEqual((missing['result'], missing['dependencyOf']), ('missing', [self.reuse.name]))

    def test_untyped_or_unsafe_requests_refuse_before_verification(self):
        self.make_runs()
        (self.project / 'runs' / 'linked').symlink_to(self.full, target_is_directory=True)
        cases = [{'runID': '../outside'}, {'runID': self.full.name, 'withDependencies': 'yes'},
                 {'runID': self.full.name, 'locale': 'fr'}, {'runID': 'not-a-batch'}, {'runID': 'linked'},
                 {'runID': self.full.name, 'config': {'command': 'arbitrary'}}, {'runID': self.full.name, 'extra': 1},
                 {}]
        for fields in cases:
            with self.subTest(fields=fields):
                result, logs, _ = self.call(**fields)
                self.assertFalse(result['ok'])
                self.assertEqual(result['error']['code'], 'invalid_request')
        result, _, _ = self.call(runID=self.full.name, workspace='/Volumes/Example')
        self.assertFalse(result['ok'])

    def test_verify_only_fields_are_rejected_on_other_operations(self):
        for fields in [{'withDependencies': True}, {'locale': 'en'}]:
            with self.subTest(fields=fields):
                result, _, _ = self.call(operation='catalog', **fields)
                self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()
