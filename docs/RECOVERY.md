# Backups and recovery

[Home](../README.md) · [Usage](USAGE.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Maintaining](MAINTAINING.md)

Keep your recovery files until you have checked the result on TARGET. Management commands work on local batches. Restoring a batch still requires the original device and final confirmation.

## Run files, reports and status

By default all generated files stay in the project folder containing the script:

```text
kobo-koreader-migrate.py
README.md / LICENSE / CHANGELOG.md
TRACKER.md / ACCEPTANCE.md / AGENTS.md
CONTRIBUTING.md / SECURITY.md
tests/
locales/                 registry and three UTF-8 foundation catalogs
scripts/                 locale/publication checks and PR helper
.github/workflows/       fixture test CI
.githooks/               optional local pre-push guard
runs/                    private; ignored by Git
  <timestamp-random-id>/
    run.json
    koreader-migration-<run-id>.log
    koreader-scan-<run-id>.json
    difference.txt / difference.json
    source-snapshot.json or source-reference.json
    target-snapshot.json / target-changes.json
    resume-plan.json / resume-reference.json   resume batches
    koreader-before-resume.zip                 only when a used runtime is replaced
    *.zip / *.manifest.json
    koreader-migration-result-<run-id>.json
.project.lock             persistent lock inode; ignored by Git
.local/                   optional private notes; ignored by Git
```

The files in a batch depend on the operation. A dry run creates reports without ZIPs. Each batch uses a flat layout to stay compatible with earlier runs. Logs and JSON records contain the version; the script filename stays the same.

Choose a different output root on the Mac:

```bash
python3 koreader-bridge.py --backup-dir ~/KoboMigration --mode full --dry-run
python3 koreader-bridge.py --backup-dir ~/KoboMigration --list-runs
```

The resulting batches are `~/KoboMigration/runs/<run-id>/`. Backups under `/Volumes` or inside a Kobo mount are refused. Management commands must use the same output root to find those runs.

Progress output includes phase timestamps, file counts, bytes, large-file transfer/hash speed and estimated time, and periodic heartbeat messages for long macOS archive commands. Database diagnostics and target comparison announce their phases. Some calls, such as a SQLite check or an individual filesystem operation, can still take time without per-record progress.

`difference.txt` and `difference.json` enumerate new, overwritten, identical, kept, skipped-metadata and target-only files, with counts/bytes and book/sidecar grouping. Target-only entries are informative; default migration does not delete those books.

