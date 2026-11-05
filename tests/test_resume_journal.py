"""Target change journal schema 2 regressions (KM-002 slice 1); fake devices only."""
from __future__ import annotations

import unittest
from unittest import mock

import test_management as managed

base = managed.base
m = base.migration


class SimulatedPowerLoss(BaseException):
    """Escapes the caught-failure rollback, like a killed process or lost power."""


class JournalTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices
    execute = managed.ManagedWorkflowTests.execute
    latest = managed.ManagedWorkflowTests.latest

    def journal(self, run):
        return m.read_json(run / 'target-changes.json')

    def test_full_success_records_completed_files_and_runtime_markers(self):
        source, target = self.prepare_devices()
        project = self.root / 'project'
        code, _ = self.execute(project, [source, target], ['--mode', 'full'])
        self.assertEqual(code, 0)
        changes = self.journal(self.latest(project))
        self.assertEqual(changes['schema_version'], 2)
        self.assertTrue(changes['touched'])
        self.assertEqual(changes['completed'], changes['touched'])
        self.assertEqual(changes['runtime'], {'action': 'replace', 'state': 'identity-applied'})
        self.assertIsInstance(changes['created_dirs'], list)

    def test_library_success_has_no_runtime_marker(self):
        source, target = self.prepare_devices()
        project = self.root / 'project'
        code, _ = self.execute(project, [source, target], ['--mode', 'library', '--conflict', 'overwrite'])
        self.assertEqual(code, 0)
        changes = self.journal(self.latest(project))
        self.assertIsNone(changes['runtime'])
        self.assertEqual(changes['completed'], changes['touched'])

    def test_power_loss_mid_library_leaves_partial_path_touched_not_completed(self):
        source, target = self.prepare_devices()
        project = self.root / 'project'
        real_copy = m.copy_with_progress
        copies = []

        def copy_then_lose_power(src, dst, label, size):
            if label.startswith('Copying '):
                copies.append(label)
                if len(copies) == 2:
                    dst.write(src.read(1))
                    raise SimulatedPowerLoss()
            return real_copy(src, dst, label, size)

        with mock.patch.object(m, 'copy_with_progress', side_effect=copy_then_lose_power), \
                self.assertRaises(SimulatedPowerLoss):
            self.execute(project, [source, target], ['--mode', 'full'])
        run = self.latest(project)
        self.assertEqual(m.read_json(run / 'run.json')['status'], 'needs-recovery')
        changes = self.journal(run)
        self.assertEqual(len(changes['touched']), 2)
        self.assertEqual(changes['completed'], changes['touched'][:1])
        self.assertEqual(changes['runtime']['state'], 'identity-applied')

    def test_power_loss_during_runtime_extraction_records_extracting(self):
        source, target = self.prepare_devices()
        project = self.root / 'project'
        real_restore_zip = m.restore_zip

        def extract_or_lose_power(archive, destination):
            if '-pre-migration-' not in archive.name:
                raise SimulatedPowerLoss()
            return real_restore_zip(archive, destination)

        with mock.patch.object(m, 'restore_zip', side_effect=extract_or_lose_power), \
                self.assertRaises(SimulatedPowerLoss):
            self.execute(project, [source, target], ['--mode', 'full'])
        run = self.latest(project)
        self.assertEqual(m.read_json(run / 'run.json')['status'], 'needs-recovery')
        changes = self.journal(run)
        self.assertEqual(changes['runtime'], {'action': 'replace', 'state': 'extracting'})
        self.assertEqual((changes['touched'], changes['completed']), ([], []))
        self.assertFalse((target / '.adds/koreader').exists())

    def test_caught_failure_rollback_keeps_journal_readable(self):
        source, target = self.prepare_devices()
        before = base.tree_contents(target)
        project = self.root / 'project'
        real_diagnostics = m.device_diagnostics
        calls = []

        def fail_after_writes(mount):
            calls.append(mount)
            if len(calls) == 3:  # SOURCE, TARGET preflight, then TARGET after writes.
                raise m.MigrationError('injected')
            return real_diagnostics(mount)

        with mock.patch.object(m, 'device_diagnostics', side_effect=fail_after_writes):
            code, _ = self.execute(project, [source, target], ['--mode', 'full'])
        self.assertEqual(code, 2)
        self.assertEqual(base.tree_contents(target), before)
        changes = self.journal(self.latest(project))
        self.assertEqual(changes['schema_version'], 2)
        self.assertEqual(changes['completed'], changes['touched'])

    def test_restore_reads_legacy_schema_1_journal(self):
        source, target = self.prepare_devices()
        before = base.tree_contents(target)
        project = self.root / 'project'
        self.execute(project, [source, target], ['--mode', 'full'])
        saved = self.latest(project)
        changes = self.journal(saved)
        m.atomic_json(saved / 'target-changes.json', {
            'schema_version': 1, 'touched': changes['touched'], 'created_dirs': changes['created_dirs']})
        code, _ = self.execute(project, [target], ['--restore-run', saved.name])
        self.assertEqual(code, 0)
        self.assertEqual(base.tree_contents(target), before)
        restore_changes = self.journal(self.latest(project))
        self.assertEqual(restore_changes['schema_version'], 2)
        self.assertIsNone(restore_changes['runtime'])
        self.assertEqual(restore_changes['completed'],
                         [p for p in restore_changes['touched'] if (target / p).exists()])

    def test_restore_refuses_unknown_journal_schema_before_connecting(self):
        source, target = self.prepare_devices()
        project = self.root / 'project'
        self.execute(project, [source, target], ['--mode', 'full'])
        saved = self.latest(project)
        after = base.tree_contents(target)
        for bad in ({'schema_version': 3}, {'created_dirs': 'Books'}):
            changes = {**self.journal(saved), **bad}
            m.atomic_json(saved / 'target-changes.json', changes)
            with self.subTest(bad=bad), self.assertRaisesRegex(m.MigrationError, 'change journal'):
                self.execute(project, [target], ['--restore-run', saved.name])
        self.assertEqual(base.tree_contents(target), after)


if __name__ == '__main__':
    unittest.main()
