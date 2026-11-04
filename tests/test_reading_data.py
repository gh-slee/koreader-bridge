"""Reading-data report and Lua data-literal parser (KM-007); synthetic fixtures only."""
from __future__ import annotations

import ast
import hashlib
import inspect
import io
import json
from pathlib import Path
import random
import unittest
from unittest import mock

import test_migration as base
m = base.migration
ROOT = Path(__file__).resolve().parents[1]


def lua_string(value: str) -> str:
    """Quote like KOReader's %q dump: backslash-newline and decimal escapes."""
    out = []
    for char in value:
        if char in '"\\':
            out.append('\\' + char)
        elif char == '\n':
            out.append('\\\n')
        elif ord(char) < 32:
            out.append('\\%d' % ord(char))
        else:
            out.append(char)
    return '"' + ''.join(out) + '"'


def sidecar(percent=0.5, xpointer='/body/DocFragment[3]/body/p[2]/text().0', page=None, status='reading',
            modified='2026-10-01', checksum=None, annotations=0, legacy=False, title='Sample "Book"') -> bytes:
    lines = ['-- we can read Lua syntax here!', 'return {']
    if percent is not None:
        lines.append(f'    ["percent_finished"] = {percent!r},')
    if xpointer is not None:
        lines.append(f'    ["last_xpointer"] = {lua_string(xpointer)},')
    if page is not None:
        lines.append(f'    ["last_page"] = {page},')
    if checksum:
        lines.append(f'    ["partial_md5_checksum"] = "{checksum}",')
    lines.append(f'    ["doc_props"] = {{ ["title"] = {lua_string(title)}, ["authors"] = "A\\nB" }},')
    lines.append(f'    ["summary"] = {{ ["status"] = "{status}", ["modified"] = "{modified}" }},')
    if legacy:
        lines.append('    ["highlight"] = { [12] = { [1] = { ["datetime"] = "2026-09-01 10:00:00", ["text"] = "x" } } },')
        lines.append('    ["bookmarks"] = { [1] = { ["page"] = 12, ["text"] = "note" } },')
    elif annotations:
        items = ', '.join(
            f'[{i}] = {{ ["datetime"] = "2026-10-0{i} 20:00:00", ["drawer"] = "lighten", ["pos0"] = "/p[{i}]",'
            f' ["note"] = {lua_string("private note " + str(i)) if i == 1 else "nil"} }}'
            for i in range(1, annotations + 1))
        lines.append(f'    ["annotations"] = {{ {items} }},')
    lines.append('}')
    return ('\n'.join(lines) + '\n').encode()


def md5_of(data: bytes) -> str:
    digest = hashlib.md5()
    for i in range(-1, 11):
        offset = 0 if i < 0 else 1024 << (2 * i)
        sample = data[offset:offset + 1024]
        if not sample:
            break
        digest.update(sample)
    return digest.hexdigest()


