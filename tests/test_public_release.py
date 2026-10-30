"""Generic device-role and publication boundaries; synthetic files only."""
from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import test_migration as base
m = base.migration

ROOT = Path(__file__).resolve().parents[1]


def load_helper(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load_helper('check_publication')
publish = load_helper('publish')
description = load_helper('check_pr_description')


class GenericDeviceTests(base.MigrationTestCase):
    def test_renamed_volume_is_discovered_but_symlink_and_adds_only_are_not(self):
        volumes = self.root / 'Volumes'
        renamed = volumes / 'My Reader'
        base.write_file(renamed / '.kobo/version', b'fixture,firmware')
        (volumes / 'KOBOeReader-old' / '.adds').mkdir(parents=True)
        (volumes / 'linked').symlink_to(renamed, target_is_directory=True)
        other = volumes / 'fake'
        other.mkdir()
        (other / '.kobo').symlink_to(renamed / '.kobo', target_is_directory=True)
        with mock.patch.object(m, 'VOLUME_ROOT', volumes):
            self.assertEqual(m.kobo_mounts(), [renamed])

    def test_multiple_renamed_readers_are_refused(self):
        with mock.patch.object(m, 'kobo_mounts', return_value=[self.root/'one', self.root/'two']):
            with self.assertRaisesRegex(m.MigrationError, 'More than one'):
                m.wait_for_single_kobo('SOURCE')

    def test_other_model_labels_are_independent_of_stale_log_hint(self):
        info = m.DeviceInfo('fixture', m.MODEL_CLARA, None, 'fingerprint', None, False, False, 0, 0)
        with mock.patch.object(m, 'prompt_yes_no', return_value=True) as confirm:
            result = m.confirm_role_model(info, 'Clara BW', 'TARGET')
        self.assertEqual(result, 'Kobo Clara BW')
        self.assertIn('TARGET is Kobo Clara BW', confirm.call_args.args[0])

    def test_even_matching_model_hints_require_confirmation(self):
        info = m.DeviceInfo('fixture', m.MODEL_CLARA, None, 'fingerprint', None, False, False, 0, 0)
        with mock.patch.object(m, 'prompt_yes_no', return_value=False):
            with self.assertRaises(m.MigrationCancelled):
                m.confirm_role_model(info, m.MODEL_CLARA, 'SOURCE')

    def test_unknown_model_accepts_manual_label_not_a_hardcoded_pair(self):
        info = m.DeviceInfo('fixture', None, None, 'fingerprint', None, False, False, 0, 0)
        with mock.patch('builtins.input', side_effect=['', 'Elipsa 2E']), \
             mock.patch.object(m, 'prompt_yes_no', return_value=True):
            self.assertEqual(m.confirm_role_model(info, None, 'SOURCE'), 'Kobo Elipsa 2E')

    def test_missing_fingerprint_refuses_migration(self):
        info = m.DeviceInfo('fixture', 'Kobo Sage', None, None, None, False, False, 0, 0)
        with self.assertRaisesRegex(m.MigrationError, 'identity'):
            m.require_device_fingerprint(info)

    def run_generic(self, source, target, compatibility=True):
        args = base.SimpleNamespace(mode='full', dry_run=False, books=True, fonts=True,
            reading_data=True, conflict='overwrite', include_dir=[], exclude_dir=[], extra_extension=[],
            source_model='Kobo Clara BW', target_model='Kobo Clara BW')
        run = self.root/'backups'
        run.mkdir(exist_ok=True)
        def answer(question, default=False):
            return compatibility if 'build is compatible' in question else True
        with mock.patch.object(m, 'run_with_spinner', side_effect=base.fake_ditto), \
             mock.patch.object(m, 'wait_for_single_kobo', side_effect=[source,target]), \
             mock.patch.object(m, 'safe_eject'), mock.patch.object(m, 'choose_identity_mode', return_value='preserve'), \
             mock.patch.object(m, 'prompt_yes_no', side_effect=answer), mock.patch('builtins.input', return_value=''):
            return m.migrate(args, run, 'test-generic', run/'test.log')

    def test_same_model_different_devices_full_migration(self):
        source, target = base.WorkflowTests.prepare_devices(self)
        before = base.tree_contents(source)
        self.assertEqual(self.run_generic(source,target),0)
        self.assertEqual(base.tree_contents(source),before)
        self.assertEqual((target/'Books/book.epub').read_bytes(),b'new book')
        self.assertEqual((target/'Books/unrelated.pdf').read_bytes(),b'keep unrelated')
        self.assertEqual(m.read_json(self.root/'backups'/'target-snapshot.json')['confirmed_model'], 'Kobo Clara BW')

    def test_same_fingerprint_refuses_without_target_modification(self):
        source, target = base.WorkflowTests.prepare_devices(self)
        (target/'.kobo/version').write_bytes((source/'.kobo/version').read_bytes())
        before = base.tree_contents(target)
        with self.assertRaisesRegex(m.MigrationError, 'same Kobo fingerprint'):
            self.run_generic(source,target)
        self.assertEqual(base.tree_contents(target),before)

    def test_unconfirmed_runtime_compatibility_leaves_target_unchanged(self):
        source, target = base.WorkflowTests.prepare_devices(self)
        before = base.tree_contents(target)
        with self.assertRaises(m.MigrationCancelled):
            self.run_generic(source,target,compatibility=False)
        self.assertEqual(base.tree_contents(target),before)
        self.assertFalse(list((self.root/'backups').glob('*pre-migration*')))


class GenericSavedWorkflowTests(base.MigrationTestCase):
    def execute(self, project, devices, flags):
        labels = [] if '--restore-run' in flags else ['--source-model', 'Kobo Clara BW', '--target-model', 'Kobo Clara BW']
        with mock.patch('sys.argv', ['tool', '--backup-dir', str(project)] + flags + labels), \
             mock.patch.object(m, 'require_macos_tools'), \
             mock.patch.object(m, 'run_with_spinner', side_effect=base.fake_ditto), \
             mock.patch.object(m, 'wait_for_single_kobo', side_effect=devices) as wait, \
             mock.patch.object(m, 'safe_eject'), mock.patch.object(m, 'choose_identity_mode', return_value='preserve'), \
             mock.patch.object(m, 'prompt_yes_no', return_value=True), mock.patch('builtins.input', return_value=''):
            return m.main(), wait.call_count

    def test_generic_saved_source_and_restore_do_not_infer_opposite_model(self):
        source, target = base.WorkflowTests.prepare_devices(self)
        before = base.tree_contents(target)
        project = self.root / 'project'
        self.assertEqual(self.execute(project, [source,target], ['--mode','full']), (0,2))
        saved = max((project/'runs').iterdir(), key=lambda p:p.stat().st_mtime_ns)
        self.assertEqual(m.read_json(saved/'source-snapshot.json')['confirmed_model'], 'Kobo Clara BW')
        self.assertEqual(self.execute(project, [target], ['--from-run',saved.name]), (0,1))
        self.assertEqual(self.execute(project, [target], ['--restore-run',saved.name]), (0,1))
        self.assertEqual(base.tree_contents(target), before)


class PublicationTests(unittest.TestCase):
    def test_device_artifacts_are_outside_allowlist(self):
        for path in ('runs/run/run.json','book.epub','.kobo/KoboReader.sqlite',
                     'example.sdr/metadata.epub.lua','source-snapshot.json','id_ed25519'):
            self.assertTrue(guard.inspect_blob(path,b'synthetic'))

    def test_private_agent_instructions_are_ignored_and_blocked_from_publication(self):
        paths = ('AGENTS.override.md', 'nested/AGENTS.override.md', '.local/notes.md')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.gitignore').write_bytes((guard.ROOT / '.gitignore').read_bytes())
            subprocess.run(['git', '-C', td, 'init', '-b', 'main'], check=True, capture_output=True)
            for path in paths:
                with self.subTest(path=path):
                    fixture = root / path
                    fixture.parent.mkdir(parents=True, exist_ok=True)
                    fixture.write_text('Synthetic local-only instructions.\n')
                    result = subprocess.run(['git', '-C', td, 'check-ignore', '-q', '--', path],
                                            capture_output=True)
                    self.assertEqual(result.returncode, 0)
                    self.assertTrue(guard.inspect_blob(path, fixture.read_bytes()))
        self.assertFalse(guard.inspect_blob('AGENTS.md', b'Synthetic shared guidance.'))

    def test_force_added_private_guidance_is_blocked_in_index_and_deleted_history(self):
        paths = ('AGENTS.override.md', 'nested/AGENTS.override.md', '.local/notes.md')
        for path in paths:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture',
                           GIT_AUTHOR_EMAIL='fixture@users.noreply.github.com',
                           GIT_COMMITTER_EMAIL='fixture@users.noreply.github.com')
                def git(*args):
                    return subprocess.run(['git', '-C', td, *args], env=env,
                                          check=True, capture_output=True)
                git('init', '-b', 'main')
                (root / '.gitignore').write_bytes((guard.ROOT / '.gitignore').read_bytes())
                fixture = root / path
                fixture.parent.mkdir(parents=True, exist_ok=True)
                fixture.write_text('Synthetic private instructions; no owner data.\n')
                git('add', '.gitignore')
                git('add', '--force', '--', path)
                with mock.patch.object(guard, 'ROOT', root):
                    self.assertIn(path + ': file is outside the publication allowlist',
                                  guard.check_index())
                git('commit', '-m', 'Synthetic force-added private file')
                git('rm', '--', path)
                git('commit', '-m', 'Remove synthetic private file from latest tree')
                with mock.patch.object(guard, 'ROOT', root):
                    self.assertFalse(guard.check_index())
                    self.assertIn(path + ': file is outside the publication allowlist',
                                  guard.check_history())

    def test_documentation_allowlist_is_exact_and_still_scans_content(self):
        for name in ('USAGE', 'RECOVERY', 'TROUBLESHOOTING', 'DEVELOPMENT', 'MAINTAINING'):
            with self.subTest(name=name):
                path = 'docs/' + name + '.md'
                self.assertFalse(guard.inspect_blob(path, b'Synthetic public guide.'))
                private_path = '/' + 'Users' + '/example/private-data'
                self.assertTrue(guard.inspect_blob(path, private_path.encode()))
        for path in ('docs/notes.md', 'docs/secrets.json', 'docs/private/USAGE.md',
                     'docs/../AGENTS.override.md'):
            self.assertTrue(guard.inspect_blob(path, b'Synthetic private data.'))

    def test_detection_never_echoes_secret_values(self):
        secret = 'gh' + 'p_' + 'a' * 32
        issues = guard.inspect_blob('README.md', ('token: ' + secret).encode())
        self.assertTrue(issues)
        self.assertNotIn(secret, '\n'.join(issues))

    def test_binary_symlink_and_personal_paths_are_blocked(self):
        self.assertTrue(guard.inspect_blob('README.md',b'\x00binary'))
        self.assertTrue(guard.inspect_blob('README.md',b'fixture','120000'))
        private_path = '/' + 'Users' + '/example/Books'
        self.assertTrue(guard.inspect_blob('README.md', private_path.encode()))

    def test_index_and_history_use_git_blobs_not_worktree_or_ignore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture',
                       GIT_AUTHOR_EMAIL='fixture@users.noreply.github.com', GIT_COMMITTER_EMAIL='fixture@users.noreply.github.com')
            def git(*args):
                return subprocess.run(['git','-C',td,*args],env=env,check=True,capture_output=True)
            git('init','-b','main')
            secret = ('gh' + 'p_' + 'x'*32).encode()
            (root/'README.md').write_bytes(secret)
            git('add','README.md')
            (root/'README.md').write_text('clean worktree')
            with mock.patch.object(guard, 'ROOT', root):
                self.assertTrue(guard.check_index())
            git('commit','-m','synthetic secret fixture')
            git('add','README.md')
            git('commit','-m','remove fixture')
            with mock.patch.object(guard, 'ROOT', root):
                self.assertFalse(guard.check_index())
                self.assertTrue(guard.check_history())

    def test_history_allows_platform_merge_committer_without_allowing_personal_emails(self):
        user = 'fixture@users.noreply.github.com'
        cases = [
            ('normal user', user, user, False, False),
            ('platform merge', user, 'noreply@github.com', True, False),
            ('platform nonmerge', user, 'noreply@github.com', False, True),
            ('platform author', 'noreply@github.com', user, True, True),
            ('personal author', 'fixture@example.invalid', 'noreply@github.com', True, True),
            ('personal committer', user, 'fixture@example.invalid', True, True),
            ('lookalike platform', user, 'noreply@github.com.example.invalid', True, True),
        ]
        for label, author, committer, merge, blocked in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                env = dict(os.environ, GIT_AUTHOR_NAME='Fixture', GIT_COMMITTER_NAME='Fixture',
                           GIT_AUTHOR_EMAIL=user, GIT_COMMITTER_EMAIL=user)
                def git(*args, identity=None):
                    return subprocess.run(['git', '-C', td, *args], env=identity or env,
                                          check=True, capture_output=True).stdout.decode().strip()
                git('init', '-b', 'main')
                (root / 'README.md').write_text('Synthetic public fixture.\n')
                git('add', 'README.md')
                git('commit', '-m', 'Initial fixture')
                first = git('rev-parse', 'HEAD')
                git('commit', '--allow-empty', '-m', 'Second fixture')
                second = git('rev-parse', 'HEAD')
                parents = ['-p', second]
                if merge:
                    parents += ['-p', first]
                identity = dict(env, GIT_AUTHOR_EMAIL=author, GIT_COMMITTER_EMAIL=committer)
                candidate = git('commit-tree', git('write-tree'), *parents,
                                '-m', 'Candidate fixture', identity=identity)
                git('update-ref', 'refs/heads/candidate', candidate)
                with mock.patch.object(guard, 'ROOT', root):
                    issues = guard.check_history()
                self.assertEqual(bool(issues), blocked)
                if blocked:
                    self.assertTrue(any('author/committer email' in issue for issue in issues))

    def test_publish_origin_must_be_exact_github_without_credentials(self):
        self.assertEqual(publish.repository_from_url('https://github.com/example/tool.git'),'example/tool')
        self.assertEqual(publish.repository_from_url('git@github.com:example/tool.git'),'example/tool')
        for url in ('https://example.com/example/tool.git','https://' + 'user:secret' + '@github.com/example/tool.git',
                    'https://github.com/example/tool.git/extra'):
            with self.assertRaises(ValueError):
                publish.repository_from_url(url)

    def test_publish_refuses_main_and_never_pushes(self):
        with mock.patch('sys.argv',['publish','--repository','example/tool','--title','Fixture',
                                    '--body-file','/tmp/fixture.md']), \
             mock.patch.object(publish.shutil,'which',return_value='/bin/gh'), \
             mock.patch.object(publish,'run',return_value='main') as execute:
            self.assertEqual(publish.main(),1)
        self.assertFalse(any(call.args[:2] == ('git','push') for call in execute.call_args_list))


    def test_publish_runs_checks_before_push_and_creates_pr_without_merge(self):
        with tempfile.TemporaryDirectory() as td:
            body = Path(td)/'body.md'
            from test_pr_description import VALID_BODY
            body.write_text(VALID_BODY)
            def execute(*cmd, capture=False):
                if cmd[:4] == ('git','symbolic-ref','--quiet','--short'):
                    return 'feature/fixture'
                if cmd[:2] == ('git','status'):
                    return ''
                if cmd[:3] == ('git','remote','get-url'):
                    return 'https://github.com/example/tool.git'
                if cmd[:3] == ('gh','pr','list'):
                    return ''
                return ''
            with mock.patch('sys.argv', ['publish','--repository','example/tool','--title','Synthetic change','--body-file',str(body)]), \
                 mock.patch.object(publish.shutil, 'which', return_value='/bin/gh'), \
                 mock.patch.dict(sys.modules, {'check_publication': guard, 'check_pr_description': description}), \
                 mock.patch.object(publish, 'run', side_effect=execute) as calls:
                self.assertEqual(publish.main(),0)
            commands = [call.args for call in calls.call_args_list]
            privacy = next(i for i, cmd in enumerate(commands) if 'scripts/check_publication.py' in cmd)
            push = next(i for i, cmd in enumerate(commands) if cmd[:2] == ('git','push'))
            create = next(i for i, cmd in enumerate(commands) if cmd[:3] == ('gh','pr','create'))
            self.assertLess(privacy, push)
            self.assertLess(push, create)
            self.assertFalse(any(cmd[:3] == ('gh','pr','merge') or '--force' in cmd for cmd in commands))


if __name__ == '__main__':
    unittest.main()
