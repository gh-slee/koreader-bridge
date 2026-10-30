# Changelog

## 1.1.0-dev.2 — connected reader identities

- Identify connected Kobo models from bounded native version metadata and cross-check USB storage ancestry, product IDs and serials. Use session-scoped opaque connection tokens; expose no raw serials or fingerprints through discovery.
- Select actual source/target readers with both connected. Revalidate the chosen connection before core write/restore/eject boundaries; reject the same reader, missing USB identity and replaced connections. Preserve sequential mode and existing CLI behavior.
- Add a physical-model correction sheet and default-No backend confirmation for unknown/conflicting/overridden models. Corrections cannot override identity failures and expire with the connection selection.
- Exercise dual-reader preview, transfer, saved-source reuse, exact restoration and write-boundary refusal with synthetic USB graphs. Native UI/device migration acceptance remains pending.

## 1.1.0-dev.1 — native desktop development

- Detect connected Kobo model hints in the idle desktop UI, populate source/target dropdowns, retain choices across reconnects and update labels after core role confirmation. Discovery is read-only and pauses during migration.

- Standardize PR summaries, module breakdowns and evidence categories; validate reviewed Markdown and explicitly replace existing PR descriptions through the publication helper.

- Center backup/cleanup empty states and shared content/footer columns; reflow selected actions and long summaries. Extend actual-app captures to all pages, three window sizes and both appearances. Keep cleanup totals current after sample creation and operations, and pass the chosen retention count consistently to preview and deletion.

- Add SwiftUI/AppKit Migration, Backups, Cleanup and Settings over the shared migration engine, with bounded request-bound JSON prompts/progress.
- Bundle a pinned relocatable CPython runtime; add isolated fresh app builds, ad-hoc signing and actual native synthetic workflow/capture checks. No shell Python, LLM or launch-time network dependency.
- Preserve CLI schemas/safety, private recovery data and unknown preference fields. Add explicit desktop/synthetic-capture publication inputs.
- Align app/CLI docs and distribution status. v1.0.0 remains a historical CLI release; native hardware/user acceptance and notarized distribution remain pending.

## 1.0.0 — stable compatibility baseline

- Establish the 1.x compatibility baseline for documented CLI flags/modes, exit meanings and versioned run/snapshot/manifest schemas. Retain FULL, KOREADER, LIBRARY, AUDIT, dry-run, the canonical and compatible legacy entries, offline operation and existing migration safeguards.
- Update version metadata and current package instructions to koreader-bridge-1.0.0.zip; keep historical tags, assets and supported older backups unchanged. No migration algorithm, confirmation default, identity, path, lock, capacity or rollback policy changes.
- Record scoped Libra 2 → Clara 2E KOREADER hardware evidence and confirmed ordinary use/progress persistence. Keep successful FULL/LIBRARY physical copying and remaining complete language/maintenance review explicitly incomplete. Stable publication accepts a documented compatibility scope, not universal hardware/plugin certification.
- Separate final exact-commit tests/package/privacy/CI and publication approval from broader acceptance follow-up. Publication facts and official downloads belong to the release list; this source heading does not claim an uploaded release exists.

## 1.0.0-rc.2 — source candidate

- Reconcile acceptance documentation with scoped Libra 2 → Clara 2E KOREADER hardware success and the f98d3a6437ae baseline's 194-test evidence, six main CI jobs, 37-file/11-check local package and 42 three-locale synthetic rehearsals. Record partial wording/result review while retaining physical FULL/LIBRARY, practical controls/progress, complete language and final publication gates. This documentation follow-up does not change the runtime or version.

- Adopt KOReader Bridge as the public project name and explicitly limit current device support to Kobo → Kobo on macOS. Track non-Kobo feasibility, portable migration policy and a future adapter separately from the first-stable Kobo milestone.
- Rename the existing GitHub repository to `gh-slee/koreader-bridge` and update current document links, CI badges and clone commands. Verify the same repository identity, refs, issues/PRs and published release/asset bytes. CLI commands, version, backup schemas and published archives remain unchanged by the rebrand.

