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

Exact restoration requires v3.1+ `target-snapshot.json`, `target-changes.json`, a run that modified its target, verified archive pairs and the same device fingerprint. Older target backups without a complete journal are not accepted by this command. The tool creates pre-restore undo backups and asks for final confirmation. Subsequent changes to the affected paths/runtime can be overwritten by restoring an older state; inspect the dry run first.

Restore cannot be combined with migration scope/model/conflict flags. Only the recorded state, `--dry-run` and `--backup-dir` control it. This is not an automatic interrupted-run resume feature.

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