class LuaParserTests(unittest.TestCase):
    def parse(self, text, **limits):
        data = text.encode() if isinstance(text, str) else text
        return m.parse_lua_data(data, m.LuaLimits(**limits) if limits else m.LuaLimits())

    def assertRejected(self, text, code, **limits):
        with self.assertRaises(m.LuaDataError) as caught:
            self.parse(text, **limits)
        self.assertEqual(caught.exception.code, code, text)

    def test_koreader_style_dump(self):
        data = sidecar(annotations=2, checksum='0123456789abcdef0123456789ABCDEF')
        table = self.parse(data)
        self.assertEqual(table['doc_props']['title'], 'Sample "Book"')
        self.assertEqual(table['doc_props']['authors'], 'A\nB')
        self.assertEqual(len(m.lua_sequence(table['annotations'])), 2)
        self.assertNotIn('note', table['annotations'][2])

    def test_literal_grammar(self):
        cases = {
            'return 1': 1, 'return -1.5e2': -150.0, 'return 0x1F': 31, 'return .5': 0.5, 'return 5.': 5.0,
            'return true': True, 'return nil': None, 'return {}': {},
            "return 'a\\tb\\\"\\'\\65\\x41\\u{263A}'": 'a\tb"\'AA☺',
            'return "a\\z   \n  b"': 'ab',
            'return [[\nfirst]]': 'first', 'return [==[a]]b]==]': 'a]]b',
            'return {1, 2; 3,}': {1: 1, 2: 2, 3: 3},
            'return {nil, 2}': {2: 2},
            'return {a = 1, ["b c"] = {x = false}, [2.0] = "two", [1.5] = "f"}':
                {'a': 1, 'b c': {'x': False}, 2: 'two', 1.5: 'f'},
            '﻿-- c\n--[==[ long\ncomment ]==]\nreturn --[[x]] { [ "k" ] = "v" } ; ': {'k': 'v'},
        }
        for text, expected in cases.items():
            self.assertEqual(self.parse(text), expected, text)

    def test_long_string_newlines_are_normalized(self):
        self.assertEqual(self.parse(b'return [[\r\na\r\nb\rc]]'), 'a\nb\nc')

    def test_invalid_utf8_is_preserved_reversibly(self):
        value = self.parse(b'return "\xff"')
        self.assertEqual(value.encode('utf-8', 'surrogateescape'), b'\xff')

    def test_executable_and_malformed_input_is_rejected(self):
        cases = {
            'os.execute("x")': 'missing_return', 'return os.execute("x")': 'executable_construct',
            'return x': 'executable_construct', 'return {a = b}': 'executable_construct',
            'return 1 + 1': 'executable_construct', 'return "a" .. "b"': 'executable_construct',
            'return function() end': 'executable_construct', 'return math.huge': 'executable_construct',
            'return inf': 'executable_construct', 'return {} return {}': 'trailing_data',
            '#!/bin/lua\nreturn {}': 'executable_construct', 'return ::l::': 'executable_construct',
            'return - -1': 'executable_construct', 'return -x': 'executable_construct',
            'return 0x': 'invalid_number', 'return 1e999': 'invalid_number', 'return 1x': 'invalid_number',
            'return 0x1p4': 'invalid_number', 'return "\\q"': 'bad_escape', 'return "\\256"': 'bad_escape',
            'return "\\x4"': 'bad_escape', 'return "\\u{D800}"': 'bad_escape', 'return "abc': 'unterminated_string',
            'return "a\nb"': 'unterminated_string', 'return [==[abc]]': 'unterminated_string',
            '--[[ open\nreturn {}': 'unterminated_comment', 'return {a = 1, a = 2}': 'duplicate_key',
            'return {1, [1] = 2}': 'duplicate_key', 'return {[nil] = 1}': 'invalid_key',
            'return {[true] = 1}': 'invalid_key', 'return {[{}] = 1}': 'invalid_key',
            'return {1 2}': 'syntax', 'return': 'syntax', '': 'missing_return', 'return {f(1)}': 'executable_construct',
            'return (1)': 'executable_construct', 'local t = {} return t': 'missing_return',
            'return {a = 1} x': 'trailing_data', 'return \x01': 'syntax',
        }
        for text, code in cases.items():
            self.assertRejected(text, code)

    def test_limits(self):
        self.assertRejected('return ' + '{' * 100 + '}' * 100, 'too_deep')
        self.assertRejected('return ' + '{' * 10000, 'too_deep')
        self.parse('return ' + '{' * 64 + '}' * 64)
        self.assertRejected('return {' + '1,' * 50 + '}', 'too_many_nodes', max_nodes=10)
        self.assertRejected('return "' + 'a' * 100 + '"', 'too_large', max_bytes=50)
        ticks = iter(range(0, 10**9, 10))
        with self.assertRaises(m.LuaDataError) as caught:
            m.parse_lua_data(('return {' + '1,' * 20000 + '}').encode(), m.LuaLimits(max_seconds=5),
                             clock=lambda: next(ticks))
        self.assertEqual(caught.exception.code, 'timeout')
        with self.assertRaises(ValueError):
            m.parse_lua_data(b'return 1', m.LuaLimits(max_depth=10_000))

    def test_error_reports_line(self):
        with self.assertRaises(m.LuaDataError) as caught:
            self.parse('return {\n  a = 1,\n  b = c,\n}')
        self.assertEqual((caught.exception.code, caught.exception.line), ('executable_construct', 3))

    def test_random_mutations_only_raise_lua_data_error(self):
        seed = sidecar(annotations=3, legacy=False)
        rng = random.Random(7)
        for _ in range(1500):
            data = bytearray(seed)
            for _ in range(rng.randint(1, 6)):
                position = rng.randrange(len(data))
                choice = rng.random()
                if choice < 0.4:
                    data[position] = rng.randrange(256)
                elif choice < 0.7:
                    del data[position]
                else:
                    data.insert(position, rng.choice(b'{}[]=,;"\'\\-.x0()'))
            try:
                m.parse_lua_data(bytes(data))
            except m.LuaDataError:
                pass

    def test_parser_source_has_no_evaluation_or_process_calls(self):
        forbidden = {'eval', 'exec', 'compile', '__import__', 'system', 'popen', 'run', 'Popen', 'loadstring'}
        for item in (m._LuaDataParser, m.parse_lua_data, m.lua_sequence, m.summarize_reading_data,
                     m.read_reading_store, m.collect_reading_side, m.build_reading_data_report):
            tree = ast.parse(inspect.getsource(item))
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            self.assertFalse(names & (forbidden | {'subprocess'}), item)

    def test_lua_sequence(self):
        self.assertEqual(m.lua_sequence({}), [])
        self.assertEqual(m.lua_sequence({1: 'a', 2: 'b'}), ['a', 'b'])
        self.assertIsNone(m.lua_sequence({1: 'a', 3: 'c'}))
        self.assertIsNone(m.lua_sequence({'a': 1}))
        self.assertIsNone(m.lua_sequence('x'))