- Add the canonical `koreader-bridge.py` CLI alongside the unchanged legacy filename/shared engine. Share startup/exit handling, run roots and lock identities; update localized branding and new manifest tool labels while accepting old labels without rewriting records.
- Align CI, validators, source packaging, docs and agent guidance. New packages use the `koreader-bridge-` prefix and exercise both entries; historical refs retain their original prefix and legacy smoke checks. Preserve prior copyright attribution while noting the new project name.
- Correct release status throughout the source distribution: RC1 was published on 2026-10-21. Pin working download/verification commands to the published RC1 assets and distinguish a source snapshot from an uploaded release.
- Record exact RC1 CI/package/download verification without treating it as evidence for a later commit or as human/hardware sign-off. Keep all first-stable acceptance gates open where still pending.
- Advance VERSION for a distinct candidate package. Migration behavior, schemas, locale catalogs, confirmation defaults and safety checks are unchanged. Existing RC1 and 3.x tags/assets remain intact; no replacement upload is intended.

## 1.0.0-rc.1 — 2026-10-21 — published release candidate

- Begin the first stable release sequence at 1.0.0-rc.1, continuing the 3.3.0-dev.6 implementation. This is a one-time numbering reset; 1.x sorts below historical 3.x versions. Existing historical tags/assets remain unchanged. RC1 is a published pre-release, not GitHub Latest.
- Keep CLI behavior, schema versions, offline operation, backups, identity and migration safeguards unchanged. Add a synthetic cross-version saved-source/restore regression using higher-numbered 3.x metadata.
- Reconcile current package links and localization status, document version/backup compatibility and consolidate explicit first-stable acceptance gates. Record only generic scoped device evidence; private reports and real backups remain local.
- Local candidate validation: 185 synthetic tests (including the cross-version regression and actual macOS ditto fixture), self-test, 3x371 locale checks, index/worktree/history privacy, 84 documentation file links, 30 anchors and 30 shell examples passed. All six exact merged-main CI jobs passed for `aaedb78f2b2233ffe91ad42ae8ea9fb312860052`. The 35-file package matched that commit and both published assets were downloaded and verified. Stable acceptance remains pending.
- Stable publication still requires remaining acceptance, exact-candidate checks and separate approval. RC1 publication does not authorize another device operation or release.

## 3.3.0-dev.6 — 2026-10-19 — published experimental pre-release

- Catalog all remaining owned runtime errors, per-file status/progress, maintenance/cleanup reasons, scan/plugin warnings, self-test notices and custom argument-combination checks. Add 123 explicit message contracts (371 entries per locale).
- Preserve English exception/reason/warning/lock-label strings and machine records while displaying structured translations. Keep grouped recovery details structured; display-only booleans localize without changing English logs or stored bool values.
- Complete an independent editorial terminology pass for the three catalogs. Human wording and end-to-end acceptance are deferred to the combined final round; bootstrap/framework/external diagnostics retain original text by design.
- Add source-coverage and temporary-fixture regressions for protection rules, data equivalence, warnings, per-file comparison, unsafe archives, CLI refusals, command/recovery details and lock refusal. Combined local validation passed 184 tests (nine new), self-test, 3x371 locales and privacy/whitespace checks, plus 73 doc file links and 30 shell examples. All six exact merged-main jobs subsequently passed. The published package later passed a connected-device KOREADER transfer with full manifest verification, TARGET identity preservation and safe eject; startup and opening an existing book were confirmed. FULL preview refused insufficient space before writes. Broader human/hardware acceptance remains pending; private device data and backups are excluded from public records.
- Published as an experimental pre-release after approval, with a source ZIP and SHA256SUMS only. No runtime dependency, migration mode or confirmation/write/rollback safety decision changed.

## 3.3.0-dev.5 — internal snapshot included in 3.3.0-dev.6 — KM-014 workflow and recovery slice 3

