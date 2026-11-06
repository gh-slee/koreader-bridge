#!/usr/bin/env python3
"""
KOReader Bridge — shared engine and legacy-compatible CLI entry.
macOS, standard library only.

Supported workflow:
  SOURCE Kobo -> TARGET Kobo; both roles confirmed by the operator

Safety model:
  - Source is read-only from the script's perspective.
  - Source KOReader is archived to the project run directory and fully hashed.
  - Target KOReader is archived before any destructive operation.
  - Target .adds/koreader is then cleanly replaced (never Finder-merged).
  - Restored files are verified against a per-file SHA-256 manifest.
  - On restore/verification failure, the target backup is automatically restored.
  - Target KOReader device_id can be preserved (recommended), regenerated, or cloned.
  - Optional ebooks are staged on the Mac and copied to matching relative paths.
  - Overwritten ebooks are backed up; copied files are hashed and rolled back on failure.

This tool intentionally clones the whole .adds/koreader tree.
Backups may contain API keys or other credentials; treat them as sensitive.
"""

from __future__ import annotations

import argparse
import fcntl
from contextlib import ExitStack, closing, contextmanager
from contextvars import ContextVar
from functools import lru_cache
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
import sqlite3
import stat
import string
import tempfile
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

PROJECT_NAME = "KOReader Bridge"
VERSION = "1.1.0-dev.9"
DEFAULT_BACKUP_DIR = Path(__file__).resolve().parent
VOLUME_ROOT = Path("/Volumes")

MODEL_CLARA = "Kobo Clara 2E"
MODEL_LIBRA = "Kobo Libra 2"

# We intentionally do not verify files that are deliberately removed after restore.
VERIFY_EXCLUDES = {
    "cache/fontlist/fontinfo.dat",
    "cache/fontinfo.dat",
}

APPLEDOUBLE_PREFIX = "._"
DEVICE_ID_RE = re.compile(
    r'(\["device_id"\]\s*=\s*)"([^"]*)"',
    flags=re.MULTILINE,
)
DETECTED_KOBO_RE = re.compile(
    r"Detected a Kobo\s+(.+?)\s+\(",
    flags=re.IGNORECASE,
)


class MigrationError(RuntimeError):
    pass


class MigrationCancelled(RuntimeError):
    """An intentional cancellation before any target modification."""
    pass


@dataclass
class DeviceInfo:
    mount: str
    detected_model: Optional[str]
    koreader_version: Optional[str]
    fingerprint_sha256: Optional[str]
    serial_hint: Optional[str]
    device_id_present: bool
    ai_assistant_config: bool  # Legacy snapshot metadata; not a dedicated UI check.
    file_count: int
    total_bytes: int


# Locale assets are reviewed data. Locale names never select arbitrary files.
LOCALE_ROOT = Path(__file__).resolve().parent / 'locales'
LOCALE_MAX_BYTES = 256 * 1024
LOCALE_TAG_RE = re.compile(r'[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?\Z')
MESSAGE_ID_RE = re.compile(r'[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\Z')
LOCALE_REQUIRED_IDS = frozenset({
    'cli.description',
    'cli.foundation_notice',
    'cli.locales_heading',
    'help.backup_dir',
    'help.books',
    'help.cleanup',
    'help.conflict',
    'help.delete_run',
    'help.dry_run',
    'help.exclude_dir',
    'help.extra_extension',
    'help.fonts',
    'help.from_run',
    'help.help',
    'help.include_dir',
    'help.keep_successful',
    'help.list_locales',
    'help.list_runs',
    'help.locale',
    'help.mode',
    'help.preview_ui',
    'help.reading_data',
    'help.restore_run',
    'help.self_test',
    'help.source_model',
    'help.target_model',
    'help.verify_run',
    'help.verify_all',
    'help.with_dependencies',
    'help.json',
    'help.resume_run',
    'help.version',
    'mode.audit',
    'mode.full',
    'mode.koreader',
    'mode.library',
    'preview.default_no',
    'preview.delete',
    'preview.file_count',
    'preview.notice',
    'preview.title',
})
PLURAL_RULES = {'one-other': {'one', 'other'}, 'other-only': {'other'}}


class LocaleError(ValueError):
    """English startup diagnostic that never includes catalog contents."""


def _locale_text(value, limit=8192, multiline=True):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LocaleError('Locale text must be a nonempty bounded string.')
    if any(unicodedata.category(ch) in {'Cc', 'Cf', 'Cs'} and
           not (multiline and ch in '\n\t') for ch in value):
        raise LocaleError('Locale text contains forbidden control characters.')
    return value


def _unique_locale_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise LocaleError('Duplicate key in locale JSON.')
        result[key] = value
    return result


def _locale_json(root: Path, name: str) -> dict:
    path = root / name
    try:
        if root.is_symlink() or not root.is_dir() or path.is_symlink() or not path.is_file():
            raise LocaleError('Locale assets must be regular files in locales/.')
        with path.open('rb') as stream:
            raw = stream.read(LOCALE_MAX_BYTES + 1)
        if len(raw) > LOCALE_MAX_BYTES:
            raise LocaleError('Locale asset exceeds the size limit.')
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_locale_object)
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, LocaleError):
            raise
        raise LocaleError('Cannot read a valid UTF-8 locale asset.') from None
    if not isinstance(result, dict) or type(result.get('schema_version')) is not int or result['schema_version'] != 1:
        raise LocaleError('Unsupported locale asset schema.')
    return result


def _normalize_locale(value: str) -> Optional[str]:
    if not isinstance(value, str) or len(value) > 80 or not re.fullmatch(r'[A-Za-z0-9_.@-]+', value.strip()):
        return None
    tag = value.strip().split('.', 1)[0].split('@', 1)[0].replace('_', '-')
    if tag.casefold() in {'c', 'posix'}:
        return 'en'
    pieces = tag.split('-')
    normalized = [pieces[0].lower()]
    for piece in pieces[1:]:
        normalized.append(piece.title() if len(piece) == 4 else piece.upper())
    tag = '-'.join(normalized)
    return tag if LOCALE_TAG_RE.fullmatch(tag) else None


def load_locale_registry(root: Path) -> dict:
    data = _locale_json(root, 'registry.json')
    if set(data) != {'schema_version', 'locales'} or not isinstance(data['locales'], list) or not 1 <= len(data['locales']) <= 100:
        raise LocaleError('Invalid locale registry.')
    entries, aliases = {}, {}
    for item in data['locales']:
        if not isinstance(item, dict) or set(item) != {'tag', 'name', 'plural_rule', 'aliases'}:
            raise LocaleError('Invalid locale registry entry.')
        tag = item['tag']
        if not isinstance(tag, str) or not LOCALE_TAG_RE.fullmatch(tag) or tag in entries:
            raise LocaleError('Invalid or duplicate registered locale.')
        _locale_text(item['name'], 80, multiline=False)
        if not isinstance(item['plural_rule'], str) or item['plural_rule'] not in PLURAL_RULES:
            raise LocaleError('Unsupported locale plural rule.')
        if not isinstance(item['aliases'], list) or len(item['aliases']) > 100:
            raise LocaleError('Invalid locale aliases.')
        entries[tag] = dict(item)
    if 'en' not in entries or entries['en']['plural_rule'] != 'one-other':
        raise LocaleError('Registry must include English with the one-other rule.')
    for tag, item in entries.items():
        for alias in [tag] + item['aliases']:
            normalized = _normalize_locale(alias)
            if normalized is None or (normalized in aliases and aliases[normalized] != tag):
                raise LocaleError('Invalid or conflicting locale alias.')
            aliases[normalized] = tag
    return {'entries': entries, 'aliases': aliases}


def resolve_locale_tag(value: str, registry: dict) -> Optional[str]:
    tag = _normalize_locale(value)
    if tag is None or tag == 'zh':
        return None
    parts = tag.split('-')
    # An explicit script must win over any region alias.
    if len(parts) >= 2 and len(parts[1]) == 4:
        return registry['entries'].get('-'.join(parts[:2]), {}).get('tag')
    if tag in registry['aliases']:
        return registry['aliases'][tag]
    return parts[0] if parts[0] in registry['entries'] else None


def select_locale(requested: Optional[str], environ: dict, registry: dict):
    if requested is not None:
        tag = resolve_locale_tag(requested, registry)
        if tag is None:
            raise LocaleError('Unsupported --locale. Use --list-locales to see supported tags.')
        return tag, []
    override = environ.get('KOBO_MIGRATE_LOCALE', '').strip()
    if override:
        tag = resolve_locale_tag(override, registry)
        return (tag, []) if tag else ('en', ['Unsupported environment locale; using English.'])
    preferences = next((environ.get(key, '').strip() for key in
                        ('LANGUAGE', 'LC_ALL', 'LC_MESSAGES', 'LANG') if environ.get(key, '').strip()), '')
    for preference in preferences.split(':'):
        tag = resolve_locale_tag(preference, registry)
        if tag:
            return tag, []
    notices = ['Chinese script is unspecified; use --locale zh-Hant or zh-Hans. Using English.'] if any(
        _normalize_locale(p) == 'zh' for p in preferences.split(':')) else []
    return 'en', notices


def _template_fields(template: str) -> set:
    _locale_text(template)
    fields = set()
    try:
        for literal, field, spec, conversion in string.Formatter().parse(template):
            if field is None:
                continue
            if not re.fullmatch(r'[a-z][a-z0-9_]*', field) or conversion is not None or spec not in {'', 'd', ',d', '.1f'}:
                raise LocaleError('Unsafe or unsupported locale placeholder.')
            fields.add(field)
    except ValueError as exc:
        if isinstance(exc, LocaleError):
            raise
        raise LocaleError('Malformed locale format string.') from None
    return fields


def load_locale_catalog(root: Path, tag: str, registry: dict, english: Optional[dict] = None, complete=False) -> dict:
    if tag not in registry['entries']:
        raise LocaleError('Unregistered locale catalog.')
    data = _locale_json(root, tag + '.json')
    if set(data) != {'schema_version', 'locale', 'messages'} or data['locale'] != tag or not isinstance(data['messages'], dict):
        raise LocaleError('Invalid locale catalog schema or tag.')
    messages = data['messages']
    if not messages or len(messages) > 2000:
        raise LocaleError('Locale catalog must contain a bounded message map.')
    if tag == 'en' and not (LOCALE_REQUIRED_IDS | UI_MESSAGE_FIELDS.keys()) <= set(messages):
        raise LocaleError('Canonical English catalog is missing required messages.')
    if english is not None and (set(messages) - set(english) or (complete and set(messages) != set(english))):
        raise LocaleError('Locale catalog message coverage does not match English.')
    forms = PLURAL_RULES[registry['entries'][tag]['plural_rule']]
    for key, value in messages.items():
        if not MESSAGE_ID_RE.fullmatch(key):
            raise LocaleError('Invalid locale message identifier.')
        if isinstance(value, str):
            fields = _template_fields(value)
        elif isinstance(value, dict) and set(value) == forms:
            variants = [_template_fields(text) for text in value.values()]
            if 'count' not in variants[0] or any(fields != variants[0] for fields in variants):
                raise LocaleError('Plural variants must use identical placeholders including count.')
            fields = variants[0]
        else:
            raise LocaleError('Invalid locale message or plural variants.')
        if tag == 'en' and key in LOCALE_REQUIRED_IDS:
            plural = key == 'preview.file_count'
            if fields != ({'count'} if plural else set()) or isinstance(value, dict) != plural:
                raise LocaleError('Canonical message placeholders do not match the startup contract.')
        if tag == 'en' and key in UI_MESSAGE_FIELDS:
            if not isinstance(value, str) or fields != UI_MESSAGE_FIELDS[key]:
                raise LocaleError('Canonical message placeholders do not match the UI contract.')
        if english is not None:
            original = english[key]
            reference = original if isinstance(original, str) else original['other']
            if isinstance(value, str) != isinstance(original, str) or fields != _template_fields(reference):
                raise LocaleError('Locale placeholders or message types do not match English.')
    return messages


@dataclass(frozen=True)
class LocaleBundle:
    tag: str
    registry: dict
    english: dict
    messages: dict
    notices: tuple

    def render(self, key: str, **values) -> str:
        if key not in self.english:
            raise LocaleError('Unknown locale message identifier.')
        original = self.english[key]
        translated = self.messages.get(key, original)
        if isinstance(original, dict):
            count = values.get('count')
            if type(count) is not int or count < 0:
                raise LocaleError('Plural messages require a nonnegative integer count.')
            rule = self.registry['entries'][self.tag]['plural_rule'] if key in self.messages else 'one-other'
            form = 'one' if rule == 'one-other' and count == 1 else 'other'
            translated = translated.get(form, original['one' if count == 1 else 'other'])
            original = original['one' if count == 1 else 'other']
        # The English field set is authoritative; mismatched callers are programmer errors.
        if set(values) != _template_fields(original):
            raise LocaleError('Message parameters do not match the English template.')
        try:
            return translated.format(**values)
        except (ValueError, TypeError, KeyError, OverflowError):
            try:
                return original.format(**values)
            except (ValueError, TypeError, KeyError, OverflowError):
                raise LocaleError('Cannot format the English locale message.') from None


def load_locale_bundle(requested=None, environ=None, root=None) -> LocaleBundle:
    root = LOCALE_ROOT if root is None else Path(root)
    registry = load_locale_registry(root)
    english = load_locale_catalog(root, 'en', registry)
    tag, notices = select_locale(requested, os.environ if environ is None else environ, registry)
    messages = english
    if tag != 'en':
        try:
            messages = load_locale_catalog(root, tag, registry, english)
        except LocaleError:
            tag, messages = 'en', english
            notices.append('Requested translation is invalid or unavailable; using English.')
    return LocaleBundle(tag, registry, english, messages, tuple(notices))


def locale_console_write(text: str, stream=None) -> None:
    """Write read-only startup output without triggering Unicode failures."""
    stream = sys.stdout if stream is None else stream
    encoding = getattr(stream, 'encoding', None) or 'utf-8'
    stream.write(text.encode(encoding, errors='backslashreplace').decode(encoding))
    stream.flush()


class LocaleArgumentParser(argparse.ArgumentParser):
    """Use public parser methods to handle non-UTF-8 help/error streams safely."""
    def print_help(self, file=None):
        locale_console_write(self.format_help(), sys.stdout if file is None else file)

    def print_usage(self, file=None):
        locale_console_write(self.format_usage(), sys.stdout if file is None else file)

    def exit(self, status=0, message=None):
        if message:
            locale_console_write(message, sys.stderr)
        raise SystemExit(status)


def preview_locale_ui(bundle: LocaleBundle) -> None:
    lines = [bundle.render('preview.title'), bundle.render('preview.notice'), '']
    for number, token in enumerate(('full', 'koreader', 'library', 'audit'), 1):
        lines.append(f"  {number}) {token.upper()}: {bundle.render('mode.' + token)}")
    lines += ['', bundle.render('preview.default_no'), bundle.render('preview.delete'),
              bundle.render('preview.file_count', count=2)]
    locale_console_write('\n'.join(lines) + '\n')



# Owned runtime presentation uses explicit IDs; bootstrap/framework diagnostics stay English.
UI_MESSAGE_FIELDS = {
    'ui.partial_notice': set(),
    'prompt.retry_yes_no': set(), 'prompt.default': set(), 'prompt.selection': set(),
    'prompt.invalid_selection': set(), 'prompt.confirmation': set(),
    'run.banner': {'version', 'run_id'}, 'run.log_path': {'path'},
    'run.cancelled': {'detail'}, 'run.interrupted': set(),
    'run.stopped': {'kind', 'detail'}, 'error.summary': {'detail'},
    'progress.files': {'label', 'bar', 'percent', 'done', 'total'},
    'progress.start': {'label', 'size'},
    'progress.bytes': {'label', 'percent', 'done', 'total', 'rate', 'elapsed', 'eta'},
    'progress.hash_file': {'name'}, 'progress.hash_archive': set(),
    'progress.verify_target': set(), 'progress.hash_payload': set(),
    'progress.archive_payload': set(), 'progress.copy_payload': set(),
    'progress.verify_members': set(), 'progress.verify_file': {'name'},
    'catalog.heading': set(), 'catalog.empty': set(),
    'cleanup.heading': set(), 'cleanup.empty': set(), 'cleanup.reclaimable': {'size'},
    'cleanup.protected': {'run_id', 'reason'}, 'cleanup.confirm': {'expected'},
    'cleanup.cancelled': set(), 'cleanup.deleted': {'run_id'},
    'verify.heading': {'run_id'}, 'verify.running': set(), 'verify.empty': set(),
    'verify.passed': {'name', 'kind'}, 'verify.failed': {'name', 'detail'},
    'verify.dependency_heading': {'run_id', 'parent'}, 'verify.missing_dependency': {'run_id', 'parent'},
    'verify.overall': {'runs', 'failed'}, 'verify.no_runs': set(),
    'verify.summary': {'verified', 'failed'},
    'difference.title': set(), 'difference.retain': set(),
    'difference.section': {'label', 'count', 'size'}, 'difference.paths': {'path'},
    'difference.new': set(), 'difference.overwrite': set(), 'difference.identical': set(),
    'difference.keep_target': set(), 'difference.metadata_skipped': set(), 'difference.target_only': set(),
    'confirm.continue': set(), 'confirm.saved_source': set(), 'confirm.restore_target': set(),
    'confirm.compatibility': set(), 'confirm.migration': set(),
    'confirm.books': set(), 'confirm.fonts': set(), 'confirm.device': {'role', 'model'},
    'prompt.source': set(), 'prompt.target': set(),
    'prompt.restore_target': {'model'}, 'device.waiting': {'role'},
    'device.connect_one': set(), 'device.detected': {'path'},
    'migration.success': {'path'}, 'migration.done': set(),
    'menu.mode': set(),
    'menu.full': set(),
    'menu.koreader': set(),
    'menu.library': set(),
    'menu.audit': set(),
    'menu.identity': set(),
    'menu.identity_preserve': set(),
    'menu.identity_unavailable': set(),
    'menu.identity_new': set(),
    'menu.identity_clone': set(),
    'menu.identity_retry': set(),
    'menu.conflict': set(),
    'menu.overwrite': set(),
    'menu.keep_target': set(),
    'inspection.title': {'role'},
    'inspection.mount': {'path'},
    'inspection.model': {'model'},
    'inspection.version': {'version'},
    'inspection.files': {'count'},
    'inspection.size': {'size'},
    'inspection.identity': {'present'},
    'inspection.serial': {'hint'},
    'value.yes': set(),
    'value.no': set(),
    'value.unknown': set(),
    'prompt.physical_model': {'role', 'suffix'},
    'device.model_retry': set(),
    'device.log_hint': set(),
    'device.model_mismatch': {'hint', 'model'},
    'device.model_confirmed': {'model', 'role'},
    'space.backup': {'free', 'label', 'need'},
    'space.target': {'effective', 'free', 'need'},
    'space.library': {'free', 'need'},
    'space.source_backup': set(),
    'space.target_backup': set(),
    'space.pre_restore': set(),
    'migration.options': {'books', 'conflict', 'fonts', 'mode'},
    'diagnostic.raw': {'detail'},
    'device.flushing': set(),
    'device.ejecting': {'path'},
    'device.eject_output': {'detail'},
    'device.ejected': set(),
    'archive.build_manifest': set(),
    'archive.verify_count': {'count'},
    'archive.verified': set(),
    'recovery.modified_failure': set(),
    'recovery.starting': set(),
    'recovery.no_original': set(),
    'recovery.runtime_success': set(),
    'recovery.runtime_restored': set(),
    'recovery.payload_success': set(),
    'identity.cloned': set(),
    'identity.preserved': set(),
    'identity.new': set(),
    'identity.applied': {'label'},
    'saved_source.using': {'run_id', 'model'},
    'saved_source.connect': set(),
    'restore.heading': {'run_id', 'model'},
    'resume.heading': {'run_id', 'model'}, 'resume.scope': set(), 'prompt.resume_target': {'model'},
    'resume.runtime_none': set(), 'resume.runtime_keep': set(),
    'resume.runtime_replace_interrupted': set(), 'resume.runtime_replace_rollback': set(),
    'resume.runtime_replace_changed': set(),
    'resume.library': {'verified', 'remaining', 'partial', 'size'},
    'resume.drifted': {'path'}, 'resume.preview': {'path'}, 'space.pre_resume': set(),
    'error.resume_operation': {'operation'}, 'error.resume_status': {'status'},
    'error.resume_phase': {'phase'}, 'error.resume_superseded': {'run_id', 'other'},
    'error.resume_plan_missing': set(), 'error.resume_plan_invalid': set(),
    'error.resume_plan_mismatch': {'path'}, 'error.resume_backup_incomplete': set(),
    'error.resume_target_model': set(), 'error.resume_drift': {'count'},
    'error.resume_chain': set(), 'error.restore_superseded': {'run_id', 'other'},
    'resume.final_plan': {'runtime', 'count'}, 'confirm.resume': set(), 'cancel.resume': set(),
    'resume.success': {'path'}, 'resume.rolled_back': set(), 'catalog.resumed_by': {'run_id'},
    'restore.scope': set(),
    'restore.plan': {'remove_count', 'runtime', 'restore_count'},
    'restore.original': {'path'},
    'restore.remove_created': {'path'},
    'restore.preview': set(),
    'restore.failed': {'detail'},
    'restore.rollback_blocked': {'detail'},
    'restore.rollback_errors': {'detail'},
    'restore.rolled_back': set(),
    'restore.success': set(),
    'workflow.preview': set(),
    'workflow.local_reports': set(),
    'workflow.disconnect': set(),
    'workflow.private_archives': set(),
    'diagnostic.metadata_mode': {'mode'},
    'diagnostic.statistics': {'detail'},
    'diagnostic.source_missing': {'count'},
    'workflow.payload': {'count', 'size'},
    'workflow.category': {'count', 'category'},
    'diagnostic.warning': {'detail'},
    'workflow.scan_report': {'path'},
    'diagnostic.plugins': {'warnings', 'count'},
    'diagnostic.plugin_warning': {'detail'},
    'preview.archive_runtime': {'path'},
    'preview.archive_payload': {'path'},
    'workflow.unplug_source': set(),
    'workflow.target_preflight': set(),
    'workflow.target_comparison': set(),
    'workflow.payload_plan': {'skip', 'overwrite', 'copy', 'keep'},
    'workflow.metadata_skipped': {'count'},
    'preview.replace_runtime': {'path'},
    'preview.backup_runtime': {'path'},
    'preview.overwrite': set(),
    'preview.create': set(),
    'preview.payload_path': {'action', 'path'},
    'preview.complete': {'path'},
    'workflow.verify_source': set(),
    'workflow.backup_runtime': set(),
    'workflow.backup_payload': set(),
    'workflow.final_plan': {'count', 'runtime'},
    'workflow.retain_unrelated': set(),
    'recovery.status_error': {'detail'},
    'recovery.migration_failed': {'kind', 'detail'},
    'recovery.blocked': {'detail'},
    'recovery.reconnect': set(),
    'recovery.error': {'detail'},
    'recovery.keep_connected': set(),
    'recovery.complete': set(),
    'diagnostic.after_missing': {'count'},
    'run.pre_interrupt': set(),
    'error.same_device': set(),
    'error.disconnected': set(),
    'error.device_changed': set(),
    'error.identity_missing': set(),
    'error.target_space': set(),
    'error.library_space': set(),
    'error.source_cycle': set(),
    'error.source_descriptor': set(),
    'error.source_reference_mode': set(),
    'error.library_snapshot': set(),
    'error.full_snapshot': set(),
    'error.runtime_archive_missing': set(),
    'error.saved_scope': set(),
    'error.full_captured_books': set(),
    'error.koreader_snapshot_scope': set(),
    'error.payload_categories': set(),
    'error.library_selection': set(),
    'error.source_model_missing': set(),
    'error.source_model_mismatch': set(),
    'error.target_snapshot': set(),
    'error.original_backup_missing': set(),
    'error.restore_unneeded': set(),
    'error.change_journal': set(),
    'error.change_paths': set(),
    'error.restore_identity': set(),
    'error.runtime_directory': set(),
    'error.conflict_mode': set(),
    'error.full_books': set(),
    'error.full_scope': set(),
    'error.koreader_scope': set(),
    'error.target_directory': set(),
    'error.full_keep_target': set(),
    'error.source_runtime_checksum': set(),
    'error.source_payload_checksum': set(),
    'error.statistics_changed': set(),
    'cancel.device': set(),
    'cancel.migration': set(),
    'cancel.restore': set(),
    'cancel.compatibility': set(),
    'cancel.final': set(),
    'error.backup_space': {'label', 'path'},
    'phase.started': {'label'},
    'phase.running': {'seconds', 'label'},
    'phase.finished': {'seconds', 'label'},
    'archive.creating': set(),
    'archive.restoring': set(),
    'error.platform': set(),
    'error.command_missing': {'command'},
    'error.multiple_devices': set(),
    'error.command_failed': {'code', 'command', 'detail'},
    'error.identity_symlink': set(),
    'error.identity_size': set(),
    'error.identity_file_missing': {'path'},
    'error.settings_table': set(),
    'error.model_ascii': set(),
    'error.source_preflight': {'paths'},
    'error.tree_root_symlink': {'path'},
    'error.runtime_symlink': {'path'},
    'error.runtime_zip_unsafe': {'name'},
    'error.runtime_zip_duplicate': {'name'},
    'error.archive_reader_missing': set(),
    'error.zip_path_duplicate': {'path'},
    'error.zip_read': {'detail', 'path'},
    'error.backup_exists': {'path'},
    'error.restore_required_missing': {'path'},
    'error.restore_file_missing': {'path'},
    'error.restore_size': {'path'},
    'error.restore_checksum': {'path'},
    'error.rollback_archive_changed': set(),
    'error.preserve_identity_missing': set(),
    'error.identity_mode': {'mode'},
    'error.identity_verify': set(),
    'error.relative_path': {'path'},
    'error.system_path': {'path'},
    'error.device_root': {'path'},
    'error.path_symlink': {'path'},
    'error.parent_directory': {'path'},
    'error.payload_regular_file': {'path'},
    'error.case_unicode_collision': {'first', 'second'},
    'error.file_directory_collision': {'first', 'path'},
    'error.book_directory': {'path'},
    'error.source_scan_changed': {'path'},
    'error.source_archive_changed': {'path'},
    'error.destination_collision': {'path', 'second'},
    'error.payload_zip_duplicate': set(),
    'error.payload_zip_missing': {'path'},
    'error.payload_zip_unsafe': {'path'},
    'error.payload_verify': {'path'},
    'error.rollback_payload_changed': {'path'},
    'error.rollback_payload_missing': set(),
    'error.statistics_symlink': set(),
    'error.statistics_wal': set(),
    'error.statistics_check': {'detail'},
    'error.statistics_read': {'detail'},
    'error.backup_on_device': set(),
    'error.lock_symlink': {'path'},
    'error.lock_regular_file': set(),
    'error.lock_busy': {'label'},
    'error.lock_directory_symlink': set(),
    'error.json_missing': {'name'},
    'error.json_read': {'name'},
    'error.json_object': {'name'},
    'error.run_reference': set(),
    'error.run_symlink': set(),
    'error.run_location': set(),
    'error.artifact_filename': set(),
    'error.artifact_missing': {'name'},
    'error.manifest_invalid': set(),
    'error.manifest_path': set(),
    'error.manifest_system_path': set(),
    'error.manifest_entry': {'path'},
    'error.saved_archive_checksum': {'name'},
    'error.saved_zip_duplicate': set(),
    'error.verify_symlink': set(),
    'error.verify_unpaired': set(),
    'error.verify_referenced_missing': {'name'},
    'error.verify_manifest_kind': set(),
    'error.verify_archive_name': {'name'},
    'error.verify_unreadable': {'detail'},
    'error.payload_members': set(),
    'error.payload_directory_entry': set(),
    'error.saved_payload_symlink': set(),
    'error.runtime_members': set(),
    'error.saved_reader_missing': set(),
    'error.saved_zip_size': {'path'},
    'error.saved_zip_checksum': {'path'},
    'error.legacy_scan_count': set(),
    'error.legacy_mode': set(),
    'error.legacy_archive_pair': set(),
    'error.preview_source_missing': set(),
    'error.legacy_payload_missing': set(),
    'error.legacy_model_missing': set(),
    'error.cleanup_keep': set(),
    'error.cleanup_ineligible': set(),
    'error.cleanup_changed': set(),
    'error.cleanup_symlink': set(),
    'error.project_location': set(),
    'error.runs_symlink': set(),
    'scan.complete': {'count'},
    'scan.archiving': {'index', 'path', 'total'},
    'scan.compare_start': {'count'},
    'scan.comparing': {'index', 'path', 'size', 'total'},
    'scan.identical': set(),
    'scan.keep_target': set(),
    'scan.overwrite': set(),
    'scan.create': set(),
    'scan.copying': {'index', 'path', 'total'},
    'scan.metadata': set(),
    'scan.statistics': {'size'},
    'scan.references': set(),
    'scan.saved_verified': {'name'},
    'scan.target_only': set(),
    'self_test.start': set(),
    'self_test.success': set(),
    'catalog.row': {'operation', 'run_id', 'size', 'status'},
    'cleanup.reason_recent': set(),
    'cleanup.reason_dependency': set(),
    'cleanup.reason_recovery': set(),
    'cleanup.reason_unconfirmed': set(),
    'scan.warning_central': set(),
    'scan.warning_scoped': set(),
    'plugin.directory_missing': set(),
    'plugin.main_missing': {'name'},
    'plugin.meta_missing': {'name'},
    'argument.delete_cleanup': set(),
    'argument.keep_minimum': set(),
    'argument.restore_settings': set(),
    'argument.preview_settings': set(),
    'argument.verify_settings': set(),
    'argument.resume_settings': set(),
    'argument.verify_options': set(),
    'lock.project': set(),
    'lock.device': set(),
    'diagnostic.join': {'first', 'second'},
    'recovery.payload_error': {'detail'},
    'recovery.runtime_error': {'detail'},
    'value.true': set(),
    'value.false': set(),
    'reading_data.title': set(),
    'reading_data.status': {'reason', 'status'},
    'reading_data.summary': {'books', 'differs', 'same', 'source_only', 'target_only', 'unparseable'},
    'reading_data.book_detail': {'source_annotations', 'source_progress', 'target_annotations', 'target_progress'},
    'reading_data.more': {'count'},
    'reading_data.value_unknown': set(),
    'reading_data.warning_replaced': {'annotations', 'count'},
    'reading_data.warning_edition': {'count'},
    'reading_data.status_complete': set(),
    'reading_data.status_partial': set(),
    'reading_data.status_skipped': set(),
    'reading_data.status_not_applicable': set(),
    'reading_data.status_failed': set(),
    'reading_data.reason_option_disabled': set(),
    'reading_data.reason_mode_koreader': set(),
    'reading_data.reason_no_books': set(),
    'reading_data.reason_limit_exceeded': set(),
    'reading_data.reason_internal_error': set(),
    'reading_data.flag_edition_mismatch': set(),
    'reading_data.flag_content_differs': set(),
    'reading_data.flag_stale_sidecar_suspected': set(),
    'reading_data.flag_moved_candidate': set(),
    'reading_data.flag_ambiguous_match': set(),
    'reading_data.flag_multiple_stores': set(),
    'reading_data.flag_unparseable': set(),
    'reading_data.flag_target_reading_data_replaced': set(),
    'reading_data.flag_target_annotations_replaced': set(),
    'reading_data.flag_target_kept': set(),
    'reading_data.flag_retained_for_different_book': set(),
}
CURRENT_UI = ContextVar('kobo_migration_ui', default=None)


