# Resume interrupted transfer: design (KM-002)

Status: **Accepted design; implementation in progress.** The owner accepted the four [decisions](#decisions) on 2026-11-03. Slice 1 (journal schema 2 and runtime markers) is implemented in 1.1.0-dev.6; resume itself is not. This document does not authorize device access.

Related: [TRACKER.md](../TRACKER.md) (KM-002), [recovery guide](RECOVERY.md), [development guide](DEVELOPMENT.md).

## Problem

A migration writes to TARGET only after verified source archives, TARGET rollback backups and a final confirmation. Caught failures roll back automatically while the reader stays connected (status `rolled-back`). Power loss, disconnection, forced termination or a failed rollback leave the batch `needs-recovery` (directly, or through `reconcile_interrupted_runs` at the next startup).

Today the only way forward from `needs-recovery` is backward: `--restore-run` (KM-001) returns TARGET to its pre-migration state, and the user then starts the migration again. For a large library that repeats every byte already copied. KM-002 adds a forward path: continue the interrupted batch's own plan, re-verifying everything instead of trusting the journal, and keep the original pre-migration rollback point.

## Goals and non-goals

Goals:

- Resume a `needs-recovery` migration batch (fresh, saved-source or an earlier resume) from the Mac, offline, with the same SOURCE artifacts, TARGET, mode and plan.
- Skip only files whose TARGET bytes hash-match the planned source bytes at resume time.
- Define exactly what happens when the interruption hit the FULL/KOREADER runtime replacement.
- Keep `--restore-run` able to return TARGET to its original pre-migration state after any number of resumes.
- Refuse, rather than guess, when TARGET no longer matches a state the batch can explain.

Non-goals:

- Resuming the read-only phases (SOURCE capture, backup creation). An interruption there leaves `interrupted`, not `needs-recovery`; rerun the migration or use `--from-run`.
- Resuming `restore-target` batches. A failed restore stays a restore problem (see [decisions](#decisions)).
- Changing mode, scope, conflict policy or identity mode while resuming.
- Native desktop support in the first slice. It follows as a typed IPC request after the CLI is accepted.

## Current state the design builds on

| Artifact | Written | What resume needs from it |
| --- | --- | --- |
| `run.json` | Every phase change | `status`, `phase`, `target_modified`, `operation`, `dependencies` |
| `target-snapshot.json` | Before final confirmation | Original TARGET device record and fingerprint, confirmed model, `replaced_koreader`, `had_koreader`, `had_adds`, rollback artifacts, `planned_paths` |
| `target-changes.json` | Before each library file write | `touched` paths (recorded **before** the write) and `created_dirs` |
| `koreader-scan-<run-id>.json` | Before final confirmation | `plan` (`copy`, `existing`, `skip`, `conflicts_kept`, `metadata_skipped`), `identity_mode`, scan options |
| Source runtime/payload ZIPs + manifests, or `source-reference.json` | SOURCE capture | Bytes and SHA-256 for every planned file |
| TARGET pre-migration ZIPs + manifests | Before final confirmation | Original runtime and overwritten library files |

`run.json.phase` already acts as a coarse marker. `replacing-koreader` is set before the runtime is removed, and `copying-library` is set only after the runtime has been re-extracted, verified and given its identity. The per-file journal records intent, not completion, so a touched path may hold a partial file.

## User interface

```bash
# Preview: verify everything and print the resume plan. No TARGET writes.
python3 koreader-bridge.py --resume-run RUN_ID --dry-run

# Resume after the same checks and a final default-cancel confirmation.
python3 koreader-bridge.py --resume-run RUN_ID
```

- `--resume-run` is mutually exclusive with `--from-run`, `--restore-run`, `--verify-run`, `--list-runs`, `--cleanup` and every mode/scope/conflict/identity option, including `--books`, `--fonts` and `--reading-data`. It accepts `--backup-dir`, `--locale`, `--dry-run` and `--target-model` (must equal the saved confirmed model).
- A new batch is created with `operation: resume-migration`. It writes `resume-reference.json` (`{"run_id": "<resumed batch>"}`) and lists the resumed batch and its source chain in `dependencies`. Earlier batches are never edited.
- Exit codes and final statuses match migration: `0` success/audited, `2` rolled-back, `3` needs-recovery, `1` failed, `130` interrupted.
- `--list-runs` shows `resume-migration` batches and marks a batch as `resumed by <run-id>` when a later resume refers to it.

## Eligibility

A batch can be resumed only when all of these hold:

1. `run.json` has `status: needs-recovery` and `target_modified: true`, and `operation` is `migration`, `saved-source` or `resume-migration`.
2. `phase` is one of `replacing-koreader`, `copying-library`, `writing-result` or `rolling-back`.
3. `target-snapshot.json`, `target-changes.json` and the scan report with a `plan` exist and pass the existing schema checks. Every `touched` path is in `planned_paths`.
4. No other batch already resumes it with status `success`, `running` or `needs-recovery`. Only the newest unfinished link in a chain is resumable, which keeps the chain linear.
5. For FULL/KOREADER with `had_koreader: true`, the TARGET pre-migration runtime archive exists.

`interrupted`, `failed`, `cancelled` and `rolled-back` batches are refused with a hint: nothing on TARGET needs continuing, so start the migration again or reuse the SOURCE with `--from-run`.

## Revalidation before any TARGET write

Resume repeats every gate a migration applies, in the same order, plus drift checks.

1. **Locks.** Exclusive project lock, `reconcile_interrupted_runs`, then device locks for the connected reader (mount and fingerprint).
2. **Source chain.** Follow `source-reference.json` links with the existing cycle limit. Verify each source runtime and payload ZIP against its manifest with the KM-010 saved-archive verifier: archive SHA-256, member list, sizes, member hashes, unsafe paths and duplicates. Any mismatch refuses resume.
3. **Rollback artifacts.** Verify the original TARGET pre-migration runtime and library ZIPs the same way. Resume does not start if the original state could not be restored afterwards.
4. **TARGET identity.** The connected reader's fingerprint must equal `target-snapshot.json.device.fingerprint_sha256`. Its detected model must match the confirmed model, using the existing correction rules (corrections cannot override a fingerprint failure). It must not match the SOURCE fingerprint. Native connected-reader sessions revalidate their session token at this boundary too.
5. **Runtime state** (FULL/KOREADER only). See [runtime replacement](#runtime-replacement).
6. **Library classification.** See [library files](#library-files). Any drifted path refuses resume.
7. **Space.** Recompute TARGET space for the runtime bytes still to be written plus the remaining library bytes, and Mac space for any pre-resume snapshot.
8. **Plan display and final confirmation.** Print and save `resume-plan.json`: runtime action, counts and bytes for verified, remaining and partial files. Then ask a new default-cancel confirmation. Consent from the original batch is never reused.

`--dry-run` stops after step 8's display and ejects safely.

## Runtime replacement

A FULL or KOREADER interruption can leave `.adds/koreader` in any of these states: the original runtime, a partly removed tree, a partly extracted source runtime, a complete source runtime without identity, or a complete runtime with identity. The batch only has a coarse phase marker, so resume never patches a runtime tree in place. It either proves the tree is complete or replaces it wholesale.

Runtime action rules:

| Recorded phase | Check at resume | Action |
| --- | --- | --- |
| `replacing-koreader` | None needed; the tree state is unknown | **Replace**: remove `.adds/koreader`, extract the verified source runtime, remove stale caches and macOS metadata, verify against the source manifest, apply identity |
| `copying-library`, `writing-result`, `rolling-back` | Every source-manifest file except `settings.reader.lua` matches by size and SHA-256, and `settings.reader.lua` exists with the expected identity | **Keep** when the check passes, otherwise **Replace** |

Expected identity in `settings.reader.lua`:

- `preserve`: the device ID read from `settings.reader.lua` inside the original TARGET pre-migration runtime ZIP, read as bytes with the existing regex and never evaluated.
- `clone`: the device ID from the source runtime manifest's `settings.reader.lua`.
- `new`: any non-empty ID that differs from the source ID. A **Replace** generates a fresh ID. The ID from the interrupted attempt is not reused or stored.

Identity mode comes from the resumed batch's scan report. Device IDs never go into logs, `resume-plan.json` or discovery output.

A failed **Keep** check after `copying-library` usually means the reader booted the new runtime between the interruption and the resume, which writes settings, history or statistics. The resume plan reports this as `runtime_changed_after_interruption`. Resume archives the current runtime into the resume batch as `koreader-before-resume.zip`, verifies the archive, and asks for confirmation before replacing (see [decisions](#decisions)). The archive is made only in this case.

If `had_adds` was false and `.adds` exists, it stays until the run finishes or rolls back. The existing empty-directory cleanup applies.

## Library files

Resume rebuilds the expected state of every path in the original plan's `copy` set from three sources: the source payload manifest (planned bytes), the TARGET pre-migration payload manifest (original bytes of overwritten paths) and the original plan (whether the path existed before). Each path is classified after the runtime action, so central metadata under `.adds/koreader` is judged against the final runtime tree.

| Current TARGET state | In the journal's `touched` | Class | Action |
| --- | --- | --- | --- |
| Matches the planned source size and SHA-256 | Either | `verified` | Skip; record as completed |
| Matches the original bytes, or is absent where the plan created it | Either | `remaining` | Copy |
| Present with other bytes | Yes | `partial` | Overwrite (expected after an interrupted write) |
| Present with other bytes, or absent where it existed before | No | `drifted` | **Refuse resume** and name the path |

- `skip`, `conflicts_kept` and `metadata_skipped` paths stay out of the write set, as in the original plan. A `keep-target` conflict whose TARGET bytes changed since planning is reported as drift.
- Paths outside the original plan are never written or deleted. Target-only books stay retained.
- The case-collision and symlink checks from `plan_payload` and `checked_path` run again on every path.
- `verified` is always decided by hashing current TARGET bytes. A journal entry alone never causes a skip.

Drift means TARGET changed in a way the batch did not cause, for example a book replaced on the device after the interruption. The safe choices are then `--restore-run` or a new migration. Resume does not merge.

## Durable per-file journal

`target-changes.json` moves to `schema_version: 2`, an additive change:

```json
{
  "schema_version": 2,
  "touched": ["books/a.epub"],
  "completed": ["books/a.epub"],
  "created_dirs": ["books"],
  "runtime": {"action": "replace", "state": "verified"}
}
```

- `touched` keeps its meaning and position: it is written and fsynced **before** each write. The KM-001 restore reader is unchanged.
- `completed` is appended after a file's post-write hash check. It is a progress hint for display and diagnostics only; resume still rehashes. FAT write-back caching means a verified read on the Mac does not prove the bytes reached flash.
- `runtime` is `null` for LIBRARY batches and for restore batches. For FULL/KOREADER migration batches it is `{"action": "replace", "state": ...}`, where `state` moves through `pending`, `removing`, `extracting`, `verified` and `identity-applied`. Each change is written before the step it names starts, except `verified` and `identity-applied`, which are written after their step succeeds. It sharpens the plan display. The rules in [runtime replacement](#runtime-replacement) stay authoritative, so batches written before this change resume the same way.
- Journal writes keep using `atomic_json` (temporary file, fsync, rename, directory fsync) under the run folder on the Mac, never on TARGET.

A resume batch writes its own `target-changes.json` that lists only its own writes. Restore combines the chain's journals (see below).

## Rollback and restore after resume

The rollback point for a resumed batch is always the **original pre-migration TARGET state** captured by the first batch in the chain.

- **Automatic rollback** on a caught failure during resume uses the original batch's verified runtime and library backups. The union of `touched` across the whole chain is the set of paths to restore or remove. The union of `created_dirs` is cleaned up in reverse order when empty. The result is `rolled-back` (exit 2), or `needs-recovery` (exit 3) if the reader disconnected or any step failed. In both cases the TARGET is protected the same way a migration is.
- **`--restore-run <resume-run-id>`** follows `resume-reference.json` to the original batch. It uses that batch's `target-snapshot.json`, and the union of touched paths across the chain, which must stay inside the original `planned_paths`.
- **`--restore-run <earlier-run-id>`** is refused when a later resume refers to it, and points the user at the newest link. That batch's own journal is incomplete once a resume has written to TARGET.
- Cleanup (KM-003) treats `resume-reference.json` like `source-reference.json`. The original batch keeps the rollback backups, so it stays protected while any dependent batch is unfinished or is the newest recovery point.

## Failure handling during resume

| Event | Result |
| --- | --- |
| Any check fails before final confirmation | `failed` or `cancelled`; no TARGET writes; earlier batch unchanged |
| Ordinary cancel at the final prompt | `cancelled` (exit 0) |
| Caught error after writes started | Automatic rollback to the original state, then `rolled-back` or `needs-recovery` |
| Kill, power loss or disconnect | `needs-recovery` at the next startup; the resume batch itself becomes resumable |

## Testing plan

All tests use disposable temporary fixtures and the existing synthetic Kobo layout. No physical reader is touched.

- Interrupt hooks that raise a test-only `BaseException` subclass skip the normal rollback, which leaves a realistic `running` batch for reconciliation. Cover these points: during runtime removal, during runtime extraction, after runtime verification and before identity, between library files, mid-file (truncated write) and during automatic rollback.
- Resume each case to `success`. Check the final TARGET against a migration that was never interrupted: every planned file, runtime manifest, identity mode and retained target-only files.
- Refusals: wrong reader, same reader as SOURCE, tampered source ZIP or member, tampered TARGET backup, drift on an untouched path, drift on a `keep-target` path, ineligible statuses, resuming a superseded link, cycles in the source chain.
- Restore after one and after two resumes returns the exact pre-migration TARGET. Restoring a superseded link is refused.
- Runtime changed after interruption: simulate a boot by editing `settings.reader.lua`/`history.lua` after `copying-library`, and confirm the plan reports it and replaces only after confirmation.
- `--dry-run` writes nothing to TARGET or to earlier batches.
- Legacy `target-changes.json` (schema 1) batches resume correctly.
- Both CLI entries, all three locales, cleanup protection, `--list-runs` display and `--verify-run` on resume batches.
- The macOS ditto fixture for runtime re-extraction.

Physical acceptance stays separate: a controlled interruption on a reader the owner has authorized for replacement, recorded in ACCEPTANCE.md.

## Implementation slices

1. **Journal v2 and runtime markers** (implemented in 1.1.0-dev.6). Migration and restore write schema 2 through the shared writer, with no behavior change. Runtime markers are written for migration batches only, since restore batches are not resumable. Restore reads schema 1 and 2 and refuses any other version before connecting a reader. Cleanup does not read the journal.
2. **Resume planner (read-only).** `--resume-run --dry-run`: eligibility, chain, source/backup verification, identity, runtime check, library classification, `resume-plan.json`.
3. **Resume writer.** Runtime action, library copy, chain-aware automatic rollback, final status.
4. **Chain-aware restore and cleanup.** `--restore-run` across resume chains, superseded-link refusal, `--list-runs` display, cleanup dependencies.
5. **Docs and locales.** USAGE, RECOVERY, TROUBLESHOOTING, three catalogs, ACCEPTANCE entry, version bump.
6. **Desktop (later, separately scoped).** A typed `resume_run` request from a catalog run ID, a Backups-page action and a request-scoped review sheet.

## Decisions

The owner accepted all four recommendations on 2026-11-03.

1. **Pre-resume runtime snapshot: yes, only when needed.** When the **Keep** check fails after `copying-library`, resume archives and verifies the current runtime before replacing it. No snapshot is made in any other case.
2. **Library drift: refuse.** Any drifted path refuses the resume and is named in the plan. There is no partial-plan mode.
3. **Failed restores: out of scope.** `restore-target` batches are not resumable. Retry with `--restore-run` against the original batch once chain-aware restore exists.
4. **Option name: `--resume-run`.**