- Translate core migration/saved-source/target-restore plans, archive/backup/verification/eject/identity notices, recovery guidance, five cancellation reasons and 36 selected refusals through the console/English-log adapter.
- Add 117 static entries/explicit placeholder contracts per locale (248 total), including archive subprocess heartbeats. Preserve exception string args in English; render structured IDs only at presentation and label unconverted integrated diagnostic details without changing the original log text.
- Report pre-run interruption once while retaining exit 130. Preserve migration decisions, identity guards, write/rollback branches, capacity/integrity checks, machine schemas and confirmation defaults.
- Add nine synthetic error/recovery regressions covering successful/blocked/failed rollback, exact-restore undo/guard, raw Unicode diagnostics, preserved English args and refusal before device access. Local validation passed 175 tests (nine new), self-test, 3x248 locale validation and publication worktree/history/whitespace checks. Subsequently merged as PR #8 with all 12 push/PR and six merged-main jobs passed. Human wording/hardware acceptance remains pending.
- Low-level/maintenance errors and detailed scanner/comparison output still need extraction. This is not full translation, hardware acceptance or a new published release.

## 3.3.0-dev.4 — internal snapshot included in 3.3.0-dev.6 — KM-014 menus and inspection slice 2

- Translate mode/identity/conflict menus, physical-model hints/confirmation, inspection fields and backup/target capacity reports through the shared console/English-log adapter.
- Add a LIBRARY capacity summary while retaining its existing free-space formula and refusal before TARGET backup/writes. Preserve numeric choices/defaults, unavailable identity retry, FULL/KOREADER conflict restrictions and physical-model confirmation.
- Add 37 static messages per locale (131 total); retain model/version/path/serial-hint values and stable machine tokens. Localize display-only yes/no/unknown labels.
- Remove the plugin-specific AI Assistant configuration indicator from console output and diagnostic logs; retain legacy snapshot metadata, generic plugin audits and whole-runtime file verification.
- Add synthetic multilingual menu/default/inspection/model and capacity-boundary regressions. Local validation passed 166 tests (12 new), self-test, 3x131 locale and privacy checks. Subsequently merged as PR #7 with all 12 push/PR and six merged-main CI jobs passed. Human review remains pending. Detailed errors/metadata/plugin/remaining workflow text is not fully translated; no new public release or hardware acceptance.


## 3.3.0-dev.3 — internal snapshot included in 3.3.0-dev.6 — KM-014 shared output routing slice 1

- Introduce explicit message IDs/parameter contracts and scoped console/English-log rendering. Integrated messages bypass the legacy tee, preserve output channels, flush progress, support non-UTF-8 consoles and never log typed answers.
- Integrate shared confirmations, progress, run status, catalog/cleanup headings and difference labels; retain English string compatibility for existing helpers. Add 58 static messages per locale (94 total); full workflow extraction and human wording review remain pending.
- Add optional ui_locale to run.json/difference.json; localize difference.txt while retaining stable category/action tokens and original paths. Old records remain readable.
- Add synthetic routing, prompt/default/token, all-mode/saved-source/restore equivalence, cancellation, interrupt and rollback tests across en/zh-Hant/zh-Hans. Device semantics and offline standalone requirements remain unchanged.
- Local validation: 154 tests (16 new shared-output/workflow cases), self-test, 3x94 locale and publication checks passed. Hosted CI and human translation/hardware acceptance remain pending.
- This is a local development slice, not a new published release or completion of KM-014/KM-015/manual hardware acceptance.

## Maintainer tooling and documentation — included in 3.3.0-dev.6

- Add offline `scripts/prepare_release.py` prepare/verify commands for explicit Git commits: guarded committed files only, complete runtime/locale assets, ZIP-to-Git byte verification, temporary-extraction smoke checks and local documentation links, SHA256SUMS and local preparation records.
- Add synthetic source-package safety regressions and CI package preparation. Existing output directories are not overwritten; the helper has no upload, tag or device-operation commands.
- Reconcile published pre-release, hosted CI and scoped hardware evidence across the README, tracker and guides. This does not complete pending manual acceptance, change migration behavior or replace the already published asset.
- Maintainer follow-up validation: 138 local tests (15 package regressions), self-test, locale and publication checks passed; merged PR #5 main CI passed all six jobs.

## 3.3.0-dev.2 — 2026-10-18 — published experimental pre-release

