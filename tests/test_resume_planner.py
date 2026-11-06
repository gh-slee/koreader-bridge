"""Read-only resume planner regressions (KM-002 slice 2); fake devices only."""
from __future__ import annotations

import contextlib
import io
import unittest
from unittest import mock

import test_management as managed
from test_resume_journal import SimulatedPowerLoss

base = managed.base
m = base.migration


class ResumePlannerTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices
    execute = managed.ManagedWorkflowTests.execute
    latest = managed.ManagedWorkflowTests.latest

    def setUp(self):
        super().setUp()
        self.project = self.root / 'project'

    def resume(self, devices, *flags, run_id=None):
        argv = ['tool', '--backup-dir', str(self.project), '--resume-run', run_id or self.batch.name, '--dry-run', *flags]
        with mock.patch('sys.argv', argv), mock.patch.object(m, 'require_macos_tools'), \
                mock.patch.object(m, 'run_with_spinner', side_effect=base.fake_ditto), \
                mock.patch.object(m, 'wait_for_single_kobo', side_effect=devices) as wait, \
                mock.patch.object(m, 'safe_eject'), \
                mock.patch.object(m, 'prompt_yes_no', return_value=True), \
                mock.patch('builtins.input', return_value=''):
            try:
                return m.main(), wait.call_count
            finally:
                self.wait_calls = wait.call_count

    def interrupt(self, devices, flags, at_copy=None, during_extract=False):
        real_copy, real_extract, copies = m.copy_with_progress, m.restore_zip, []

        def copy(src, dst, label, size):
            if at_copy and label.startswith('Copying '):
                copies.append(label)
                if len(copies) == at_copy:
                    dst.write(src.read(1))
                    raise SimulatedPowerLoss()
            return real_copy(src, dst, label, size)

        def extract(archive, destination):
            if during_extract and '-pre-migration-' not in archive.name:
                raise SimulatedPowerLoss()
            return real_extract(archive, destination)

        with mock.patch.object(m, 'copy_with_progress', side_effect=copy), \
                mock.patch.object(m, 'restore_zip', side_effect=extract), \
                self.assertRaises(SimulatedPowerLoss):
            self.execute(self.project, devices, flags)
        self.batch = self.latest(self.project)
        self.assertEqual(m.read_json(self.batch / 'run.json')['status'], 'needs-recovery')

    def preview(self, target, *flags):
        before = base.tree_contents(target)
        code, calls = self.resume([target], *flags)
        self.assertEqual((code, calls), (0, 1))
        self.assertEqual(base.tree_contents(target), before)
        run = self.latest(self.project)
        state = m.read_json(run / 'run.json')
        self.assertEqual((state['operation'], state['status']), ('resume-migration', 'audited'))
        self.assertIn(self.batch.name, state['dependencies'])
        self.assertEqual(m.read_json(run / 'resume-reference.json'), {'run_id': self.batch.name})
        return run, m.read_json(run / 'resume-plan.json')

    def test_mid_library_power_loss_keeps_verified_runtime_and_classifies_files(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        touched = m.read_json(self.batch / 'target-changes.json')['touched']
        run, plan = self.preview(target)
        self.assertEqual(plan['runtime'], {'action': 'keep', 'reason': None, 'snapshot_before_replace': False})
        self.assertEqual(plan['library']['verified'], touched[:1])
        self.assertEqual(plan['library']['partial'], touched[1:2])
        self.assertEqual(len(plan['library']['remaining']), 1)
        self.assertEqual(plan['library']['drifted'], [])
        self.assertEqual((plan['interrupted_phase'], plan['identity_mode']), ('copying-library', 'preserve'))
        protected = {r['run_id'] for r in m.cleanup_plan(self.project, 1)['protected']}
        self.assertIn(self.batch.name, protected)
        self.assertNotIn('TARGET', (run / 'resume-plan.json').read_text())

    def test_interruption_during_runtime_extraction_replaces_runtime(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], during_extract=True)
        _, plan = self.preview(target)
        self.assertEqual(plan['runtime'], {'action': 'replace', 'reason': 'interrupted_during_replacement',
                                           'snapshot_before_replace': False})
        self.assertEqual(plan['counts']['partial'] + plan['counts']['drifted'], 0)
        self.assertGreater(plan['runtime_bytes'], 0)

    def test_runtime_used_after_interruption_needs_snapshot_then_replace(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        base.write_file(target / '.adds/koreader/history.lua', b'return {}')
        _, plan = self.preview(target)
        self.assertEqual(plan['runtime'], {'action': 'replace', 'reason': 'runtime_changed_after_interruption',
                                           'snapshot_before_replace': True})

    def test_runtime_with_wrong_identity_is_not_kept(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        settings = target / '.adds/koreader/settings.reader.lua'
        m.set_device_id(settings, 'SOMEONE-ELSE')
        _, plan = self.preview(target)
        self.assertEqual(plan['runtime']['action'], 'replace')

    def test_drift_on_untouched_path_refuses_and_names_it(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        changes = m.read_json(self.batch / 'target-changes.json')
        plan = m.read_json(self.batch / f'koreader-scan-{self.batch.name}.json')['plan']
        untouched = next(p for p in plan['copy'] if p not in changes['touched'])
        base.write_file(target / untouched, b'edited on the reader after the interruption')
        before = base.tree_contents(target)
        with self.assertRaisesRegex(m.MigrationError, 'Resume refused'):
            self.resume([target])
        self.assertEqual(base.tree_contents(target), before)
        run = self.latest(self.project)
        self.assertEqual(m.read_json(run / 'run.json')['status'], 'failed')
        self.assertEqual(m.read_json(run / 'resume-plan.json')['library']['drifted'], [untouched])

    def test_library_mode_interruption_has_no_runtime_action(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'library', '--conflict', 'overwrite'], at_copy=1)
        _, plan = self.preview(target)
        self.assertEqual(plan['runtime']['action'], 'none')
        self.assertEqual(plan['counts']['partial'], 1)

    def test_saved_source_batch_records_source_chain(self):
        source, target = self.prepare_devices()
        self.execute(self.project, [source, target], ['--mode', 'full'])
        original = self.latest(self.project)
        base.write_file(target / 'Books/book.epub', b'changed before reuse')
        self.interrupt([target], ['--from-run', original.name], at_copy=1)
        run, plan = self.preview(target)
        self.assertEqual(plan['source_run'], original.name)
        self.assertEqual(sorted(m.read_json(run / 'run.json')['dependencies']), sorted([original.name, self.batch.name]))

    def test_wrong_reader_is_refused_without_changes(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        before = base.tree_contents(source)
        with self.assertRaisesRegex(m.MigrationError, 'changed|different'):
            self.resume([source])
        self.assertEqual(base.tree_contents(source), before)

    def test_tampered_source_archive_is_refused_before_connecting(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        archive = next(p for p in self.batch.glob('library-*.zip') if '-pre-migration-' not in p.name)
        data = bytearray(archive.read_bytes())
        data[-30] ^= 1
        archive.write_bytes(bytes(data))
        with self.assertRaises(m.MigrationError):
            self.resume([target])
        self.assertEqual(self.wait_calls, 0)

    def test_ineligible_runs_are_refused_before_connecting(self):
        source, target = self.prepare_devices()
        self.execute(self.project, [source, target], ['--mode', 'full'])
        self.batch = self.latest(self.project)
        with self.assertRaisesRegex(m.MigrationError, 'status is success'):
            self.resume([target])
        self.assertEqual(self.wait_calls, 0)

    def test_superseded_batch_and_target_model_mismatch_are_refused(self):
        source, target = self.prepare_devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        with self.assertRaisesRegex(m.MigrationError, 'target-model'):
            self.resume([target], '--target-model', m.MODEL_CLARA)
        run, _ = self.preview(target)
        state = m.read_json(run / 'run.json')
        state['status'] = 'success'
        m.atomic_json(run / 'run.json', state)
        with self.assertRaisesRegex(m.MigrationError, 'already resumed'):
            self.resume([target])

    def test_cli_requires_dry_run_and_rejects_scope_options(self):
        runs_before = set((self.project / 'runs').glob('*')) if (self.project / 'runs').exists() else set()
        for flags in (['--resume-run', 'x'], ['--resume-run', 'x', '--dry-run', '--mode', 'full'],
                      ['--resume-run', 'x', '--dry-run', '--no-reading-data']):
            argv = ['tool', '--backup-dir', str(self.project), *flags]
            with self.subTest(flags=flags), mock.patch('sys.argv', argv), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                m.main()
        runs_after = set((self.project / 'runs').glob('*')) if (self.project / 'runs').exists() else set()
        self.assertEqual(runs_after, runs_before)


if __name__ == '__main__':
    unittest.main()
