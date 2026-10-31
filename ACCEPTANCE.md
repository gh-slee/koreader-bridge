# Native desktop acceptance

Development **1.1.0-dev.2** adds connection-bound reader selection and model correction to the Mac app; historical CLI evidence below remains scoped to its source. See [Mac instructions](docs/MACOS.md).

- Automated: invalid protocol/version/operation, path/symlink refusal, unknown fields, sample confinement, real ditto synthetic transfer/restore, exact cleanup and packaging/privacy.
- Native: actual app plus bundled Python; save/reopen unknown preferences, preview/FULL/restore/saved-source, both library policies, typed synthetic deletion and final decline.
- Visual: inspect actual app-window captures in light/dark appearance, sidebar/table/forms, empty/error/loading states, focus/keyboard and minimum-window resizing. Capture only sample content; record any OS capture limitation.
- User/hardware: native-UI operator sign-off remains pending; automated development does not modify physical readers or delete real recovery data.
- Distribution: local arm64/macOS14+ app is ad-hoc signed, not notarized. Public app/DMG requires separate review/authorization.

## Connected readers and model correction (KM-026)

Ready for controlled user testing after automated verification; no new physical migration sign-off is implied.

- Connect two readers; select the actual source/target volumes and confirm native/USB model information. Confirm the same physical reader cannot fill both roles.
- Open Correct model, select a different known model or enter another Kobo model, cancel and confirm separately. Unknown/conflicting identification must require explicit physical-model confirmation; missing/mismatched USB identity must remain blocked.
- Reconnect or replace a selected reader and verify the old choice cannot start work. Retain verified backups when testing interruptions; do not disconnect a reader during writes as an acceptance experiment.
- Verify dual-reader preview, source capture, target backups, final confirmation and safe eject with an explicitly approved test target. Preview alone does not approve actual migration. Retest sequential mode and saved-source/restore routing.
- Check the correction sheet, disconnected state, warnings and menus with keyboard navigation, at minimum/wide window sizes and both appearances. Raw USB serials must not appear in discovery output or screenshots.

# Manual acceptance and sign-off