@lru_cache(maxsize=8)
def _english_output_bundle(root: Path):
    return load_locale_bundle('en', {}, root)


def current_ui():
    ui = CURRENT_UI.get()
    return ui if ui is not None else UIOutput(_english_output_bundle(LOCALE_ROOT), preflight=False)


class UIMessage(str):
    """A stable message ID with English string compatibility for existing helpers."""
    def __new__(cls, key, **values):
        ui = current_ui()
        english, _ = ui.render(key, values)
        result = str.__new__(cls, english)
        result.key, result.values = key, dict(values)
        return result


def message(key, **values):
    return UIMessage(key, **values)


def exception_detail(exc):
    """Render owned structured errors; preserve and label unconverted diagnostics."""
    if len(exc.args) == 1 and isinstance(exc.args[0], UIMessage):
        return exc.args[0]
    return message('diagnostic.raw', detail=str(exc))


def diagnostic_detail(value):
    """Preserve an owned message ID or label a raw diagnostic at presentation."""
    return value if isinstance(value, UIMessage) else message('diagnostic.raw', detail=str(value))


def join_diagnostics(details):
    """Join structured recovery details without flattening translated children."""
    result = details[0]
    for item in details[1:]:
        result = message('diagnostic.join', first=result, second=item)
    return result


def display_bool(value: bool):
    return message('value.true' if value else 'value.false')


class UIOutput:
    """Render console and English diagnostics separately, before writing either."""
    def __init__(self, bundle, log=None, stdout=None, stderr=None, preflight=True):
        self.bundle = bundle
        self.english = LocaleBundle('en', bundle.registry, bundle.english, bundle.english, ())
        self.log = log
        self.stdout = sys.stdout if stdout is None else stdout
        self.stderr = sys.stderr if stderr is None else stderr
        # Format every integrated message before creating runs or accessing devices.
        if preflight:
            for key, fields in UI_MESSAGE_FIELDS.items():
                self.render(key, {field: 0 for field in fields})

    def text(self, value, english=False):
        if isinstance(value, UIMessage):
            pair = self.render(value.key, value.values)
            return pair[0 if english else 1]
        return str(value)

    def render(self, key, values):
        english_values = {key: self.text(value, True) if isinstance(value, UIMessage) else value
                          for key, value in values.items()}
        console_values = {key: self.text(value) if isinstance(value, UIMessage) else value
                          for key, value in values.items()}
        english = self.english.render(key, **english_values)
        console = self.bundle.render(key, **console_values)
        return english, console

    def deliver(self, english, console, *, channel='stdout', severity='info', prefix='', end='\n'):
        if channel not in {'stdout', 'stderr'} or severity not in {'info', 'warning', 'error'}:
            raise ValueError('Invalid UI event channel or severity.')
        stream = self.stderr if channel == 'stderr' else self.stdout
        locale_console_write(prefix + console + end, stream)
        if self.log is not None:
            self.log.write(prefix + english + end)
            self.log.flush()

    def write(self, value, **presentation):
        self.deliver(self.text(value, True), self.text(value), **presentation)

    def emit(self, key, *, channel='stdout', severity='info', prefix='', end='\n', **values):
        english, console = self.render(key, values)
        self.deliver(english, console, channel=channel, severity=severity, prefix=prefix, end=end)

    def read(self, prompt, suffix=''):
        self.write(prompt, end=suffix)
        try:
            # Never log user responses or patch builtins.input/print.
            return input()
        finally:
            if self.log is not None:
                self.log.write('\n')
                self.log.flush()


@contextmanager
def ui_session(bundle, log=None, stdout=None, stderr=None):
    ui = UIOutput(bundle, log, stdout, stderr)
    token = CURRENT_UI.set(ui)
    try:
        yield ui
    finally:
        CURRENT_UI.reset(token)


def ui_emit(key, **values):
    current_ui().emit(key, **values)