class ExtractionTests(unittest.TestCase):
    def summary(self, data):
        return m.summarize_reading_data(m.parse_lua_data(data))

    def test_unified_annotations(self):
        result = self.summary(sidecar(annotations=3, checksum='A' * 32))
        fields = result['fields']
        self.assertEqual(fields['schema_family'], 'annotations')
        self.assertEqual(fields['counts'], {'annotations': 3, 'highlights': 3, 'bookmarks': 0, 'notes': 1})
        self.assertEqual(fields['latest_annotation'], '2026-10-03 20:00:00')
        self.assertEqual(fields['partial_md5_checksum'], 'a' * 32)
        self.assertEqual(fields['position_kind'], 'xpointer')
        self.assertEqual(fields['summary_status'], 'reading')
        self.assertEqual(result['identity'], ('Sample "Book"', 'A\nB'))
        self.assertNotIn('private note', json.dumps(fields))

    def test_legacy_and_mixed(self):
        legacy = self.summary(sidecar(legacy=True, xpointer=None, page=12))['fields']
        self.assertEqual(legacy['schema_family'], 'legacy')
        self.assertEqual(legacy['counts'], {'annotations': None, 'highlights': 1, 'bookmarks': 1, 'notes': 1})
        self.assertEqual((legacy['position_kind'], legacy['last_page']), ('page', 12))
        mixed = m.summarize_reading_data({'annotations': {}, 'bookmarks': {}})['fields']
        self.assertEqual(mixed['schema_family'], 'mixed')
        self.assertEqual(m.summarize_reading_data({})['fields']['schema_family'], 'none')

    def test_invalid_fields_are_reported_not_fatal(self):
        fields = m.summarize_reading_data({'percent_finished': 1.5, 'last_page': -1, 'partial_md5_checksum': 'xyz',
                                           'summary': {'status': 'on hold', 'modified': 'yesterday'},
                                           'annotations': {'a': 1}, 'last_xpointer': 'x' * 2000})['fields']
        self.assertEqual(fields['invalid_fields'],
                         ['annotations', 'last_page', 'partial_md5_checksum', 'percent_finished', 'summary.modified'])
        self.assertEqual(fields['summary_status'], 'other')
        self.assertEqual(len(fields['last_xpointer']), m.READING_XPOINTER_CHARS)
        self.assertIsNone(fields['percent_finished'])

    def test_partial_md5_matches_documented_offsets(self):
        rng = random.Random(3)
        for size in (0, 10, 1024, 1500, 5 * 1024, 70 * 1024, 3 * 1024 * 1024):
            data = bytes(rng.randrange(256) for _ in range(min(size, 4096))) * (size // 4096 + 1)
            data = data[:size]
            self.assertEqual(m.koreader_partial_md5(io.BytesIO(data)), md5_of(data), size)


class ReadingWorkflowTests(base.MigrationTestCase):
    def devices(self):
        source, target = self.root / 'source', self.root / 'target'
        source_kr = self.make_koreader(source, b'source runtime', 'SOURCE')
        target_kr = self.make_koreader(target, b'target runtime', 'TARGET')
        base.write_file(source / '.kobo/version', b'SOURCE-SERIAL,firmware')
        base.write_file(target / '.kobo/version', b'TARGET-SERIAL,firmware')
        base.write_file(source_kr / 'crash.log', b'Detected a Kobo Clara 2E (id)')
        base.write_file(target_kr / 'crash.log', b'Detected a Kobo Libra 2 (id)')
        both = lambda rel, data: (base.write_file(source / rel, data), base.write_file(target / rel, data))
        book = lambda name: (b'%s edition one ' % name.encode()) * 400
        both('Books/same.epub', book('same'))
        both('Books/same.sdr/metadata.epub.lua', sidecar(percent=0.25))
        both('Books/progress.epub', book('progress'))
        base.write_file(source / 'Books/progress.sdr/metadata.epub.lua', sidecar(percent=0.8, modified='2026-10-05'))
        base.write_file(target / 'Books/progress.sdr/metadata.epub.lua', sidecar(percent=0.3, annotations=2))
        base.write_file(source / 'Books/edition.epub', book('edition'))
        base.write_file(target / 'Books/edition.epub', book('edition-2'))
        base.write_file(source / 'Books/edition.sdr/metadata.epub.lua', sidecar(checksum=md5_of(book('edition'))))
        base.write_file(target / 'Books/edition.sdr/metadata.epub.lua', sidecar(checksum=md5_of(book('edition-2'))))
        base.write_file(source / 'Books/content.epub', book('content'))
        base.write_file(target / 'Books/content.epub', book('content-2'))
        both('Books/content.sdr/metadata.epub.lua', sidecar())
        both('Books/broken.epub', book('broken'))
        base.write_file(source / 'Books/broken.sdr/metadata.epub.lua', b'return os.execute("touch /tmp/pwned")')
        base.write_file(source / 'Books/moved.epub', book('moved'))
        base.write_file(source / 'Books/moved.sdr/metadata.epub.lua', sidecar())
        base.write_file(target / 'Books/renamed.epub', book('moved'))
        base.write_file(target / 'Books/renamed.sdr/metadata.epub.lua', sidecar(checksum=md5_of(book('moved'))))
        base.write_file(source / 'Books/twin.epub', book('twin'))
        base.write_file(source / 'Books/twin.sdr/metadata.epub.lua', sidecar())
        for name in ('twin-a', 'twin-b'):
            base.write_file(target / f'Books/{name}.epub', book('twin'))
            base.write_file(target / f'Books/{name}.sdr/metadata.epub.lua', sidecar(checksum=md5_of(book('twin'))))
        both('Books/stale.epub', book('stale'))
        both('Books/stale.sdr/metadata.epub.lua', sidecar(checksum='f' * 32))
        both('Books/hash.epub', book('hash'))
        both('Books/hash.sdr/metadata.epub.lua', sidecar())
        digest = md5_of(book('hash'))
        base.write_file(target_kr / f'hashdocsettings/{digest[:2]}/{digest}.sdr/metadata.epub.lua', sidecar(percent=0.9))
        base.write_file(source / 'Books/orphan.epub', book('orphan'))
        base.write_file(target / 'Books/orphan.epub', book('orphan-2'))
        base.write_file(target / 'Books/orphan.sdr/metadata.epub.lua', sidecar(annotations=1))
        return source, target

    def execute(self, project, devices, flags):
        return base_execute(self, project, devices, flags)

    def latest(self, project):
        return max((project / 'runs').iterdir(), key=lambda p: p.stat().st_mtime_ns)

    def books(self, run):
        section = m.read_json(run / 'difference.json')['reading_data']
        return section, {entry['book']: entry for entry in section['books']}

    def test_library_preview_reports_conflicts_without_changing_devices(self):
        source, target = self.devices()
        source_before, target_before = base.tree_contents(source), base.tree_contents(target)
        project = self.root / 'project'
        code, _ = self.execute(project, [source, target], ['--mode', 'library', '--books', '--no-fonts',
                                                            '--conflict', 'overwrite', '--dry-run'])
        self.assertEqual(code, 0)
        self.assertEqual(base.tree_contents(source), source_before)
        self.assertEqual(base.tree_contents(target), target_before)
        run = self.latest(project)
        section, books = self.books(run)
        self.assertEqual(section['status'], 'complete')
        self.assertIsNone(books['Books/same.epub']['flags'] or None)
        self.assertEqual(books['Books/same.epub']['comparison']['progress'], 'same')
        progress = books['Books/progress.epub']
        self.assertEqual(progress['comparison']['progress'], 'differs')
        self.assertEqual(progress['comparison']['percent_delta'], 0.5)
        self.assertEqual(progress['comparison']['annotations'], 'differs')
        self.assertEqual(progress['comparison']['newer_hint'], {'side': 'source', 'basis': 'summary_modified'})
        self.assertIn('target_annotations_replaced', progress['flags'])
        self.assertIn('target_reading_data_replaced', progress['flags'])
        self.assertEqual(progress['target']['stores'][0]['planned_action'], 'overwrite')
        self.assertIn('edition_mismatch', books['Books/edition.epub']['flags'])
        self.assertIn('content_differs', books['Books/content.epub']['flags'])
        broken = books['Books/broken.epub']
        self.assertEqual(broken['source']['stores'][0]['parse_status'], 'executable_construct')
        self.assertIn('unparseable', broken['flags'])
        moved = books['Books/moved.epub']
        self.assertEqual(moved['match']['confidence'], 'probable')
        self.assertEqual(moved['match']['candidates'], ['Books/renamed.epub'])
        self.assertIn('moved_candidate', moved['flags'])
        twin = books['Books/twin.epub']
        self.assertEqual(twin['match']['candidates'], ['Books/twin-a.epub', 'Books/twin-b.epub'])
        self.assertIn('ambiguous_match', twin['flags'])
        self.assertIn('stale_sidecar_suspected', books['Books/stale.epub']['flags'])
        hashed = books['Books/hash.epub']
        self.assertIn('multiple_stores', hashed['flags'])
        self.assertEqual({s['location'] for s in hashed['target']['stores']}, {'sidecar', 'hashdocsettings'})
        self.assertIn('retained_for_different_book', books['Books/orphan.epub']['flags'])
        self.assertEqual(section['summary']['unreadable_files'], 1)
        self.assertEqual(section['summary']['unparseable'], 1)
        serialized = json.dumps(section, ensure_ascii=False)
        for private in ('private note', 'Sample', 'A\\nB'):
            self.assertNotIn(private, serialized)
        text = (run / 'difference.txt').read_text(encoding='utf-8')
        self.assertIn('Reading data (report only', text)
        self.assertIn('TARGET annotations will be replaced', text)
        self.assertNotIn('Books/same.epub', text.split('Reading data (report only')[1])
        log = '\n'.join(p.read_text(encoding='utf-8') for p in run.glob('*.log'))
        self.assertIn('WARNING: TARGET reading data for', log)

    def test_reporter_does_not_change_plan_or_copy_result(self):
        source, target = self.devices()
        twin = self.root / 'twin'
        __import__('shutil').copytree(target, twin)
        project = self.root / 'project'
        flags = ['--mode', 'library', '--books', '--no-fonts', '--conflict', 'overwrite']
        self.assertEqual(self.execute(project, [source, target], flags)[0], 0)
        reported = m.read_json(self.latest(project) / 'difference.json')
        with mock.patch.object(m, 'reading_data_section', return_value=m.reading_data_skipped('skipped', 'option_disabled')), \
                mock.patch.object(m, 'capture_source_reading', return_value=None):
            self.assertEqual(self.execute(self.root / 'project2', [source, twin], flags)[0], 0)
        plain = m.read_json(self.latest(self.root / 'project2') / 'difference.json')
        self.assertEqual(base.tree_contents(target), base.tree_contents(twin))
        self.assertEqual(reported['files'], plain['files'])
        self.assertEqual(reported['summary'], plain['summary'])
        # The report describes TARGET before writes: replaced annotations are recorded.
        _, books = self.books(self.latest(project))
        self.assertEqual(books['Books/progress.epub']['target']['stores'][0]['fields']['counts']['annotations'], 2)
        self.assertEqual((target / 'Books/progress.sdr/metadata.epub.lua').read_bytes(),
                         (source / 'Books/progress.sdr/metadata.epub.lua').read_bytes())

    def test_saved_source_reads_verified_archives(self):
        source, target = self.devices()
        project = self.root / 'project'
        flags = ['--mode', 'library', '--books', '--no-fonts', '--conflict', 'overwrite']
        self.assertEqual(self.execute(project, [source, target], flags)[0], 0)
        saved = self.latest(project)
        live = self.books(saved)[1]
        base.write_file(target / 'Books/progress.sdr/metadata.epub.lua', sidecar(percent=0.3, annotations=2))
        code, calls = self.execute(project, [target], ['--from-run', saved.name, '--dry-run'])
        self.assertEqual((code, calls), (0, 1))
        section, books = self.books(self.latest(project))
        self.assertEqual(section['status'], 'complete')
        self.assertIn('target_annotations_replaced', books['Books/progress.epub']['flags'])
        self.assertEqual(books['Books/progress.epub']['source']['stores'][0]['sha256'],
                         live['Books/progress.epub']['source']['stores'][0]['sha256'])
        self.assertIsNone(books['Books/progress.epub']['source']['stores'][0]['mtime'])

    def test_full_reports_central_stores_replaced_by_runtime(self):
        source, target = self.devices()
        base.write_file(source / '.adds/koreader/docsettings/mnt/onboard/Books/same.sdr/metadata.epub.lua', sidecar(percent=0.6))
        base.write_file(target / '.adds/koreader/docsettings/mnt/onboard/Books/same.sdr/metadata.epub.lua',
                        sidecar(percent=0.4, annotations=1))
        project = self.root / 'project'
        code, _ = self.execute(project, [source, target], ['--mode', 'full', '--dry-run'])
        self.assertEqual(code, 0)
        _, books = self.books(self.latest(project))
        same = books['Books/same.epub']
        actions = {(s['location'], s['planned_action']) for s in same['target']['stores']}
        self.assertIn(('docsettings', 'removed_by_runtime'), actions)
        self.assertIn(('docsettings', 'via_runtime'), {(s['location'], s['planned_action']) for s in same['source']['stores']})
        self.assertIn('target_annotations_replaced', same['flags'])
        self.assertIn('removed_by_runtime', {s['planned_action'] for s in books['Books/hash.epub']['target']['stores']})

    def test_skipped_modes_and_options(self):
        cases = [(['--mode', 'koreader', '--dry-run'], 'not_applicable', 'mode_koreader'),
                 (['--mode', 'library', '--books', '--no-fonts', '--no-reading-data', '--conflict', 'overwrite',
                   '--dry-run'], 'skipped', 'option_disabled'),
                 (['--mode', 'library', '--no-books', '--fonts', '--conflict', 'overwrite', '--dry-run'],
                  'skipped', 'no_books')]
        for index, (flags, status, reason) in enumerate(cases):
            source, target = self.devices() if index == 0 else (self.root / 'source', self.root / 'target')
            base.write_file(source / 'fonts/custom.ttf', b'font')
            project = self.root / f'project{index}'
            self.assertEqual(self.execute(project, [source, target], flags)[0], 0, flags)
            section = m.read_json(self.latest(project) / 'difference.json')['reading_data']
            self.assertEqual((section['status'], section['reason']), (status, reason), flags)

    def test_keep_target_marks_source_data_not_copied(self):
        source, target = self.devices()
        project = self.root / 'project'
        code, _ = self.execute(project, [source, target], ['--mode', 'library', '--books', '--no-fonts',
                                                            '--conflict', 'keep-target', '--dry-run'])
        self.assertEqual(code, 0)
        _, books = self.books(self.latest(project))
        self.assertIn('target_kept', books['Books/edition.epub']['flags'])
        self.assertNotIn('target_annotations_replaced', books['Books/progress.epub']['flags'])

    def test_reporter_failure_and_limits_never_block_migration(self):
        source, target = self.devices()
        flags = ['--mode', 'library', '--books', '--no-fonts', '--conflict', 'overwrite', '--dry-run']
        with mock.patch.object(m, 'build_reading_data_report', side_effect=RuntimeError('boom')):
            self.assertEqual(self.execute(self.root / 'p1', [source, target], flags)[0], 0)
        section = m.read_json(self.latest(self.root / 'p1') / 'difference.json')['reading_data']
        self.assertEqual((section['status'], section['reason']), ('failed', 'internal_error'))
        with mock.patch.object(m, 'READING_MAX_STORES', 3):
            self.assertEqual(self.execute(self.root / 'p2', [source, target], flags)[0], 0)
        section = m.read_json(self.latest(self.root / 'p2') / 'difference.json')['reading_data']
        self.assertEqual((section['status'], section['reason']), ('partial', 'limit_exceeded'))
        self.assertTrue(any(s['parse_status'] == 'skipped_limit' for b in section['books']
                            for s in b['source']['stores'] + b['target']['stores']))

    def test_localized_difference_text(self):
        source, target = self.devices()
        expected = {'zh-Hant': ('閱讀資料（僅供檢視', 'TARGET 的註記將被取代'),
                    'zh-Hans': ('阅读数据（仅供查看', 'TARGET 的批注将被替换')}
        for tag, phrases in expected.items():
            project = self.root / tag
            code, _ = self.execute(project, [source, target], ['--locale', tag, '--mode', 'library', '--books',
                                                               '--no-fonts', '--conflict', 'overwrite', '--dry-run'])
            self.assertEqual(code, 0)
            text = (self.latest(project) / 'difference.txt').read_text(encoding='utf-8')
            for phrase in phrases:
                self.assertIn(phrase, text)


def base_execute(case, project, devices, flags):
    argv = ['tool', '--backup-dir', str(project)] + flags
    if '--from-run' not in flags:
        argv += ['--source-model', m.MODEL_CLARA, '--target-model', m.MODEL_LIBRA]
    with mock.patch('sys.argv', argv), mock.patch.object(m, 'require_macos_tools'), \
            mock.patch.object(m, 'run_with_spinner', side_effect=base.fake_ditto), \
            mock.patch.object(m, 'wait_for_single_kobo', side_effect=devices) as wait, \
            mock.patch.object(m, 'safe_eject'), mock.patch.object(m, 'choose', return_value='1'), \
            mock.patch.object(m, 'choose_identity_mode', return_value='preserve'), \
            mock.patch.object(m, 'prompt_yes_no', return_value=True), mock.patch('builtins.input', return_value=''):
        return m.main(), wait.call_count


if __name__ == '__main__':
    unittest.main()
