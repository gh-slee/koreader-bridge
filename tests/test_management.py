"""Run-management, saved migration, restore and cleanup regressions; fake devices only."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import test_migration as base
m = base.migration


class ManagedWorkflowTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices

    def execute(self, project, devices, flags):
        argv = ['tool', '--backup-dir', str(project)] + flags
        if '--restore-run' not in flags:
            argv += ['--source-model', m.MODEL_CLARA, '--target-model', m.MODEL_LIBRA]
        with mock.patch('sys.argv', argv), mock.patch.object(m, 'require_macos_tools'), \
             mock.patch.object(m, 'run_with_spinner', side_effect=base.fake_ditto), \
             mock.patch.object(m, 'wait_for_single_kobo', side_effect=devices) as wait, \
             mock.patch.object(m, 'safe_eject'), mock.patch.object(m, 'choose', return_value='1'), \
             mock.patch.object(m, 'choose_identity_mode', return_value='preserve'), \
             mock.patch.object(m, 'prompt_yes_no', return_value=True), mock.patch('builtins.input', return_value=''):
            code = m.main()
            return code, wait.call_count

    def latest(self, project):
        return max((project/'runs').iterdir(), key=lambda p: p.stat().st_mtime_ns)

    def test_full_status_difference_and_target_only_are_recorded(self):
        source, target = self.prepare_devices()
        base.write_file(target/'Books/unrelated.sdr/metadata.pdf.lua', b'target only progress')
        before = base.tree_contents(source)
        project = self.root/'project'
        code, calls = self.execute(project, [source, target], ['--mode', 'full'])
        self.assertEqual((code, calls), (0, 2))
        run = self.latest(project)
        state = m.read_json(run/'run.json')
        self.assertEqual(state['status'], 'success')
        self.assertTrue(state['target_modified'])
        diff = m.read_json(run/'difference.json')
        only = {f['path'] for f in diff['files']['target_only']}
        self.assertEqual(only, {'Books/unrelated.pdf', 'Books/unrelated.sdr/metadata.pdf.lua'})
        group = next(g for g in diff['book_groups'] if g['book']=='Books/unrelated.pdf')
        self.assertEqual(len(group['sidecars']), 1)
        self.assertIn('OVERWRITE', (run/'difference.txt').read_text())
        self.assertTrue((run/'target-snapshot.json').is_file())
        self.assertEqual(base.tree_contents(source), before)

    def test_saved_source_reuses_archives_and_connects_only_target(self):
        source, target = self.prepare_devices()
        project = self.root/'project'
        self.execute(project, [source, target], ['--mode', 'full'])
        saved = self.latest(project)
        base.write_file(target/'Books/book.epub', b'different again')
        base.write_file(target/'Books/keep.pdf', b'keep')
        with mock.patch.object(m, 'create_archive', wraps=m.create_archive) as archive:
            code, calls = self.execute(project, [target], ['--from-run', saved.name])
        self.assertEqual((code, calls), (0, 1))
        new = self.latest(project)
        state = m.read_json(new/'run.json')
        self.assertEqual(state['dependencies'], [saved.name])
        self.assertEqual(state['status'], 'success')
        self.assertEqual((target/'Books/book.epub').read_bytes(), b'new book')
        self.assertEqual((target/'Books/keep.pdf').read_bytes(), b'keep')
        self.assertTrue(all(call.args[0]==target/'.adds/koreader' for call in archive.call_args_list))
        self.assertFalse(any('-pre-migration-' not in p.name for p in new.glob('*.zip')))

    def test_restore_target_snapshot_is_exact_and_has_undo_backups(self):
        source, target = self.prepare_devices()
        before = base.tree_contents(target)
        project = self.root/'project'
        self.execute(project, [source, target], ['--mode', 'full'])
        saved = self.latest(project)
        self.assertNotEqual(base.tree_contents(target), before)
        code, calls = self.execute(project, [target], ['--restore-run', saved.name])
        self.assertEqual((code, calls), (0, 1))
        self.assertEqual(base.tree_contents(target), before)
        run = self.latest(project)
        self.assertEqual(m.read_json(run/'run.json')['status'], 'success')
        self.assertTrue((run/'koreader-before-restore.zip').is_file())
        self.assertTrue((run/'restore-result.json').is_file())

    def test_numbering_reset_reuses_and_restores_supported_higher_version_snapshots(self):
        source, target = self.prepare_devices()
        source_before, target_before = base.tree_contents(source), base.tree_contents(target)
        project = self.root/'project'
        with mock.patch.object(m, 'VERSION', '3.3.0-dev.6'):
            self.execute(project, [source, target], ['--mode', 'full'])
        saved = self.latest(project)
        self.assertEqual(m.read_json(saved/'run.json')['tool_version'], '3.3.0-dev.6')
        artifacts = {p.name: p.read_bytes() for p in saved.iterdir()
                     if p.suffix == '.zip' or p.name.endswith('.manifest.json')}
        base.write_file(target/'Books/book.epub', b'changed after migration')
        code, calls = self.execute(project, [target], ['--from-run', saved.name])
        self.assertEqual((code, calls), (0, 1))
        self.assertEqual((target/'Books/book.epub').read_bytes(), b'new book')
        self.assertEqual(m.read_json(self.latest(project)/'run.json')['tool_version'], m.VERSION)
        code, calls = self.execute(project, [target], ['--restore-run', saved.name])
        self.assertEqual((code, calls), (0, 1))
        self.assertEqual(base.tree_contents(target), target_before)
        self.assertEqual(base.tree_contents(source), source_before)
        self.assertEqual({name: (saved/name).read_bytes() for name in artifacts}, artifacts)
        self.assertEqual(m.read_json(saved/'run.json')['tool_version'], '3.3.0-dev.6')

    def test_restore_dry_run_never_changes_device(self):
        source, target = self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        before=base.tree_contents(target)
        code,_=self.execute(project,[target],['--restore-run',saved.name,'--dry-run'])
        self.assertEqual(code,0)
        self.assertEqual(base.tree_contents(target),before)
        run=self.latest(project)
        self.assertEqual(m.read_json(run/'run.json')['status'],'audited')
        self.assertFalse(list(run.glob('*.zip')))

    def test_saved_source_dry_run_never_changes_device(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        before=base.tree_contents(target)
        code,calls=self.execute(project,[target],['--from-run',saved.name,'--dry-run'])
        self.assertEqual((code,calls),(0,1))
        self.assertEqual(base.tree_contents(target),before)
        self.assertFalse(list(self.latest(project).glob('*.zip')))

    def test_restore_wrong_device_rejected_before_modification(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        before=base.tree_contents(source)
        with self.assertRaisesRegex(m.MigrationError,'changed'):
            self.execute(project,[source],['--restore-run',saved.name])
        self.assertEqual(base.tree_contents(source),before)
        self.assertEqual(m.read_json(self.latest(project)/'run.json')['status'],'failed')

    def test_saved_corrupt_archive_is_rejected_before_any_device_connection(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        desc=m.read_json(saved/'source-snapshot.json')
        with (saved/desc['payload']['archive']).open('ab') as stream:
            stream.write(b'corrupt')
        with mock.patch.object(m,'wait_for_single_kobo') as wait:
            with self.assertRaisesRegex(m.MigrationError,'checksum'):
                self.execute(project,[],['--from-run',saved.name])
            wait.assert_not_called()

    def test_legacy_cancelled_source_run_can_be_reused_without_target_writes(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        (saved/'source-snapshot.json').unlink()
        before=base.tree_contents(target)
        code,calls=self.execute(project,[target],['--from-run',saved.name,'--dry-run'])
        self.assertEqual((code,calls),(0,1))
        self.assertEqual(base.tree_contents(target),before)

    def test_restore_failure_rolls_back_to_pre_restore_state(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        before=base.tree_contents(target)
        original=m.restore_payload
        calls=0
        def injected(*args,**kwargs):
            nonlocal calls
            calls+=1
            original(*args,**kwargs)
            if calls==1:
                raise m.MigrationError('injected restore failure')
        with mock.patch.object(m,'restore_payload',side_effect=injected):
            code,_=self.execute(project,[target],['--restore-run',saved.name])
        self.assertEqual(code,2)
        self.assertEqual(base.tree_contents(target),before)
        self.assertEqual(m.read_json(self.latest(project)/'run.json')['status'],'rolled-back')

    def test_migration_failure_state_is_rolled_back(self):
        source,target=self.prepare_devices()
        before=base.tree_contents(target)
        project=self.root/'project'
        original=m.restore_payload
        calls=0
        def injected(*args,**kwargs):
            nonlocal calls
            calls+=1
            original(*args,**kwargs)
            if calls==1: raise m.MigrationError('test failure')
        with mock.patch.object(m,'restore_payload',side_effect=injected):
            code,_=self.execute(project,[source,target],['--mode','full'])
        self.assertEqual(code,2)
        self.assertEqual(base.tree_contents(target),before)
        state=m.read_json(self.latest(project)/'run.json')
        self.assertEqual(state['status'],'rolled-back')

    def test_cancelled_and_audited_states_are_not_success(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        with mock.patch.object(m,'migrate',side_effect=m.MigrationCancelled('cancelled')):
            code,_=self.execute(project,[],['--mode','full'])
        self.assertEqual(code,0)
        self.assertEqual(m.read_json(self.latest(project)/'run.json')['status'],'cancelled')
        code,_=self.execute(project,[source,target],['--mode','full','--dry-run'])
        self.assertEqual(code,0)
        self.assertEqual(m.read_json(self.latest(project)/'run.json')['status'],'audited')

    def test_saved_library_preserves_runtime_and_restores_its_snapshot(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        before=base.tree_contents(target)
        self.execute(project,[source,target],['--mode','library','--books','--fonts'])
        saved=self.latest(project)
        snapshot=m.read_json(saved/'source-snapshot.json')
        self.assertIsNone(snapshot['koreader'])
        self.assertEqual((target/'.adds/koreader/reader.lua').read_bytes(),b'target runtime')
        code,calls=self.execute(project,[target],['--from-run',saved.name,'--mode','library'])
        self.assertEqual((code,calls),(0,1))
        self.assertEqual((target/'.adds/koreader/docsettings/mnt/onboard/Books/book.sdr/metadata.epub.lua').read_bytes(),b'central reading progress')
        code,_=self.execute(project,[target],['--restore-run',saved.name])
        self.assertEqual(code,0)
        self.assertEqual(base.tree_contents(target),before)

    def test_saved_koreader_copies_only_runtime(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        books_before=base.tree_contents(target/'Books')
        self.execute(project,[source,target],['--mode','koreader'])
        saved=self.latest(project)
        self.assertIsNone(m.read_json(saved/'source-snapshot.json')['payload'])
        code,calls=self.execute(project,[target],['--from-run',saved.name])
        self.assertEqual((code,calls),(0,1))
        self.assertEqual(base.tree_contents(target/'Books'),books_before)

    def test_full_snapshot_cannot_silently_be_reused_as_library_without_central_data(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        before=base.tree_contents(target)
        with self.assertRaisesRegex(m.MigrationError,'LIBRARY-captured'):
            self.execute(project,[],['--from-run',saved.name,'--mode','library'])
        self.assertEqual(base.tree_contents(target),before)

    def test_reused_source_run_can_be_selected_again_via_reference(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        first=self.latest(project)
        self.execute(project,[target],['--from-run',first.name])
        second=self.latest(project)
        code,calls=self.execute(project,[target],['--from-run',second.name,'--dry-run'])
        self.assertEqual((code,calls),(0,1))
        dependencies=m.read_json(self.latest(project)/'run.json')['dependencies']
        self.assertEqual(set(dependencies),{first.name,second.name})

    def test_rollback_failure_records_needs_recovery(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        with mock.patch.object(m,'restore_payload',side_effect=m.MigrationError('copy failed')), \
             mock.patch.object(m,'rollback_target',side_effect=m.MigrationError('restore failed')):
            code,_=self.execute(project,[source,target],['--mode','full'])
        self.assertEqual(code,3)
        self.assertEqual(m.read_json(self.latest(project)/'run.json')['status'],'needs-recovery')

    def test_manually_confirmed_model_is_saved_when_device_log_detection_is_missing(self):
        source,target=self.prepare_devices()
        (source/'.adds/koreader/crash.log').unlink()
        (target/'.adds/koreader/crash.log').unlink()
        before=base.tree_contents(target)
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        saved=self.latest(project)
        self.assertIsNone(m.read_json(saved/'source-snapshot.json')['device']['detected_model'])
        self.assertEqual(m.read_json(saved/'source-snapshot.json')['confirmed_model'],m.MODEL_CLARA)
        self.assertEqual(m.read_json(saved/'target-snapshot.json')['confirmed_model'],m.MODEL_LIBRA)
        self.execute(project,[target],['--from-run',saved.name,'--dry-run'])
        code,_=self.execute(project,[target],['--restore-run',saved.name])
        self.assertEqual(code,0)
        self.assertEqual(base.tree_contents(target),before)

    def test_target_only_scan_handles_missing_selected_root(self):
        source,target=self.prepare_devices()
        scan,_=m.scan_payload(source,True,False,include_dirs=['Books'])
        manifest=m.hash_payload(source,scan)
        for p in (target/'Books').rglob('*'):
            if p.is_file(): p.unlink()
        (target/'Books').rmdir()
        plan=m.plan_payload(target,manifest)
        diff=m.build_difference_report(target,manifest['files'],plan,True,False,{'include_dirs':['Books']})
        self.assertEqual(diff['files']['target_only'],[])


class LockAndCatalogTests(base.MigrationTestCase):
    def make_run(self,project,name,status='success',dependencies=None,fingerprint=None):
        run=project/'runs'/name
        run.mkdir(parents=True)
        m.atomic_json(run/'run.json',{'status':status,'run_id':name,'ended_at':name,
            'dependencies':dependencies or [],'target_fingerprint':fingerprint})
        (run/'archive.zip').write_bytes(b'fixture')
        return run

    def test_real_cross_process_lock_and_stale_release(self):
        lock=self.root/'lock'
        code='import fcntl,sys; f=open(sys.argv[1],"a+"); fcntl.flock(f,fcntl.LOCK_EX); print("ready",flush=True); sys.stdin.read(1)'
        proc=subprocess.Popen([sys.executable,'-c',code,str(lock)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        try:
            self.assertEqual(proc.stdout.readline().strip(),'ready')
            with self.assertRaisesRegex(m.MigrationError,'busy'):
                with m.FileLock(lock,'test'): pass
        finally:
            proc.terminate()
            proc.wait(timeout=5)
            proc.stdin.close()
            proc.stdout.close()
        with m.FileLock(lock,'test'): pass
        self.assertTrue(lock.exists())

    def test_device_fingerprint_locks_across_different_mounts(self):
        one,two=self.root/'one',self.root/'two'
        one.mkdir();two.mkdir()
        left,right=m.DeviceLocks(),m.DeviceLocks()
        fingerprint=hashlib.sha256(str(self.root).encode()).hexdigest()
        try:
            left.acquire(one,fingerprint)
            with self.assertRaisesRegex(m.MigrationError,'busy'):
                right.acquire(two,fingerprint)
        finally:
            left.close();right.close()

    def test_interrupted_state_reconciles_based_on_target_changes(self):
        project=self.root/'project'
        a=self.make_run(project,'a','running')
        b=self.make_run(project,'b','running')
        state=m.read_json(b/'run.json');state['target_modified']=True;m.atomic_json(b/'run.json',state)
        with m.FileLock(project/'.project.lock','project'):
            m.reconcile_interrupted_runs(project)
        self.assertEqual(m.read_json(a/'run.json')['status'],'interrupted')
        self.assertEqual(m.read_json(b/'run.json')['status'],'needs-recovery')

    def test_cleanup_protects_recent_dependencies_unknown_failed_and_last_device_backup(self):
        project=self.root/'project'
        self.make_run(project,'01',fingerprint='only-other-device')
        self.make_run(project,'02')
        self.make_run(project,'03','failed')
        self.make_run(project,'04','needs-recovery')
        self.make_run(project,'05',dependencies=['02'])
        self.make_run(project,'06')
        self.make_run(project,'07')
        self.make_run(project,'08')
        legacy=project/'runs'/'legacy';legacy.mkdir()
        plan=m.cleanup_plan(project,2)
        eligible={r['run_id'] for r in plan['candidates']}
        self.assertEqual(eligible,{'05','06'})
        self.assertEqual(plan['reclaimable_bytes'],sum(r['bytes'] for r in plan['candidates']))
        protected={r['run_id'] for r in plan['protected']}
        self.assertTrue({'01','02','03','04','07','08','legacy'}<=protected)

    def test_cleanup_preview_and_cancel_never_delete(self):
        project=self.root/'project'
        self.make_run(project,'01');self.make_run(project,'02');self.make_run(project,'03')
        before=base.tree_contents(project)
        self.assertEqual(m.cleanup_command(project,2,[]),0)
        self.assertEqual(base.tree_contents(project),before)
        with mock.patch('builtins.input',return_value='no'):
            self.assertEqual(m.cleanup_command(project,2,['01']),0)
        self.assertTrue(((project/'runs/01').resolve()).exists())

    def test_explicit_cleanup_deletes_only_selected_eligible_batch(self):
        project=self.root/'project'
        old=self.make_run(project,'01');self.make_run(project,'02');self.make_run(project,'03')
        with mock.patch('builtins.input',return_value='DELETE 01'):
            self.assertEqual(m.cleanup_command(project,2,['01']),0)
        self.assertFalse(old.exists())
        self.assertTrue((project/'runs/02').exists())
        self.assertTrue((project/'runs/03').exists())

    def test_cleanup_refuses_protected_or_symlink_batches(self):
        project=self.root/'project'
        old=self.make_run(project,'01');self.make_run(project,'02');self.make_run(project,'03')
        with mock.patch('builtins.input',return_value='DELETE 03'):
            with self.assertRaises(m.MigrationError):m.cleanup_command(project,2,['03'])
        (old/'link').symlink_to(self.root/'outside')
        with mock.patch('builtins.input',return_value='DELETE 01'):
            with self.assertRaises(m.MigrationError):m.cleanup_command(project,2,['01'])
        self.assertTrue(old.exists())

    def test_resolve_run_rejects_traversal_and_external_paths(self):
        project=self.root/'project'
        self.make_run(project,'01')
        outside=self.root/'outside';outside.mkdir()
        for reference in ('../outside',str(outside),'missing'):
            with self.subTest(reference=reference),self.assertRaises(m.MigrationError):
                m.resolve_saved_run(project,reference)
        self.assertEqual(m.resolve_saved_run(project,'01'),(project/'runs/01').resolve())

    def test_cleanup_dry_run_overrides_explicit_deletion_selection(self):
        project=self.root/'project'
        self.make_run(project,'01');self.make_run(project,'02');self.make_run(project,'03')
        before=base.tree_contents(project)
        with mock.patch('sys.argv',['tool','--backup-dir',str(project),'--cleanup','--delete-run','01','--dry-run']), \
             mock.patch('builtins.input') as confirmation:
            self.assertEqual(m.main(),0)
            confirmation.assert_not_called()
        self.assertEqual(base.tree_contents(project),before)

    def test_project_busy_creates_no_new_batch(self):
        project=self.root/'project'
        with m.FileLock(project/'.project.lock','project'), \
             mock.patch('sys.argv',['tool','--backup-dir',str(project),'--mode','full']), \
             mock.patch.object(m,'require_macos_tools'):
            with self.assertRaisesRegex(m.MigrationError,'busy'):
                m.main()
        self.assertFalse((project/'runs').exists())

    def test_saved_manifest_member_hash_mismatch_detected_even_if_archive_hash_is_updated(self):
        archive=self.root/'payload.zip'
        with zipfile.ZipFile(archive,'w') as zf: zf.writestr('book.epub',b'changed')
        manifest={'archive_sha256':m.sha256_file(archive),'files':{'book.epub':{
            'size':7,'sha256':hashlib.sha256(b'oldbook').hexdigest(),'category':'books'}}}
        with self.assertRaisesRegex(m.MigrationError,'checksum mismatch'):
            m.verify_saved_archive(archive,manifest,'payload')

    def test_saved_manifest_unsafe_paths_and_unlisted_members_are_rejected(self):
        archive=self.root/'payload.zip'
        with zipfile.ZipFile(archive,'w') as zf:
            zf.writestr('book.epub',b'book')
            zf.writestr('unlisted.epub',b'hidden')
        manifest={'archive_sha256':m.sha256_file(archive),'files':{'book.epub':{
            'size':4,'sha256':hashlib.sha256(b'book').hexdigest(),'category':'books'}}}
        with self.assertRaisesRegex(m.MigrationError,'do not match'):
            m.verify_saved_archive(archive,manifest,'payload')
        manifest['files']['../escape.epub']=manifest['files']['book.epub']
        with self.assertRaisesRegex(m.MigrationError,'Unsafe'):
            m.verify_saved_archive(archive,manifest,'payload')

    def test_catalog_corrupt_state_is_protected(self):
        project=self.root/'project'
        bad=self.make_run(project,'bad')
        (bad/'run.json').write_text('{broken')
        plan=m.cleanup_plan(project)
        self.assertEqual(plan['protected'][0]['status'],'unreadable')

    def test_list_and_preview_commands_do_not_require_macos_tools_or_touch_project(self):
        project=self.root/'project'
        self.make_run(project,'01')
        before=base.tree_contents(project)
        for command in ('--list-runs','--cleanup'):
            with mock.patch('sys.argv',['tool','--backup-dir',str(project),command]),mock.patch.object(m,'require_macos_tools') as require:
                self.assertEqual(m.main(),0)
                require.assert_not_called()
        self.assertEqual(base.tree_contents(project),before)



class BackupVerificationTests(base.MigrationTestCase):
    prepare_devices = base.WorkflowTests.prepare_devices
    execute = ManagedWorkflowTests.execute
    latest = ManagedWorkflowTests.latest
    make_run = LockAndCatalogTests.make_run

    def verify(self, project, run_id, *extra):
        out=io.StringIO()
        with mock.patch('sys.argv',['tool','--backup-dir',str(project),'--verify-run',run_id,*extra]), \
             mock.patch.object(m,'require_macos_tools') as require, mock.patch('sys.stdout',out), mock.patch('sys.stderr',out):
            code=m.main()
        require.assert_not_called()
        return code,out.getvalue()

    def test_verify_run_checks_every_saved_archive_without_changes(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        run=self.latest(project)
        results=m.verify_run_artifacts(run)
        self.assertEqual({r['status'] for r in results},{'verified'})
        self.assertEqual({r['kind'] for r in results},{'koreader','payload'})
        self.assertTrue(any('-pre-migration-' in r['name'] for r in results))
        before=base.tree_contents(project)
        code,output=self.verify(project,run.name)
        self.assertEqual(code,0)
        self.assertIn(f'{len(results)} verified, 0 failed',output)
        self.assertEqual(base.tree_contents(project),before)

    def test_verify_run_reports_corrupt_unpaired_and_missing_references(self):
        source,target=self.prepare_devices()
        project=self.root/'project'
        self.execute(project,[source,target],['--mode','full'])
        run=self.latest(project)
        payload=next(p for p in run.glob('library-*.zip') if '-pre-migration-' not in p.name)
        payload.write_bytes(payload.read_bytes()[:-1]+b'X')
        runtime=next(p for p in run.glob('koreader-*.zip') if '-pre-migration-' in p.name)
        runtime.with_suffix('.manifest.json').unlink()
        results={r['name']:r for r in m.verify_run_artifacts(run)}
        self.assertEqual(results[payload.name]['status'],'failed')
        self.assertEqual(results[runtime.name]['detail'].key,'error.verify_unpaired')
        self.assertTrue(any(r['kind']=='descriptor' and r['detail'].key=='error.verify_referenced_missing'
                            for r in results.values()))
        code,output=self.verify(project,run.name,'--locale','zh-Hant')
        self.assertEqual(code,1)
        self.assertIn('驗證失敗',output)

    def test_verify_run_rejects_symlinks_traversal_and_migration_settings(self):
        project=self.root/'project'
        run=self.make_run(project,'01')
        (run/'link.zip').symlink_to(run/'archive.zip')
        with self.assertRaises(m.MigrationError):
            m.verify_run_artifacts(run)
        with self.assertRaises(m.MigrationError):
            m.verify_run_command(project,'../01')
        with mock.patch('sys.argv',['tool','--verify-run','01','--mode','full']), \
             mock.patch('sys.stderr',io.StringIO()), self.assertRaises(SystemExit):
            m.parse_args()

    def test_verify_run_reports_unreadable_archive_as_failure(self):
        project=self.root/'project'
        run=self.make_run(project,'01')
        (run/'archive.manifest.json').write_text(json.dumps({'archive_sha256':m.sha256_file(run/'archive.zip'),'files':{}}))
        [result]=m.verify_run_artifacts(run)
        self.assertEqual((result['status'],result['detail'].key),('failed','error.verify_unreadable'))


if __name__=='__main__':
    unittest.main(verbosity=2)