- Explicitly close read-only statistics connections after diagnostics, including error exits. SQLite transaction context management alone does not close a connection and can leave the migration process blocking safe eject.
- Tolerate already-removed descendants during KOReader tree replacement, rollback and restore on older supported Python versions. Keep missing-root, permission and symlink errors visible. This handles disappearing macOS AppleDouble entries without suppressing other deletion errors.
- Add synthetic removal-race, permission, missing-root and symlink regressions.
- Add retained-connection regressions for successful and invalid-database diagnostics, verifying deterministic closure and unchanged fixture bytes.
- Validation: 123 local tests, self-test, locale validation and publication checks passed. Connected-device source capture, verified target recovery and saved-source KOREADER transfer completed with full manifest verification; basic KOReader operation was subsequently confirmed. The exact release commit passed all six [main CI jobs](https://github.com/gh-slee/koreader-bridge/actions/runs/39155468946). The [experimental pre-release](https://github.com/gh-slee/koreader-bridge/releases/tag/v3.3.0-dev.2) is published; broader hardware acceptance and FULL book migration remain pending.

## Publication guard follow-up — 2026-10-15 — subsequently merged

- Diagnosed PR-only CI rejection of GitHub's public merge committer address. Approved branch push CI passed all six macOS/Linux and Python 3.9/3.12/3.14 jobs.
- Permit exact `noreply@github.com` only as a merge committer; user noreply authors, all file/content/history scans and personal-email rejection remain required.
- Added real Git-history fixtures covering seven allowed/rejected identity cases. All 115 tests, self-test and locale validation passed locally. The guard follow-up was subsequently merged into main; physical acceptance remains separate from automated checks and PR merge.

## 3.3.0-dev.1 — 2026-10-15 — KM-013 foundation; ready for user testing

- Added offline JSON locale registry/catalogs for en, zh-Hant and zh-Hans, explicit/environment selection, script-aware aliases and safe English fallback.
- Added localized help descriptions, --list-locales and a read-only --preview-ui sample. Actual migration/maintenance UI and diagnostic logs remain English; full localization is pending KM-014/KM-015.
- Added bounded UTF-8/schema/duplicate-key/placeholder/control-character/plural validation, exact locale-file publication allowlist, validator CLI and CI/publish-helper checks.
- 114 tests passed locally, including existing archive/migration regressions and equivalent temporary FULL outcomes in all three locale choices. Standalone self-test passed. No real Kobo was accessed or migrated, no real backups were deleted, and no physical-device acceptance was inferred. This batch was subsequently published for review as PR #1 after explicit approval.

## 3.2.0 — 2026-10-14 — Public preparation; physical acceptance pending

- Replaced fixed model-pair direction with operator-confirmed SOURCE/TARGET roles; log model labels are hints, not hardware verification.
- Discover renamed Kobo volumes by safe .kobo directory markers; require device fingerprints and explicit runtime compatibility confirmation.
- Saved-source/target-restore workflows accept confirmed model labels without inferring an opposite model. Existing archive names/snapshots remain usable.
- Added detailed generic documentation, MIT license, privacy ignore/allowlist/index/history checks, pre-push guard, fixture CI and standalone feature-branch PR helper.
- FULL, KOREADER, LIBRARY, AUDIT and conservative cleanup/rollback behavior retained.

## 3.1.0 — 2026-10-12 — Ready for user testing

- KM-011: OS-backed project/device locks, atomic run.json status and interruption reconciliation.
- KM-005: detailed text/JSON migration differences, target-only inventory in the same supported scope and book/sidecar grouping.
- KM-001: verified saved source reuse, reference/dependency tracking and distinct exact TARGET snapshot restoration for v3.1+ runs; legacy source imports are conservative.
- KM-003: run catalog, retention/dependency/recovery protections, read-only cleanup preview and explicit typed batch deletion.
- Added tests for cross-process locks, archive integrity, source reuse, exact restore and restore rollback, cleanup protection and actual macOS ditto fixture workflow.
- Existing FULL, KOREADER, LIBRARY and AUDIT semantics retained. Physical Kobo validation and human sign-off are pending.

## 3.0.4 — Existing baseline

Normal cancellation messaging, file/byte progress, stable project-relative script and per-run output folders; 45 portable regression tests passed before this release.
