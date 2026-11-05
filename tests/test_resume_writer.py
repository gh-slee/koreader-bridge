"""Resume writes, chain-aware rollback and restore (KM-002 slices 3-4); fake devices only."""
from __future__ import annotations

import contextlib
import io
import shutil
import unittest
from unittest import mock

import test_management as managed
from test_resume_journal import SimulatedPowerLoss
import test_resume_planner as planner

base = managed.base
m = base.migration


class ResumeWriterTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices
    execute = managed.ManagedWorkflowTests.execute
    latest = managed.ManagedWorkflowTests.latest
    resume = planner.ResumePlannerTests.resume
    interrupt = planner.ResumePlannerTests.interrupt

    def setUp(self):
        super().setUp()
        self.project = self.root / 'project'

    def devices(self):
        source, target = self.prepare_devices()
        self.original_target = base.tree_contents(target)
        # Identical copies migrated without interruption give the expected final TARGET.
        clean_source, clean_target = self.root / 'clean-source', self.root / 'clean-target'
        shutil.copytree(source, clean_source)
        shutil.copytree(target, clean_target)
        self.clean_project = self.root / 'clean-project'
        return source, target, clean_source, clean_target

    def expected(self, clean_source, clean_target, flags):
        code, _ = self.execute(self.clean_project, [clean_source, clean_target], flags)
        self.assertEqual(code, 0)
        return base.tree_contents(clean_target)

    def write_resume(self, target, run_id=None, answers=None):
        code, calls = self.resume([target], run_id=run_id, dry_run=False, answers=answers)
        run = self.latest(self.project)
        return code, run, m.read_json(run / 'run.json')

    def test_resume_after_mid_library_power_loss_matches_uninterrupted_migration(self):
        source, target, clean_source, clean_target = self.devices()
        expected = self.expected(clean_source, clean_target, ['--mode', 'full'])
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        code, run, state = self.write_resume(target)
        self.assertEqual((code, state['status'], state['operation']), (0, 'success', 'resume-migration'))
        self.assertEqual(base.tree_contents(target), expected)
        plan = m.read_json(run / 'resume-plan.json')
        changes = m.read_json(run / 'target-changes.json')
        self.assertEqual(changes['touched'], [p for p in plan['library']['partial'] + plan['library']['remaining']
                                              if p in changes['touched']])
        self.assertNotIn(plan['library']['verified'][0], changes['touched'])
        self.assertIsNone(changes['runtime'])
        self.assertTrue((run / f'koreader-migration-result-{run.name}.json').is_file())

    def test_resume_after_runtime_extraction_loss_reinstalls_runtime(self):
        source, target, clean_source, clean_target = self.devices()
        expected = self.expected(clean_source, clean_target, ['--mode', 'full'])
        self.interrupt([source, target], ['--mode', 'full'], during_extract=True)
        code, run, state = self.write_resume(target)
        self.assertEqual((code, state['status']), (0, 'success'))
        self.assertEqual(base.tree_contents(target), expected)
        self.assertEqual(m.read_device_id(target / '.adds/koreader/settings.reader.lua'), 'TARGET')
        self.assertEqual(m.read_json(run / 'target-changes.json')['runtime']['state'], 'identity-applied')

    def test_used_runtime_is_backed_up_before_replacement(self):
        source, target, clean_source, clean_target = self.devices()
        expected = self.expected(clean_source, clean_target, ['--mode', 'full'])
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        base.write_file(target / '.adds/koreader/history.lua', b'return {}')
        code, run, _ = self.write_resume(target)
        self.assertEqual(code, 0)
        self.assertEqual(base.tree_contents(target), expected)
        snapshot = run / 'koreader-before-resume.zip'
        self.assertTrue(snapshot.is_file())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(m.verify_run_command(self.project, run.name), 0)

    def test_library_resume_completes_without_touching_runtime(self):
        source, target, clean_source, clean_target = self.devices()
        flags = ['--mode', 'library', '--conflict', 'overwrite']
        expected = self.expected(clean_source, clean_target, flags)
        self.interrupt([source, target], flags, at_copy=1)
        code, _, _ = self.write_resume(target)
        self.assertEqual(code, 0)
        self.assertEqual(base.tree_contents(target), expected)

    def test_failed_resume_rolls_back_to_original_pre_migration_state(self):
        source, target, _, _ = self.devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        with mock.patch.object(m, 'device_diagnostics', side_effect=m.MigrationError('injected after writes')):
            code, run, state = self.write_resume(target)
        self.assertEqual((code, state['status']), (2, 'rolled-back'))
        self.assertEqual(base.tree_contents(target), self.original_target)

    def test_cancel_at_final_confirmation_changes_nothing(self):
        source, target, _, _ = self.devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        before = base.tree_contents(target)
        code, run, state = self.write_resume(target, answers=[True, False])
        self.assertEqual((code, state['status']), (0, 'cancelled'))
        self.assertEqual(base.tree_contents(target), before)

    def test_restore_after_resume_returns_original_and_superseded_batch_is_refused(self):
        source, target, _, _ = self.devices()
        self.interrupt([source, target], ['--mode', 'full'], at_copy=2)
        original_batch = self.batch
        code, resumed, _ = self.write_resume(target)
        self.assertEqual(code, 0)
        with self.assertRaisesRegex(m.MigrationError, 'restore run'):
            self.execute(self.project, [target], ['--restore-run', original_batch.name])
        code, _ = self.execute(self.project, [target], ['--restore-run', resumed.name])
        self.assertEqual(code, 0)
        self.assertEqual(base.tree_contents(target), self.original_target)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            m.print_catalog(m.run_catalog(self.project))
        self.assertIn(f'resumed by {resumed.name}', out.getvalue())

    def test_interrupted_resume_can_be_resumed_and_restored(self):
        source, target, clean_source, clean_target = self.devices()
        expected = self.expected(clean_source, clean_target, ['--mode', 'full'])
        self.interrupt([source, target], ['--mode', 'full'], at_copy=1)
        first = self.batch
        real_copy, copies = m.copy_with_progress, []

        def lose_power_on_second_copy(src, dst, label, size):
            if label.startswith('Copying '):
                copies.append(label)
                if len(copies) == 2:
                    raise SimulatedPowerLoss()
            return real_copy(src, dst, label, size)

        with mock.patch.object(m, 'copy_with_progress', side_effect=lose_power_on_second_copy), \
                self.assertRaises(SimulatedPowerLoss):
            self.resume([target], dry_run=False)
        second = self.latest(self.project)
        self.assertEqual(m.read_json(second / 'run.json')['status'], 'needs-recovery')
        with self.assertRaisesRegex(m.MigrationError, 'already resumed'):
            self.resume([target], run_id=first.name, dry_run=False)
        code, third, state = self.write_resume(target, run_id=second.name)
        self.assertEqual((code, state['status']), (0, 'success'))
        self.assertEqual(base.tree_contents(target), expected)
        self.assertEqual(m.read_json(third / 'resume-plan.json')['chain'], [first.name, second.name])
        self.assertTrue({first.name, second.name} <= set(state['dependencies']))
        code, _ = self.execute(self.project, [target], ['--restore-run', third.name])
        self.assertEqual(code, 0)
        self.assertEqual(base.tree_contents(target), self.original_target)


if __name__ == '__main__':
    unittest.main()