<a id="reading-data-report"></a>
From 1.1.0-dev.5, `difference.json` has an additive `reading_data` object (its own `schema_version` 1; the file's `schema_version` stays 1 and older runs simply lack it). `status` is `complete`, `partial` (size/time limit reached), `skipped`, `not_applicable` or `failed`, with a machine `reason`. Each entry in `books` names the book, its `planned_action` and `book_content`, the SOURCE and TARGET metadata stores with their `planned_action` and `parse_status`, a `comparison` of progress/position/status/annotations with a `newer_hint`, and `flags` such as `target_annotations_replaced`, `edition_mismatch` or `ambiguous_match`. Stores record counts, positions, statuses and checksums only, never annotation text, notes, titles or authors. The report is computed before any TARGET write and does not affect restore, `--verify-run` or cleanup; use the TARGET rollback backup to recover replaced reading data.

`run.json` tracks phases and final states:

| Status | Meaning |
| --- | --- |
| `running` | Worker has not recorded a final result. |
| `success` | Operation and verification completed. |
| `audited` | Inspection/preview completed without device writes. |
| `cancelled` | Ordinary user cancellation before target changes. |
| `failed` | Failure recorded before target modification. |
| `interrupted` | Interrupted without recorded target modification. |
| `rolled-back` | Operation failed; automatic rollback succeeded. |
| `needs-recovery` | Target may have changed and needs inspection/recovery. |
| legacy/unknown | No trustworthy modern status; conservatively protected. |

The operating system owns project and device locks and releases them when the process exits. A leftover lock **filename** therefore does not mean a worker is still running. Never delete a live lock file to bypass its owner. At the next exclusive project startup, the tool checks unfinished `running` records and reconciles them conservatively. Stop older v3.0.x workers before starting a newer version; they do not honour these locks.

## Version numbering and existing backups

The first-stable 1.x sequence is a numbering reset from earlier 3.x development builds. Tool version strings in logs/JSON are provenance; snapshot/manifest schema versions and integrity checks determine supported reuse, not whether a tool version sorts above another. Existing valid supported 3.x snapshots remain usable through the same saved-source/restore commands. Modern snapshots still require their complete archive/manifest/record pairs; a version reset cannot repair incomplete or corrupt backups.

Do not rename run IDs, edit existing version metadata or recreate old manifests to match 1.x. Keep using the output root containing those runs; a new checkout's default output directory does not automatically discover another checkout's backups. Existing source references/dependencies and cleanup protection continue to apply. See [version policy](MAINTAINING.md#versioning-and-first-stable-release).

## Saved source migration and target restoration

List existing runs first:

```bash
python3 koreader-bridge.py --list-runs
```

### Verify a saved batch

Check a batch's archives before relying on it, without connecting a Kobo:

```bash
python3 koreader-bridge.py --verify-run <run-id>
```

The check pairs each `*.zip` with its `*.manifest.json` and applies the same rules used before saved-source and restore writes: archive SHA-256, member sizes and hashes, unsafe or duplicate paths, unlisted members and snapshot references. It lists each artifact as verified or failed and exits with status 1 if anything fails. It reads only; it never repairs, rewrites or deletes files. A batch still marked `running` may be incomplete. Saved-source and restore commands verify again before writing, so a passing result does not replace those checks.

### Reuse a saved SOURCE

```bash
python3 koreader-bridge.py --from-run RUN_ID --dry-run
python3 koreader-bridge.py --from-run RUN_ID
```

Replace `RUN_ID` with an ID listed under this project's `runs/`. Only TARGET is connected. The tool verifies archive SHA-256, manifests, member paths and contents. It references the original SOURCE archives and records dependencies instead of duplicating large ZIPs.

| Captured snapshot | Permitted migration mode |
| --- | --- |
| FULL | FULL or KOREADER |
| KOREADER | KOREADER |
| LIBRARY | LIBRARY |

Default mode follows the captured mode. You cannot silently use a FULL snapshot as LIBRARY: its central metadata is inside the runtime archive. Legacy source batches need a complete scan report and valid archive/manifest pairs with an identifiable source model. Legacy run status remains unknown/protected.

Saved run selection is limited to this project's run directories; an absolute path is accepted only when it resolves to a direct run child in that same project. Use `--backup-dir` to select another project root.

### Restore the original TARGET state

```bash
python3 koreader-bridge.py --restore-run RUN_ID --dry-run
python3 koreader-bridge.py --restore-run RUN_ID
```

Restoration uses the previous run's **TARGET pre-migration snapshot**. It restores recorded originals and removes files created by that migration, while retaining unrelated library files. If the run replaced KOReader, restoration replaces the whole KOReader tree with its previous backup. The SOURCE snapshot is used for a new migration, not this restore.

Exact restoration requires v3.1+ `target-snapshot.json`, `target-changes.json`, a run that modified its target, verified archive pairs and the same device fingerprint. Older target backups without a complete journal are not accepted by this command. From 1.1.0-dev.6, `target-changes.json` uses schema 2, which adds a per-file `completed` list and a `runtime` progress marker for FULL/KOREADER runs; restore accepts schema 1 and 2 journals and refuses any other version. The tool creates pre-restore undo backups and asks for final confirmation. Subsequent changes to the affected paths/runtime can be overwritten by restoring an older state; inspect the dry run first.

Restore cannot be combined with migration scope/model/conflict flags. Only the recorded state, `--dry-run` and `--backup-dir` control it. This is not an automatic interrupted-run resume feature.

### Resume an interrupted migration

From 1.1.0-dev.8 an interrupted migration can continue forward instead of being restored. Preview first:

```bash
python3 koreader-bridge.py --resume-run RUN_ID --dry-run
python3 koreader-bridge.py --resume-run RUN_ID
```

Only a migration or saved-source batch with status `needs-recovery` that changed TARGET qualifies. It must have stopped while replacing KOReader, copying the library, writing the result, ejecting or rolling back. The preview re-verifies the SOURCE archives and the original TARGET backups, asks for the same reader (fingerprint and model), and compares every planned file on TARGET by hash. `resume-plan.json` in the new batch says whether the KOReader runtime would be kept or replaced, and lists files as verified, remaining, partly written or changed outside the migration. Any file changed outside the migration refuses the resume; use `--restore-run` or start a new migration instead.

The preview never writes to the Kobo, and its batch ends as `audited`. Without `--dry-run` the same checks run, then a final confirmation that defaults to No. Resume then:

- replaces the KOReader runtime only when the plan says so, first saving `koreader-before-resume.zip` in the new batch if the reader was probably used after the interruption;
- copies only remaining and partly written files, and keeps files already verified;
- writes its own `target-changes.json` and result file, and ends as `success`.

If resume fails after it starts writing, it rolls TARGET back to the **original pre-migration state** captured by the first batch, not to the interrupted state, and ends as `rolled-back`. A resume that is itself interrupted becomes `needs-recovery` and can be resumed again. Run `--resume-run` on the newest batch: older batches in the chain are refused.

Each resume batch records the batch it continues in `resume-reference.json` and lists every earlier batch as a dependency, so cleanup keeps them. `--list-runs` shows `resumed by <run-id>` under a batch that a newer resume continues.

To undo a resumed migration, restore the **newest** batch in the chain. `--restore-run` follows the chain back to the first batch, uses its TARGET backups and combines every batch's change journal, so TARGET returns to its original pre-migration state. Restoring an older batch in the chain is refused with the run to use instead. See the [resume design](RESUME_DESIGN.md) for the rules.

## Backup cleanup

These commands do not require a connected Kobo:

```bash
# Inventory only.
python3 koreader-bridge.py --list-runs

# Preview only. This does not delete anything.
python3 koreader-bridge.py --cleanup

# Preview with a larger recent-success retention count.
python3 koreader-bridge.py --cleanup --keep-successful 5
```

The default retention count is two; the minimum is one. Cleanup protects recent successful batches, referenced dependencies, the newest known successful recovery point per target, and all non-success/legacy/unknown batches. It deletes only whole eligible batches explicitly selected by ID:

```bash
python3 koreader-bridge.py --cleanup --delete-run RUN_ID
```

You must type the exact `DELETE ...` text shown by the tool. Multiple `--delete-run` flags select multiple eligible batches. The tool locks and rechecks eligibility and rejects symlink-containing batches. Adding `--dry-run` suppresses deletion even when IDs are supplied. There is no scheduled deletion, individual-ZIP pruning or automatic removal of failed runs. Keep recovery batches until physical testing is complete.

## Recovery boundaries

Caught failures attempt rollback while the original TARGET remains connected. Power loss, disconnection, hardware failure or forced termination can prevent recovery. A checksum verifies captured bytes, not settings compatibility. See [troubleshooting and exit codes](TROUBLESHOOTING.md#exit-codes) before retrying a failed operation. Preserve original backups and do not edit manifests to bypass verification.
