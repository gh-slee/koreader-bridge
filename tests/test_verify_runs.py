"""Multi-batch, dependency and JSON verification (P1-4, KM-010 extension); fake devices only."""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import unittest
from unittest import mock

import test_management as managed

base = managed.base
m = base.migration


class VerifyRunsTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices
    execute = managed.ManagedWorkflowTests.execute
    latest = managed.ManagedWorkflowTests.latest

    def setUp(self):
        super().setUp()
        self.project = self.root / 'project'

    def make_runs(self):
        source, target = self.prepare_devices()
        self.execute(self.project, [source, target], ['--mode', 'full'])
        self.full = self.latest(self.project)
        self.execute(self.project, [target], ['--from-run', self.full.name])
        self.reuse = self.latest(self.project)
        self.assertEqual(m.read_json(self.reuse / 'run.json')['status'], 'success')

    def verify(self, *flags):
        out, err = io.StringIO(), io.StringIO()
        argv = ['tool', '--backup-dir', str(self.project), *flags]
        with mock.patch('sys.argv', argv), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = m.main()
        return code, out.getvalue(), err.getvalue()

    def corrupt_source_payload(self, run):
        archive = next(p for p in run.glob('library-*.zip') if '-pre-migration-' not in p.name)
        data = bytearray(archive.read_bytes())
        data[-30] ^= 1
        archive.write_bytes(bytes(data))
        return archive.name

    def test_repeated_verify_run_checks_each_batch_and_changes_nothing(self):
        self.make_runs()
        before = base.tree_contents(self.project)
        code, out, _ = self.verify('--verify-run', self.full.name, '--verify-run', self.reuse.name)
        self.assertEqual(code, 0)
        self.assertIn(self.full.name, out)
        self.assertIn(self.reuse.name, out)
        self.assertIn('2 batches checked, 0 with problems', out)
        self.assertEqual(base.tree_contents(self.project), before)

    def test_single_run_output_is_unchanged(self):
        self.make_runs()
        code, out, _ = self.verify('--verify-run', self.full.name)
        self.assertEqual(code, 0)
        self.assertIn('Verification finished:', out)
        self.assertNotIn('All verification finished', out)

    def test_dependencies_are_followed_and_reported_as_json(self):
        self.make_runs()
        code, out, err = self.verify('--verify-run', self.reuse.name, '--with-dependencies', '--json')
        self.assertEqual(code, 0)
        report = json.loads(out)
        self.assertEqual((report['schema_version'], report['operation']), (1, 'verify-runs'))
        runs = {entry['run_id']: entry for entry in report['runs']}
        self.assertEqual(set(runs), {self.full.name, self.reuse.name})
        self.assertTrue(runs[self.reuse.name]['requested'])
        self.assertEqual(runs[self.full.name]['dependency_of'], [self.reuse.name])
        self.assertEqual(runs[self.full.name]['result'], 'verified')
        self.assertEqual(report['summary']['failed'] + report['summary']['missing'], 0)
        self.assertNotIn(str(self.root), out)
        self.assertIn('needed by', err)

    def test_verify_all_reports_failures_in_english_json_and_exits_1(self):
        self.make_runs()
        broken = self.corrupt_source_payload(self.full)
        code, out, _ = self.verify('--locale', 'zh-Hant', '--verify-all', '--json')
        self.assertEqual(code, 1)
        report = json.loads(out)
        runs = {entry['run_id']: entry for entry in report['runs']}
        self.assertEqual(runs[self.full.name]['result'], 'failed')
        self.assertEqual(runs[self.reuse.name]['result'], 'verified')  # its own TARGET backups
        [failure] = [a for a in runs[self.full.name]['artifacts'] if a['status'] == 'failed']
        self.assertEqual(failure['name'], broken)
        self.assertTrue(failure['detail'].isascii())
        self.assertEqual(report['summary']['failed'], 1)

    def test_missing_dependency_fails(self):
        self.make_runs()
        shutil.rmtree(self.full)
        code, out, _ = self.verify('--verify-run', self.reuse.name, '--with-dependencies')
        self.assertEqual(code, 1)
        self.assertIn(f'batch {self.full.name}, needed by {self.reuse.name}, is missing', out)

    def test_resume_chain_dependencies_are_followed(self):
        run = self.project / 'runs' / 'resume'
        original = self.project / 'runs' / 'original'
        for path in (run, original):
            path.mkdir(parents=True)
        m.atomic_json(run / 'resume-reference.json', {'run_id': 'original'})
        self.assertEqual(m.run_dependency_names(run), ['original'])
        code, out, _ = self.verify('--verify-run', 'resume', '--with-dependencies', '--json')
        self.assertEqual(code, 0)
        self.assertEqual([e['run_id'] for e in json.loads(out)['runs']], ['resume', 'original'])

    def test_empty_project_and_option_misuse(self):
        code, out, _ = self.verify('--verify-all')
        self.assertEqual(code, 0)
        self.assertIn('No saved batches', out)
        for flags in (['--json'], ['--with-dependencies', '--list-runs'], ['--verify-all', '--mode', 'full'],
                      ['--verify-all', '--verify-run', 'x']):
            with self.subTest(flags=flags), self.assertRaises(SystemExit):
                self.verify(*flags)

    def test_unknown_requested_batch_is_an_error_before_any_check(self):
        with self.assertRaises(m.MigrationError):
            self.verify('--verify-run', 'does-not-exist')


if __name__ == '__main__':
    unittest.main()