def ui_input(prompt):
    return current_ui().read(prompt)


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def human_bytes(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    n = float(value)
    for unit in units:
        if n < 1024.0 or unit == units[-1]:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{value} B"


def prompt_yes_no(question: str, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        ans = current_ui().read(question, suffix=suffix).strip().lower()
        if not ans:
            return default
        if ans in {"y", "yes"}:
            return True
        if ans in {"n", "no"}:
            return False
        ui_emit('prompt.retry_yes_no')


def choose(question: str, options: List[Tuple[str, str]], default: Optional[str] = None) -> str:
    current_ui().write(question)
    for key, label in options:
        ui = current_ui()
        marker = ' ' + ui.text(message('prompt.default')) if key == default else ''
        log_marker = ' ' + ui.text(message('prompt.default'), True) if key == default else ''
        # Numeric choices and model/path values are never translated.
        ui.deliver(f'  {key}) {ui.text(label, True)}{log_marker}',
                   f'  {key}) {ui.text(label)}{marker}')
    while True:
        ans = ui_input(message('prompt.selection')).strip()
        if not ans and default is not None:
            return default
        if any(ans == key for key, _ in options):
            return ans
        ui_emit('prompt.invalid_selection')


def require_macos_tools() -> None:
    if sys.platform != "darwin":
        raise MigrationError(message('error.platform'))
    for cmd in ("ditto", "diskutil", "sync"):
        if shutil.which(cmd) is None:
            raise MigrationError(message('error.command_missing', command=cmd))


def kobo_mounts() -> List[Path]:
    mounts: List[Path] = []
    if not VOLUME_ROOT.exists():
        return mounts
    for path in sorted(VOLUME_ROOT.iterdir()):
        if path.is_symlink() or not path.is_dir():
            continue
        if (path / ".kobo").is_dir() and not (path / ".kobo").is_symlink():
            mounts.append(path)
    return mounts


def wait_for_single_kobo(role: str) -> Path:
    print()
    ui_emit('device.waiting', role=role)
    ui_emit('device.connect_one')
    while True:
        mounts = kobo_mounts()
        if len(mounts) > 1:
            raise MigrationError(
                message('error.multiple_devices')
            )
        if len(mounts) == 1:
            ui_emit('device.detected', path=mounts[0])
            return mounts[0]
        time.sleep(2)


def run_with_spinner(cmd: List[str], label: str, env: Optional[dict] = None) -> None:
    with tempfile.TemporaryFile(mode='w+t') as stdout, tempfile.TemporaryFile(mode='w+t') as stderr:
        proc = subprocess.Popen(cmd, stdout=stdout, stderr=stderr, text=True, env=env)
        started = last = time.monotonic()
        log_status(message('phase.started', label=label))
        try:
            while proc.poll() is None:
                now = time.monotonic()
                if now - last >= 5:
                    log_status(message('phase.running', label=label, seconds=f"{now-started:.0f}"))
                    last = now
                time.sleep(0.12)
        except BaseException:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            raise
        log_status(message('phase.finished', label=label, seconds=time.monotonic()-started))
        if proc.returncode != 0:
            stderr.seek(0)
            stdout.seek(0)
            detail = (stderr.read() or stdout.read()).strip()
            raise MigrationError(message('error.command_failed', code=proc.returncode, command=' '.join(cmd), detail=message('diagnostic.raw', detail=detail)))


def run_checked(cmd: List[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MigrationError(
            message('error.command_failed', code=proc.returncode, command=' '.join(cmd), detail=message('diagnostic.raw', detail=(proc.stderr or proc.stdout).strip()))
        )
    return proc.stdout.strip()


def safe_eject(mount: Path) -> None:
    ui_emit('device.flushing')
    run_checked(["sync"])
    time.sleep(2)
    ui_emit('device.ejecting', path=mount)
    out = run_checked(["diskutil", "eject", str(mount)])
    if out:
        ui_emit('device.eject_output', detail=message('diagnostic.raw', detail=out))
    for _ in range(20):
        if not mount.exists():
            break
        time.sleep(0.5)
    ui_emit('device.ejected')


def canonical_model(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    name = " ".join(name.strip().split())
    low = name.lower()
    if low in {"clara 2e", "kobo clara 2e"}:
        return MODEL_CLARA
    if low in {"libra 2", "kobo libra 2"}:
        return MODEL_LIBRA
    return name if low.startswith("kobo ") else "Kobo " + name


def tail_text(path: Path, max_bytes: int = 2_000_000) -> str:
    if not path.exists() or not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    return data.decode("utf-8", errors="replace")


def detect_model(mount: Path) -> Optional[str]:
    kr = mount / ".adds" / "koreader"

    # A copied KOReader log may describe a different device. This is a hint,
    # never hardware verification; the operator must confirm each role.
    for candidate in (kr / "crash.log", kr / "version.log"):
        text = tail_text(candidate)
        matches = DETECTED_KOBO_RE.findall(text)
        if matches:
            return canonical_model(matches[-1])

        # Best-effort fallback for version logs containing a friendly model name.
        for known in (MODEL_CLARA, MODEL_LIBRA):
            if known.lower() in text.lower():
                return known
    return None


def read_koreader_version(mount: Path) -> Optional[str]:
    git_rev = mount / ".adds" / "koreader" / "git-rev"
    if git_rev.is_file():
        value = git_rev.read_text(encoding="utf-8", errors="replace").strip()
        return value or None

    crash = tail_text(mount / ".adds" / "koreader" / "crash.log")
    matches = re.findall(r"\[\*\]\s+Version:\s+([^\r\n]+)", crash)
    return matches[-1].strip() if matches else None


def device_fingerprint(mount: Path) -> Tuple[Optional[str], Optional[str]]:
    version_file = mount / ".kobo" / "version"
    if not version_file.is_file():
        return None, None
    if mount.is_symlink() or (mount / '.kobo').is_symlink() or version_file.is_symlink():
        raise MigrationError(message('error.identity_symlink'))
    if version_file.stat().st_size > 65536:
        raise MigrationError(message('error.identity_size'))
    raw = version_file.read_bytes()
    if not raw.strip():
        return None, None
    fp = hashlib.sha256(raw).hexdigest()

    text = raw.decode("utf-8", errors="replace").strip()
    first = text.split(",", 1)[0].strip() if text else ""
    if first:
        hint = ("*" * max(0, len(first) - 4)) + first[-4:]
    else:
        hint = None
    return fp, hint


def read_device_id(settings_file: Path) -> Optional[str]:
    if not settings_file.is_file():
        return None
    text = settings_file.read_text(encoding="utf-8", errors="replace")
    match = DEVICE_ID_RE.search(text)
    if not match:
        return None
    value = match.group(2)
    return value if value else None


def set_device_id(settings_file: Path, new_id: str) -> None:
    if not settings_file.is_file():
        raise MigrationError(message('error.identity_file_missing', path=settings_file))

    text = settings_file.read_text(encoding="utf-8", errors="strict")
    match = DEVICE_ID_RE.search(text)

    if match:
        replacement = match.group(1) + f'"{new_id}"'
        updated = text[:match.start()] + replacement + text[match.end():]
    else:
        # KOReader's settings file is a Lua table. If device_id is absent,
        # add it immediately after "return {".
        marker = re.search(r"return\s*\{", text)
        if not marker:
            raise MigrationError(
                message('error.settings_table')
            )
        insert_at = marker.end()
        updated = (
            text[:insert_at]
            + f'\n    ["device_id"] = "{new_id}",'
            + text[insert_at:]
        )

    tmp = settings_file.with_suffix(settings_file.suffix + ".tmp-migration")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, settings_file)


def should_exclude_rel(rel: str) -> bool:
    rel = rel.replace("\\", "/").lstrip("/")
    if rel in VERIFY_EXCLUDES:
        return True
    parts = rel.split("/")
    if any(part == ".DS_Store" or part.startswith(APPLEDOUBLE_PREFIX) for part in parts):
        return True
    return False


def walk_tree_stats(root: Path) -> Tuple[int, int]:
    count = 0
    total = 0
    if not root.exists():
        return 0, 0
    for base, _, files in os.walk(root):
        for name in files:
            p = Path(base) / name
            try:
                st = p.stat()
            except FileNotFoundError:
                continue
            count += 1
            total += st.st_size
    return count, total


def basic_plugin_audit(koreader: Path) -> Tuple[List[str], List[str]]:
    plugins_dir = koreader / "plugins"
    plugins: List[str] = []
    warnings: List[str] = []
    if not plugins_dir.is_dir():
        warnings.append(message('plugin.directory_missing'))
        return plugins, warnings

    for p in sorted(plugins_dir.glob("*.koplugin")):
        if not p.is_dir():
            continue
        plugins.append(p.name)
        # Structural audit only; not a dependency/compatibility guarantee.
        if not (p / "main.lua").is_file():
            warnings.append(message('plugin.main_missing', name=p.name))
        if not (p / "_meta.lua").is_file():
            warnings.append(message('plugin.meta_missing', name=p.name))
    return plugins, warnings


def inspect_device(mount: Path) -> DeviceInfo:
    koreader = mount / ".adds" / "koreader"
    count, total = walk_tree_stats(koreader)
    fingerprint, serial_hint = device_fingerprint(mount)
    settings = koreader / "settings.reader.lua"
    ai_cfg = koreader / "plugins" / "assistant.koplugin" / "configuration.lua"
    return DeviceInfo(
        mount=str(mount),
        detected_model=detect_model(mount),
        koreader_version=read_koreader_version(mount),
        fingerprint_sha256=fingerprint,
        serial_hint=serial_hint,
        device_id_present=read_device_id(settings) is not None,
        ai_assistant_config=ai_cfg.is_file(),
        file_count=count,
        total_bytes=total,
    )


def display_device_info(info: DeviceInfo, label: str) -> None:
    print()
    ui_emit('inspection.title', role=label)
    print('-' * 60)
    ui_emit('inspection.mount', path=info.mount)
    ui_emit('inspection.model', model=info.detected_model or message('value.unknown'))
    ui_emit('inspection.version', version=info.koreader_version or message('value.unknown'))
    ui_emit('inspection.files', count=info.file_count)
    ui_emit('inspection.size', size=human_bytes(info.total_bytes))
    ui_emit('inspection.identity', present=message('value.yes' if info.device_id_present else 'value.no'))
    if info.serial_hint:
        ui_emit('inspection.serial', hint=info.serial_hint)


def confirm_role_model(info: DeviceInfo, requested: Optional[str], role: str) -> str:
    """Confirm the physical model independently from possibly cloned logs."""
    expected = canonical_model(requested)
    if expected is None:
        hint = canonical_model(info.detected_model)
        suffix = f" [{hint}]" if hint else ""
        while not expected:
            value = ui_input(message('prompt.physical_model', role=role, suffix=suffix)).strip()
            expected = canonical_model(value) if value else hint
            if not expected:
                ui_emit('device.model_retry')
    if len(expected) > 80 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ._()+-]*", expected):
        raise MigrationError(message('error.model_ascii'))
    verify_expected_model(info, expected, role)
    return expected


def verify_expected_model(info: DeviceInfo, expected: str, role: str) -> None:
    detected = canonical_model(info.detected_model)
    ui_emit('device.log_hint')
    if detected and detected.casefold() != expected.casefold():
        ui_emit('device.model_mismatch', hint=detected, model=expected, severity='warning')
    if not prompt_yes_no(message('confirm.device', role=role, model=expected)):
        raise MigrationCancelled(message('cancel.device'))
    ui_emit('device.model_confirmed', role=role, model=expected)


def require_device_fingerprint(info: DeviceInfo) -> None:
    if not info.fingerprint_sha256:
        raise MigrationError(message('error.identity_missing'))


def ensure_source_structure(mount: Path) -> None:
    kr = mount / ".adds" / "koreader"
    required = [
        kr,
        kr / "reader.lua",
        kr / "frontend",
        kr / "plugins",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise MigrationError(
            message('error.source_preflight', paths="\n  ".join(missing))
        )


def ensure_backup_space(backup_dir: Path, required_bytes: int, label: str) -> None:
    free = shutil.disk_usage(backup_dir).free
    # Conservative because ZIP may not compress much.
    need = int(required_bytes * 1.10) + 100 * 1024 * 1024
    ui_emit('space.backup', label=label, free=human_bytes(free), need=human_bytes(need))
    if free < need:
        raise MigrationError(message('error.backup_space', path=backup_dir, label=label))


def ensure_target_space(target_mount: Path, source_size: int, existing_target_size: int) -> None:
    free = shutil.disk_usage(target_mount).free
    # Existing target will be removed before restore, so its size becomes reusable.
    effective = free + existing_target_size
    need = int(source_size * 1.10) + 50 * 1024 * 1024
    ui_emit('space.target', free=human_bytes(free), effective=human_bytes(effective), need=human_bytes(need))
    if effective < need:
        raise MigrationError(message('error.target_space'))


def log_status(message: str) -> None:
    current_ui().write(message, prefix=f"[{datetime.now().strftime('%H:%M:%S')}] ")


class ByteProgress:
    def __init__(self, label: str, total: int):
        self.label, self.total, self.done = label, total, 0
        self.started = self.last = time.monotonic()
        log_status(message('progress.start', label=label, size=human_bytes(total)))

    def update(self, count: int, final: bool = False) -> None:
        self.done += count
        now = time.monotonic()
        if not final and now - self.last < 2:
            return
        elapsed = max(now - self.started, 0.001)
        rate = self.done / elapsed
        percent = self.done / self.total * 100 if self.total else 100
        remaining = max(self.total - self.done, 0) / rate if rate > 0 else None
        eta = f'{remaining:.0f}s' if remaining is not None else 'unknown'
        log_status(message('progress.bytes', label=self.label, percent=f'{percent:.1f}',
                           done=human_bytes(self.done), total=human_bytes(self.total),
                           rate=human_bytes(int(rate)), elapsed=f'{elapsed:.0f}', eta=eta))
        self.last = now


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    progress = ByteProgress(message('progress.hash_file', name=path.name), size) if size >= 32 * 1024 * 1024 else None
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            if progress:
                progress.update(len(chunk))
    if progress:
        progress.update(0, final=True)
    return h.hexdigest()


def copy_with_progress(src, dst, label: str, size: int) -> None:
    progress = ByteProgress(label, size) if size >= 32 * 1024 * 1024 else None
    for chunk in iter(lambda: src.read(1024 * 1024), b''):
        dst.write(chunk)
        if progress:
            progress.update(len(chunk))
    if progress:
        progress.update(0, final=True)


def print_progress(label: str, done: int, total: int) -> None:
    width = 28
    if total <= 0:
        pct = 1.0
    else:
        pct = min(1.0, done / total)
    filled = int(width * pct)
    bar = "#" * filled + "-" * (width - filled)
    ui_emit('progress.files', label=label, bar=bar, percent=f'{pct * 100:5.1f}',
            done=done, total=total, prefix='\r', end='\n' if done >= total else '')


def validate_tree_symlinks(root: Path) -> None:
    if root.is_symlink():
        raise MigrationError(message('error.tree_root_symlink', path=root))
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            if (Path(base) / name).is_symlink():
                raise MigrationError(message('error.runtime_symlink', path=Path(base) / name))


def validate_koreader_zip(archive: Path) -> None:
    seen = set()
    paths = []
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = info.filename
            parts = name.rstrip('/').split('/')
            if (not name or name.startswith('/') or '\\' in name
                    or parts[0] not in {'koreader', '__MACOSX'}
                    or any(part in {'', '.', '..'} for part in parts)
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise MigrationError(message('error.runtime_zip_unsafe', name=name))
            if name in seen:
                raise MigrationError(message('error.runtime_zip_duplicate', name=name))
            seen.add(name)
            if not info.is_dir():
                paths.append(name)
    assert_unique_paths(paths)


def archive_entries(zf: zipfile.ZipFile) -> List[zipfile.ZipInfo]:
    entries: List[zipfile.ZipInfo] = []
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        if not name.startswith("koreader/"):
            continue
        rel = name[len("koreader/"):]
        if not rel or should_exclude_rel(rel):
            continue
        entries.append(info)
    return entries


def build_manifest(
    zip_path: Path,
    manifest_path: Path,
    source_info: DeviceInfo,
    plugins: List[str],
    plugin_warnings: List[str],
    strict_source: bool = True,
) -> dict:
    validate_koreader_zip(zip_path)
    ui_emit('archive.build_manifest')
    files: Dict[str, dict] = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        if strict_source and "koreader/reader.lua" not in names:
            raise MigrationError(message('error.archive_reader_missing'))

        entries = archive_entries(zf)
        seen = set()
        for idx, info in enumerate(entries, 1):
            rel = info.filename.replace("\\", "/")[len("koreader/"):]
            if rel in seen:
                raise MigrationError(message('error.zip_path_duplicate', path=rel))
            seen.add(rel)

            h = hashlib.sha256()
            try:
                with zf.open(info, "r") as src:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
            except Exception as exc:
                raise MigrationError(message('error.zip_read', path=rel, detail=exception_detail(exc))) from exc

            files[rel] = {
                "sha256": h.hexdigest(),
                "size": info.file_size,
            }
            print_progress(message('progress.hash_archive'), idx, len(entries))

    manifest = {
        "strict_source": strict_source,
        "schema_version": 1,
        "tool": f"{PROJECT_NAME} {VERSION}",
        "created_at": iso_now(),
        "source": {
            "detected_model": source_info.detected_model,
            "koreader_version": source_info.koreader_version,
            "device_fingerprint_sha256": source_info.fingerprint_sha256,
            "serial_hint": source_info.serial_hint,
            "device_id_present": source_info.device_id_present,
            "ai_assistant_config": source_info.ai_assistant_config,
        },
        "archive": {
            "filename": zip_path.name,
            "sha256": sha256_file(zip_path),
            "size": zip_path.stat().st_size,
        },
        "plugins": plugins,
        "plugin_structural_warnings": plugin_warnings,
        "excluded_from_full_hash_verification": sorted(VERIFY_EXCLUDES),
        "files": files,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def create_archive(
    source_koreader: Path,
    zip_path: Path,
    manifest_path: Path,
    source_info: DeviceInfo,
    plugins: List[str],
    plugin_warnings: List[str],
    strict_source: bool = True,
) -> dict:
    if zip_path.exists() or manifest_path.exists():
        raise MigrationError(message('error.backup_exists', path=zip_path))
    validate_tree_symlinks(source_koreader)

    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"
    run_with_spinner(
        ["ditto", "-c", "-k", "--keepParent", str(source_koreader), str(zip_path)],
        message('archive.creating'),
        env=env,
    )

    try:
        return build_manifest(
            zip_path,
            manifest_path,
            source_info,
            plugins,
            plugin_warnings,
            strict_source=strict_source,
        )
    except Exception:
        # Do not leave a backup that failed validation looking like a good backup.
        try:
            manifest_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def remove_tree(root: Path) -> None:
    """Remove a tree while tolerating descendants already removed by the filesystem."""
    root_path = os.path.abspath(root)
    def handle_error(function, path, exc_info):
        error = exc_info[1]
        # Match Python 3.13 behavior on older supported interpreters. FAT/macOS
        # may remove an AppleDouble companion while its listed entry remains.
        if isinstance(error, FileNotFoundError) and os.path.abspath(path) != root_path:
            return
        raise error.with_traceback(exc_info[2])
    shutil.rmtree(root, onerror=handle_error)


def remove_macos_metadata(root: Path) -> int:
    removed = 0
    if not root.exists():
        return removed
    for base, dirs, files in os.walk(root, topdown=False):
        base_p = Path(base)
        for name in files:
            if name == ".DS_Store" or name.startswith("._"):
                try:
                    (base_p / name).unlink()
                    removed += 1
                except FileNotFoundError:
                    pass
        for name in dirs:
            if name.startswith("._"):
                try:
                    remove_tree(base_p / name)
                    removed += 1
                except FileNotFoundError:
                    pass
    return removed


def remove_stale_caches(koreader: Path) -> None:
    for rel in VERIFY_EXCLUDES:
        p = koreader / rel
        try:
            p.unlink()
        except FileNotFoundError:
            pass


def verify_restored_tree(target_koreader: Path, manifest: dict) -> None:
    required = [
        target_koreader / "reader.lua",
        target_koreader / "frontend",
        target_koreader / "plugins",
    ]
    for p in (required if manifest.get("strict_source", True) else []):
        if not p.exists():
            raise MigrationError(message('error.restore_required_missing', path=p))

    files = manifest["files"]
    items = list(files.items())
    ui_emit('archive.verify_count', count=len(items))

    for idx, (rel, meta) in enumerate(items, 1):
        p = target_koreader / rel
        if not p.is_file():
            raise MigrationError(message('error.restore_file_missing', path=rel))
        if p.stat().st_size != meta["size"]:
            raise MigrationError(message('error.restore_size', path=rel))
        actual = sha256_file(p)
        if actual != meta["sha256"]:
            raise MigrationError(message('error.restore_checksum', path=rel))
        print_progress(message('progress.verify_target'), idx, len(items))

    ui_emit('archive.verified')


def restore_zip(zip_path: Path, target_adds: Path) -> None:
    validate_koreader_zip(zip_path)
    env = os.environ.copy()
    env["COPYFILE_DISABLE"] = "1"
    run_with_spinner(
        ["ditto", "-x", "-k", str(zip_path), str(target_adds)],
        message('archive.restoring'),
        env=env,
    )


def rollback_target(
    target_koreader: Path,
    target_adds: Path,
    target_backup_zip: Optional[Path],
    target_backup_manifest: Optional[dict],
) -> None:
    print()
    ui_emit('recovery.modified_failure', severity='error')
    ui_emit('recovery.starting')

    if target_backup_zip is not None:
        validate_koreader_zip(target_backup_zip)
        if target_backup_manifest and sha256_file(target_backup_zip) != target_backup_manifest['archive']['sha256']:
            raise MigrationError(message('error.rollback_archive_changed'))
    if target_koreader.exists():
        remove_tree(target_koreader)
    if target_backup_zip is None:
        ui_emit('recovery.no_original')
        return
    restore_zip(target_backup_zip, target_adds)
    if target_backup_manifest is not None:
        verify_restored_tree(target_koreader, target_backup_manifest)
    ui_emit('recovery.runtime_success')
    ui_emit('recovery.runtime_restored')


def choose_identity_mode(target_device_id: Optional[str]) -> str:
    default = "1" if target_device_id else "2"
    options = []
    if target_device_id:
        options.append(("1", message('menu.identity_preserve')))
    else:
        options.append(("1", message('menu.identity_unavailable')))
    options += [
        ("2", message('menu.identity_new')),
        ("3", message('menu.identity_clone')),
    ]
    while True:
        choice = choose(message('menu.identity'), options, default=default)
        if choice == "1" and not target_device_id:
            ui_emit('menu.identity_retry', severity='warning')
            continue
        return {"1": "preserve", "2": "new", "3": "clone"}[choice]


def apply_identity_mode(target_koreader: Path, mode: str, target_device_id: Optional[str]) -> Optional[str]:
    settings = target_koreader / "settings.reader.lua"

    if mode == "clone":
        ui_emit('identity.cloned')
        return read_device_id(settings)

    if mode == "preserve":
        if not target_device_id:
            raise MigrationError(message('error.preserve_identity_missing'))
        new_id = target_device_id
        label = message('identity.preserved')
    elif mode == "new":
        new_id = uuid.uuid4().hex.upper()
        label = message('identity.new')
    else:
        raise MigrationError(message('error.identity_mode', mode=mode))

    set_device_id(settings, new_id)
    check = read_device_id(settings)
    if check != new_id:
        raise MigrationError(message('error.identity_verify'))
    ui_emit('identity.applied', label=label)
    return new_id



# Electronic reading formats; generic image folders/ZIPs are opt-in.
EBOOK_EXTENSIONS = {
    '.epub', '.kepub', '.pdf', '.cbz', '.cbr', '.cb7', '.cbt', '.cba',
    '.mobi', '.azw', '.azw3', '.azw4', '.prc', '.pdb', '.fb2', '.fb3',
    '.djvu', '.djv', '.txt', '.rtf', '.doc', '.docx', '.html', '.htm',
    '.xhtml', '.md', '.chm', '.odt', '.tif', '.tiff', '.xps', '.oxps',
}
METADATA_DIRS = ('docsettings', 'hashdocsettings', 'history')


def checked_path(mount: Path, rel: str, allow_metadata: bool = False) -> Path:
    parts = rel.split('/')
    allowed_hidden = allow_metadata and len(parts) >= 2 and parts[:2] == ['.adds', 'koreader']
    if not rel or any(part in {'', '.', '..'} for part in parts):
        raise MigrationError(message('error.relative_path', path=rel))
    if any(part.startswith('.') for part in parts) and not allowed_hidden:
        raise MigrationError(message('error.system_path', path=rel))
    current = mount
    if mount.is_symlink() or not mount.is_dir():
        raise MigrationError(message('error.device_root', path=mount))
    for idx, part in enumerate(parts):
        current = current / part
        if current.is_symlink():
            raise MigrationError(message('error.path_symlink', path=rel))
        if current.exists() and idx < len(parts) - 1 and not current.is_dir():
            raise MigrationError(message('error.parent_directory', path=rel))
    return current


def payload_path(mount: Path, rel: str) -> Path:
    central = any(rel.startswith(f'.adds/koreader/{name}/') for name in METADATA_DIRS)
    path = checked_path(mount, rel, allow_metadata=central)
    if path.exists() and not path.is_file():
        raise MigrationError(message('error.payload_regular_file', path=rel))
    return path


def path_key(rel: str) -> str:
    return unicodedata.normalize('NFC', rel).casefold()


def assert_unique_paths(paths) -> None:
    seen = {}
    spellings = {}
    for rel in paths:
        parts = rel.split('/')
        for idx in range(1, len(parts) + 1):
            prefix = '/'.join(parts[:idx])
            key = path_key(prefix)
            if key in spellings and spellings[key] != prefix:
                raise MigrationError(message('error.case_unicode_collision', first=spellings[key], second=prefix))
            spellings[key] = prefix
        seen[path_key(rel)] = rel
    for rel in paths:
        parts = rel.split('/')
        for idx in range(1, len(parts)):
            key = path_key('/'.join(parts[:idx]))
            if key in seen:
                raise MigrationError(message('error.file_directory_collision', first=seen[key], path=rel))


def scan_payload(mount: Path, include_books: bool, include_fonts: bool,
                 include_metadata: bool = True, include_dirs=None,
                 exclude_dirs=None, extra_extensions=None, missing_roots_ok: bool = False, include_central_metadata: bool = True) -> Tuple[dict, dict]:
    files = {}
    report = {'books': [], 'sidecars': [], 'central_metadata': [], 'fonts': [],
              'unrecognized': [], 'skipped_symlinks': [], 'warnings': []}
    extensions = set(EBOOK_EXTENSIONS)
    for ext in extra_extensions or []:
        extensions.add('.' + ext.lower().lstrip('.'))
    excluded = []
    for rel in exclude_dirs or []:
        checked_path(mount, rel)
        excluded.append(rel.rstrip('/'))

    def excluded_path(rel):
        return any(rel == prefix or rel.startswith(prefix + '/') for prefix in excluded)

    def add(path, category):
        rel = path.relative_to(mount).as_posix()
        if excluded_path(rel) or rel in files:
            return
        if path.is_symlink():
            report['skipped_symlinks'].append(rel)
            return
        payload_path(mount, rel)
        if not path.is_file():
            return
        files[rel] = {'size': path.stat().st_size, 'category': category}
        report[category].append(rel)

    def walk_regular(root, category):
        if root.is_symlink():
            report['skipped_symlinks'].append(root.relative_to(mount).as_posix())
            return
        if not root.exists():
            return
        for base, dirs, names in os.walk(root, followlinks=False):
            for name in list(dirs):
                path = Path(base) / name
                rel = path.relative_to(mount).as_posix()
                if path.is_symlink():
                    report['skipped_symlinks'].append(rel)
                if name.startswith('.') or path.is_symlink() or excluded_path(rel):
                    dirs.remove(name)
            for name in names:
                if not name.startswith('.'):
                    add(Path(base) / name, category)

    if include_books:
        roots = [mount]
        if include_dirs:
            roots = [checked_path(mount, rel) for rel in include_dirs]
            for root in roots:
                if not root.is_dir() and not missing_roots_ok:
                    raise MigrationError(message('error.book_directory', path=root))
            roots = [root for root in roots if root.is_dir()]
        for root in roots:
            for base, dirs, names in os.walk(root, followlinks=False):
                for name in list(dirs):
                    path = Path(base) / name
                    rel = path.relative_to(mount).as_posix()
                    if path.is_symlink():
                        report['skipped_symlinks'].append(rel)
                    if (name.startswith('.') or name.endswith('.sdr') or path.is_symlink()
                            or excluded_path(rel) or rel == 'fonts'):
                        dirs.remove(name)
                for name in sorted(names):
                    path = Path(base) / name
                    rel = path.relative_to(mount).as_posix()
                    if name.startswith('.') or excluded_path(rel):
                        continue
                    if path.is_symlink():
                        report['skipped_symlinks'].append(rel)
                    elif path.suffix.lower() in extensions or name.lower().endswith('.fb2.zip'):
                        add(path, 'books')
                        if include_metadata:
                            walk_regular(path.with_suffix('.sdr'), 'sidecars')
                    elif path.is_file():
                        report['unrecognized'].append(rel)
        if include_metadata and include_central_metadata and not include_dirs and not exclude_dirs:
            for name in METADATA_DIRS:
                root = checked_path(mount, f'.adds/koreader/{name}', allow_metadata=True)
                walk_regular(root, 'central_metadata')
            report['warnings'].append(message('scan.warning_central'))
    if include_metadata and include_books and (include_dirs or exclude_dirs):
        report['warnings'].append(message('scan.warning_scoped'))
    if include_fonts:
        root = checked_path(mount, 'fonts')
        if root.is_dir():
            for base, dirs, names in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith('.') and not (Path(base) / d).is_symlink()]
                for name in names:
                    if not name.startswith('.') and Path(name).suffix.lower() in {'.ttf', '.otf', '.ttc', '.otc'}:
                        add(Path(base) / name, 'fonts')
    assert_unique_paths(files)
    files = dict(sorted(files.items()))
    for category in ('books', 'sidecars', 'central_metadata', 'fonts', 'unrecognized', 'skipped_symlinks'):
        report[category] = sorted(set(report[category]))
    report['file_count'] = len(files)
    report['total_bytes'] = sum(meta['size'] for meta in files.values())
    report['extensions'] = sorted(extensions)
    log_status(message('scan.complete', count=len(files)))
    return files, report


def hash_payload(mount: Path, files: dict) -> dict:
    result = {}
    for idx, (rel, meta) in enumerate(files.items(), 1):
        path = payload_path(mount, rel)
        if path.stat().st_size != meta['size']:
            raise MigrationError(message('error.source_scan_changed', path=rel))
        result[rel] = {**meta, 'sha256': sha256_file(path)}
        print_progress(message('progress.hash_payload'), idx, len(files))
    return {'files': result}


def create_payload_archive(mount: Path, files: dict, archive: Path) -> dict:
    manifest = hash_payload(mount, files)
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        for idx, (rel, meta) in enumerate(manifest['files'].items(), 1):
            path = payload_path(mount, rel)
            log_status(message('scan.archiving', index=idx, total=len(files), path=rel))
            with path.open('rb') as src, zf.open(rel, 'w', force_zip64=True) as dst:
                copy_with_progress(src, dst, f'Archiving {rel}', meta['size'])
            digest = hashlib.sha256()
            progress = ByteProgress(message('progress.verify_file', name=rel), meta['size']) if meta['size'] >= 32 * 1024 * 1024 else None
            with zf.open(rel) as member:
                for chunk in iter(lambda: member.read(1024 * 1024), b''):
                    digest.update(chunk)
                    if progress:
                        progress.update(len(chunk))
            if progress:
                progress.update(0, final=True)
            if digest.hexdigest() != meta['sha256']:
                raise MigrationError(message('error.source_archive_changed', path=rel))
            print_progress(message('progress.archive_payload'), idx, len(files))
    manifest.update({'tool_version': VERSION, 'created_at': iso_now(),
                     'archive_sha256': sha256_file(archive)})
    archive.with_suffix('.manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def plan_payload(target: Path, manifest: dict, conflict: str = 'overwrite') -> dict:
    files = manifest['files']
    assert_unique_paths(files)
    plan = {'copy': {}, 'skip': [], 'existing': {}, 'conflicts_kept': []}
    directory_names = {}
    log_status(message('scan.compare_start', count=len(files)))
    # Check the spelling of each existing component even on case-sensitive hosts.
    for index, (rel, meta) in enumerate(files.items(), 1):
        log_status(message('scan.comparing', index=index, total=len(files), path=rel, size=human_bytes(meta["size"])))
        path = payload_path(target, rel)
        current = target
        for part in rel.split('/'):
            if current.is_dir():
                if current not in directory_names:
                    directory_names[current] = {path_key(p.name): p.name for p in current.iterdir()}
                existing_name = directory_names[current].get(path_key(part))
                if existing_name is not None and existing_name != part:
                    raise MigrationError(message('error.destination_collision', path=rel, second=existing_name))
            current = current / part
        if path.exists():
            if path.stat().st_size == meta['size'] and sha256_file(path) == meta['sha256']:
                plan['skip'].append(rel)
                log_status(message('scan.identical'))
                continue
            if conflict == 'keep-target':
                plan['conflicts_kept'].append(rel)
                log_status(message('scan.keep_target'))
                continue
            plan['existing'][rel] = {'size': path.stat().st_size, 'category': meta.get('category', 'backup')}
        plan['copy'][rel] = meta
        log_status(message('scan.overwrite' if rel in plan['existing'] else 'scan.create'))
    kept_books = [rel for rel in plan['conflicts_kept'] if files[rel].get('category') == 'books']
    protected_sidecars = [str(Path(rel).with_suffix('.sdr')).replace(os.sep, '/') + '/' for rel in kept_books]
    plan['metadata_skipped'] = []
    if kept_books:
        for rel in list(plan['copy']):
            category = files[rel].get('category')
            if category == 'central_metadata' or any(rel.startswith(prefix) for prefix in protected_sidecars):
                del plan['copy'][rel]
                plan['existing'].pop(rel, None)
                plan['metadata_skipped'].append(rel)
    return plan


def restore_payload(target: Path, archive: Path, files: dict, journal: dict) -> None:
    with zipfile.ZipFile(archive) as zf:
        all_names = zf.namelist()
        if len(all_names) != len(set(all_names)):
            raise MigrationError(message('error.payload_zip_duplicate'))
        assert_unique_paths(files)
        for rel, meta in files.items():
            payload_path(target, rel)
            try:
                member = zf.getinfo(rel)
            except KeyError as exc:
                raise MigrationError(message('error.payload_zip_missing', path=rel)) from exc
            if member.is_dir() or stat.S_ISLNK(member.external_attr >> 16) or member.file_size != meta['size']:
                raise MigrationError(message('error.payload_zip_unsafe', path=rel))
        for idx, (rel, meta) in enumerate(files.items(), 1):
            path = payload_path(target, rel)
            missing = []
            parent = path.parent
            while parent != target and not parent.exists():
                missing.append(parent)
                parent = parent.parent
            for directory in reversed(missing):
                directory.mkdir()
                journal['created_dirs'].append(directory)
            journal['touched'].append(rel)
            persist_target_changes(journal)
            with zf.open(rel) as src, path.open('wb') as dst:
                log_status(message('scan.copying', index=idx, total=len(files), path=rel))
                copy_with_progress(src, dst, f'Copying {rel}', meta['size'])
            if path.stat().st_size != meta['size'] or sha256_file(path) != meta['sha256']:
                raise MigrationError(message('error.payload_verify', path=rel))
            # Progress hint only; resume must rehash before trusting a completed path.
            journal.setdefault('completed', []).append(rel)
            persist_target_changes(journal)
            print_progress(message('progress.copy_payload'), idx, len(files))


def rollback_payload(target: Path, backup: Optional[Path], previous: dict, journal: dict) -> None:
    # Validate backup before deleting any currently restored payload files.
    if backup is not None:
        with zipfile.ZipFile(backup) as zf:
            for rel in journal['touched']:
                if rel in previous:
                    meta = previous[rel]
                    digest = hashlib.sha256()
                    with zf.open(rel) as member:
                        for chunk in iter(lambda: member.read(1024 * 1024), b''):
                            digest.update(chunk)
                    if digest.hexdigest() != meta['sha256']:
                        raise MigrationError(message('error.rollback_payload_changed', path=rel))
    # Only restore overwritten files that were actually touched.
    for rel in reversed(journal['touched']):
        payload_path(target, rel).unlink(missing_ok=True)
    restore = {rel: meta for rel, meta in previous.items() if rel in journal['touched']}
    if restore:
        if backup is None:
            raise MigrationError(message('error.rollback_payload_missing'))
        restore_payload(target, backup, restore, {'touched': [], 'created_dirs': []})
    for directory in reversed(journal['created_dirs']):
        if directory.exists() and not any(directory.iterdir()):
            directory.rmdir()
    ui_emit('recovery.payload_success')


def device_diagnostics(mount: Path) -> dict:
    log_status(message('scan.metadata'))
    kr = checked_path(mount, '.adds/koreader', allow_metadata=True)
    result = {'metadata_mode': 'unknown', 'statistics': None, 'missing_references': []}
    settings = checked_path(mount, '.adds/koreader/settings.reader.lua', allow_metadata=True)
    if settings.is_file() and not settings.is_symlink():
        text = settings.read_text(encoding='utf-8', errors='replace')
        match = re.search(r'\["document_metadata_folder"\]\s*=\s*"([^"]+)"', text)
        result['metadata_mode'] = match.group(1) if match else 'doc (default)'
    db = checked_path(mount, '.adds/koreader/settings/statistics.sqlite3', allow_metadata=True)
    if db.is_symlink():
        raise MigrationError(message('error.statistics_symlink'))
    if db.is_file():
        if db.with_name(db.name + '-wal').exists() and db.with_name(db.name + '-wal').stat().st_size:
            raise MigrationError(message('error.statistics_wal'))
        try:
            with closing(sqlite3.connect(db.as_uri() + '?mode=ro&immutable=1', uri=True)) as conn:
                log_status(message('scan.statistics', size=human_bytes(db.stat().st_size)))
                checks = [row[0] for row in conn.execute('PRAGMA quick_check')]
                if checks != ['ok']:
                    raise MigrationError(message('error.statistics_check', detail=message('diagnostic.raw', detail='; '.join(checks))))
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                counts = {table: conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                          for table in ('book', 'page_stat_data', 'page_stat') if table in tables}
                result['statistics'] = {'quick_check': 'ok', 'rows': counts}
        except sqlite3.Error as exc:
            raise MigrationError(message('error.statistics_read', detail=exception_detail(exc))) from exc
    log_status(message('scan.references'))
    for rel in ('history.lua', 'settings/collection.lua', 'settings.reader.lua'):
        path = checked_path(mount, '.adds/koreader/' + rel, allow_metadata=True)
        if path.is_file() and not path.is_symlink():
            text = path.read_text(encoding='utf-8', errors='replace')
            for device_path in set(re.findall(r'"(/mnt/onboard/[^"\n]+)"', text)):
                # Report literal references only; do not evaluate Lua or rewrite paths.
                if '\\' not in device_path:
                    relative = device_path[len('/mnt/onboard/'):]
                    if not (mount / relative).exists():
                        result['missing_references'].append({'file': rel, 'path': device_path})
    return result


class LogTee:
    def __init__(self, stream, log):
        self.stream, self.log = stream, log

    def write(self, value):
        self.stream.write(value)
        self.log.write(value)
        return len(value)

    def flush(self):
        self.stream.flush()
        self.log.flush()


def ensure_local_backup(backup_dir: Path, mount: Path) -> None:
    if backup_dir == mount or mount in backup_dir.parents:
        raise MigrationError(message('error.backup_on_device'))


def confirm_device(mount: Path, fingerprint: Optional[str]) -> None:
    if not mount.is_dir() or not (mount / '.kobo').is_dir():
        raise MigrationError(message('error.disconnected'))
    if fingerprint and device_fingerprint(mount)[0] != fingerprint:
        raise MigrationError(message('error.device_changed'))



def self_test() -> None:
    import tempfile

    ui_emit('self_test.start')

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        settings = root / "settings.reader.lua"
        settings.write_text(
            'return {\n    ["device_id"] = "ABC123",\n    ["language"] = "en",\n}\n',
            encoding="utf-8",
        )

        assert read_device_id(settings) == "ABC123"
        set_device_id(settings, "XYZ789")
        assert read_device_id(settings) == "XYZ789"

        settings2 = root / "settings2.reader.lua"
        settings2.write_text('return {\n    ["language"] = "en",\n}\n', encoding="utf-8")
        set_device_id(settings2, "NEWID")
        assert read_device_id(settings2) == "NEWID"

        assert should_exclude_rel("cache/fontlist/fontinfo.dat")
        assert should_exclude_rel("foo/._bar")
        assert should_exclude_rel("foo/.DS_Store")
        assert not should_exclude_rel("fonts/noto/NotoSans-Regular.ttf")

        assert canonical_model("Kobo Clara 2E") == MODEL_CLARA
        assert canonical_model("Kobo Libra 2") == MODEL_LIBRA

        # Reading-data literals are parsed, never executed.
        assert parse_lua_data(b'return {["a"] = {1, "x"}, b = true}') == {'a': {1: 1, 2: 'x'}, 'b': True}
        try:
            parse_lua_data(b'return os.execute("x")')
            raise AssertionError('executable Lua accepted')
        except LuaDataError as exc:
            assert exc.code == 'executable_construct'

        source = root / "source"
        target = root / "target"
        (source / "Books").mkdir(parents=True)
        target.mkdir()
        (source / "Books/book.epub").write_bytes(b"new book")
        (source / "Books/book.sdr").mkdir()
        (source / "Books/book.sdr/metadata.epub.lua").write_bytes(b"return {}")
        scanned, report = scan_payload(source, True, False)
        assert len(scanned) == 2 and len(report['sidecars']) == 1
        archive = root / 'payload.zip'
        manifest = create_payload_archive(source, scanned, archive)
        plan = plan_payload(target, manifest)
        journal = {'touched': [], 'created_dirs': []}
        restore_payload(target, archive, plan['copy'], journal)
        assert len(plan_payload(target, manifest)['skip']) == 2
        rollback_payload(target, None, {}, journal)
        assert not (target / 'Books').exists()

    ui_emit('self_test.success')


def parse_args() -> argparse.Namespace:
    bootstrap = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    bootstrap.add_argument('--locale')
    initial, _ = bootstrap.parse_known_args()
    try:
        bundle = load_locale_bundle(initial.locale)
    except LocaleError as exc:
        bootstrap.error('Locale initialization failed; keep the complete locales/ folder beside the script. ' + str(exc))
    for notice in bundle.notices:
        locale_console_write('WARNING: ' + notice + '\n', sys.stderr)
    parser = LocaleArgumentParser(description=bundle.render('cli.description'),
        epilog=bundle.render('cli.foundation_notice'), allow_abbrev=False, add_help=False)
    parser.add_argument('-h', '--help', action='help', help=bundle.render('help.help'))
    parser.add_argument('--locale', metavar='TAG', help=bundle.render('help.locale'))
    parser.add_argument('--mode', choices=('full', 'koreader', 'library', 'audit'), help=bundle.render('help.mode'))
    parser.add_argument('--source-model', help=bundle.render('help.source_model'))
    parser.add_argument('--target-model', help=bundle.render('help.target_model'))
    parser.add_argument('--dry-run', action='store_true', help=bundle.render('help.dry_run'))
    parser.add_argument('--books', action=argparse.BooleanOptionalAction, default=None, help=bundle.render('help.books'))
    parser.add_argument('--fonts', action=argparse.BooleanOptionalAction, default=None, help=bundle.render('help.fonts'))
    parser.add_argument('--reading-data', action=argparse.BooleanOptionalAction, default=True, help=bundle.render('help.reading_data'))
    parser.add_argument('--conflict', choices=('overwrite', 'keep-target'), help=bundle.render('help.conflict'))
    parser.add_argument('--include-dir', action='append', default=[], help=bundle.render('help.include_dir'))
    parser.add_argument('--exclude-dir', action='append', default=[], help=bundle.render('help.exclude_dir'))
    parser.add_argument('--extra-extension', action='append', default=[], help=bundle.render('help.extra_extension'))
    parser.add_argument('--backup-dir', type=Path, default=DEFAULT_BACKUP_DIR, help=bundle.render('help.backup_dir'))
    operations = parser.add_mutually_exclusive_group()
    operations.add_argument('--preview-ui', action='store_true', help=bundle.render('help.preview_ui'))
    operations.add_argument('--list-locales', action='store_true', help=bundle.render('help.list_locales'))
    operations.add_argument('--from-run', metavar='RUN_ID', help=bundle.render('help.from_run'))
    operations.add_argument('--restore-run', metavar='RUN_ID', help=bundle.render('help.restore_run'))
    operations.add_argument('--list-runs', action='store_true', help=bundle.render('help.list_runs'))
    operations.add_argument('--verify-run', metavar='RUN_ID', action='append', help=bundle.render('help.verify_run'))
    operations.add_argument('--verify-all', action='store_true', help=bundle.render('help.verify_all'))
    operations.add_argument('--resume-run', metavar='RUN_ID', help=bundle.render('help.resume_run'))
    operations.add_argument('--cleanup', action='store_true', help=bundle.render('help.cleanup'))
    parser.add_argument('--keep-successful', type=int, default=2, help=bundle.render('help.keep_successful'))
    parser.add_argument('--delete-run', action='append', default=[], metavar='RUN_ID', help=bundle.render('help.delete_run'))
    parser.add_argument('--with-dependencies', action='store_true', help=bundle.render('help.with_dependencies'))
    parser.add_argument('--json', action='store_true', help=bundle.render('help.json'))
    parser.add_argument('--self-test', action='store_true', help=bundle.render('help.self_test'))
    parser.add_argument('--version', action='version', version=f'%(prog)s {VERSION}', help=bundle.render('help.version'))
    args = parser.parse_args()
    if args.delete_run and not args.cleanup:
        parser.error(bundle.render('argument.delete_cleanup'))
    if args.keep_successful < 1:
        parser.error(bundle.render('argument.keep_minimum'))
    if args.restore_run and (args.source_model or args.target_model or args.mode or args.books is not None or args.fonts is not None or args.conflict
                            or args.include_dir or args.exclude_dir or args.extra_extension or not args.reading_data):
        parser.error(bundle.render('argument.restore_settings'))
    verifying = bool(args.verify_run or args.verify_all)
    if (args.with_dependencies or args.json) and not verifying:
        parser.error(bundle.render('argument.verify_options'))
    if verifying and (args.dry_run or args.mode or args.self_test or args.books is not None or args.fonts is not None
            or args.source_model or args.target_model or args.conflict or args.include_dir or args.exclude_dir
            or args.extra_extension or not args.reading_data or args.delete_run):
        parser.error(bundle.render('argument.verify_settings'))
    if args.resume_run and (args.source_model or args.mode or args.books is not None or args.fonts is not None
            or args.conflict or args.include_dir or args.exclude_dir or args.extra_extension
            or not args.reading_data or args.delete_run or args.self_test):
        parser.error(bundle.render('argument.resume_settings'))
    args.locale = bundle.tag
    args.locale_bundle = bundle
    if (args.preview_ui or args.list_locales) and (args.mode or args.self_test or args.books is not None or args.fonts is not None
            or args.source_model or args.target_model or args.conflict or args.include_dir or args.exclude_dir
            or args.extra_extension or not args.reading_data):
        parser.error(bundle.render('argument.preview_settings'))
    return args


# Run management deliberately uses OS locks, not stale PID-file ownership.
CURRENT_RUN = None
CURRENT_LOCKS = None


def atomic_json(path: Path, data: dict) -> None:
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, indent=2, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


class FileLock:
    def __init__(self, path: Path, label: str):
        self.path, self.label, self.fd = path, label, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise MigrationError(message('error.lock_symlink', path=self.path))
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise MigrationError(message('error.lock_regular_file'))
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MigrationError(message('error.lock_busy', label=self.label)) from exc
            os.ftruncate(fd, 0)
            os.write(fd, json.dumps({'pid': os.getpid(), 'started_at': iso_now(), 'label': self.label}).encode())
            self.fd = fd
            return self
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, *exc):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
        # Keep the inode: deleting it could let a second lock bypass a waiting holder.


class DeviceLocks:
    def __init__(self):
        self.stack, self.keys = ExitStack(), set()

    def acquire(self, mount: Path, fingerprint: Optional[str]):
        identities = ['mount:' + str(mount.resolve())]
        if fingerprint:
            identities.append('device:' + fingerprint)
        base = Path(tempfile.gettempdir()) / f'koreader-migration-locks-{os.getuid()}'
        if base.is_symlink():
            raise MigrationError(message('error.lock_directory_symlink'))
        for identity in identities:
            key = hashlib.sha256(identity.encode()).hexdigest()
            if key not in self.keys:
                self.stack.enter_context(FileLock(base / (key + '.lock'), message('lock.device')))
                self.keys.add(key)

    def close(self):
        self.stack.close()


class RunState:
    def __init__(self, directory: Path, run_id: str, operation: str):
        self.directory = directory
        self.data = {'schema_version': 1, 'tool_version': VERSION, 'run_id': run_id,
                     'operation': operation, 'status': 'running', 'phase': 'starting',
                     'ui_locale': current_ui().bundle.tag,
                     'pid': os.getpid(), 'started_at': iso_now(), 'updated_at': iso_now(),
                     'target_modified': False, 'dependencies': []}
        self.update()

    def update(self, **fields):
        self.data.update(fields)
        self.data['updated_at'] = iso_now()
        atomic_json(self.directory / 'run.json', self.data)

    def finish(self, status: str, **fields):
        self.update(status=status, ended_at=iso_now(), **fields)


def run_phase(phase: str, **fields):
    if CURRENT_RUN is not None:
        CURRENT_RUN.update(phase=phase, **fields)


def acquire_device(mount: Path, fingerprint: Optional[str]):
    if CURRENT_LOCKS is not None:
        CURRENT_LOCKS.acquire(mount, fingerprint)


def read_json(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise MigrationError(message('error.json_missing', name=path.name))
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as exc:
        raise MigrationError(message('error.json_read', name=path.name)) from exc
    if not isinstance(data, dict):
        raise MigrationError(message('error.json_object', name=path.name))
    return data


def resolve_saved_run(project: Path, reference: str) -> Path:
    root = project / 'runs'
    candidate = Path(reference).expanduser()
    if not candidate.is_absolute():
        if len(candidate.parts) != 1:
            raise MigrationError(message('error.run_reference'))
        candidate = root / reference
    if candidate.is_symlink() or root.is_symlink():
        raise MigrationError(message('error.run_symlink'))
    if not candidate.is_dir() or candidate.resolve().parent != root.resolve():
        raise MigrationError(message('error.run_location'))
    return candidate.resolve()


def saved_file(run: Path, name: str) -> Path:
    if not isinstance(name, str) or Path(name).name != name or name in {'', '.', '..'}:
        raise MigrationError(message('error.artifact_filename'))
    path = run / name
    if path.is_symlink() or not path.is_file():
        raise MigrationError(message('error.artifact_missing', name=name))
    return path


def validate_file_manifest(files: dict, payload: bool):
    if not isinstance(files, dict):
        raise MigrationError(message('error.manifest_invalid'))
    assert_unique_paths(files)
    for rel, meta in files.items():
        if not isinstance(rel, str) or '\\' in rel or rel.startswith('/'):
            raise MigrationError(message('error.manifest_path'))
        parts = rel.split('/')
        if any(part in {'', '.', '..'} for part in parts):
            raise MigrationError(message('error.manifest_path'))
        if payload:
            central = any(rel.startswith(f'.adds/koreader/{name}/') for name in METADATA_DIRS)
            if any(part.startswith('.') for part in parts) and not central:
                raise MigrationError(message('error.manifest_system_path'))
        if (not isinstance(meta, dict) or not isinstance(meta.get('size'), int)
                or meta['size'] < 0 or not re.fullmatch(r'[0-9a-f]{64}', str(meta.get('sha256', '')))):
            raise MigrationError(message('error.manifest_entry', path=rel))


def verify_saved_archive(archive: Path, manifest: dict, kind: str) -> None:
    payload = kind == 'payload'
    files = manifest.get('files')
    validate_file_manifest(files, payload)
    expected = manifest.get('archive_sha256') if payload else manifest.get('archive', {}).get('sha256')
    if not isinstance(expected, str) or sha256_file(archive) != expected:
        raise MigrationError(message('error.saved_archive_checksum', name=archive.name))
    if not payload:
        validate_koreader_zip(archive)
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if len(names) != len(set(names)):
            raise MigrationError(message('error.saved_zip_duplicate'))
        if payload:
            actual = {info.filename for info in zf.infolist() if not info.is_dir()}
            if actual != set(files):
                raise MigrationError(message('error.payload_members'))
            for info in zf.infolist():
                if info.is_dir():
                    raise MigrationError(message('error.payload_directory_entry'))
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise MigrationError(message('error.saved_payload_symlink'))
                validate_file_manifest({info.filename: files.get(info.filename, {})}, True) if not info.is_dir() else None
        else:
            actual = {info.filename[len('koreader/'):] for info in archive_entries(zf)}
            if actual != set(files):
                raise MigrationError(message('error.runtime_members'))
            if manifest.get('strict_source', True) and 'reader.lua' not in files:
                raise MigrationError(message('error.saved_reader_missing'))
        for index, (rel, meta) in enumerate(files.items(), 1):
            member_name = rel if payload else 'koreader/' + rel
            info = zf.getinfo(member_name)
            if info.file_size != meta['size']:
                raise MigrationError(message('error.saved_zip_size', path=rel))
            digest = hashlib.sha256()
            progress = ByteProgress(message('progress.verify_file', name=rel), meta['size']) if meta['size'] >= 32 * 1024 * 1024 else None
            with zf.open(member_name) as member:
                for chunk in iter(lambda: member.read(1024 * 1024), b''):
                    digest.update(chunk)
                    if progress:
                        progress.update(len(chunk))
            if progress:
                progress.update(0, final=True)
            if digest.hexdigest() != meta['sha256']:
                raise MigrationError(message('error.saved_zip_checksum', path=rel))
            print_progress(message('progress.verify_members'), index, len(files))
    log_status(message('scan.saved_verified', name=archive.name))


def load_artifact(run: Path, entry: Optional[dict], kind: str):
    if entry is None:
        return None, None
    archive = saved_file(run, entry['archive'])
    manifest = read_json(saved_file(run, entry['manifest']))
    verify_saved_archive(archive, manifest, kind)
    return archive, manifest


def verify_run_artifacts(run: Path) -> List[dict]:
    """Read-only check of every archive/manifest pair in one batch; never repairs or rewrites."""
    entries = list(run.iterdir())
    if any(p.is_symlink() for p in entries):
        raise MigrationError(message('error.verify_symlink'))
    archives = {p.name[:-len('.zip')]: p for p in entries if p.is_file() and p.name.endswith('.zip')}
    manifests = {p.name[:-len('.manifest.json')]: p for p in entries
                 if p.is_file() and p.name.endswith('.manifest.json')}
    results = []
    for name in ('source-snapshot.json', 'target-snapshot.json'):
        if not (run / name).exists():
            continue
        try:
            descriptor = read_json(run / name)
        except MigrationError as exc:
            results.append({'name': name, 'kind': 'descriptor', 'status': 'failed', 'detail': exception_detail(exc)})
            continue
        for key in ('koreader', 'payload'):
            entry = descriptor.get(key)
            for field in ('archive', 'manifest') if isinstance(entry, dict) else ():
                if not (run / str(entry.get(field))).is_file():
                    results.append({'name': name, 'kind': 'descriptor', 'status': 'failed',
                                    'detail': message('error.verify_referenced_missing', name=entry.get(field))})
    for stem in sorted(set(archives) | set(manifests)):
        label = stem + '.zip'
        kind = None
        try:
            if stem not in archives or stem not in manifests:
                raise MigrationError(message('error.verify_unpaired'))
            manifest = read_json(manifests[stem])
            if 'archive_sha256' in manifest:
                kind = 'payload'
            elif isinstance(manifest.get('archive'), dict):
                kind = 'koreader'
                if manifest['archive'].get('filename', label) != label:
                    raise MigrationError(message('error.verify_archive_name', name=manifest['archive'].get('filename')))
            else:
                raise MigrationError(message('error.verify_manifest_kind'))
            try:
                verify_saved_archive(archives[stem], manifest, kind)
            except (zipfile.BadZipFile, OSError) as exc:
                raise MigrationError(message('error.verify_unreadable', detail=str(exc))) from exc
            results.append({'name': label, 'kind': kind, 'status': 'verified'})
        except MigrationError as exc:
            results.append({'name': label, 'kind': kind, 'status': 'failed', 'detail': exception_detail(exc)})
    return results


def run_dependency_names(run: Path) -> List[str]:
    """Batches this run relies on: run.json dependencies plus source/resume references."""
    names = []
    try:
        state = read_json(run / 'run.json') if (run / 'run.json').is_file() else {}
    except MigrationError:
        state = {}
    dependencies = state.get('dependencies', [])
    if isinstance(dependencies, list):
        names += [name for name in dependencies if isinstance(name, str)]
    for reference in ('source-reference.json', 'resume-reference.json'):
        path = run / reference
        if path.is_file() and not path.is_symlink():
            try:
                value = read_json(path).get('run_id')
            except MigrationError:
                value = None
            if isinstance(value, str):
                names.append(value)
    return [name for name in dict.fromkeys(names) if name != run.name]


def verify_runs(project: Path, references: List[str], verify_all: bool = False,
                with_dependencies: bool = False) -> List[dict]:
    """Read-only verification of several batches; requested names must resolve, dependencies may be missing."""
    if verify_all:
        requested = [record['run_id'] for record in run_catalog(project)]
    else:
        requested = list(dict.fromkeys(references))
        for name in requested:
            resolve_saved_run(project, name)
    entries, queue = {}, [(name, None) for name in requested]
    while queue:
        name, parent = queue.pop(0)
        if name in entries:
            if parent and parent not in entries[name]['dependency_of']:
                entries[name]['dependency_of'].append(parent)
            continue
        entry = {'run_id': name, 'requested': parent is None, 'dependency_of': [parent] if parent else [],
                 'status': None, 'result': None, 'detail': None, 'artifacts': []}
        entries[name] = entry
        if parent:
            ui_emit('verify.dependency_heading', run_id=name, parent=parent)
        else:
            ui_emit('verify.heading', run_id=name)
        try:
            run = resolve_saved_run(project, name)
        except MigrationError as exc:
            entry.update(result='missing', detail=str(exception_detail(exc)))
            ui_emit('verify.missing_dependency', run_id=name, parent=parent or '', severity='error')
            continue
        try:
            entry['status'] = read_json(run / 'run.json').get('status') if (run / 'run.json').is_file() else None
        except MigrationError:
            entry['status'] = 'unreadable'
        if entry['status'] == 'running':
            ui_emit('verify.running', severity='warning')
        try:
            results = verify_run_artifacts(run)
        except MigrationError as exc:
            results = [{'name': name, 'kind': None, 'status': 'failed', 'detail': exception_detail(exc)}]
        if not results:
            ui_emit('verify.empty')
        for result in results:
            if result['status'] == 'verified':
                ui_emit('verify.passed', name=result['name'], kind=result['kind'])
            else:
                ui_emit('verify.failed', name=result['name'], detail=result['detail'], severity='error')
        failed = sum(r['status'] == 'failed' for r in results)
        ui_emit('verify.summary', verified=len(results) - failed, failed=failed,
                severity='error' if failed else 'info')
        entry['artifacts'] = [{'name': r['name'], 'kind': r['kind'], 'status': r['status'],
                               **({'detail': str(r['detail'])} if r['status'] != 'verified' else {})}
                              for r in results]
        entry['result'] = 'failed' if failed else 'verified' if results else 'empty'
        if with_dependencies:
            queue += [(dependency, name) for dependency in run_dependency_names(run)]
    return list(entries.values())


def verify_report(entries: List[dict]) -> dict:
    """Stable English machine report; run IDs only, never absolute paths."""
    artifacts = [artifact for entry in entries for artifact in entry['artifacts']]
    return {'schema_version': 1, 'tool_version': VERSION, 'operation': 'verify-runs', 'runs': entries,
            'summary': {'runs': len(entries),
                        **{result: sum(entry['result'] == result for entry in entries)
                           for result in ('verified', 'empty', 'failed', 'missing')},
                        'artifacts_verified': sum(a['status'] == 'verified' for a in artifacts),
                        'artifacts_failed': sum(a['status'] != 'verified' for a in artifacts)}}


def verify_runs_command(project: Path, references: List[str], verify_all: bool = False,
                        with_dependencies: bool = False, as_json: bool = False) -> int:
    if as_json:
        # Human progress goes to stderr so stdout stays one JSON document.
        stdout = sys.stdout
        with ui_session(current_ui().bundle, stdout=sys.stderr, stderr=sys.stderr):
            entries = verify_runs(project, references, verify_all, with_dependencies)
        report = verify_report(entries)
        stdout.write(json.dumps(report, indent=2, ensure_ascii=True) + '\n')
        stdout.flush()
    else:
        entries = verify_runs(project, references, verify_all, with_dependencies)
        report = verify_report(entries)
        if verify_all and not entries:
            ui_emit('verify.no_runs')
        elif len(entries) > 1:
            bad = report['summary']['failed'] + report['summary']['missing']
            ui_emit('verify.overall', runs=len(entries), failed=bad, severity='error' if bad else 'info')
    summary = report['summary']
    return 1 if summary['failed'] or summary['missing'] else 0


def verify_run_command(project: Path, reference: str) -> int:
    return verify_runs_command(project, [reference])


def artifact_entry(archive: Optional[Path]) -> Optional[dict]:
    return {'archive': archive.name, 'manifest': archive.with_suffix('.manifest.json').name} if archive else None


def save_source_snapshot(run: Path, info: DeviceInfo, mode: str, books: bool, fonts: bool,
                         scan_report: dict, kr_archive: Optional[Path], payload_archive: Optional[Path], confirmed_model: Optional[str] = None):
    descriptor = {'schema_version': 1, 'role': 'source', 'mode': mode,
                  'device': asdict(info), 'confirmed_model': confirmed_model, 'books': books, 'fonts': fonts,
                  'source_diagnostics': scan_report['source_diagnostics'],
                  'scan_report': scan_report, 'koreader': artifact_entry(kr_archive),
                  'payload': artifact_entry(payload_archive)}
    atomic_json(run / 'source-snapshot.json', descriptor)


def source_descriptor(run: Path) -> dict:
    if (run / 'source-snapshot.json').exists():
        return read_json(run / 'source-snapshot.json')
    # Import old flat runs conservatively. Require finished manifests and scan metadata.
    reports = list(run.glob('koreader-scan-*.json'))
    if len(reports) != 1:
        raise MigrationError(message('error.legacy_scan_count'))
    report = read_json(reports[0])
    mode = report.get('mode')
    if mode not in {'full', 'koreader', 'library'}:
        raise MigrationError(message('error.legacy_mode'))
    kr = [p for p in run.glob('koreader-*.manifest.json') if '-pre-migration-' not in p.name]
    library = [p for p in run.glob('library-*.manifest.json') if '-pre-migration-' not in p.name]
    if (mode in {'full', 'koreader'} and len(kr) != 1) or len(library) > 1:
        raise MigrationError(message('error.legacy_archive_pair'))
    if report.get('dry_run'):
        raise MigrationError(message('error.preview_source_missing'))
    book_count = len(report.get('books', []))
    payload_count = book_count + len(report.get('sidecars', [])) + len(report.get('fonts', []))
    if mode == 'library':
        payload_count += len(report.get('central_metadata', []))
    if payload_count and not library:
        raise MigrationError(message('error.legacy_payload_missing'))
    kr_manifest = read_json(kr[0]) if kr else None
    source = kr_manifest.get('source', {}) if kr_manifest else {}
    model = source.get('detected_model')
    if not model:
        raise MigrationError(message('error.legacy_model_missing'))
    info = DeviceInfo('', model, source.get('koreader_version'), source.get('device_fingerprint_sha256'),
                      source.get('serial_hint'), bool(source.get('device_id_present')),
                      bool(source.get('ai_assistant_config')), len(kr_manifest.get('files', {})),
                      sum(m['size'] for m in kr_manifest.get('files', {}).values()))
    return {'schema_version': 1, 'role': 'source', 'mode': mode, 'device': asdict(info),
            'books': bool(book_count), 'fonts': bool(report.get('fonts')),
            'source_diagnostics': report.get('source_diagnostics', {}), 'scan_report': report,
            'koreader': artifact_entry(kr[0].with_suffix('').with_suffix('.zip')) if kr else None,
            'payload': artifact_entry(library[0].with_suffix('').with_suffix('.zip')) if library else None}


# --- KOReader Lua data literals (KM-007; reused by KM-008/KM-009) -------------------------
# Device Lua is parsed as a data literal only. It is never evaluated, compiled or executed.

@dataclass(frozen=True)
class LuaLimits:
    max_bytes: int = 8 * 1024 * 1024
    max_depth: int = 64
    max_nodes: int = 1_000_000
    max_seconds: float = 2.0


class LuaDataError(ValueError):
    """A rejected Lua data literal; `code` is a stable English machine token."""
    def __init__(self, code: str, detail: str, offset: int = 0, line: int = 1):
        super().__init__(f'{detail} (line {line}, byte {offset})')
        self.code, self.offset, self.line = code, offset, line


LUA_MAX_DEPTH_CEILING = 200
LUA_WHITESPACE = b' \t\r\n\f\v'
LUA_SIMPLE_ESCAPES = {ord('a'): 7, ord('b'): 8, ord('f'): 12, ord('n'): 10, ord('r'): 13,
                      ord('t'): 9, ord('v'): 11, ord('\\'): 92, ord('"'): 34, ord("'"): 39}
LUA_NAME_RE = re.compile(rb'[A-Za-z_][A-Za-z0-9_]*')
LUA_DECIMAL_RE = re.compile(rb'(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?')
LUA_HEX_RE = re.compile(rb'0[xX]([0-9A-Fa-f]+)')
LUA_LONG_OPEN_RE = re.compile(rb'\[(=*)\[')
LUA_NEWLINES_RE = re.compile(rb'\r\n|\n\r|\r')
LUA_QUOTED_STOP = {ord('"'): re.compile(rb'[\\\r\n"]'), ord("'"): re.compile(rb"[\\\r\n']")}
LUA_LITERAL_WORDS = {b'true', b'false', b'nil', b'return'}


class _LuaDataParser:
    def __init__(self, data: bytes, limits: LuaLimits, clock):
        self.data, self.limits, self.clock = data, limits, clock
        self.pos, self.nodes, self.ticks = 0, 0, 0
        self.deadline = clock() + limits.max_seconds
        self.peeked = None

    def fail(self, code: str, detail: str, offset: Optional[int] = None):
        offset = self.pos if offset is None else offset
        raise LuaDataError(code, detail, offset, self.data.count(b'\n', 0, offset) + 1)

    def skip_space(self) -> None:
        data, n = self.data, len(self.data)
        while self.pos < n:
            byte = data[self.pos]
            if byte in LUA_WHITESPACE:
                self.pos += 1
            elif data.startswith(b'--', self.pos):
                start = self.pos
                opener = LUA_LONG_OPEN_RE.match(data, self.pos + 2)
                if opener:
                    end = data.find(b']' + opener.group(1) + b']', opener.end())
                    if end < 0:
                        self.fail('unterminated_comment', 'Unterminated long comment.', start)
                    self.pos = end + len(opener.group(1)) + 2
                else:
                    newline = data.find(b'\n', self.pos)
                    self.pos = n if newline < 0 else newline + 1
            else:
                return

    def next_token(self):
        if self.peeked is not None:
            token, self.peeked = self.peeked, None
            return token
        self.ticks += 1
        if self.ticks % 4096 == 0 and self.clock() > self.deadline:
            self.fail('timeout', 'Parsing exceeded the time limit.')
        self.skip_space()
        data, start = self.data, self.pos
        if start >= len(data):
            return ('eof', None, start)
        byte = data[start]
        if byte in b'{}]=,;':
            self.pos += 1
            return (chr(byte), None, start)
        if byte == ord('['):
            opener = LUA_LONG_OPEN_RE.match(data, start)
            if opener:
                return ('str', self.long_string(opener), start)
            self.pos += 1
            return ('[', None, start)
        if byte in LUA_QUOTED_STOP:
            return ('str', self.quoted_string(byte), start)
        if byte == ord('-') or byte == ord('.') or 48 <= byte <= 57:
            return ('num', self.number(), start)
        name = LUA_NAME_RE.match(data, start)
        if name:
            self.pos = name.end()
            word = name.group()
            if word in LUA_LITERAL_WORDS:
                return (word.decode('ascii'), None, start)
            return ('name', word.decode('ascii'), start)
        if 33 <= byte <= 126:
            self.fail('executable_construct', f'Operator or call syntax {chr(byte)!r} is not data.', start)
        self.fail('syntax', f'Unexpected byte 0x{byte:02x}.', start)

    def peek(self):
        if self.peeked is None:
            self.peeked = self.next_token()
        return self.peeked

    def number(self):
        data, start = self.data, self.pos
        negative = data[start] == ord('-')
        body = start + 1 if negative else start
        if negative and not (body < len(data) and (48 <= data[body] <= 57 or data[body] == ord('.'))):
            self.fail('executable_construct', 'Unary minus is only accepted before a numeric literal.', start)
        hexadecimal = LUA_HEX_RE.match(data, body)
        if hexadecimal:
            end, value = hexadecimal.end(), int(hexadecimal.group(1), 16)
        else:
            if data.startswith((b'0x', b'0X'), body):
                self.fail('invalid_number', 'Hexadecimal literal has no digits.', start)
            decimal = LUA_DECIMAL_RE.match(data, body)
            if not decimal or decimal.group() == b'.':
                self.fail('executable_construct', 'A dot outside a number is not data.', start)
            end, text = decimal.end(), decimal.group()
            value = float(text) if any(c in text for c in b'.eE') else int(text)
            if isinstance(value, float) and value in (float('inf'), float('-inf')):
                self.fail('invalid_number', 'Non-finite numbers are not accepted.', start)
        if end < len(data) and (data[end:end + 1].isalnum() or data[end] in b'_.'):
            self.fail('invalid_number', 'Malformed numeric literal.', start)
        self.pos = end
        return -value if negative else value

    def quoted_string(self, quote: int) -> str:
        data, start = self.data, self.pos
        stop, pos, out = LUA_QUOTED_STOP[quote], start + 1, bytearray()
        while True:
            found = stop.search(data, pos)
            if not found:
                self.fail('unterminated_string', 'Unterminated string.', start)
            out += data[pos:found.start()]
            pos, byte = found.start() + 1, data[found.start()]
            if byte == quote:
                self.pos = pos
                return out.decode('utf-8', 'surrogateescape')
            if byte in b'\r\n':
                self.fail('unterminated_string', 'Unescaped newline in string.', start)
            if pos >= len(data):
                self.fail('unterminated_string', 'Unterminated string.', start)
            code = data[pos]
            if code in LUA_SIMPLE_ESCAPES:
                out.append(LUA_SIMPLE_ESCAPES[code])
                pos += 1
            elif code in b'\r\n':
                pos += 2 if data[pos + 1:pos + 2] in (b'\r', b'\n') and data[pos + 1] != code else 1
                out.append(10)
            elif 48 <= code <= 57:
                digits = re.match(rb'[0-9]{1,3}', data[pos:pos + 3]).group()
                if int(digits) > 255:
                    self.fail('bad_escape', 'Decimal escape is larger than 255.', pos - 1)
                out.append(int(digits))
                pos += len(digits)
            elif code == ord('x'):
                digits = data[pos + 1:pos + 3]
                if not re.fullmatch(rb'[0-9A-Fa-f]{2}', digits):
                    self.fail('bad_escape', 'Hexadecimal escape needs two digits.', pos - 1)
                out.append(int(digits, 16))
                pos += 3
            elif code == ord('z'):
                pos += 1
                while pos < len(data) and data[pos] in LUA_WHITESPACE:
                    pos += 1
            elif code == ord('u'):
                escape = re.match(rb'u\{([0-9A-Fa-f]{1,8})\}', data[pos:pos + 11])
                point = int(escape.group(1), 16) if escape else -1
                if not 0 <= point <= 0x10FFFF or 0xD800 <= point <= 0xDFFF:
                    self.fail('bad_escape', 'Invalid Unicode escape.', pos - 1)
                out += chr(point).encode('utf-8')
                pos += len(escape.group())
            else:
                self.fail('bad_escape', f'Unknown escape \\{chr(code)!r}.', pos - 1)

    def long_string(self, opener) -> str:
        start, closing = opener.start(), b']' + opener.group(1) + b']'
        end = self.data.find(closing, opener.end())
        if end < 0:
            self.fail('unterminated_string', 'Unterminated long string.', start)
        body = self.data[opener.end():end]
        for newline in (b'\r\n', b'\n\r', b'\n', b'\r'):
            if body.startswith(newline):
                body = body[len(newline):]
                break
        self.pos = end + len(closing)
        return LUA_NEWLINES_RE.sub(b'\n', body).decode('utf-8', 'surrogateescape')

    def expect(self, kind: str) -> None:
        token = self.next_token()
        if token[0] != kind:
            code = 'executable_construct' if token[0] == 'name' else 'syntax'
            self.fail(code, f'Expected {kind!r}, found {token[0]!r}.', token[2])

    def count_node(self) -> None:
        self.nodes += 1
        if self.nodes > self.limits.max_nodes:
            self.fail('too_many_nodes', 'Too many values.')

    def value(self, depth: int):
        kind, value, start = self.next_token()
        self.count_node()
        if kind in {'str', 'num'}:
            return value
        if kind in {'true', 'false'}:
            return kind == 'true'
        if kind == 'nil':
            return None
        if kind == '{':
            return self.table(depth + 1, start)
        if kind == 'name':
            self.fail('executable_construct', f'Identifier {value!r} is not a data value.', start)
        self.fail('syntax', f'Expected a value, found {kind!r}.', start)

    def key(self):
        kind, value, start = self.next_token()
        if kind == 'str':
            return value
        if kind == 'num':
            return int(value) if isinstance(value, float) and value.is_integer() else value
        self.fail('invalid_key', f'Unsupported table key {kind!r}.', start)

    def table(self, depth: int, start: int) -> dict:
        if depth > self.limits.max_depth:
            self.fail('too_deep', 'Tables are nested too deeply.', start)
        result, seen, index = {}, set(), 1
        while True:
            kind, value, offset = self.peek()
            if kind == '}':
                self.next_token()
                return result
            if kind == '[':
                self.next_token()
                key = self.key()
                self.expect(']')
                self.expect('=')
            elif kind == 'name':
                self.next_token()
                if self.peek()[0] != '=':
                    self.fail('executable_construct', f'Identifier {value!r} is not a data value.', offset)
                self.next_token()
                key = value
            else:
                key, index = index, index + 1
            if key in seen:
                self.fail('duplicate_key', f'Duplicate table key {key!r}.', offset)
            seen.add(key)
            item = self.value(depth)
            if item is not None:
                result[key] = item
            separator = self.peek()[0]
            if separator in {',', ';'}:
                self.next_token()
            elif separator != '}':
                code = 'executable_construct' if separator == 'name' else 'syntax'
                self.fail(code, f'Expected a separator or closing brace, found {separator!r}.', self.peek()[2])

    def chunk(self):
        if self.data.startswith(b'\xef\xbb\xbf'):
            self.pos = 3
        kind, _, start = self.next_token()
        if kind != 'return':
            self.fail('missing_return', 'The file must contain one return statement.', start)
        result = self.value(0)
        if self.peek()[0] == ';':
            self.next_token()
        kind, _, start = self.next_token()
        if kind != 'eof':
            self.fail('trailing_data', 'Unexpected content after the returned value.', start)
        return result


def parse_lua_data(data: bytes, limits: LuaLimits = LuaLimits(), clock=time.monotonic):
    """Parse one `return <literal>` chunk. Tables become dicts; nothing is evaluated."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError('Lua data must be bytes.')
    if len(data) > limits.max_bytes:
        raise LuaDataError('too_large', 'Input exceeds the size limit.', limits.max_bytes)
    if not 1 <= limits.max_depth <= LUA_MAX_DEPTH_CEILING:
        raise ValueError('Unsupported Lua depth limit.')
    return _LuaDataParser(bytes(data), limits, clock).chunk()


def lua_sequence(table) -> Optional[list]:
    """Return the values of a table whose keys are exactly 1..n, else None."""
    if not isinstance(table, dict):
        return None
    keys = [key for key in table if type(key) is int]
    if len(keys) != len(table) or sorted(keys) != list(range(1, len(table) + 1)):
        return None
    return [table[key] for key in range(1, len(table) + 1)]


# --- Reading-data conflict report (KM-007) -------------------------------------------------
# Read-only. It explains the existing plan and never changes it, merges or picks a side.

READING_DATA_SCHEMA = 1
READING_LIMITS = LuaLimits()
READING_MAX_STORES = 50_000
READING_MAX_TOTAL_BYTES = 512 * 1024 * 1024
READING_MAX_SECONDS = 120.0
READING_PROGRESS_TOLERANCE = 0.0005
READING_MTIME_TOLERANCE = 2.0
READING_XPOINTER_CHARS = 512
READING_MAX_CANDIDATES = 10
READING_TEXT_BOOKS = 500
READING_STATUSES = {'reading', 'complete', 'abandoned'}
READING_LOCATIONS = ('sidecar', 'docsettings', 'hashdocsettings')
READING_MODE_LOCATION = {'doc': 'sidecar', 'dir': 'docsettings', 'hash': 'hashdocsettings'}
READING_FLAGS = ('edition_mismatch', 'content_differs', 'stale_sidecar_suspected', 'moved_candidate',
                 'ambiguous_match', 'multiple_stores', 'unparseable', 'target_reading_data_replaced',
                 'target_annotations_replaced', 'target_kept', 'retained_for_different_book')
MD5_HEX_RE = re.compile(r'[0-9a-fA-F]{32}\Z')
DATE_RE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')


def koreader_partial_md5(handle) -> str:
    """KOReader util.partialMD5: 1 KiB samples at 0 and 1024 << 2i (i = 0..10). Unverified on hardware."""
    digest = hashlib.md5(usedforsecurity=False)
    for i in range(-1, 11):
        handle.seek(0 if i < 0 else 1024 << (2 * i))
        sample = handle.read(1024)
        if not sample:
            break
        digest.update(sample)
    return digest.hexdigest()


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def summarize_reading_data(table) -> dict:
    """Extract bounded, non-personal fields from one parsed metadata.<ext>.lua table."""
    invalid, fields = [], {}

    def take(name, valid, convert=lambda value: value):
        if name not in table:
            return None
        value = table[name]
        if not valid(value):
            invalid.append(name)
            return None
        return convert(value)

    fields['percent_finished'] = take('percent_finished', lambda v: _is_number(v) and 0 <= v <= 1, float)
    xpointer = take('last_xpointer', lambda v: isinstance(v, str))
    page = take('last_page', lambda v: _is_number(v) and v >= 0 and float(v).is_integer(), int)
    fields['position_kind'] = 'xpointer' if xpointer is not None else 'page' if page is not None else 'none'
    fields['last_page'] = page
    fields['last_xpointer'] = None if xpointer is None else xpointer[:READING_XPOINTER_CHARS]
    fields['doc_pages'] = take('doc_pages', lambda v: _is_number(v) and v >= 0 and float(v).is_integer(), int)
    summary = take('summary', lambda v: isinstance(v, dict)) or {}
    status = summary.get('status')
    fields['summary_status'] = (status if status in READING_STATUSES else 'other') if isinstance(status, str) else None
    modified = summary.get('modified')
    fields['summary_modified'] = modified if isinstance(modified, str) and DATE_RE.match(modified) else None
    if 'modified' in summary and fields['summary_modified'] is None:
        invalid.append('summary.modified')
    checksum = take('partial_md5_checksum', lambda v: isinstance(v, str) and bool(MD5_HEX_RE.match(v)), str.lower)
    fields['partial_md5_checksum'] = checksum
    props = table.get('doc_props') if isinstance(table.get('doc_props'), dict) else {}
    identity = tuple(props.get(name) if isinstance(props.get(name), str) else None for name in ('title', 'authors'))
    annotations = lua_sequence(table['annotations']) if isinstance(table.get('annotations'), dict) else None
    if 'annotations' in table and annotations is None:
        invalid.append('annotations')
    highlight = table.get('highlight') if isinstance(table.get('highlight'), dict) else None
    bookmarks = lua_sequence(table['bookmarks']) if isinstance(table.get('bookmarks'), dict) else None
    latest = []
    counts = None
    if annotations is not None:
        items = [item for item in annotations if isinstance(item, dict)]
        marked = [item for item in items if 'pos0' in item or 'drawer' in item]
        counts = {'annotations': len(annotations), 'highlights': len(marked),
                  'bookmarks': len(items) - len(marked),
                  'notes': sum(1 for item in items if isinstance(item.get('note'), str) and item['note'].strip())}
        latest = [item.get(name) for item in items for name in ('datetime_updated', 'datetime')]
    elif highlight is not None or bookmarks is not None:
        pages = [lua_sequence(items) or [] for items in (highlight or {}).values()]
        marks = [item for item in bookmarks or [] if isinstance(item, dict)]
        counts = {'annotations': None, 'highlights': sum(len(items) for items in pages),
                  'bookmarks': len(bookmarks or []),
                  'notes': sum(1 for item in marks if isinstance(item.get('text'), str) and item['text'].strip())}
        latest = [item.get('datetime') for items in pages for item in items if isinstance(item, dict)]
        latest += [item.get('datetime') for item in marks]
    legacy = highlight is not None or bookmarks is not None
    fields['schema_family'] = ('mixed' if annotations is not None and legacy else 'annotations'
                               if annotations is not None else 'legacy' if legacy else 'none')
    fields['counts'] = counts
    stamps = [value for value in latest if isinstance(value, str) and len(value) <= 32]
    fields['latest_annotation'] = max(stamps) if stamps else None
    fields['invalid_fields'] = sorted(set(invalid))
    return {'fields': fields, 'identity': identity if any(identity) else None}


class _ReadingBudget:
    def __init__(self, clock=time.monotonic):
        self.clock, self.deadline = clock, clock() + READING_MAX_SECONDS
        self.stores = self.bytes = 0
        self.exhausted = False

    def allow(self, size: int) -> bool:
        if (self.exhausted or self.stores >= READING_MAX_STORES
                or self.bytes + size > READING_MAX_TOTAL_BYTES or self.clock() > self.deadline):
            self.exhausted = True
            return False
        self.stores, self.bytes = self.stores + 1, self.bytes + size
        return True


class _MountReadingSide:
    """Read-only access to one mounted device; path safety follows checked_path."""
    def __init__(self, mount: Path, hashes: Optional[dict] = None):
        self.mount, self.hashes = mount, hashes or {}

    def path(self, rel: str) -> Path:
        return checked_path(self.mount, rel, allow_metadata=rel.startswith('.adds/koreader/'))

    def info(self, rel: str):
        path = self.path(rel)
        if path.is_symlink() or not path.is_file():
            return None
        status = path.stat()
        return {'size': status.st_size,
                'mtime': datetime.fromtimestamp(status.st_mtime, timezone.utc).isoformat(timespec='seconds'),
                'mtime_epoch': status.st_mtime}

    def read(self, rel: str, size: int) -> bytes:
        with self.path(rel).open('rb') as handle:
            return handle.read(size + 1)

    def partial_md5(self, rel: str) -> str:
        with self.path(rel).open('rb') as handle:
            return koreader_partial_md5(handle)

    def has_prefix(self, prefix: str) -> bool:
        try:
            path = self.path(prefix.rstrip('/'))
            return path.is_dir() and not path.is_symlink() and any(True for _ in path.iterdir())
        except (MigrationError, OSError):
            return False


class _ArchiveReadingSide:
    """Read-only access to verified saved-source ZIPs; ZIP mtimes are not device mtimes."""
    def __init__(self, stack: ExitStack, payload_zip=None, payload_files=None, runtime_zip=None, runtime_files=None):
        self.members, self.hashes = {}, {}
        if payload_zip is not None:
            archive = stack.enter_context(zipfile.ZipFile(payload_zip))
            for rel, meta in (payload_files or {}).items():
                self.members[rel] = (archive, rel, meta['size'])
                self.hashes[rel] = meta.get('sha256')
        if runtime_zip is not None:
            archive = stack.enter_context(zipfile.ZipFile(runtime_zip))
            for rel, meta in (runtime_files or {}).items():
                if rel.startswith(('docsettings/', 'hashdocsettings/')):
                    self.members['.adds/koreader/' + rel] = (archive, 'koreader/' + rel, meta['size'])
                    self.hashes['.adds/koreader/' + rel] = meta.get('sha256')

    def info(self, rel: str):
        member = self.members.get(rel)
        return None if member is None else {'size': member[2], 'mtime': None, 'mtime_epoch': None}

    def read(self, rel: str, size: int) -> bytes:
        archive, name, _ = self.members[rel]
        with archive.open(name) as handle:
            return handle.read(size + 1)

    def partial_md5(self, rel: str) -> str:
        archive, name, _ = self.members[rel]
        with archive.open(name) as handle:
            return koreader_partial_md5(handle)

    def has_prefix(self, prefix: str) -> bool:
        return any(rel.startswith(prefix) for rel in self.members)


def reading_store_paths(book: str, partial_md5: Optional[str] = None) -> List[Tuple[str, str]]:
    """Candidate metadata locations for one device-relative book path (assumptions A4/A5)."""
    sdr = Path(book).with_suffix('.sdr').as_posix()
    name = f'metadata.{Path(book).suffix.lower().lstrip(".")}.lua'
    paths = [('sidecar', f'{sdr}/{name}'),
             ('docsettings', f'.adds/koreader/docsettings/mnt/onboard/{sdr}/{name}')]
    if partial_md5:
        paths.append(('hashdocsettings', f'.adds/koreader/hashdocsettings/{partial_md5[:2]}/{partial_md5}.sdr/{name}'))
    return paths


def collect_reading_side(side, books: Dict[str, int], central: bool, budget: _ReadingBudget) -> dict:
    """Parse every metadata store that maps to one of `books`; never raises for per-file problems."""
    result = {'books': {}, 'limited': False}
    hashed = central and side.has_prefix('.adds/koreader/hashdocsettings/')

    def locate(location, rel):
        try:
            info = side.info(rel)
        except (MigrationError, OSError) as exc:
            return {'location': location, 'path': rel,
                    'parse_status': 'unsafe_path' if isinstance(exc, MigrationError) else 'unreadable'}
        return None if info is None else {'location': location, 'path': rel, **info}

    def book_md5(rel):
        try:
            return side.partial_md5(rel)
        except (MigrationError, OSError, KeyError, zipfile.BadZipFile):
            return None

    for book in sorted(books, key=path_key):
        record = {'size': books[book], 'partial_md5': None, 'stores': []}
        found = [store for store in (locate(location, rel) for location, rel in reading_store_paths(book)
                                     if central or location == 'sidecar') if store]
        if (found or hashed) and budget.allow(0):
            record['partial_md5'] = book_md5(book)
        if hashed and record['partial_md5']:
            store = locate(*reading_store_paths(book, record['partial_md5'])[2])
            found += [store] if store else []
        for store in found:
            if 'parse_status' not in store:
                store.update(read_reading_store(side, store, budget))
                result['limited'] = result['limited'] or store['parse_status'] == 'skipped_limit'
            old = locate(store['location'], store['path'] + '.old')
            store['old_backup'] = bool(old and 'parse_status' not in old)
            record['stores'].append(store)
        if record['stores']:
            result['books'][book] = record
    return result


def read_reading_store(side, store: dict, budget: _ReadingBudget) -> dict:
    size = store.get('size', 0)
    if size > READING_LIMITS.max_bytes:
        return {'parse_status': 'too_large'}
    if not budget.allow(size):
        return {'parse_status': 'skipped_limit'}
    try:
        data = side.read(store['path'], READING_LIMITS.max_bytes)
    except (MigrationError, OSError, KeyError, zipfile.BadZipFile):
        return {'parse_status': 'unreadable'}
    digest = hashlib.sha256(data).hexdigest()
    expected = side.hashes.get(store['path'])
    if expected and expected != digest:
        return {'parse_status': 'changed', 'sha256': digest}
    try:
        table = parse_lua_data(data, READING_LIMITS)
    except LuaDataError as exc:
        return {'parse_status': exc.code, 'parse_error': {'line': exc.line, 'byte': exc.offset}, 'sha256': digest}
    if not isinstance(table, dict):
        return {'parse_status': 'not_table', 'sha256': digest}
    return {'parse_status': 'ok', 'sha256': digest, **summarize_reading_data(table)}


def reading_mode_location(metadata_mode) -> str:
    mode = str(metadata_mode or '').split(' ')[0]
    return READING_MODE_LOCATION.get(mode, 'sidecar')


def _primary_store(record: Optional[dict], preferred: str) -> Optional[dict]:
    stores = [store for store in (record or {}).get('stores', []) if store.get('parse_status') == 'ok']
    order = [preferred] + [location for location in READING_LOCATIONS if location != preferred]
    stores.sort(key=lambda store: order.index(store['location']))
    return stores[0] if stores else None


def _has_reading(store: dict) -> bool:
    fields = store.get('fields') or {}
    counts = fields.get('counts') or {}
    return (fields.get('percent_finished') is not None or fields.get('position_kind', 'none') != 'none'
            or any(value for value in counts.values()))


def _has_annotations(store: dict) -> bool:
    counts = (store.get('fields') or {}).get('counts') or {}
    return any(counts.get(name) for name in ('annotations', 'highlights', 'bookmarks', 'notes'))


def _newer_hint(source: dict, target: dict) -> dict:
    for basis in ('latest_annotation', 'summary_modified', 'mtime_epoch'):
        left = source.get(basis) if basis == 'mtime_epoch' else source['fields'].get(basis)
        right = target.get(basis) if basis == 'mtime_epoch' else target['fields'].get(basis)
        if left is None or right is None:
            continue
        if basis == 'mtime_epoch' and abs(left - right) <= READING_MTIME_TOLERANCE:
            continue
        if left != right:
            return {'side': 'source' if left > right else 'target',
                    'basis': 'file_mtime' if basis == 'mtime_epoch' else basis}
    return {'side': 'unknown', 'basis': None}


def compare_reading_stores(source: dict, target: dict) -> dict:
    left, right = source['fields'], target['fields']
    if left['percent_finished'] is None or right['percent_finished'] is None:
        progress, delta = 'unknown', None
    else:
        delta = round(left['percent_finished'] - right['percent_finished'], 6)
        progress = 'same' if abs(delta) < READING_PROGRESS_TOLERANCE else 'differs'
    if 'none' in (left['position_kind'], right['position_kind']):
        position = 'unknown'
    elif left['position_kind'] != right['position_kind']:
        position = 'incomparable'
    else:
        key = 'last_xpointer' if left['position_kind'] == 'xpointer' else 'last_page'
        position = 'same' if left[key] == right[key] else 'differs'

    def verdict(a, b):
        return 'unknown' if a is None or b is None else 'same' if a == b else 'differs'

    # A side without any annotation table has no annotations; any on the other side differs.
    annotations = verdict(left['counts'], right['counts'])
    if annotations == 'unknown' and any(_has_annotations(store) for store in (source, target)):
        annotations = 'differs'
    return {'progress': progress, 'percent_delta': delta, 'position': position,
            'status': verdict(left['summary_status'], right['summary_status']),
            'annotations': annotations,
            'doc_props': verdict(source.get('identity'), target.get('identity')),
            'newer_hint': _newer_hint(source, target)}


def _public_store(store: dict, action: str) -> dict:
    keys = ('location', 'path', 'size', 'mtime', 'sha256', 'old_backup', 'parse_status')
    result = {key: store.get(key) for key in keys}
    if 'parse_error' in store:
        result['parse_error'] = store['parse_error']
    result['planned_action'] = action
    if store.get('parse_status') == 'ok':
        result['schema_family'] = store['fields']['schema_family']
        result['fields'] = {key: value for key, value in store['fields'].items() if key != 'schema_family'}
    return result


def reading_data_skipped(status: str, reason: str) -> dict:
    return {'schema_version': READING_DATA_SCHEMA, 'status': status, 'reason': reason, 'books': [],
            'summary': {}, 'notes': ['Report only; reading data is never merged or chosen automatically.']}


def build_reading_data_report(difference: dict, source_reading: dict, target_reading: dict, *,
                              full: bool, source_mode, target_mode) -> dict:
    """Compare per-book reading data against the existing plan; the plan is never changed."""
    actions = {entry['path']: label for label, entries in difference['files'].items()
               for entry in entries if label != 'target_only'}
    target_only_books = {entry['path'] for entry in difference['files'].get('target_only', [])
                         if entry.get('category') == 'books'}
    source_books, target_books = source_reading['books'], target_reading['books']
    source_pref, target_pref = reading_mode_location(source_mode), reading_mode_location(target_mode)
    by_checksum = {}
    for book, record in target_books.items():
        if book in target_only_books:
            for store in record['stores']:
                checksum = (store.get('fields') or {}).get('partial_md5_checksum')
                for value in {checksum, record.get('partial_md5')} - {None}:
                    by_checksum.setdefault(value, set()).add(book)
    flag_counts = dict.fromkeys(READING_FLAGS, 0)
    summary = {'books': 0, 'both': 0, 'source_only': 0, 'target_only': 0, 'same': 0, 'differs': 0,
               'unreadable_files': 0, **flag_counts}
    books = []
    for book in sorted(set(source_books) | set(target_books), key=path_key):
        source, target = source_books.get(book), target_books.get(book)
        planned = 'target_only' if book in target_only_books else actions.get(book, 'target_only')
        content = {'identical': 'identical', 'new': 'source_only', 'target_only': 'target_only'}.get(planned, 'different')
        flags = set()

        def source_action(store):
            if store['path'] in actions:
                return actions[store['path']]
            return 'via_runtime' if full and store['location'] != 'sidecar' else 'not_copied'

        def target_action(store):
            if store['path'] in actions:
                return actions[store['path']]
            return 'removed_by_runtime' if full and store['location'] != 'sidecar' else 'retained'

        source_stores = [_public_store(store, source_action(store)) for store in (source or {}).get('stores', [])]
        target_stores = [_public_store(store, target_action(store)) for store in (target or {}).get('stores', [])]
        for raw, public in zip((target or {}).get('stores', []), target_stores):
            if public['planned_action'] in {'overwrite', 'removed_by_runtime'} and raw.get('parse_status') == 'ok':
                if _has_reading(raw):
                    flags.add('target_reading_data_replaced')
                if _has_annotations(raw):
                    flags.add('target_annotations_replaced')
            if public['planned_action'] == 'retained' and planned == 'overwrite':
                flags.add('retained_for_different_book')
        if any(store['planned_action'] in {'keep_target', 'metadata_skipped'} for store in source_stores):
            flags.add('target_kept')
        for side in (source_stores, target_stores):
            if sum(store['parse_status'] == 'ok' for store in side) > 1:
                flags.add('multiple_stores')
            if any(store['parse_status'] != 'ok' for store in side):
                flags.add('unparseable')
        summary['unreadable_files'] += sum(store['parse_status'] != 'ok' for store in source_stores + target_stores)
        left, right = _primary_store(source, source_pref), _primary_store(target, target_pref)
        for record, store in ((source, left), (target, right)):
            checksum = (store or {}).get('fields', {}).get('partial_md5_checksum')
            if checksum and record.get('partial_md5') and checksum != record['partial_md5'] and store['location'] != 'hashdocsettings':
                flags.add('stale_sidecar_suspected')
        left_sum = (left or {}).get('fields', {}).get('partial_md5_checksum')
        right_sum = (right or {}).get('fields', {}).get('partial_md5_checksum')
        if left_sum and right_sum and left_sum != right_sum:
            flags.add('edition_mismatch')
        elif content == 'different' and source and target:
            flags.add('content_differs')
        match = {'method': 'path', 'confidence': 'exact' if source and target else 'unmatched', 'candidates': []}
        if planned == 'new' and source:
            keys = {(source or {}).get('partial_md5'), left_sum} - {None}
            candidates = sorted({book_rel for key in keys for book_rel in by_checksum.get(key, ())
                                 if target_books[book_rel]['size'] == source['size']}, key=path_key)
            if candidates:
                match = {'method': 'partial_md5', 'confidence': 'probable' if len(candidates) == 1 else 'ambiguous',
                         'candidates': candidates[:READING_MAX_CANDIDATES]}
                flags.add('moved_candidate' if len(candidates) == 1 else 'ambiguous_match')
        comparison = compare_reading_stores(left, right) if left and right else None
        summary['books'] += 1
        summary['both' if source and target else 'source_only' if source else 'target_only'] += 1
        if comparison:
            same = all(comparison[key] in {'same', 'unknown'} for key in ('progress', 'position', 'status', 'annotations'))
            summary['same' if same else 'differs'] += 1
        for flag in flags:
            summary[flag] += 1
        books.append({'book': book, 'planned_action': planned, 'book_content': content, 'match': match,
                      'source': {'book_partial_md5': (source or {}).get('partial_md5'), 'stores': source_stores},
                      'target': {'book_partial_md5': (target or {}).get('partial_md5'), 'stores': target_stores},
                      'comparison': comparison, 'flags': [flag for flag in READING_FLAGS if flag in flags]})
    limited = source_reading.get('limited') or target_reading.get('limited')
    return {'schema_version': READING_DATA_SCHEMA, 'status': 'partial' if limited else 'complete',
            'reason': 'limit_exceeded' if limited else None,
            'parser': {'grammar': 'lua-data-literal', 'version': 1, 'limits': asdict(READING_LIMITS)},
            'assumptions': {'partial_md5': 'unverified', 'central_layout': 'unverified',
                            'active_store': 'not_resolved'},
            'metadata_mode': {'source': source_mode, 'target': target_mode},
            'summary': summary, 'books': books,
            'notes': ['Report only; reading data is never merged or chosen automatically.',
                      'Comparison uses the store matching each device metadata mode first; '
                      'it does not claim which store KOReader will open.']}


def reading_data_targets(difference: dict, target: Path) -> Dict[str, int]:
    """TARGET books worth inspecting: existing counterparts of SOURCE books plus target-only books."""
    books = {}
    for label, entries in difference['files'].items():
        for entry in entries:
            if entry.get('category') != 'books':
                continue
            if label == 'target_only':
                books[entry['path']] = entry['size']
            elif label != 'new':
                try:
                    path = payload_path(target, entry['path'])
                    if path.is_file():
                        books[entry['path']] = path.stat().st_size
                except (MigrationError, OSError):
                    continue
    return books


def source_reading_books(files: dict) -> Dict[str, int]:
    return {rel: meta['size'] for rel, meta in files.items() if meta.get('category') == 'books'}


def reading_data_applicability(mode: str, books: bool, reading_data: bool) -> Optional[dict]:
    if mode == 'koreader':
        return reading_data_skipped('not_applicable', 'mode_koreader')
    if not books:
        return reading_data_skipped('skipped', 'no_books')
    if not reading_data:
        return reading_data_skipped('skipped', 'option_disabled')
    return None


def capture_source_reading(side, files: dict, central: bool) -> dict:
    """SOURCE half of the report, taken before eject; failures are reported, never raised."""
    try:
        return collect_reading_side(side, source_reading_books(files), central, _ReadingBudget())
    except Exception as exc:  # Report only: never block migration on a reporter bug.
        log_status(message('diagnostic.raw', detail=f'Reading data: SOURCE capture failed: {exc!r}'))
        return {'failed': True, 'books': {}, 'limited': False}


def reading_data_section(difference: dict, source_reading: Optional[dict], target: Path, *, mode: str,
                         books: bool, reading_data: bool, central: bool, source_mode, target_mode) -> dict:
    skipped = reading_data_applicability(mode, books, reading_data)
    if skipped is not None:
        return skipped
    try:
        if source_reading is None or source_reading.get('failed'):
            raise RuntimeError('SOURCE reading data unavailable')
        target_books = reading_data_targets(difference, target)
        target_reading = collect_reading_side(_MountReadingSide(target), target_books, central, _ReadingBudget())
        return build_reading_data_report(difference, source_reading, target_reading, full=mode == 'full',
                                         source_mode=source_mode, target_mode=target_mode)
    except Exception as exc:  # Report only: never block migration on a reporter bug.
        log_status(message('diagnostic.raw', detail=f'Reading data report failed: {exc!r}'))
        return reading_data_skipped('failed', 'internal_error')


def emit_reading_data(section: dict) -> None:
    if section['status'] not in {'complete', 'partial'}:
        ui_emit('reading_data.status', status=message('reading_data.status_' + section['status']),
                reason=message('reading_data.reason_' + section['reason']))
        return
    summary = section['summary']
    ui_emit('reading_data.summary', books=summary['books'], same=summary['same'], differs=summary['differs'],
            source_only=summary['source_only'], target_only=summary['target_only'], unparseable=summary['unreadable_files'])
    if section['status'] == 'partial':
        ui_emit('reading_data.status', status=message('reading_data.status_partial'),
                reason=message('reading_data.reason_limit_exceeded'), severity='warning')
    if summary['target_reading_data_replaced']:
        ui_emit('reading_data.warning_replaced', count=summary['target_reading_data_replaced'],
                annotations=summary['target_annotations_replaced'], severity='warning')
    if summary['edition_mismatch'] or summary['content_differs']:
        ui_emit('reading_data.warning_edition', count=summary['edition_mismatch'] + summary['content_differs'],
                severity='warning')


def reading_data_lines(section: dict) -> List[str]:
    ui = current_ui()
    lines = [ui.text(message('reading_data.title'))]
    if section['status'] not in {'complete', 'partial'}:
        lines.append(ui.text(message('reading_data.status', status=message('reading_data.status_' + section['status']),
                                     reason=message('reading_data.reason_' + section['reason']))))
        return lines + ['']
    summary = section['summary']
    lines.append(ui.text(message('reading_data.summary', books=summary['books'], same=summary['same'],
                                 differs=summary['differs'], source_only=summary['source_only'],
                                 target_only=summary['target_only'], unparseable=summary['unreadable_files'])))
    if section['status'] == 'partial':
        lines.append(ui.text(message('reading_data.status', status=message('reading_data.status_partial'),
                                     reason=message('reading_data.reason_limit_exceeded'))))
    unknown = ui.text(message('reading_data.value_unknown'))

    def side_values(side):
        store = next((s for s in side['stores'] if s.get('parse_status') == 'ok'), None)
        if store is None:
            return unknown, unknown
        fields = store['fields']
        percent = unknown if fields['percent_finished'] is None else f'{fields["percent_finished"] * 100:.1f}%'
        counts = fields.get('counts') or {}
        total = counts.get('annotations')
        if total is None:
            # No annotation table means no annotations; legacy files count highlights and bookmarks.
            total = (counts.get('highlights') or 0) + (counts.get('bookmarks') or 0)
        return percent, str(total)

    shown = [book for book in section['books']
             if book['flags'] or (book['comparison'] and any(book['comparison'][key] == 'differs'
                                  for key in ('progress', 'position', 'status', 'annotations')))]
    for book in shown[:READING_TEXT_BOOKS]:
        source_progress, source_notes = side_values(book['source'])
        target_progress, target_notes = side_values(book['target'])
        lines.append('  ' + book['book'])
        lines.append('    ' + ui.text(message('reading_data.book_detail', source_progress=source_progress,
                                               target_progress=target_progress, source_annotations=source_notes,
                                               target_annotations=target_notes)))
        lines.extend('    - ' + ui.text(message('reading_data.flag_' + flag)) for flag in book['flags'])
    if len(shown) > READING_TEXT_BOOKS:
        lines.append(ui.text(message('reading_data.more', count=len(shown) - READING_TEXT_BOOKS)))
    return lines + ['']


def build_difference_report(target: Path, source_files: dict, plan: dict, books: bool, fonts: bool,
                            scan_options: dict) -> dict:
    categories = {'new': [], 'overwrite': [], 'identical': [], 'keep_target': [],
                  'metadata_skipped': [], 'target_only': []}
    for rel, meta in plan['copy'].items():
        category = 'overwrite' if rel in plan['existing'] else 'new'
        categories[category].append({'path': rel, **meta,
            'target_size': plan['existing'].get(rel, {}).get('size')})
    for label, key in (('identical', 'skip'), ('keep_target', 'conflicts_kept'), ('metadata_skipped', 'metadata_skipped')):
        categories[label] = [{'path': rel, **source_files[rel]} for rel in plan[key]]
    log_status(message('scan.target_only'))
    target_files, target_scan = scan_payload(target, books, fonts, include_metadata=books, include_central_metadata=False,
        include_dirs=scan_options.get('include_dirs') or None,
        exclude_dirs=scan_options.get('exclude_dirs') or None,
        extra_extensions=scan_options.get('extra_extensions') or None,
        missing_roots_ok=True)
    for rel, meta in target_files.items():
        if rel not in source_files:
            categories['target_only'].append({'path': rel, **meta, 'action': 'retain'})
    groups = {}
    for label, entries in categories.items():
        for entry in entries:
            rel = entry['path']
            if entry.get('category') == 'books':
                groups[rel] = {'book': rel, 'action': label, 'sidecars': []}
    for label, entries in categories.items():
        for entry in entries:
            if entry.get('category') == 'sidecars':
                owners = [rel for rel in groups if entry['path'].startswith(Path(rel).with_suffix('.sdr').as_posix() + '/')]
                for owner in owners:
                    groups[owner]['sidecars'].append({'path': entry['path'], 'action': label})
    summary = {label: {'count': len(entries), 'bytes': sum(e.get('size', 0) for e in entries),
                      'source_bytes': 0 if label == 'target_only' else sum(e.get('size', 0) for e in entries),
                      'target_bytes': sum((e.get('target_size') or e.get('size', 0)) for e in entries)}
               for label, entries in categories.items()}
    return {'schema_version': 1, 'created_at': iso_now(), 'ui_locale': current_ui().bundle.tag, 'summary': summary,
            'files': categories, 'book_groups': list(groups.values()),
            'scope': scan_options, 'notes': ['Target-only files are retained; mirror deletion is not enabled.',
            'Discovery uses the same supported extensions and selected roots; this is not a complete disk inventory.']}


def write_difference(run: Path, difference: dict):
    atomic_json(run / 'difference.json', difference)
    ui = current_ui()
    lines = [ui.text(message('difference.title')), ui.text(message('difference.retain')), '']
    for label, entries in difference['files'].items():
        summary = difference['summary'][label]
        category = message('difference.' + label)
        lines.append(ui.text(message('difference.section', label=category, count=summary['count'],
                                     size=human_bytes(summary['bytes']))))
        lines.extend('  ' + entry['path'] for entry in entries)
        lines.append('')
        ui_emit('difference.section', label=category, count=summary['count'], size=human_bytes(summary['bytes']))
    if 'reading_data' in difference:
        lines.extend(reading_data_lines(difference['reading_data']))
    (run / 'difference.txt').write_text('\n'.join(lines), encoding='utf-8')
    ui_emit('difference.paths', path=run / 'difference.txt')


def run_catalog(project: Path) -> List[dict]:
    root = project / 'runs'
    if not root.is_dir() or root.is_symlink():
        return []
    records = []
    for run in sorted(root.iterdir()):
        if not run.is_dir() or run.is_symlink():
            continue
        try:
            state = read_json(run / 'run.json') if (run / 'run.json').is_file() else {}
        except MigrationError:
            state = {'status': 'unreadable'}
        if not isinstance(state.get('dependencies', []), list) or any(not isinstance(d, str) for d in state.get('dependencies', [])):
            state = {'status': 'unreadable'}
        total = sum(p.stat().st_size for p in run.rglob('*') if p.is_file() and not p.is_symlink())
        resumes = None
        reference = run / 'resume-reference.json'
        if reference.is_file() and not reference.is_symlink():
            try:
                resumes = read_json(reference).get('run_id')
            except MigrationError:
                resumes = None
        records.append({'resumes': resumes if isinstance(resumes, str) else None, 'run_id': run.name, 'path': str(run), 'bytes': total,
                        'status': state.get('status', 'legacy/unknown'),
                        'ended_at': state.get('ended_at'), 'operation': state.get('operation', 'unknown'),
                        'dependencies': state.get('dependencies', []), 'target_modified': state.get('target_modified', False),
                        'target_fingerprint': state.get('target_fingerprint')})
    return records


def cleanup_plan(project: Path, keep_successful: int = 2) -> dict:
    if keep_successful < 1:
        raise MigrationError(message('error.cleanup_keep'))
    records = run_catalog(project)
    successes = sorted([r for r in records if r['status'] == 'success'],
                       key=lambda r: (r['ended_at'] or '', r['run_id']), reverse=True)
    keep = {r['run_id'] for r in successes[:keep_successful]}
    # Conservatively protect all dependency targets, including references from old runs.
    dependencies = {dep for record in records for dep in record['dependencies']}
    latest_recovery = {}
    for record in successes:
        if record.get('target_fingerprint'):
            latest_recovery.setdefault(record['target_fingerprint'], record['run_id'])
    recovery_ids = set(latest_recovery.values())
    candidates, protected = [], []
    for record in records:
        reason = None
        if record['run_id'] in keep:
            reason = message('cleanup.reason_recent')
        elif record['run_id'] in dependencies:
            reason = message('cleanup.reason_dependency')
        elif record['run_id'] in recovery_ids:
            reason = message('cleanup.reason_recovery')
        elif record['status'] != 'success':
            reason = message('cleanup.reason_unconfirmed')
        if reason:
            protected.append({**record, 'reason': reason})
        else:
            candidates.append(record)
    return {'keep_successful': keep_successful, 'candidates': candidates, 'protected': protected,
            'reclaimable_bytes': sum(r['bytes'] for r in candidates)}


def print_catalog(records: List[dict]):
    ui_emit('catalog.heading')
    resumed_by = {record['resumes']: record['run_id'] for record in records
                  if record.get('resumes') and record['status'] in RESUME_BLOCKING_STATUSES}
    for record in records:
        ui_emit('catalog.row', run_id=record["run_id"], status=record["status"], operation=record["operation"], size=human_bytes(record["bytes"]))
        if record['run_id'] in resumed_by:
            ui_emit('catalog.resumed_by', run_id=resumed_by[record['run_id']])
    if not records:
        ui_emit('catalog.empty')


def cleanup_command(project: Path, keep: int, selected: List[str]) -> int:
    def show(plan):
        ui_emit('cleanup.heading')
        if plan['candidates']:
            print_catalog(plan['candidates'])
        else:
            ui_emit('cleanup.empty')
        ui_emit('cleanup.reclaimable', size=human_bytes(plan['reclaimable_bytes']))
        for record in plan['protected']:
            ui_emit('cleanup.protected', run_id=record['run_id'], reason=record['reason'])
    if not selected:
        show(cleanup_plan(project, keep))
        return 0
    with FileLock(project / '.project.lock', message('lock.project')):
        plan = cleanup_plan(project, keep)
        show(plan)
        allowed = {r['run_id'] for r in plan['candidates']}
        if len(set(selected)) != len(selected) or not set(selected) <= allowed:
            raise MigrationError(message('error.cleanup_ineligible'))
        expected = 'DELETE ' + ','.join(sorted(selected))
        ui_emit('cleanup.confirm', expected=expected, severity='warning')
        if ui_input(message('prompt.confirmation')).strip() != expected:
            ui_emit('cleanup.cancelled')
            return 0
        # Recompute protection at the final step; the project lock blocks new dependents.
        allowed = {r['run_id'] for r in cleanup_plan(project, keep)['candidates']}
        if not set(selected) <= allowed:
            raise MigrationError(message('error.cleanup_changed'))
        for run_id in selected:
            run = resolve_saved_run(project, run_id)
            if any(p.is_symlink() for p in run.rglob('*')):
                raise MigrationError(message('error.cleanup_symlink'))
        for run_id in selected:
            shutil.rmtree(resolve_saved_run(project, run_id))
            ui_emit('cleanup.deleted', run_id=run_id)
    return 0


def reconcile_interrupted_runs(project: Path):
    # Called only with the exclusive project lock. Prior live workers cannot coexist.
    for record in run_catalog(project):
        if record['status'] == 'running':
            path = Path(record['path']) / 'run.json'
            state = read_json(path)
            state.update(status='needs-recovery' if state.get('target_modified') else 'interrupted',
                         updated_at=iso_now(), note='Previous process ended without a final status; inspect before reuse/cleanup.')
            atomic_json(path, state)



def main() -> int:
    args = parse_args()
    with ui_session(args.locale_bundle):
        try:
            return run_main(args)
        except KeyboardInterrupt as exc:
            ui_emit('run.pre_interrupt', severity='warning')
            exc.ui_reported = True
            raise
        except MigrationError as exc:
            ui_emit('error.summary', detail=exception_detail(exc), channel='stderr', severity='error')
            exc.ui_reported = True
            raise


def run_main(args) -> int:
    global CURRENT_RUN, CURRENT_LOCKS
    if getattr(args, 'list_locales', False):
        bundle = args.locale_bundle
        lines = [bundle.render('cli.locales_heading')]
        lines += [f"  {tag}: {entry['name']}" for tag, entry in bundle.registry['entries'].items()]
        locale_console_write('\n'.join(lines) + '\n')
        return 0
    if getattr(args, 'preview_ui', False):
        preview_locale_ui(args.locale_bundle)
        return 0
    if getattr(args, 'locale', 'en') != 'en':
        ui_emit('ui.partial_notice', channel='stderr')
    if args.self_test:
        self_test()
        return 0
    project = args.backup_dir.expanduser().resolve()
    if VOLUME_ROOT.resolve() == project or VOLUME_ROOT.resolve() in project.parents:
        raise MigrationError(message('error.project_location'))
    if (project / 'runs').is_symlink():
        raise MigrationError(message('error.runs_symlink'))
    if getattr(args, 'list_runs', False):
        print_catalog(run_catalog(project))
        return 0
    if getattr(args, 'verify_run', None) or getattr(args, 'verify_all', False):
        return verify_runs_command(project, args.verify_run or [], args.verify_all,
                                   args.with_dependencies, args.json)
    if getattr(args, 'cleanup', False):
        return cleanup_command(project, args.keep_successful, [] if args.dry_run else args.delete_run)
    require_macos_tools()
    with FileLock(project / '.project.lock', message('lock.project')):
        reconcile_interrupted_runs(project)
        run_id = now_stamp() + '-' + uuid.uuid4().hex[:8]
        directory = project / 'runs' / run_id
        directory.mkdir(parents=True, exist_ok=False)
        if getattr(args, 'restore_run', None):
            operation = 'restore-target'
        elif getattr(args, 'resume_run', None):
            operation = 'resume-migration'
        elif getattr(args, 'from_run', None):
            operation = 'saved-source'
        else:
            operation = 'migration'
        state = RunState(directory, run_id, operation)
        CURRENT_RUN, CURRENT_LOCKS = state, DeviceLocks()
        log_path = directory / f'koreader-migration-{run_id}.log'
        try:
            with log_path.open('x', encoding='utf-8', buffering=1) as log:
                stdout, stderr = sys.stdout, sys.stderr
                with ui_session(args.locale_bundle, log, stdout, stderr):
                    sys.stdout, sys.stderr = LogTee(stdout, log), LogTee(stderr, log)
                    try:
                        ui_emit('run.banner', version=VERSION, run_id=run_id)
                        ui_emit('run.log_path', path=log_path)
                        if operation == 'restore-target':
                            code = restore_saved_target(args, project, directory, run_id, log_path)
                        elif operation == 'resume-migration':
                            code = resume_migration(args, project, directory, run_id, log_path)
                        elif operation == 'saved-source':
                            code = migrate_saved_source(args, project, directory, run_id, log_path)
                        else:
                            code = migrate(args, directory, run_id, log_path)
                        status = {2: 'rolled-back', 3: 'needs-recovery'}.get(code)
                        if status is None:
                            status = 'audited' if args.dry_run or state.data.get('dry_run') else 'success'
                        state.finish(status, exit_code=code)
                        return code
                    except MigrationCancelled as exc:
                        ui_emit('run.cancelled', detail=exception_detail(exc))
                        state.finish('cancelled', exit_code=0)
                        return 0
                    except KeyboardInterrupt:
                        ui_emit('run.interrupted', severity='warning')
                        state.finish('needs-recovery' if state.data['target_modified'] else 'interrupted', exit_code=130)
                        return 130
                    except BaseException as exc:
                        ui_emit('run.stopped', kind=type(exc).__name__, detail=exception_detail(exc), severity='error')
                        state.finish('needs-recovery' if state.data['target_modified'] else 'failed', exit_code=1)
                        raise
                    finally:
                        sys.stdout, sys.stderr = stdout, stderr
        finally:
            CURRENT_LOCKS.close()
            CURRENT_RUN, CURRENT_LOCKS = None, None


def migrate_saved_source(args, project: Path, run: Path, run_id: str, log_path: Path) -> int:
    selected = saved = resolve_saved_run(project, args.from_run)
    seen = set()
    selected_mode = None
    while (saved / 'source-reference.json').exists():
        if saved.name in seen or len(seen) >= 20:
            raise MigrationError(message('error.source_cycle'))
        seen.add(saved.name)
        reference = read_json(saved / 'source-reference.json')
        selected_mode = selected_mode or reference.get('mode')
        saved = resolve_saved_run(project, reference['run_id'])
    dependencies = sorted({selected.name, saved.name})
    run_phase('verifying-saved-source', dependencies=dependencies)
    descriptor = source_descriptor(saved)
    if descriptor.get('role') != 'source' or descriptor.get('mode') not in {'full', 'koreader', 'library'}:
        raise MigrationError(message('error.source_descriptor'))
    original_mode = descriptor['mode']
    if selected_mode not in {None, 'full', 'koreader', 'library'}:
        raise MigrationError(message('error.source_reference_mode'))
    mode = args.mode or selected_mode or original_mode
    if mode == 'audit':
        mode = original_mode
        dry_run = True
    else:
        dry_run = args.dry_run
    if mode == 'library' and original_mode != 'library':
        raise MigrationError(message('error.library_snapshot'))
    if mode == 'full' and original_mode != 'full':
        raise MigrationError(message('error.full_snapshot'))
    if mode in {'full', 'koreader'} and not descriptor.get('koreader'):
        raise MigrationError(message('error.runtime_archive_missing'))
    if args.include_dir or args.exclude_dir or args.extra_extension:
        raise MigrationError(message('error.saved_scope'))
    if mode == 'full' and (args.books is False or not args.reading_data):
        raise MigrationError(message('error.full_captured_books'))
    if mode == 'koreader' and (args.books is True or args.fonts is True):
        raise MigrationError(message('error.koreader_snapshot_scope'))
    source_zip, source_manifest = load_artifact(saved, descriptor.get('koreader'), 'koreader') if mode != 'library' else (None, None)
    payload_zip, payload_manifest = load_artifact(saved, descriptor.get('payload'), 'payload') if mode != 'koreader' else (None, None)
    payload_manifest = payload_manifest or {'files': {}}
    if any(meta.get('category') not in {'books', 'sidecars', 'central_metadata', 'fonts'} for meta in payload_manifest['files'].values()):
        raise MigrationError(message('error.payload_categories'))
    if mode == 'full' and args.fonts is False:
        payload_manifest = {**payload_manifest, 'files': {p: m for p, m in payload_manifest['files'].items() if m.get('category') != 'fonts'}}
    if mode == 'library':
        books = descriptor.get('books', True) if args.books is None else args.books
        fonts = descriptor.get('fonts', False) if args.fonts is None else args.fonts
        allowed = ({'books', 'sidecars', 'central_metadata'} if books else set()) | ({'fonts'} if fonts else set())
        if not args.reading_data:
            allowed -= {'sidecars', 'central_metadata'}
        payload_manifest = {**payload_manifest, 'files': {p: m for p, m in payload_manifest['files'].items() if m.get('category') in allowed}}
        if not books and not fonts:
            raise MigrationError(message('error.library_selection'))
    else:
        books, fonts = mode == 'full', mode == 'full' and args.fonts is not False
    conflict = select_conflict_policy(mode, args.conflict)
    info = DeviceInfo(**descriptor['device'])
    source_expected = canonical_model(descriptor.get('confirmed_model') or info.detected_model)
    if not source_expected:
        raise MigrationError(message('error.source_model_missing'))
    require_device_fingerprint(info)
    if args.source_model and canonical_model(args.source_model).casefold() != source_expected.casefold():
        raise MigrationError(message('error.source_model_mismatch'))
    target_expected = args.target_model
    target_slug = 'target'
    source_diag = descriptor.get('source_diagnostics', {})
    report = dict(descriptor.get('scan_report', {}))
    report.update(tool_version=VERSION, mode=mode, saved_source_run=saved.name, source_diagnostics=source_diag)
    scanned = payload_manifest['files']
    source_manifest_path = saved_file(saved, descriptor['koreader']['manifest']) if source_zip else None
    report_path = run / f'koreader-scan-{run_id}.json'
    atomic_json(report_path, report)
    # Reference verified originals; no multi-GiB duplication of source archives.
    atomic_json(run / 'source-reference.json', {'run_id': saved.name, 'mode': mode})
    run_phase('waiting-for-target', mode=mode, dry_run=dry_run)
    ui_emit('saved_source.using', run_id=saved.name, model=source_expected)
    ui_emit('saved_source.connect')
    if not prompt_yes_no(message('confirm.saved_source')):
        raise MigrationCancelled(message('cancel.migration'))
    source_reading = None
    if reading_data_applicability(mode, books, args.reading_data) is None:
        scope = report.get('scan_options') or {}
        with ExitStack() as stack:
            side = _ArchiveReadingSide(stack, payload_zip, payload_manifest['files'],
                                       source_zip if mode == 'full' else None,
                                       (source_manifest or {}).get('files') if mode == 'full' else None)
            source_reading = capture_source_reading(side, payload_manifest['files'],
                                                    central=not (scope.get('include_dirs') or scope.get('exclude_dirs')))
    return migrate_target(args, run, run_id, log_path, mode, dry_run, mode in {'full', 'koreader'},
                          books, fonts, conflict, info, source_expected, target_expected, target_slug,
                          source_zip, source_manifest_path, source_manifest, payload_zip,
                          payload_manifest, scanned, source_diag, report, report_path,
                          source_reading=source_reading)


TARGET_CHANGES_SCHEMAS = (1, 2)


def persist_target_changes(journal: dict):
    # Schema 2 is additive: touched/created_dirs keep their schema 1 meaning.
    if CURRENT_RUN is not None and journal.get('_mount') is not None:
        mount = journal['_mount']
        atomic_json(CURRENT_RUN.directory / 'target-changes.json', {
            'schema_version': 2, 'touched': journal['touched'],
            'completed': journal.get('completed', []),
            'created_dirs': [p.relative_to(mount).as_posix() for p in journal['created_dirs']],
            'runtime': journal.get('runtime')})


def read_change_journal(run: Path) -> dict:
    changes = read_json(run / 'target-changes.json')
    if changes.get('schema_version', 1) not in TARGET_CHANGES_SCHEMAS:
        raise MigrationError(message('error.change_journal'))
    for key in ('touched', 'created_dirs', 'completed'):
        value = changes.get(key, [])
        if not isinstance(value, list) or any(not isinstance(p, str) for p in value):
            raise MigrationError(message('error.change_journal'))
    return changes


def mark_runtime(journal: dict, state: str) -> None:
    journal['runtime'] = {'action': 'replace', 'state': state}
    persist_target_changes(journal)


def restore_saved_target(args, project: Path, run: Path, run_id: str, log_path: Path) -> int:
    saved = resolve_saved_run(project, args.restore_run)
    # A resumed migration restores to the first batch's pre-migration state using every link's journal.
    links = resolve_resume_chain(project, saved)
    root = links[0]
    run_phase('verifying-target-snapshot', dependencies=sorted(link.name for link in links), dry_run=args.dry_run)
    successor = resume_successor(project, saved.name, exclude={run.name})
    if successor:
        raise MigrationError(message('error.restore_superseded', run_id=saved.name, other=successor))
    descriptor = read_json(root / 'target-snapshot.json')
    if descriptor.get('role') != 'target':
        raise MigrationError(message('error.target_snapshot'))
    if descriptor.get('replaced_koreader') and descriptor.get('had_koreader') and not descriptor.get('koreader'):
        raise MigrationError(message('error.original_backup_missing'))
    changes = chain_changes(links)
    prior_state = read_json(saved / 'run.json')
    resumed = prior_state.get('operation') == 'resume-migration' and prior_state.get('status') == 'success'
    if not (prior_state.get('target_modified') or resumed):
        raise MigrationError(message('error.restore_unneeded'))
    original = DeviceInfo(**descriptor['device'])
    kr_archive, kr_manifest = load_artifact(root, descriptor.get('koreader'), 'koreader')
    payload_archive, payload_manifest = load_artifact(root, descriptor.get('payload'), 'payload')
    previous = payload_manifest['files'] if payload_manifest else {}
    touched = changes.get('touched', [])
    allowed_paths = set(descriptor.get('planned_paths', []))
    if not set(touched) <= allowed_paths:
        raise MigrationError(message('error.change_paths'))
    removed = [p for p in touched if p not in previous]
    restored = {p: m for p, m in previous.items() if p in touched}
    expected = canonical_model(descriptor.get('confirmed_model') or original.detected_model)
    if not expected or not original.fingerprint_sha256:
        raise MigrationError(message('error.restore_identity'))
    ui_emit('restore.heading', run_id=saved.name, model=expected)
    ui_emit('restore.scope')
    ui_input(message('prompt.restore_target', model=expected))
    mount = wait_for_single_kobo('RESTORE TARGET')
    acquire_device(mount, device_fingerprint(mount)[0])
    confirm_device(mount, original.fingerprint_sha256)
    ensure_local_backup(run, mount.resolve())
    info = inspect_device(mount)
    verify_expected_model(info, expected, 'RESTORE TARGET')
    kr = checked_path(mount, '.adds/koreader', allow_metadata=True)
    if kr.exists() and not kr.is_dir():
        raise MigrationError(message('error.runtime_directory'))
    if kr.is_dir():
        validate_tree_symlinks(kr)
    current_files = {}
    for rel in changes.get('created_dirs', []):
        checked_path(mount, rel, allow_metadata=rel.startswith('.adds/koreader/'))
    for rel in set(touched) | set(restored):
        path = payload_path(mount, rel)
        if path.exists():
            current_files[rel] = {'size': path.stat().st_size, 'category': previous.get(rel, {}).get('category', 'backup')}
    replacing_kr = bool(descriptor.get('replaced_koreader'))
    ui_emit('restore.plan', runtime=display_bool(replacing_kr), restore_count=len(restored), remove_count=len(removed))
    for rel in sorted(restored):
        ui_emit('restore.original', path=rel)
    for rel in sorted(removed):
        ui_emit('restore.remove_created', path=rel)
    restore_plan = {'operation': 'restore-target', 'from_run': saved.name,
                    'restore_paths': sorted(restored), 'remove_created_paths': removed}
    atomic_json(run / 'restore-plan.json', restore_plan)
    if args.dry_run:
        ui_emit('restore.preview')
        safe_eject(mount)
        return 0
    ensure_backup_space(run, (info.total_bytes if replacing_kr else 0) + sum(m['size'] for m in current_files.values()), message('space.pre_restore'))
    ensure_target_space(mount, (sum(m['size'] for m in kr_manifest['files'].values()) if kr_manifest else 0)
                        + sum(m['size'] for m in restored.values()), info.total_bytes if replacing_kr else 0)
    undo_kr, undo_manifest = None, None
    if replacing_kr and kr.is_dir():
        undo_kr = run / 'koreader-before-restore.zip'
        plugins, warnings = basic_plugin_audit(kr)
        undo_manifest = create_archive(kr, undo_kr, undo_kr.with_suffix('.manifest.json'), info, plugins, warnings, strict_source=False)
    undo_payload, undo_files = None, {}
    if current_files:
        undo_payload = run / 'library-before-restore.zip'
        undo_files = create_payload_archive(mount, current_files, undo_payload)['files']
    atomic_json(run / 'target-snapshot.json', {'schema_version': 1, 'role': 'target', 'device': asdict(info),
        'confirmed_model': expected, 'replaced_koreader': replacing_kr, 'had_koreader': kr.is_dir(), 'had_adds': kr.parent.exists(), 'koreader': artifact_entry(undo_kr),
        'payload': artifact_entry(undo_payload), 'planned_paths': sorted(set(touched) | set(restored))})
    if not prompt_yes_no(message('confirm.restore_target')):
        safe_eject(mount)
        raise MigrationCancelled(message('cancel.restore'))
    journal = {'touched': [], 'completed': [], 'created_dirs': [], '_mount': mount, 'runtime': None}
    kr_modified = False
    try:
        confirm_device(mount, original.fingerprint_sha256)
        run_phase('restoring-target', target_modified=True)
        if replacing_kr:
            kr_modified = True
            if kr.exists():
                remove_tree(kr)
            if descriptor.get('had_koreader'):
                if kr_archive is None:
                    raise MigrationError(message('error.original_backup_missing'))
                kr.parent.mkdir(parents=True, exist_ok=True)
                restore_zip(kr_archive, kr.parent)
                verify_restored_tree(kr, kr_manifest)
        for rel in removed:
            path = payload_path(mount, rel)
            journal['touched'].append(rel)
            persist_target_changes(journal)
            path.unlink(missing_ok=True)
        if restored:
            restore_payload(mount, payload_archive, restored, journal)
        for rel in reversed(changes.get('created_dirs', [])):
            directory = checked_path(mount, rel, allow_metadata=rel.startswith('.adds/koreader/'))
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if replacing_kr and not descriptor.get('had_adds', True) and kr.parent.is_dir() and not any(kr.parent.iterdir()):
            kr.parent.rmdir()
        atomic_json(run / 'restore-result.json', {**restore_plan, 'completed_at': iso_now(), 'tool_version': VERSION})
    except (Exception, KeyboardInterrupt) as exc:
        ui_emit('restore.failed', detail=exception_detail(exc), severity='error')
        errors = []
        try:
            confirm_device(mount, original.fingerprint_sha256)
        except Exception as error:
            ui_emit('restore.rollback_blocked', detail=exception_detail(error), severity='error')
            return 3
        try:
            rollback_payload(mount, undo_payload, undo_files, journal)
        except Exception as error:
            errors.append(exception_detail(error))
        if kr_modified:
            try:
                rollback_target(kr, kr.parent, undo_kr, undo_manifest)
            except Exception as error:
                errors.append(exception_detail(error))
        if errors:
            ui_emit('restore.rollback_errors', detail=join_diagnostics(errors), severity='error')
            return 3
        ui_emit('restore.rolled_back')
        return 2
    safe_eject(mount)
    ui_emit('restore.success')
    return 0


RESUMABLE_OPERATIONS = frozenset({'migration', 'saved-source', 'resume-migration'})
RESUMABLE_PHASES = frozenset({'replacing-koreader', 'copying-library', 'writing-result',
                              'ejecting-target', 'rolling-back'})
RUNTIME_SETTINGS = 'settings.reader.lua'
RUNTIME_PREFIX = '.adds/koreader/'


def zip_device_id(archive: Path) -> Optional[str]:
    # Read the literal only; device IDs are never logged or written to plans.
    with zipfile.ZipFile(archive) as zf:
        try:
            data = zf.read('koreader/' + RUNTIME_SETTINGS)
        except KeyError:
            return None
    match = DEVICE_ID_RE.search(data.decode('utf-8', errors='replace'))
    return (match.group(2) or None) if match else None


def runtime_identity_ok(settings: Path, identity_mode: str, source_id: Optional[str],
                        original_id: Optional[str]) -> bool:
    current = read_device_id(settings) if settings.is_file() and not settings.is_symlink() else None
    if identity_mode == 'preserve':
        return original_id is not None and current == original_id
    if identity_mode == 'clone':
        return current == source_id
    if identity_mode == 'new':
        return bool(current) and current != source_id
    return False


def runtime_tree_matches(kr: Path, files: dict, identity_mode: str, source_id: Optional[str],
                         original_id: Optional[str]) -> bool:
    """True only when the TARGET runtime is the verified source runtime plus the expected identity."""
    if not kr.is_dir() or kr.is_symlink():
        return False
    present = set()
    for base, _, names in os.walk(kr, followlinks=False):
        for name in names:
            rel = (Path(base) / name).relative_to(kr).as_posix()
            if not should_exclude_rel(rel):
                present.add(rel)
    if present - {RUNTIME_SETTINGS} != set(files) - {RUNTIME_SETTINGS}:
        return False
    checked = [rel for rel in files if rel != RUNTIME_SETTINGS]
    for index, rel in enumerate(checked, 1):
        path = kr / rel
        if path.is_symlink() or path.stat().st_size != files[rel]['size'] or sha256_file(path) != files[rel]['sha256']:
            return False
        print_progress(message('progress.verify_target'), index, len(checked))
    return runtime_identity_ok(kr / RUNTIME_SETTINGS, identity_mode, source_id, original_id)


def classify_resume_path(mount: Path, rel: str, planned: dict, original: Optional[dict],
                         existed: bool, touched: bool) -> str:
    """verified, remaining, partial or drifted; decided from current TARGET bytes, never the journal alone."""
    try:
        path = payload_path(mount, rel)
    except MigrationError:
        return 'drifted'
    if path.is_file():
        size, digest = path.stat().st_size, None

        def matches(meta):
            nonlocal digest
            if size != meta['size']:
                return False
            digest = digest or sha256_file(path)
            return digest == meta['sha256']

        if matches(planned):
            return 'verified'
        if existed and original is not None and matches(original):
            return 'remaining'
        return 'partial' if touched else 'drifted'
    if not existed:
        return 'remaining'
    return 'partial' if touched else 'drifted'


def resolve_source_chain(project: Path, batch: Path):
    saved, seen = batch, set()
    while (saved / 'source-reference.json').exists():
        if saved.name in seen or len(seen) >= 20:
            raise MigrationError(message('error.source_cycle'))
        seen.add(saved.name)
        reference = read_json(saved / 'source-reference.json').get('run_id')
        if not isinstance(reference, str):
            raise MigrationError(message('error.source_descriptor'))
        saved = resolve_saved_run(project, reference)
    return saved, seen | {saved.name}


def string_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


RESUME_BLOCKING_STATUSES = frozenset({'success', 'running', 'needs-recovery'})
RESUME_ROOT_OPERATIONS = frozenset({'migration', 'saved-source'})


def resume_successor(project: Path, run_name: str, exclude=()) -> Optional[str]:
    """Newer resume batch that already continues run_name, if any."""
    for record in run_catalog(project):
        if (record['run_id'] not in exclude and record.get('resumes') == run_name
                and record['status'] in RESUME_BLOCKING_STATUSES):
            return record['run_id']
    return None


def resolve_resume_chain(project: Path, run: Path) -> List[Path]:
    """[original batch, resume, ..., run] following resume-reference.json links."""
    links, seen = [run], {run.name}
    while (links[0] / 'resume-reference.json').exists():
        reference = read_json(links[0] / 'resume-reference.json').get('run_id')
        if not isinstance(reference, str):
            raise MigrationError(message('error.resume_chain'))
        previous = resolve_saved_run(project, reference)
        if previous.name in seen or len(seen) > 20:
            raise MigrationError(message('error.resume_chain'))
        seen.add(previous.name)
        links.insert(0, previous)
    if len(links) > 1:
        operations = [read_json(link / 'run.json').get('operation') for link in links]
        if operations[0] not in RESUME_ROOT_OPERATIONS or any(op != 'resume-migration' for op in operations[1:]):
            raise MigrationError(message('error.resume_chain'))
    return links


def chain_changes(links: List[Path]) -> dict:
    """Union of the change journals in a resume chain; the original batch must have one."""
    touched, created = [], []
    for index, link in enumerate(links):
        if index and not (link / 'target-changes.json').exists():
            continue  # A resume that stopped before its first write has no journal.
        changes = read_change_journal(link)
        touched += [p for p in changes.get('touched', []) if p not in touched]
        created += [p for p in changes.get('created_dirs', []) if p not in created]
    return {'touched': touched, 'created_dirs': created}


def rollback_resume_chain(mount: Path, links: List[Path], journal: dict, descriptor: dict,
                          payload_backup: Optional[Path], previous: dict,
                          kr_backup: Optional[Path], kr_backup_manifest: Optional[dict]) -> List[str]:
    """Return TARGET to the original pre-migration state recorded by the first batch."""
    errors = []
    prior = chain_changes(links[:-1]) if len(links) > 1 else {'touched': [], 'created_dirs': []}
    touched = prior['touched'] + [p for p in journal['touched'] if p not in prior['touched']]
    created = []
    try:
        for rel in prior['created_dirs']:
            created.append(checked_path(mount, rel, allow_metadata=rel.startswith(RUNTIME_PREFIX)))
        created += [p for p in journal['created_dirs'] if p not in created]
        rollback_payload(mount, payload_backup, previous, {'touched': touched, 'created_dirs': created})
    except Exception as error:
        errors.append(message('recovery.payload_error', detail=exception_detail(error)))
    if descriptor.get('replaced_koreader'):
        try:
            kr = checked_path(mount, '.adds/koreader', allow_metadata=True)
            rollback_target(kr, kr.parent, kr_backup, kr_backup_manifest)
            if not descriptor.get('had_adds', True) and kr.parent.is_dir() and not any(kr.parent.iterdir()):
                kr.parent.rmdir()
        except Exception as error:
            errors.append(message('recovery.runtime_error', detail=exception_detail(error)))
    return errors


def resume_migration(args, project: Path, run: Path, run_id: str, log_path: Path) -> int:
    """Continue an interrupted migration forward (KM-002). --dry-run previews without device writes."""
    dry_run = args.dry_run
    saved = resolve_saved_run(project, args.resume_run)
    run_phase('verifying-resume', dependencies=[saved.name], dry_run=dry_run)
    prior = read_json(saved / 'run.json')
    if prior.get('operation') not in RESUMABLE_OPERATIONS:
        raise MigrationError(message('error.resume_operation', operation=str(prior.get('operation'))))
    if prior.get('status') != 'needs-recovery' or not prior.get('target_modified'):
        raise MigrationError(message('error.resume_status', status=str(prior.get('status'))))
    if prior.get('phase') not in RESUMABLE_PHASES:
        raise MigrationError(message('error.resume_phase', phase=str(prior.get('phase'))))
    successor = resume_successor(project, saved.name, exclude={run.name})
    if successor:
        raise MigrationError(message('error.resume_superseded', run_id=saved.name, other=successor))
    links = resolve_resume_chain(project, saved)
    root = links[0]
    atomic_json(run / 'resume-reference.json', {'run_id': saved.name})

    descriptor = read_json(root / 'target-snapshot.json')
    if descriptor.get('role') != 'target' or not isinstance(descriptor.get('device'), dict):
        raise MigrationError(message('error.target_snapshot'))
    changes = chain_changes(links)
    report = read_json(root / f'koreader-scan-{root.name}.json')
    plan = report.get('plan')
    if not isinstance(plan, dict) or not isinstance(plan.get('copy'), dict):
        raise MigrationError(message('error.resume_plan_missing'))
    copy, existing = plan['copy'], plan.get('existing', {})
    skip, kept = plan.get('skip', []), plan.get('conflicts_kept', [])
    if not isinstance(existing, dict) or not string_list(skip) or not string_list(kept) or not set(existing) <= set(copy):
        raise MigrationError(message('error.resume_plan_invalid'))
    validate_file_manifest(copy, True)
    planned_paths = descriptor.get('planned_paths', [])
    if not string_list(planned_paths) or set(planned_paths) != set(copy):
        raise MigrationError(message('error.resume_plan_invalid'))
    touched = set(changes['touched'])
    if not touched <= set(copy):
        raise MigrationError(message('error.change_paths'))
    full = bool(descriptor.get('replaced_koreader'))
    identity_mode = report.get('identity_mode')
    if full and identity_mode not in {'preserve', 'new', 'clone'}:
        raise MigrationError(message('error.resume_plan_invalid'))

    source_run, chain = resolve_source_chain(project, root)
    run_phase('verifying-resume', dependencies=sorted(chain | {link.name for link in links}))
    source = source_descriptor(source_run)
    if source.get('role', 'source') != 'source' or not isinstance(source.get('device'), dict):
        raise MigrationError(message('error.source_descriptor'))
    source_info = DeviceInfo(**source['device'])
    original = DeviceInfo(**descriptor['device'])
    expected = canonical_model(descriptor.get('confirmed_model') or original.detected_model)
    if not expected or not original.fingerprint_sha256:
        raise MigrationError(message('error.restore_identity'))
    if args.target_model and (canonical_model(args.target_model) or '').casefold() != expected.casefold():
        raise MigrationError(message('error.resume_target_model'))
    if source_info.fingerprint_sha256 and source_info.fingerprint_sha256 == original.fingerprint_sha256:
        raise MigrationError(message('error.same_device'))

    log_status(message('workflow.verify_source'))
    source_zip, source_manifest = None, None
    if full:
        source_zip, source_manifest = load_artifact(source_run, source.get('koreader'), 'koreader')
        if source_zip is None:
            raise MigrationError(message('error.runtime_archive_missing'))
    payload_zip, payload_files = None, {}
    if copy or skip:
        payload_zip, payload_manifest = load_artifact(source_run, source.get('payload'), 'payload')
        payload_files = (payload_manifest or {}).get('files', {})
    for rel in list(copy) + skip:
        planned, actual = copy.get(rel), payload_files.get(rel)
        if actual is None or (planned is not None and (actual['size'], actual['sha256']) != (planned['size'], planned['sha256'])):
            raise MigrationError(message('error.resume_plan_mismatch', path=rel))
    kr_backup, kr_backup_manifest = load_artifact(root, descriptor.get('koreader'), 'koreader')
    if full and descriptor.get('had_koreader') and kr_backup is None:
        raise MigrationError(message('error.original_backup_missing'))
    payload_backup, payload_backup_manifest = load_artifact(root, descriptor.get('payload'), 'payload')
    previous = payload_backup_manifest['files'] if payload_backup_manifest else {}
    if not set(existing) <= set(previous):
        raise MigrationError(message('error.resume_backup_incomplete'))
    source_id = zip_device_id(source_zip) if full else None
    original_id = zip_device_id(kr_backup) if full and kr_backup else None

    ui_emit('resume.heading', run_id=saved.name, model=expected)
    ui_emit('resume.scope')
    ui_input(message('prompt.resume_target', model=expected))
    mount = wait_for_single_kobo('TARGET')
    acquire_device(mount, device_fingerprint(mount)[0])
    confirm_device(mount, original.fingerprint_sha256)
    ensure_local_backup(run, mount.resolve())
    info = inspect_device(mount)
    run_phase('planning-resume', target_fingerprint=info.fingerprint_sha256, target_model=expected)
    verify_expected_model(info, expected, 'TARGET')
    kr = checked_path(mount, '.adds/koreader', allow_metadata=True)
    if kr.exists() and not kr.is_dir():
        raise MigrationError(message('error.runtime_directory'))
    if kr.is_dir():
        validate_tree_symlinks(kr)

    phase = prior['phase']
    runtime = {'action': 'none', 'reason': None, 'snapshot_before_replace': False}
    if full:
        if phase == 'replacing-koreader':
            runtime.update(action='replace', reason='interrupted_during_replacement')
        elif runtime_tree_matches(kr, source_manifest['files'], identity_mode, source_id, original_id):
            runtime.update(action='keep')
        elif phase == 'rolling-back':
            runtime.update(action='replace', reason='rollback_interrupted')
        else:
            runtime.update(action='replace', reason='runtime_changed_after_interruption',
                           snapshot_before_replace=kr.is_dir())
    source_runtime = source_manifest['files'] if full else {}

    def classify(rel, planned, existed, was_touched):
        if runtime['action'] == 'replace' and rel.startswith(RUNTIME_PREFIX):
            # Replacement resets this path to the source runtime copy before library writes.
            predicted = source_runtime.get(rel[len(RUNTIME_PREFIX):])
            same = predicted is not None and (predicted['size'], predicted['sha256']) == (planned['size'], planned['sha256'])
            return 'verified' if same else 'remaining'
        return classify_resume_path(mount, rel, planned, previous.get(rel), existed, was_touched)

    log_status(message('workflow.target_comparison'))
    classes = {'verified': [], 'remaining': [], 'partial': [], 'drifted': []}
    for index, (rel, meta) in enumerate(copy.items(), 1):
        classes[classify(rel, meta, rel in existing, rel in touched)].append(rel)
        print_progress(message('progress.verify_target'), index, len(copy))
    for rel in skip:
        if classify(rel, payload_files[rel], True, False) != 'verified':
            classes['drifted'].append(rel)
    for rel in kept:
        try:
            if not payload_path(mount, rel).is_file():
                classes['drifted'].append(rel)
        except MigrationError:
            classes['drifted'].append(rel)
    pending = set(classes['remaining'] + classes['partial'])
    to_write = {rel: meta for rel, meta in copy.items() if rel in pending}
    write_bytes = sum(meta['size'] for meta in to_write.values())
    runtime_bytes = sum(m['size'] for m in source_runtime.values()) if runtime['action'] == 'replace' else 0
    resume_plan = {'schema_version': 1, 'tool_version': VERSION, 'operation': 'resume-migration',
                   'resumed_run': saved.name, 'root_run': root.name, 'chain': [link.name for link in links],
                   'source_run': source_run.name, 'mode': report.get('mode'),
                   'interrupted_phase': phase, 'identity_mode': identity_mode, 'runtime': runtime,
                   'library': {key: sorted(value) for key, value in classes.items()},
                   'counts': {key: len(value) for key, value in classes.items()},
                   'write_bytes': write_bytes, 'runtime_bytes': runtime_bytes,
                   'journal_completed_hint': len(read_change_journal(saved).get('completed', []))
                   if (saved / 'target-changes.json').exists() else 0}
    plan_path = run / 'resume-plan.json'
    atomic_json(plan_path, resume_plan)

    if runtime['action'] == 'none':
        ui_emit('resume.runtime_none')
    elif runtime['action'] == 'keep':
        ui_emit('resume.runtime_keep')
    elif runtime['reason'] == 'interrupted_during_replacement':
        ui_emit('resume.runtime_replace_interrupted', severity='warning')
    elif runtime['reason'] == 'rollback_interrupted':
        ui_emit('resume.runtime_replace_rollback', severity='warning')
    else:
        ui_emit('resume.runtime_replace_changed', severity='warning')
    ui_emit('resume.library', verified=len(classes['verified']), remaining=len(classes['remaining']),
            partial=len(classes['partial']), size=human_bytes(write_bytes))
    if classes['drifted']:
        drifted = sorted(set(classes['drifted']))
        for rel in drifted:
            ui_emit('resume.drifted', path=rel, severity='error')
        raise MigrationError(message('error.resume_drift', count=len(drifted)))
    replacing = runtime['action'] == 'replace'
    current_kr = walk_tree_stats(kr)[1] if replacing else 0
    if replacing:
        ensure_target_space(mount, runtime_bytes + write_bytes, current_kr)
        if runtime['snapshot_before_replace']:
            ensure_backup_space(run, current_kr, message('space.pre_resume'))
    else:
        free = shutil.disk_usage(mount).free
        need = int(write_bytes * 1.1) + 50 * 1024 * 1024
        ui_emit('space.library', free=human_bytes(free), need=human_bytes(need))
        if free < need:
            raise MigrationError(message('error.library_space'))
    if dry_run:
        ui_emit('resume.preview', path=plan_path)
        safe_eject(mount)
        return 0

    snapshot = None
    if runtime['snapshot_before_replace']:
        # The reader may have been used after the interruption; keep that runtime recoverable.
        log_status(message('workflow.backup_runtime'))
        plugins, warnings = basic_plugin_audit(kr)
        snapshot = run / 'koreader-before-resume.zip'
        create_archive(kr, snapshot, snapshot.with_suffix('.manifest.json'), info, plugins, warnings, strict_source=False)
    run_phase('awaiting-final-confirmation')
    ui_emit('resume.final_plan', runtime=display_bool(replacing), count=len(to_write))
    if not prompt_yes_no(message('confirm.resume')):
        safe_eject(mount)
        raise MigrationCancelled(message('cancel.resume'))
    journal = {'touched': [], 'completed': [], 'created_dirs': [], '_mount': mount,
               'runtime': {'action': 'replace', 'state': 'pending'} if replacing else None}
    persist_target_changes(journal)
    try:
        confirm_device(mount, original.fingerprint_sha256)
        if replacing:
            run_phase('replacing-koreader', target_modified=True)
            checked_path(mount, '.adds/koreader', allow_metadata=True)
            kr.parent.mkdir(exist_ok=True)
            if kr.exists():
                mark_runtime(journal, 'removing')
                remove_tree(kr)
            mark_runtime(journal, 'extracting')
            restore_zip(source_zip, kr.parent)
            remove_stale_caches(kr)
            remove_macos_metadata(kr)
            verify_restored_tree(kr, source_manifest)
            mark_runtime(journal, 'verified')
            apply_identity_mode(kr, identity_mode, original_id)
            mark_runtime(journal, 'identity-applied')
            ensure_source_structure(mount)
        if to_write:
            run_phase('copying-library', target_modified=True)
            restore_payload(mount, payload_zip, to_write, journal)
        after = device_diagnostics(mount)
        source_diag = source.get('source_diagnostics') or {}
        if full and 'statistics' in source_diag and after['statistics'] != source_diag['statistics']:
            raise MigrationError(message('error.statistics_changed'))
        run_phase('writing-result')
        result_path = run / f'koreader-migration-result-{run_id}.json'
        atomic_json(result_path, {
            'tool_version': VERSION, 'operation': 'resume-migration', 'mode': report.get('mode'),
            'completed_at': iso_now(), 'resumed_run': saved.name, 'root_run': root.name,
            'runtime_action': runtime['action'], 'payload_copied': len(to_write),
            'verified_skipped': len(classes['verified']),
            'pre_resume_runtime_backup': snapshot.name if snapshot else None,
            'diagnostics_after': after, 'log': str(log_path)})
    except (Exception, KeyboardInterrupt) as exc:
        try:
            run_phase('rolling-back')
        except OSError as status_error:
            log_status(message('recovery.status_error', detail=exception_detail(status_error)))
        ui_emit('recovery.migration_failed', kind=type(exc).__name__, detail=exception_detail(exc), severity='error')
        try:
            confirm_device(mount, original.fingerprint_sha256)
        except Exception as guard_exc:
            ui_emit('recovery.blocked', detail=exception_detail(guard_exc), severity='error')
            ui_emit('recovery.reconnect')
            return 3
        errors = rollback_resume_chain(mount, links + [run], journal, descriptor, payload_backup, previous,
                                       kr_backup, kr_backup_manifest)
        if errors:
            for error in errors:
                ui_emit('recovery.error', detail=diagnostic_detail(error), severity='error')
            ui_emit('recovery.keep_connected')
            return 3
        ui_emit('resume.rolled_back')
        return 2
    ui_emit('resume.success', path=result_path)
    run_phase('ejecting-target')
    safe_eject(mount)
    ui_emit('migration.done')
    return 0


def select_conflict_policy(mode: str, requested: Optional[str]) -> str:
    if mode in {'full', 'koreader'}:
        if requested == 'keep-target':
            raise MigrationError(message('error.conflict_mode'))
        return 'overwrite'
    if mode == 'audit':
        return requested or 'overwrite'
    return requested or {'1': 'overwrite', '2': 'keep-target'}[choose(
        message('menu.conflict'),
        [('1', message('menu.overwrite')), ('2', message('menu.keep_target'))], default='1')]


def migrate(args, backup_dir: Path, run_id: str, log_path: Path) -> int:
    mode = args.mode or {'1': 'full', '2': 'koreader', '3': 'library', '4': 'audit'}[choose(
        message('menu.mode'),
        [('1', message('menu.full')),
         ('2', message('menu.koreader')),
         ('3', message('menu.library')),
         ('4', message('menu.audit'))], default='1')]
    dry_run = args.dry_run or mode == 'audit'
    full = mode in {'full', 'koreader', 'audit'}
    if mode == 'full':
        if args.books is False or not args.reading_data:
            raise MigrationError(message('error.full_books'))
        if args.include_dir or args.exclude_dir:
            raise MigrationError(message('error.full_scope'))
        books = True
        fonts = args.fonts if args.fonts is not None else True
    elif mode == 'koreader':
        if args.books is True or args.fonts is True:
            raise MigrationError(message('error.koreader_scope'))
        books, fonts = False, False
    else:
        books = args.books if args.books is not None else prompt_yes_no(message('confirm.books'), default=True)
        fonts = args.fonts if args.fonts is not None else prompt_yes_no(message('confirm.fonts'), default=False)
    if not full and not books and not fonts:
        raise MigrationError(message('error.library_selection'))
    conflict = select_conflict_policy(mode, args.conflict)
    source_expected, target_expected = getattr(args, 'source_model', None), getattr(args, 'target_model', None)
    source_slug, target_slug = 'source', 'target'
    ui_emit('migration.options', mode=mode.upper(), books=display_bool(books), fonts=display_bool(fonts), conflict=conflict)
    if dry_run:
        ui_emit('workflow.preview')
        ui_emit('workflow.local_reports')
    ui_emit('workflow.disconnect')
    ui_emit('workflow.private_archives')
    if not prompt_yes_no(message('confirm.continue')):
        raise MigrationCancelled(message('cancel.migration'))
    ui_input(message('prompt.source'))
    source_mount = wait_for_single_kobo('SOURCE')
    ensure_local_backup(backup_dir, source_mount.resolve())
    source_kr = checked_path(source_mount, '.adds/koreader', allow_metadata=True)
    if full:
        ensure_source_structure(source_mount)
    if source_kr.is_dir():
        validate_tree_symlinks(source_kr)
    acquire_device(source_mount, device_fingerprint(source_mount)[0])
    source_info = inspect_device(source_mount)
    run_phase('capturing-source', mode=mode, dry_run=dry_run)
    display_device_info(source_info, 'SOURCE')
    require_device_fingerprint(source_info)
    source_expected = confirm_role_model(source_info, source_expected, 'SOURCE')
    source_diag = device_diagnostics(source_mount)
    ui_emit('diagnostic.metadata_mode', mode=source_diag["metadata_mode"])
    ui_emit('diagnostic.statistics', detail=source_diag["statistics"])
    ui_emit('diagnostic.source_missing', count=len(source_diag["missing_references"]))
    scanned, scan_report = scan_payload(source_mount, books, fonts,
        include_metadata=args.reading_data, include_dirs=args.include_dir,
        exclude_dirs=args.exclude_dir, extra_extensions=args.extra_extension)
    # In FULL, the KOReader ZIP already includes all central metadata.
    if full:
        scanned = {rel: meta for rel, meta in scanned.items() if not rel.startswith('.adds/koreader/')}
    ui_emit('workflow.payload', count=len(scanned), size=human_bytes(sum(m["size"] for m in scanned.values())))
    for category in ('books', 'sidecars', 'central_metadata', 'fonts', 'unrecognized', 'skipped_symlinks'):
        ui_emit('workflow.category', category=category, count=len(scan_report[category]))
    for warning in scan_report['warnings']:
        ui_emit('diagnostic.warning', detail=diagnostic_detail(warning), severity='warning')
    report_path = backup_dir / f'koreader-scan-{run_id}.json'
    scan_report.update({'tool_version': VERSION, 'mode': mode, 'source_diagnostics': source_diag,
                        'scan_options': {'include_dirs': args.include_dir, 'exclude_dirs': args.exclude_dir, 'extra_extensions': args.extra_extension}})
    report_path.write_text(json.dumps(scan_report, indent=2, ensure_ascii=False), encoding='utf-8')
    ui_emit('workflow.scan_report', path=report_path)
    source_zip = backup_dir / f'koreader-{source_slug}-{run_id}.zip'
    source_manifest_path = source_zip.with_suffix('.manifest.json')
    payload_zip = backup_dir / f'library-{source_slug}-{run_id}.zip'
    source_manifest = None
    payload_manifest = {'files': {}}
    required = (source_info.total_bytes if full else 0) + sum(m['size'] for m in scanned.values())
    ensure_backup_space(backup_dir, required, message('space.source_backup'))
    if full:
        plugins, warnings = basic_plugin_audit(source_kr)
        ui_emit('diagnostic.plugins', count=len(plugins), warnings=len(warnings))
        for warning in warnings:
            ui_emit('diagnostic.plugin_warning', detail=diagnostic_detail(warning), severity='warning')
        if dry_run:
            ui_emit('preview.archive_runtime', path=source_zip)
        else:
            source_manifest = create_archive(source_kr, source_zip, source_manifest_path,
                source_info, plugins, warnings)
    if scanned:
        if dry_run:
            payload_manifest = hash_payload(source_mount, scanned)
            ui_emit('preview.archive_payload', path=payload_zip)
        else:
            payload_manifest = create_payload_archive(source_mount, scanned, payload_zip)
    source_reading = None
    if reading_data_applicability(mode, books, args.reading_data) is None:
        hashes = {rel: meta.get('sha256') for rel, meta in payload_manifest['files'].items()}
        source_reading = capture_source_reading(_MountReadingSide(source_mount, hashes), payload_manifest['files'],
                                                central=not (args.include_dir or args.exclude_dir))
    if not dry_run:
        save_source_snapshot(backup_dir, source_info, mode, books, fonts, scan_report,
                             source_zip if full else None, payload_zip if scanned else None, confirmed_model=source_expected)
    run_phase('waiting-for-target')
    safe_eject(source_mount)
    ui_emit('workflow.unplug_source')
    return migrate_target(args, backup_dir, run_id, log_path, mode, dry_run, full, books, fonts,
                          conflict, source_info, source_expected, target_expected, target_slug,
                          source_zip if full else None, source_manifest_path if full else None,
                          source_manifest, payload_zip if scanned else None, payload_manifest,
                          scanned, source_diag, scan_report, report_path, source_reading=source_reading)


def migrate_target(args, backup_dir, run_id, log_path, mode, dry_run, full, books, fonts,
                   conflict, source_info, source_expected, target_expected, target_slug,
                   source_zip, source_manifest_path, source_manifest, payload_zip,
                   payload_manifest, scanned, source_diag, scan_report, report_path, source_reading=None):
    ui_input(message('prompt.target'))
    target_mount = wait_for_single_kobo('TARGET')
    ensure_local_backup(backup_dir, target_mount.resolve())
    target_kr = checked_path(target_mount, '.adds/koreader', allow_metadata=True)
    target_adds = target_mount / '.adds'
    if target_kr.exists() and not target_kr.is_dir():
        raise MigrationError(message('error.target_directory'))
    if target_kr.is_dir():
        validate_tree_symlinks(target_kr)
    acquire_device(target_mount, device_fingerprint(target_mount)[0])
    target_info = inspect_device(target_mount)
    run_phase('planning-target', target_fingerprint=target_info.fingerprint_sha256, target_model=target_info.detected_model)
    display_device_info(target_info, 'TARGET')
    require_device_fingerprint(target_info)
    target_expected = confirm_role_model(target_info, target_expected, 'TARGET')
    run_phase('planning-target', target_model=target_expected)
    if full and not prompt_yes_no(message('confirm.compatibility'), default=False):
        raise MigrationCancelled(message('cancel.compatibility'))
    if (source_info.fingerprint_sha256 and target_info.fingerprint_sha256
            and source_info.fingerprint_sha256 == target_info.fingerprint_sha256):
        raise MigrationError(message('error.same_device'))
    log_status(message('workflow.target_preflight'))
    target_diag = device_diagnostics(target_mount)
    log_status(message('workflow.target_comparison'))
    plan = plan_payload(target_mount, payload_manifest, conflict)
    ui_emit('workflow.payload_plan', copy=len(plan["copy"]), skip=len(plan["skip"]), overwrite=len(plan["existing"]), keep=len(plan["conflicts_kept"]))
    kept_books = [rel for rel in plan['conflicts_kept']
                  if payload_manifest['files'][rel].get('category') == 'books']
    if full and kept_books:
        raise MigrationError(message('error.full_keep_target'))
    if plan['metadata_skipped']:
        ui_emit('workflow.metadata_skipped', count=len(plan["metadata_skipped"]), severity="warning")
    difference = build_difference_report(target_mount, payload_manifest['files'], plan, books, fonts, scan_report.get('scan_options', {}))
    scope = scan_report.get('scan_options', {})
    difference['reading_data'] = reading_data_section(
        difference, source_reading, target_mount, mode=mode, books=books, reading_data=args.reading_data,
        central=not (scope.get('include_dirs') or scope.get('exclude_dirs')),
        source_mode=source_diag.get('metadata_mode'), target_mode=target_diag.get('metadata_mode'))
    write_difference(backup_dir, difference)
    emit_reading_data(difference['reading_data'])
    copy_size = sum(m['size'] for m in plan['copy'].values())
    if full:
        ensure_target_space(target_mount, source_info.total_bytes + copy_size, target_info.total_bytes)
    else:
        free = shutil.disk_usage(target_mount).free
        need = int(copy_size * 1.1) + 50 * 1024 * 1024
        ui_emit('space.library', free=human_bytes(free), need=human_bytes(need))
        if free < need:
            raise MigrationError(message('error.library_space'))
    ensure_backup_space(backup_dir, (target_info.total_bytes if full else 0)
                        + sum(m['size'] for m in plan['existing'].values()), message('space.target_backup'))
    identity_mode = choose_identity_mode(read_device_id(target_kr / 'settings.reader.lua')) if full else None
    target_id = read_device_id(target_kr / 'settings.reader.lua') if full else None
    target_zip = backup_dir / f'koreader-{target_slug}-pre-migration-{run_id}.zip'
    target_manifest_path = target_zip.with_suffix('.manifest.json')
    payload_backup = backup_dir / f'library-{target_slug}-pre-migration-{run_id}.zip'
    scan_report.update({'target_diagnostics_before': target_diag, 'plan': plan,
                        'identity_mode': identity_mode, 'dry_run': dry_run})
    report_path.write_text(json.dumps(scan_report, indent=2, ensure_ascii=False), encoding='utf-8')
    if dry_run:
        if full:
            ui_emit('preview.replace_runtime', path=target_kr)
            ui_emit('preview.backup_runtime', path=target_zip)
        for rel in plan['copy']:
            ui_emit('preview.payload_path', action=message('preview.overwrite' if rel in plan['existing'] else 'preview.create'), path=rel)
        ui_emit('preview.complete', path=report_path)
        safe_eject(target_mount)
        return 0
    confirm_device(target_mount, target_info.fingerprint_sha256)
    # Validate saved archives before any target writes.
    log_status(message('workflow.verify_source'))
    if full:
        if sha256_file(source_zip) != source_manifest['archive']['sha256']:
            raise MigrationError(message('error.source_runtime_checksum'))
        validate_koreader_zip(source_zip)
    if scanned and sha256_file(payload_zip) != payload_manifest['archive_sha256']:
        raise MigrationError(message('error.source_payload_checksum'))
    target_manifest, actual_target_zip = None, None
    if full and target_kr.is_dir():
        plugins, warnings = basic_plugin_audit(target_kr)
        log_status(message('workflow.backup_runtime'))
        target_manifest = create_archive(target_kr, target_zip, target_manifest_path,
                                        target_info, plugins, warnings, strict_source=False)
        actual_target_zip = target_zip
    previous, actual_payload_backup = {}, None
    if plan['existing']:
        log_status(message('workflow.backup_payload'))
        previous = create_payload_archive(target_mount, plan['existing'], payload_backup)['files']
        actual_payload_backup = payload_backup
    atomic_json(backup_dir / 'target-snapshot.json', {'schema_version': 1, 'role': 'target',
        'device': asdict(target_info), 'confirmed_model': target_expected, 'replaced_koreader': full, 'had_koreader': target_kr.is_dir(), 'had_adds': target_adds.exists(),
        'koreader': artifact_entry(actual_target_zip), 'payload': artifact_entry(actual_payload_backup),
        'planned_paths': list(plan['copy'])})
    run_phase('awaiting-final-confirmation')
    ui_emit('workflow.final_plan', runtime=display_bool(full), count=len(plan['copy']))
    ui_emit('workflow.retain_unrelated')
    if not prompt_yes_no(message('confirm.migration')):
        safe_eject(target_mount)
        raise MigrationCancelled(message('cancel.final'))
    journal = {'touched': [], 'completed': [], 'created_dirs': [], '_mount': target_mount,
               'runtime': {'action': 'replace', 'state': 'pending'} if full else None}
    persist_target_changes(journal)
    kr_modified = False
    adds_created = False
    try:
        confirm_device(target_mount, target_info.fingerprint_sha256)
        if full:
            run_phase('replacing-koreader', target_modified=True)
            checked_path(target_mount, '.adds/koreader', allow_metadata=True)
            if not target_adds.exists():
                target_adds.mkdir()
                adds_created = True
            kr_modified = True
            if target_kr.exists():
                if not target_kr.is_dir():
                    raise MigrationError(message('error.target_directory'))
                mark_runtime(journal, 'removing')
                remove_tree(target_kr)
            mark_runtime(journal, 'extracting')
            restore_zip(source_zip, target_adds)
            remove_stale_caches(target_kr)
            remove_macos_metadata(target_kr)
            verify_restored_tree(target_kr, source_manifest)
            mark_runtime(journal, 'verified')
            apply_identity_mode(target_kr, identity_mode, target_id)
            mark_runtime(journal, 'identity-applied')
            ensure_source_structure(target_mount)
        if plan['copy']:
            run_phase('copying-library', target_modified=True)
            restore_payload(target_mount, payload_zip, plan['copy'], journal)
        after = device_diagnostics(target_mount)
        if full and 'statistics' in source_diag and after['statistics'] != source_diag['statistics']:
            raise MigrationError(message('error.statistics_changed'))
        result = {'tool_version': VERSION, 'mode': mode, 'completed_at': iso_now(),
            'source_model': source_expected, 'target_model': target_expected,
            'source_archive': str(source_zip) if full else None,
            'source_payload': str(payload_zip) if scanned else None,
            'target_backup': str(actual_target_zip) if actual_target_zip else None,
            'target_payload_backup': str(actual_payload_backup) if actual_payload_backup else None,
            'payload_copied': len(plan['copy']), 'identical_skipped': len(plan['skip']),
            'conflicts_kept': len(plan['conflicts_kept']), 'metadata_skipped': len(plan['metadata_skipped']),
            'identity_mode': identity_mode,
            'diagnostics_after': after, 'scan_report': str(report_path), 'log': str(log_path)}
        run_phase('writing-result')
        result_path = backup_dir / f'koreader-migration-result-{run_id}.json'
        result_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
    except (Exception, KeyboardInterrupt) as exc:
        try:
            run_phase('rolling-back')
        except OSError as status_error:
            log_status(message('recovery.status_error', detail=exception_detail(status_error)))
        ui_emit('recovery.migration_failed', kind=type(exc).__name__, detail=exception_detail(exc), severity='error')
        errors = []
        try:
            confirm_device(target_mount, target_info.fingerprint_sha256)
        except Exception as guard_exc:
            ui_emit('recovery.blocked', detail=exception_detail(guard_exc), severity='error')
            ui_emit('recovery.reconnect')
            return 3
        try:
            rollback_payload(target_mount, actual_payload_backup, previous, journal)
        except Exception as error:
            errors.append(message('recovery.payload_error', detail=exception_detail(error)))
        if kr_modified:
            try:
                checked_path(target_mount, '.adds/koreader', allow_metadata=True)
                rollback_target(target_kr, target_adds, actual_target_zip, target_manifest)
                if adds_created and target_adds.exists() and not any(target_adds.iterdir()):
                    target_adds.rmdir()
            except Exception as error:
                errors.append(message('recovery.runtime_error', detail=exception_detail(error)))
        if errors:
            for error in errors:
                ui_emit('recovery.error', detail=diagnostic_detail(error), severity='error')
            ui_emit('recovery.keep_connected')
            return 3
        ui_emit('recovery.complete')
        return 2
    ui_emit('migration.success', path=result_path)
    ui_emit('diagnostic.after_missing', count=len(after["missing_references"]))
    run_phase('ejecting-target')
    safe_eject(target_mount)
    ui_emit('migration.done')
    return 0


def cli() -> int:
    """Shared process boundary; fallback diagnostics stay English before UI setup."""
    try:
        return main()
    except KeyboardInterrupt as exc:
        if not getattr(exc, "ui_reported", False):
            print("\nCancelled by user.")
        return 130
    except MigrationError as exc:
        if not getattr(exc, "ui_reported", False):
            print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(cli())