This source snapshot is **1.0.0**, continuing the published [1.0.0-rc.1](https://github.com/gh-slee/koreader-bridge/releases/tag/v1.0.0-rc.1). The implementation continues the [3.3.0-dev.6 experimental package](https://github.com/gh-slee/koreader-bridge/releases/tag/v3.3.0-dev.6), published on 2026-10-19. A KOREADER transfer from that package passed full manifest verification, TARGET identity preservation and safe eject; startup and opening an existing TARGET book were explicitly confirmed. FULL preview safely refused insufficient space before writes. These are scoped results, not ticket-wide or all-device sign-off. The release criteria below distinguish required artifact/publication review from broader acceptance follow-up. Earlier recovery evidence remains historical. Private device reports/backups stay local. See the [numbering policy](docs/MAINTAINING.md#versioning-and-first-stable-release).

Run commands from the repository root, or pass `--backup-dir` consistently if using a separate private output root. Stop any older migration worker first. Use disposable test books and retain all recovery snapshots until acceptance is complete.

## KOReader Bridge name and scope review (KM-019)

Status: Ready for human review. This is documentation work; no device connection or migration is needed.

- README identifies the project as KOReader Bridge and states that only Kobo → Kobo migration on macOS is currently implemented. General Kobo build compatibility and remaining first-stable acceptance limits are still explicit.
- Kindle and other device families are labelled future/unsupported. Non-Kobo tickets do not block the existing Kobo `1.0.0` milestone or count as implemented support.
- Existing CLI options, schemas, output paths, locks and published archive names remain compatible. Current source adds a canonical entry and updates three catalog presentation labels; the original entry remains available. Download links still point to existing assets, and pinned old-package commands retain the old name.
- The existing GitHub repository is now `gh-slee/koreader-bridge` (KM-020). Current badges, clone commands and release links use this canonical identity; historical CLI/archive names remain intact. Verify the link-update PR and CI after publication. Rename continuity checks are complete, but are not physical-device sign-off.

## Canonical and legacy CLI compatibility (KM-024)

Status: Ready for test; no new physical acceptance is implied. Use a disposable checkout and synthetic runs.

- From a different working directory, run version/help/list-locales/preview through both names. Program-name differences and help wrapping are expected; locale content, options and exit semantics should match.
- Verify both entries see the same script-relative synthetic runs and refuse a held project/device lock. Keep the same output and lock identities; never rename real backups or stale lock files as a test.
- Rehearse a synthetic FULL transfer through each entry and an exact TARGET restore through the opposite entry. Check SOURCE remains unchanged, original TARGET bytes return and captured archives remain intact.
- Verify an old-branded manifest and a historical package from its original Git ref. New packages must include both scripts/locales and pass all 11 extracted checks; old source retains its original prefix and six checks.
- Review all three updated banners/help/preview titles and new manifest display label. Schema keys, legacy metadata, published assets and copyright attribution remain intact. These checks do not complete the remaining physical/translation/stable gates.

## Validation record: 2026-10-22

Keep these evidence sets separate; a later documentation commit does not rerun or extend them.

| Evidence set | Source and method | Observed result |
| --- | --- | --- |
| Connected-device KOREADER | Published 3.3.0-dev.6 package; Kobo Libra 2 SOURCE → Kobo Clara 2E TARGET; both readers reported KOReader v2026.07.2. | Whole-runtime replacement, full manifest verification, TARGET identity preservation and safe eject passed. The operator confirmed KOReader startup and opening an existing TARGET book, then confirmed usual functions and progress persistence after reopening. This was actual hardware testing and remains valid within that scope; it does not certify all plugins or hardware combinations. |
| Physical FULL preview | The same build and device direction; read-only planning. | Insufficient TARGET capacity was refused before writes. This verifies a refusal, not a successful FULL migration. |
| Unit tests and CI | CLI baseline [f98d3a6437ae](https://github.com/gh-slee/koreader-bridge/commit/f98d3a6437ae4dd571c8b73184a5a5115456f693); its Git tree matches the feature commit that passed 194 tests and both entry self-tests. [Exact merged-main CI](https://github.com/gh-slee/koreader-bridge/actions/runs/39836316408) passed six macOS/Ubuntu Python 3.9/3.12/3.14 jobs. | Automated compatibility and safety evidence, including cross-entry transfer/restore. Ubuntu fixtures do not imply Linux device support. |
| Current local package | Source ZIP from exact f98d3a6437ae; guarded Git content, independently checked against that commit. | 37 files and 11 extracted offline checks passed, including canonical and legacy entries. This local candidate was not published. A final release commit needs its own package checks. |
| Current local rehearsal | The same f98d3a6437ae package; canonical entry with an injected shared engine, synthetic devices and scripted prompt answers. Real macOS ditto and migration/archive/restore code; mocked USB selection/eject and denied socket access. | 42 cases passed: 14 each in en, zh-Hant and zh-Hans. Four cross-locale comparisons matched category counts, bytes, paths and book/sidecar actions. No real device or existing recovery backup was accessed. |

The current 42-case rehearsal covers:

| Cases per locale | Checks |
| --- | --- |
| FULL preview and transfer (2) | Preview leaves fixture devices unchanged; transfer preserves SOURCE, paths, EPUB/CBZ and Unicode files, adjacent/central metadata, root font bytes, TARGET identity and unrelated library content. |
| Saved-source preview and transfer (2) | Only the synthetic TARGET is selected; dependencies and original archives are retained. |
| Exact-restore preview and restore (2) | Preview makes no changes; restored TARGET byte hashes match its original tree and pre-restore undo backups remain. |
| LIBRARY overwrite and keep-target (2) | Matching book/sidecar/font policy is applied; installed TARGET runtime and identity remain intact. |
| Final default-No (1) | An empty final response cancels without TARGET modification; captured recovery archives remain. |
| Busy and released locks (2) | A busy owner refuses before device selection; a released lock's persistent filename does not block a new owner. |
| Cleanup preview, wrong confirmation and explicit fixture deletion (3) | Preview/wrong text delete nothing; exact confirmation deletes only the selected eligible disposable batch and retains protected batches. |

Font fixtures check bytes, not font rendering. Synthetic fixtures and mocked transport cannot validate firmware, controls, plugins or reading behavior. These 42 cases are separate from the 194-test unit suite. The historical RC1 rehearsal also passed 42 cases at its own commit; it is not the source of the current-baseline result.

Human review has accepted the four Traditional Chinese behavior summaries for FULL, KOREADER, exact restore and cleanup, and the presented historical RC1 offline results. That review does not sign off all three 371-entry catalogs, operator-performed tests of the current rehearsal, complete feature tickets or stable publication. Raw reports, device identifiers, book names and recovery archives remain private.

## Remaining practical checks

- Usual functions and progress persistence after reopening have been confirmed on the previously tested KOREADER TARGET. Continue collecting evidence for additional controls, settings, plugins and model/build combinations; record only what was actually observed.
- For physical FULL/LIBRARY acceptance, identify a capacity-sufficient, controlled TARGET whose affected data may be replaced. First inspect roles, build compatibility, capacity and planned differences without writes. Agree on the exact write/restore scope before migration.
- Check actual books, annotations/progress and relevant fonts on the device after copying, alongside file/identity verification and safe eject. KOREADER alone does not copy external library sidecars.
- Retain verified recovery and undo backups. Use disposable fixtures for induced failures and cleanup deletion; do not erase real library data merely to force a capacity pass.
- Continue remaining language/recovery/maintenance review as explicit follow-up. Before publication, validate the final release commit/package and review the disclosed limitations. A version label does not convert incomplete acceptance into a pass.

## First stable release gates

The `1.0.0` release baseline retains FULL, KOREADER, LIBRARY and AUDIT with the existing safety and compatibility contract. Publication review may accept the disclosed validation limits below; complete physical testing of every mode and complete manual review are follow-up work, not claims implied by the stable version. The final source/asset approval must explicitly cover this scope. The earlier comprehensive acceptance checklist remains useful; incomplete items stay open rather than being marked passed.

| Area | Evidence and remaining limits | Release treatment |
| --- | --- | --- |
| FULL and LIBRARY | Current-baseline synthetic transfers passed. FULL preview refused insufficient space; successful physical FULL/LIBRARY copying with adequate capacity remains pending. | Retained modes; incomplete hardware validation must be prominent in README and release notes. Track further physical acceptance. |
| KOREADER | Libra 2 → Clara 2E transfer, manifest hashes, TARGET identity and safe eject passed on 3.3.0-dev.6. Startup, book opening, usual use and progress persistence confirmed. | Scoped hardware evidence; do not claim every build/model/plugin or the final 1.0 package was physically tested. |
| Saved-source and restoration | Synthetic preview/transfer/exact-restore and historical scoped recovery evidence exist. Broader practical review remains incomplete. | Preserve integrity/identity/undo protections; track remaining practical acceptance. |
| Locks, cancellation and cleanup | Automated busy/released-lock, default-No and explicit disposable cleanup cases passed; historical RC1 results reviewed. Wider manual sign-off remains incomplete. | Retain safeguards and follow-up acceptance; no real backup deletion is needed for release. |
| Languages | Three 371-entry catalogs have automated/editorial checks. Four Traditional Chinese behavior summaries reviewed; complete three-catalog human review remains incomplete. | Disclose the review boundary and retain wording follow-up. |
| Candidate and distribution | Final exact commit must pass tests, locales, both entries, privacy/history, docs and independent package checks. Historical evidence alone does not certify a new artifact. | Required before publication; remote CI must pass. Downloaded published bytes must match the reviewed assets. |
| Public contract and release | Support/compatibility limits, changelog, exact source commit, public metadata and final asset names/sizes/hashes reviewed. | Required: source-push approval, owner PR merge, and exact-scope release approval. Do not infer approval or completed tests from a version label. |

Never unplug a real reader or corrupt/delete its recovery data to induce a failure. Use synthetic disposable data for rollback/fault/deletion scenarios. A FULL capacity refusal is safety evidence, not FULL migration acceptance. Do not require all Kobo models/plugins to be tested: state the actual supported/tested scope and remaining limits precisely. Retain real backups until their recovery value is no longer needed and separate deletion is authorized.

## Offline checks (no Kobo connected)

```bash
python3 koreader-bridge.py --version
python3 -m unittest discover -s tests -p 'test_*.py'
python3 koreader-bridge.py --self-test
python3 koreader-bridge.py --list-runs
python3 koreader-bridge.py --cleanup
python3 scripts/check_publication.py --worktree
```

Confirm that these work with AI applications closed and without AI services/credentials. Cleanup alone must list eligibility without deleting anything. Legacy/non-success runs must remain protected.

## Statistics handles and safe eject (3.3.0-dev.2)

Current scoped evidence: connected-device KOREADER transfer and verified target recovery completed, and basic KOReader operation was confirmed. This does not sign off all controls/plugins, other modes or the remaining feature checklists.

- With a statistics database present, run KOREADER dry-run and confirm both SOURCE and TARGET safely eject without the migration process retaining the SQLite file.
- No device files or ZIPs should be created by the preview. Keep the run audited only after the entire preview succeeds.
- Success/error connection-closure regressions use synthetic databases; never corrupt a real device database for this test. A preview result does not sign off migration writes or hardware settings.

## KM-011: locks and durable status

- Start a preview and attempt another run against the same output root. The second worker must report busy and refuse.
- Complete a preview; inspect `run.json` for `audited`. Decline final confirmation; expect a friendly message, status `cancelled` and no target changes.
- A stale lock filename after process exit must not block a new worker. Do not delete a live lock to test this.
- Interruption and failure records must not be marked successful. Test destructive fault scenarios only on synthetic fixtures.

## KM-005: difference report

Prepare a disposable library with one new book, one different matching-path book, one identical book and one TARGET-only book, with matching `.sdr` sidecars.

```bash
python3 koreader-bridge.py --mode full --dry-run
python3 koreader-bridge.py --mode library --books --no-fonts --conflict keep-target --dry-run
```

Check `difference.txt`/JSON categories and book/sidecar groups. Preview must not modify either Kobo or create ZIPs. TARGET-only books are retained. Keep-target must protect the different book's reading metadata.

## Generic SOURCE/TARGET workflow

- Confirm physical model labels, even when hints agree. A copied/stale log must not be reported as hardware verification.
- Renamed volumes containing `.kobo/` should be found; multiple mounted readers must be refused.
- Two distinct readers of the same model should be allowed; the same fingerprint in both roles must be refused.
- FULL/KOREADER require explicit SOURCE runtime compatibility confirmation. A missing identity file must refuse migration.
- After a controlled FULL transfer, inspect books, progress, annotations, fonts, plugins and TARGET identity. TARGET-only books outside KOReader must remain.
- KOREADER must change only the whole `.adds/koreader` tree; external books/fonts must remain untouched.

## KM-001: saved source and exact target restore

Use a successfully captured disposable test batch. Replace RUN_ID with its actual ID.

```bash
python3 koreader-bridge.py --from-run RUN_ID --dry-run
python3 koreader-bridge.py --restore-run RUN_ID --dry-run
```

Saved-source preview must need only TARGET and record a dependency on the source batch. Exact restore must require the original target and display the planned restorations/removals. A different fingerprint or missing/corrupt archive/manifest must refuse writes. Do not corrupt your only real recovery copy to test this; use fixture copies.

After reviewing the restore preview, a controlled restore should return the affected test paths/runtime to their pre-migration state. It creates pre-restore undo backups. Later changes to affected paths can be overwritten, so use disposable data.

## KM-003: backup management

- Catalog lists status and sizes. Cleanup previews protection reasons and reclaimable eligible batches.
- Recent successes, source dependencies, latest per-target recovery points and failed/interrupted/legacy batches remain protected.
- `--cleanup --delete-run RUN_ID --dry-run` must not delete.
- Wrong typed confirmation must not delete.
- Actual whole-batch deletion requires explicit eligible IDs and exact typed confirmation. Test this using disposable generated fixtures only; it is not required to delete real backups for sign-off.

## Publication review

- README explains all current modes/options and limitations using generic paths.
- Public Git content has no actual books, backups, reports, device configurations, personal paths or credentials.
- Review staged diff and public author identity, then run the index/history publication guard.
- Feature changes use PRs. Approval and passing CI precede merge; no automatic merge.

## Sign-off record

Record version, tested macOS/Python versions, hardware model pair, modes tested, ticket IDs, result and remaining problems. Keep serial numbers, book names and private reports out of public records. Leave each ticket Ready for test until explicit human acceptance is recorded.


## KM-013: locale foundation (3.3.0-dev.1)

Status: Ready for human test. This section describes the original locale foundation; completed owned-runtime localization is included in 3.3.0-dev.6 and the candidate source. No Kobo is needed for these foundation checks. Keep locales/ beside the script.

```bash
python3 koreader-bridge.py --list-locales
python3 koreader-bridge.py --locale en --preview-ui
python3 koreader-bridge.py --locale zh-Hant --preview-ui
python3 koreader-bridge.py --locale zh-Hans --help
python3 scripts/check_locales.py
```

- Check all three options, translation wording, FULL/KOREADER distinctions, default-No examples and exact DELETE RUN_ID text. Previews must not request an answer, connect devices, inspect run data or create runs/logs/backups.
- Use a known terminal locale alias or KOBO_MIGRATE_LOCALE to confirm preference selection. Explicit --locale must win. Bare zh must not silently guess a Chinese script.
- An unsupported explicit locale must fail before device activity. Do not damage production catalogs to test fallback; malformed/missing assets are covered by synthetic automated tests.
- The published 3.3.0-dev.2 messages remain English. Development 3.3.0-dev.3 partially localizes runtime presentation; tool-owned log text remains English. Do not sign off all of KM-014/KM-015 based on a preview.
- Automated evidence: 114 fixture tests, including language-independent FULL outcomes and the actual macOS ditto fixture; this is not hardware acceptance. Record explicit human feedback before marking KM-013 Done.

## KM-018: local source package preparation (no Kobo)

Status: Ready for human test. The helper is included in the published 3.3.0-dev.6 ZIP and the current candidate source; it was absent from the older 3.3.0-dev.2 ZIP. Run from a clone containing the helper after committing the reviewed changes:

```bash
python3 scripts/prepare_release.py prepare --ref HEAD
```

- The helper must create a fresh `.local/releases/VERSION-COMMIT/` with a complete source ZIP, `SHA256SUMS` and local-only `PREPARATION.json`. It must not create a tag, access a Kobo or contact GitHub.
- Use the printed directory and exact source commit with `python3 scripts/prepare_release.py verify DIRECTORY --ref COMMIT`. Verification must recheck actual ZIP bytes against that commit, not trust the preparation record or checksum alone.
- Offline commands and local documentation file links must pass from a temporary extraction. Required locale assets must be included, even for English.
- Repeating preparation into the same destination must refuse without overwriting anything. Different output parents can hold separate copies.
- Synthetic regressions cover private/untracked and modified files, bad refs, missing locales, symlinks, unsafe/duplicate ZIP members, tampering, failed extracted commands and broken links. Do not tamper with a real recovery archive for testing.
- This is source-package validation, not a new full unit-test run, privacy guarantee, hardware certification or publication approval. See [maintainer instructions](docs/MAINTAINING.md#local-package-preparation-and-verification).

## KM-014 slice 1: shared routing (3.3.0-dev.3)

Historical slice status: this describes 3.3.0-dev.3 at implementation time. The published 3.3.0-dev.6 ZIP and current candidate include completed owned-runtime extraction; human wording review remains pending. Use the combined acceptance and first-stable gates for current status.

- In a disposable project root, use --list-runs/--cleanup in en, zh-Hant and zh-Hans. Headings/instructions should match the selected locale; run IDs/status tokens and protection reasons retain their technical/English values. Preview creates no deletion.
- Review translated SOURCE/TARGET confirmation wording and [y/N]/[Y/n] defaults. Only y/yes/n/no are accepted; numeric choices and exact DELETE RUN_ID remain unchanged. Use synthetic disposable batches for any cleanup deletion test.
- In controlled migration tests, inspect console versus the saved log: integrated owned messages should be localized on screen and occur once in English in the log. Raw diagnostics, user/device data and unconverted messages are preserved; Unicode filenames can appear in both. Responses typed at prompts must not be recorded.
- Check localized difference.txt against stable difference.json category/path/action data. ui_locale may be present in modern records; older records without it must remain usable.
- Rendering/fallback, ascii-console safety, all-mode equivalence, saved-source/restore, final default-No, rollback after writes and context/exit-state regressions use temporary fixtures. Do not induce failures on real readers or corrupt a real recovery backup for this test.
- Record manual feedback separately. For slice 1, menu/device extraction was still pending. Slice 2 adds menus/basic inspection; detailed metadata/plugin diagnostics/errors and remaining workflow messages still need extraction; do not label this full interface translation or full hardware acceptance.

## KM-014 slice 2: menus and inspection (3.3.0-dev.4)

Historical slice status for 3.3.0-dev.4: extraction was still in progress at this point. The later 3.3.0-dev.6 package and candidate source include completed extraction; human wording/hardware acceptance remains pending. Use only disposable data for induced failures; no real Kobo is required for the synthetic tests.

- Review all three languages for mode/identity/conflict menus. Numeric choices/defaults must match: FULL default; preserve identity when available, new otherwise; unavailable preserve must retry; keep-target remains unsupported for FULL/KOREADER.
- Inspect a synthetic device with known and unknown values. Labels/yes/no/unknown should localize; model/version/path/serial-hint/size/count values must remain intact. English logs must not contain translated owned labels or duplicate entries.
- Confirm there is no AI Assistant configuration indicator in any console locale or the English log, whether that plugin configuration exists or not. Plugin files must still be included in FULL/KOREADER runtime archives and integrity verification; no plugin is executed. Older saved metadata remains readable.
- Review physical-model hints and mismatch warnings. A log hint never proves the hardware model; the following confirmation still defaults to No.
- Capacity reports should show the same values in all languages. Synthetic tests cover backup/target thresholds one byte below, exactly at and one byte above the requirement; replaced-runtime space is still counted. LIBRARY low space must refuse before TARGET backup/writes.
- Detailed errors/metadata/plugin diagnostics and other workflow notices are not fully translated. Existing release assets and older saved runs must remain usable; this slice is not a new public release or full translation/hardware sign-off.

## KM-014 slice 3: workflow and recovery (3.3.0-dev.5)

Historical slice status for 3.3.0-dev.5: extraction was still in progress at this point. The later 3.3.0-dev.6 package and candidate source include completed extraction. Use synthetic/disposable data for failure paths. Successful CI/merge is not human wording or hardware sign-off.

- Review en/zh-Hant/zh-Hans migration, saved-source and exact-target-restore plans, final scope, backup/verification/eject/identity notices and archive heartbeats. Original paths/numbers/category tokens and confirmation defaults must remain intact.
- Compare translated console output with the English log. Selected refusal/cancellation reasons should translate; exception string/JSON values stay English. Raw diagnostic labels should preserve the complete original detail, including Unicode paths, without duplicate tee output.
- Run the synthetic recovery tests: refusal before device access, write failure with successful rollback (exit 2), changed-device rollback refusal and secondary rollback failure (exit 3), and exact-target-restore failure with undo or identity guard. Do not induce these failures on a real reader.
- In temporary fixtures, compare status/exit codes and affected paths across all three locales. SOURCE remains unchanged; changed-device guards allow no further writes; retained snapshots must stay available.
- Pre-run interruption should print one localized message, retain exit 130 and clear the UI context. An interrupt before locale parsing can still use English.
- Low-level errors, detailed scan/comparison output, maintenance reasons/errors and startup/argparse messages are still pending extraction. Record manual wording feedback separately; this slice does not complete full translation or hardware acceptance.

## Combined localization acceptance (3.3.0-dev.6)

Status: KM-014/KM-015/KM-016 Ready for test. Complete the implementation and run automated checks first; combine human language and functional acceptance in one final round. Prior merges/CI and the editorial pass do not sign off these tickets.

- Review all 371 entries in each en/zh-Hant/zh-Hans catalog, with special attention to negation, default-No, backup-before-overwrite, retained files, snapshot restore versus rollback/manual recovery and exact DELETE RUN_ID. Keep y/yes/n/no and numeric choices unchanged.
- Exercise owned errors, per-file progress, cleanup protection reasons, warnings and custom CLI refusals. Compare console and English log, including preserved Unicode paths. Ensure no duplicate output or typed-answer logging.
- Confirm English JSON/exception/warning/reason/lock-label data and actual bool values stay equivalent across languages. A raw warning loaded from older JSON must remain raw without guessing a translation ID.
- Validate final default-No, same/changed-device guards, malformed archives, insufficient space, lock refusal and successful/blocked/failed rollback using disposable fixtures. Do not induce failures on real readers.
- Expect safe English bootstrap diagnostics when catalogs cannot load, original Python-generated argparse/traceback messages, technical tokens and raw external diagnostics. These are deliberate boundaries, not unreviewed translation gaps.
- Finish the existing mode, difference, saved-source, exact-restore, cleanup-preview and package checklists using the final reviewed build. Record human results together and retain recovery backups until sign-off.

## Native review and language acceptance (1.1.0-dev.3)

KM-027/KM-028 are Ready for test. Use isolated sample readers first; physical-reader operations need their own explicit scope. Existing hardware records do not sign off this changed interface.

- In Settings, change Language among English, Traditional Chinese and Simplified Chinese. Check all four pages, empty/error/loading states, model correction and review sheets. Close/reopen and verify the selected language persists. Paths/model names and raw diagnostics remain original; prior activity is not retranslated.
- With distinct connected sample readers, Preview changes should start directly. Start migration should show roles/scope, an unchecked FULL/KOREADER compatibility acknowledgement and default keep-target identity (new when missing). Back up and prepare must remain unavailable until required acknowledgements are supplied.
- After required backups finish, check Ready to migrate: roles/scope are visible, the default Return action cancels and Migrate now is explicit. Cancel must leave TARGET unchanged and retain the recovery batch. A fresh operation must require a fresh review.
- Unknown/conflicting/manual models still require attention. Reconnecting invalidates selection; identity changes after final confirmation must refuse writes. Confirm sequential mode/CLI retain their prompts, restore retains its own review, and cleanup still needs the exact DELETE text.
- Review Chinese safety wording and compact-window wrapping with a human. Automated fixtures, screenshots, source publication and prior hardware success do not constitute this acceptance.
