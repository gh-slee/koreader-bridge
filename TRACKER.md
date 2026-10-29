# KOReader Bridge development tracker

Last reconciled: **2026-10-29**. Source snapshot version: **1.1.0-dev.1** (native desktop development; the published 1.0.0 remains a CLI release). [1.0.0-rc.1](https://github.com/gh-slee/koreader-bridge/releases/tag/v1.0.0-rc.1) was published on 2026-10-21 as a pre-release, not Latest. Check the release list for later published assets. Broader physical/manual acceptance remains pending. See [first-stable release gates](ACCEPTANCE.md#first-stable-release-gates) and the [version policy](docs/MAINTAINING.md#versioning-and-first-stable-release).

Status vocabulary: `Queued`, `In progress`, `Ready for test`, `Blocked`, `Done`, `Deferred`. KM-011, KM-005, KM-001 and KM-003 are implemented and ready for user testing; ticket-wide human sign-off remains pending despite scoped KOREADER success. Entries represent planned work, not permission to operate physical devices or delete backups.

## Project identity and supported scope

Public project name: **KOReader Bridge**, continuing the existing Kobo migration tool. The current device scope is **Kobo → Kobo on macOS with Python 3.9+**. Kindle and other KOReader device families are future work, not supported migration targets. Linux CI remains fixture validation only.

Use `koreader-bridge.py` as the canonical entry while retaining `kobo-koreader-migrate.py` as the shared engine and compatible CLI. Preserve existing CLI tokens, schemas, run paths, lock identities, backup compatibility and published release assets. The canonical repository is `gh-slee/koreader-bridge`, renamed from `gh-slee/kobo-koreader-migrate`. Repository identity, Git refs, issues/PRs and all three published releases were preserved; six downloaded asset hashes matched the pre-rename baseline. Local origin and GitHub CLI default now use the canonical repository. Current-document link review and publication remain tracked in KM-020.

## Mandatory runtime requirement (all tickets)

Every current and future feature must be implemented as ordinary executable code that users can run directly from Terminal without any LLM. Do not depend on AI inference APIs, local/remote model servers, model downloads, an agent framework, or an active Codex/ChatGPT session. LLMs may assist authoring and maintenance only.

Acceptance for every ticket must include standalone CLI operation without AI API keys/services, explicit algorithmic rules, and documented commands/ordinary user confirmations where needed. Preserve the offline core migration/maintenance workflow. Copying existing KOReader AI-plugin files does not authorize executing them.

## Native desktop milestone: 1.1

KM-025 implements a development SwiftUI app with Migration, Backups, Cleanup and Settings, bounded request/prompt JSON over the existing core, private persistent preferences, existing-batch reopening, sample readers, bundled pinned Python and ad-hoc local builds. Backend tests, actual app integration and visual inspection are separate from physical/user acceptance. Intel packaging, Developer ID/notarized distribution and a public DMG remain future work. Existing v1.0.0 releases/ticket sign-offs are unchanged.

## Current acceptance work

1. **KM-011**: execution lock and durable run status (foundation for safe cleanup/resume).
2. **KM-005**: pre-migration difference report.
3. **KM-001**: migrate/restore from verified saved archives.
4. **KM-003**: backup management and cleanup preview.

These four tickets await human testing/sign-off. See ACCEPTANCE.md. KM-013 is implemented and Ready for test for locale selection, localized help and read-only UI samples. KM-014 owned-runtime extraction, KM-015 three-catalog editorial work and KM-016 validator/regression work are Ready for test in 3.3.0-dev.6. Four Traditional Chinese behavior summaries and the presented historical RC1 offline results have scoped human acceptance. Complete three-catalog wording and practical end-to-end acceptance remain pending; see the [dated record](ACCEPTANCE.md#validation-record-2026-10-22). Bootstrap/framework/external output remains an explicit original-text boundary; KM-017 language-expansion guidance is queued. Other Queued work is not authorized by this release.

## First stable milestone: 1.0.0

Scope is the existing four modes, migration/backup/recovery safeguards and three locales. Do not add queued resume, mirroring, hardware-policy, discovery, GUI or platform-expansion work just to complete this milestone. Gates are maintained in [ACCEPTANCE.md](ACCEPTANCE.md#first-stable-release-gates).

- The 3.3.0-dev.6 package passed an actual Libra 2 → Clara 2E KOREADER transfer, full file verification, identity preservation and safe eject; the operator confirmed startup and opening an existing TARGET book. Usual functions and progress persistence after reopening were subsequently confirmed. Keep scope limited to those observations; additional model/plugin combinations remain unverified.
- FULL preview safely refused insufficient space. Successful physical FULL/LIBRARY copying is still pending and tracked as acceptance follow-up; use a capacity-sufficient, controlled setup when available rather than deleting real data to force a pass.
- The f98d3a6437ae CLI baseline passed 42 local synthetic rehearsals (14 per locale), separately from its 194-test unit evidence, six main CI jobs and 37-file/11-check local package. Transport was mocked; existing device data and backups were not accessed. These results do not replace physical FULL/LIBRARY acceptance.
- Four Traditional Chinese behavior summaries and historical RC1 offline results have been reviewed; remaining language, mode/recovery/maintenance and wider device-control acceptance stays open as documented follow-up. No ticket-wide status is promoted to Done.
- Version 1.0.0 retains all modes and the public compatibility baseline with explicit validation limits. Successful FULL/LIBRARY physical copying and broader language/maintenance review remain follow-up, not completed tests or a requirement to buy new hardware. Exact final tests, package checks, remote CI and source/release approval remain publication requirements. Existing RC1/3.x assets and real recovery backups remain unchanged.

## Device-support roadmap

The broader name describes the project direction, not delivered multi-device support. Non-Kobo work is queued after the Kobo first-stable milestone and requires its own implementation scope.

1. **KM-021 — Feasibility and support matrix:** research candidate device families, including Kindle, then choose the first platform and explicit migration directions. Record access/installation prerequisites, supported versions, host transport, runtime locations, identities, metadata and evidence gaps.
2. **KM-022 — Portable data and platform safeguards:** define what can move between device families, what must remain on TARGET and which combinations must be refused. Do not assume copying a complete Kobo runtime is safe on another family. Preserve existing exact Kobo FULL/KOREADER semantics; new policies must be explicit. Coordinate with KM-007/008/009 for metadata/hardware/settings handling.
3. **KM-023 — First non-Kobo adapter:** platform and supported directions remain to be selected after KM-021/022. Implement ordinary offline code, synthetic fixtures and controlled hardware acceptance, including capacity, backup, identity, path, rollback and restore behavior. Update user docs/support matrix only after the implemented scope is validated.

No Kindle support, platform priority, delivery date or complete cross-platform migration guarantee is implied by these tickets. Add other device families through separately scoped tickets. Existing Kobo migration must remain available and its pending acceptance must not be marked complete by this roadmap.

## Backlog

| ID | Priority | Status | Feature | Acceptance criteria / key constraints |
| --- | --- | --- | --- | --- |
| KM-001 | P1 | Ready for test | Restore/migrate from saved backup | Select an existing source run, verify ZIP + manifest + member paths before writes, require correct target/model confirmation, create target rollback backup, retain identity options. Separate restore of a previous target snapshot from new source migration; no source Kobo needed. |
| KM-002 | P2 | Queued | Resume interrupted transfer | Durable per-file journal; revalidate source archive and target identity; hash completed files before skipping; define recovery for interruption during FULL runtime replacement; preserve rollback capability. Depends on KM-011 and benefits from KM-001. |
| KM-003 | P1 | Ready for test | Backup management and cleanup preview | List runs, size, age, status and dependencies; preview reclaimable space; retain configurable recent successful batches; never select active/incomplete/only-recovery backups by default. Deletion needs an explicit user action. Depends on KM-011. |
| KM-004 | P3 | Queued | Exact library mirror option | Opt-in only; dry-run lists target-only books and sidecars to remove; back up removals, verify source scan completeness and capacity, support rollback. Default FULL behavior must continue retaining target-only books. |
| KM-005 | P1 | Ready for test | Detailed migration difference report | Human-readable and JSON lists/counts/bytes for new, overwritten, identical, kept and target-only files; group books with sidecars; inspect/report target-only books without silently broadening source format assumptions. Existing scan.json is a partial foundation. |
| KM-006 | P2 | Queued | Content-assisted book detection | Safe bounded signature/container checks for extensionless or mislabeled EPUB/PDF and selected formats; discovery confidence and reason in report; exclude system files; no claim of complete DRM/library discovery. |
| KM-007 | P2 | Queued | Reading-data conflict report | Read-only comparison of locations, mtimes, progress and annotation counts when safely parseable; show ambiguity/edition mismatches; no Lua execution and no silent annotation merging. Establish supported metadata schema before parsing. |
| KM-008 | P2 | Queued | Preserve target hardware settings | Optional portable policy preserving target-specific keys (buttons, rotation, lighting, calibration) while moving reading preferences. Use a tested Lua literal parser, not whole-table regex or Lua execution. Keep exact FULL clone option. |
| KM-009 | P2 | Queued | Settings-only migration | Preserve destination KOReader runtime/version, transfer compatible settings/custom plugins/resources, validate version compatibility and rollback; decide interaction with portable hardware policy KM-008. Avoid copying source core plugins blindly. |
| KM-010 | P2 | Queued | Standalone backup verification | CLI to verify existing archive SHA-256 and member content against manifest, unsafe paths/duplicates, corruption and missing pairs; read-only and usable without any Kobo. Reusable by KM-001/KM-003. |
| KM-011 | P1 | Ready for test | Execution lock and run status | Prevent concurrent runs targeting the same project/device; recover stale lock safely; durable status transitions (running, success, cancelled, failed, rolled-back, needs-recovery), distinguish interruption from success, update on every exit. Logs alone are insufficient for status. |
| KM-012 | P2 | Queued | Maintainable project structure and Git hygiene | Tracker, agent instructions, README and portable tests are now present. Git ignore policy, changelog and project-owned macOS fixture test were added with 3.1.0. Public-release privacy guard, documentation, CI and PR helper are implemented. Shared AGENTS.md guidance and native ignored Codex override now separate public project rules from private maintainer context. |
| KM-013 | P1 | Ready for test | i18n locale foundation | en, zh-Hant, zh-Hans; explicit/env locale resolution, reviewed aliases, JSON catalogs, safe named placeholders/plurals and English fallback; no runtime LLM or network. |
| KM-014 | P1 | Ready for test | Localized CLI and English diagnostic output | Separate console/log rendering, localize owned help/prompts/progress/errors and human report labels, stable English machine schemas and additive ui_locale metadata; preserve all migration safety. Owned runtime extraction completed in 3.3.0-dev.6; source coverage prevents uncatalogued runtime errors/status lines. Bootstrap/framework/external boundaries and final acceptance are documented in docs/DEVELOPMENT.md. |
| KM-015 | P1 | Ready for test | Initial three reviewed translations | Complete English, Traditional Chinese and Simplified Chinese catalogs; consistent terminology and exact destructive confirmation tokens. Three-catalog editorial pass completed; human safety-wording sign-off awaits combined acceptance. |
| KM-016 | P1 | Ready for test | Locale validation and multilingual regression | Schema/duplicate-key/coverage/placeholder/control-character checks, exact publication allowlist extensions and CI; equivalent migration/device outcomes in all three locales. |
| KM-017 | P2 | Queued | Translation contribution and expansion guide | Document CLI selection, packaging, aliases, fallback, supported plural rules and acceptance; new languages require reviewed registry/catalog changes and privacy checks. |
| KM-018 | P1 | Ready for test | Local source package preparation and verification | Package only guarded files from an explicit Git commit; require complete locale assets, verify ZIP bytes against Git, smoke-test a temporary extraction, check local doc links, generate SHA256SUMS and local metadata; no overwrite, network, device access or publication. Included in the published 3.3.0-dev.6 source package; human acceptance remains pending. |
| KM-019 | P2 | Ready for test | KOReader Bridge identity and Kobo-only scope | README name/tagline, explicit device support matrix, future-device roadmap and acceptance checks are documented. Review links and public wording; Retain existing commands/schemas/published archives; canonical CLI/runtime-brand follow-up is tracked in KM-024. No non-Kobo compatibility claim. |
| KM-020 | P2 | Ready for test | GitHub repository rename and link transition | Existing repository renamed to `gh-slee/koreader-bridge`; same repository ID, all branch/tag refs, 11 issue/PR identities, three releases and six downloaded asset hashes verified. Old Git/API redirects and existing exact-main CI passed; local origin/gh default updated. Canonical link updates merged in PR #12; six exact merged-main CI jobs passed. Final human link review remains. Do not recreate the old slug or rewrite published assets. See docs/MAINTAINING.md. |
| KM-021 | P2 | Queued | Non-Kobo feasibility and support matrix | Research Kindle and other candidate families; select a first platform and supported routes only after documenting prerequisites, versions, access/transport, runtime/metadata/hardware differences and available test hardware. No implementation or compatibility claim from research alone. |
| KM-022 | P2 | Queued | Cross-device migration policy and safeguards | Define portable versus platform-specific content, compatibility/refusal rules and adapter boundaries after KM-021. Preserve Kobo FULL/KOREADER behavior and all offline/identity/path/space/backup/rollback protections. Coordinate with KM-007/008/009; do not execute device Lua/plugins. |
| KM-023 | P2 | Queued | First non-Kobo device adapter (platform TBD) | Depends on KM-021/022 and a separately authorized implementation scope. Add explicit route selection and platform-specific offline capture/apply/restore, synthetic failure/compatibility regressions and controlled hardware acceptance; document exact tested scope and unsupported routes before advertising support. |
| KM-024 | P2 | Ready for test | Canonical CLI and runtime branding | Add koreader-bridge.py while retaining the shared legacy entry; align three-locale help/banner/preview and new manifest labels; preserve schemas, output root and locks. Coordinate docs/CI/checkers/publication allowlist and current/historical packaging. Verify equivalent offline CLI, cross-entry FULL/restore, shared locks, old manifests/packages and unchanged existing assets. Human wording acceptance remains pending. |
| KM-025 | P1 | Ready for test | Native macOS application | SwiftUI/AppKit over shared core; bounded helper, bundled runtime, persistent unknown-safe preferences, existing batches, guarded operations and isolated real-app tests. Sample-only actual screenshots; physical user sign-off/notarized distribution pending. |

## Completed baseline (verified in current code)

| ID | Status | Feature |
| --- | --- | --- |
| BASE-001 | Done | FULL, KOREADER, LIBRARY, AUDIT and dry-run; FULL automatically includes supported books + reading data and default root fonts. |
| BASE-002 | Done | Original relative paths, adjacent `.sdr`, central `docsettings/`, `hashdocsettings/`, legacy metadata and root font copying. Scoped scans conservatively skip central metadata. |
| BASE-003 | Done | Incremental size/SHA-256 comparison; library overwrite/keep-target policies with metadata protection. |
| BASE-004 | Done | Source and target backups, per-file manifests, restore verification and caught-failure rollback. |
| BASE-005 | Done | Best-effort model detection, same-device fingerprint guard, disk-space checks, safe eject and device_id options. |
| BASE-006 | Done | Plugin structural audit, read-only statistics quick_check/row counts, missing literal references, symlink/ZIP/path checks. |
| BASE-007 | Done | Detailed file/byte progress, large-file speed/ETA and subprocess heartbeat output. |
| BASE-008 | Done | Stable script filename, version in output/log/JSON; generated files under script-relative `runs/<run-id>/`. |
| BASE-009 | Done | Normal cancellation uses MigrationCancelled and a friendly message rather than MigrationError/ERROR. |

## Current constraints and historical evidence

- The build published as the 3.3.0-dev.2 pre-release completed a connected-device KOREADER file transfer with full manifest verification and target identity preservation. Basic KOReader operation was confirmed; broader hardware acceptance and FULL book migration remain pending. Do not infer hardware acceptance from file verification or fixture tests.
- Backup batch files are flat inside each run. Proposed `source/`, `target-backup/`, `reports/` subdivision is not implemented.
- Retention/cleanup preview, durable run status and execution locks exist in 3.1.0. Automatic resume is still queued. Legacy runs without run.json stay protected as legacy/unknown.
- FULL/KOREADER copy source runtime version. Target-specific hardware settings are not selectively preserved; only device_id has a dedicated policy.
- Standard-library tool and fixture tests target Python 3.9+. Record actual local/CI versions separately.
- Credentials can exist in archives; do not print, commit or upload them. Tests must not read physical Kobo contents.

## Development and validation status

[1.0.0-rc.1](https://github.com/gh-slee/koreader-bridge/releases/tag/v1.0.0-rc.1) was published on 2026-10-21 from `aaedb78f2b2233ffe91ad42ae8ea9fb312860052`. Its baseline passed 185 synthetic tests, all six exact merged-main CI jobs and independent 35-file package checks. Both published assets were downloaded and matched the reviewed bytes; the release is a non-draft pre-release, not Latest. The later CLI baseline f98d3a6437ae has its own 194-test evidence, six exact-main CI jobs, 37-file/11-check local package and 42 local synthetic rehearsals across three locales; see the [dated acceptance record](ACCEPTANCE.md#validation-record-2026-10-22). Final publication still needs checks against the final commit/package and separate approval. Physical FULL/LIBRARY writes and wider manual acceptance remain pending. The following entries describe historical baselines, including scoped device evidence from 3.3.0-dev.6.

The [3.3.0-dev.2 experimental pre-release](https://github.com/gh-slee/koreader-bridge/releases/tag/v3.3.0-dev.2) was published on 2026-10-18 from commit `721e2cad01c7c2811baeb9bd3fff424bba87f275`. Its [main CI](https://github.com/gh-slee/koreader-bridge/actions/runs/39155468946) passed all six macOS/Ubuntu Python 3.9/3.12/3.14 jobs; the release baseline also passed 123 local tests, self-test, locale and privacy checks. The fixes close read-only statistics connections before safe eject and tolerate already-removed descendants during runtime replacement/recovery. Verified target recovery and saved-source KOREADER transfer completed on connected hardware, with basic KOReader operation confirmed. Broader hardware acceptance and FULL book migration remain pending. KM-011/KM-005/KM-001/KM-003/KM-013 remain Ready for test; this scoped success does not sign off entire tickets. Use ACCEPTANCE.md for verification. A public roadmap describes product work, not authority to access devices or publish changes.

The merged PR #5 follow-up added KM-018 local source-package tooling and reconciles release status documentation; these changes were not in the earlier 3.3.0-dev.2 ZIP and are included in 3.3.0-dev.6. The helper never uploads, creates tags or runs device operations. Local follow-up validation passed 138 tests (15 for packaging), self-test, locale and worktree/history privacy checks. The helper was merged in PR #5 and merged-main CI 39165980479 passed all six jobs. The existing release CI result is not evidence for later commits.

Target restoration needs a modern target-snapshot.json and target-changes.json plus verified archive pairs. A FULL source snapshot can serve FULL/KOREADER, not LIBRARY; central metadata belongs to the runtime archive. See README.md for compatibility and recovery details.

[PR #1](https://github.com/gh-slee/koreader-bridge/pull/1) merged into main on 2026-10-16 as [564234e](https://github.com/gh-slee/koreader-bridge/commit/564234e2256bb6a64085cc10a4d3c5535322313e). Its [main CI](https://github.com/gh-slee/koreader-bridge/actions/runs/38918881111) passed all six macOS/Linux Python matrix jobs. The pre-merge dedc884 baseline passed 117 local tests, self-test, locale validation and all twelve push/PR CI checks. This is automated evidence; merge does not record physical/manual acceptance.

## Agent-assisted development

Shared project guidance uses the AGENTS.md open format. The public file covers code conventions, safety and checks; it does not store personal preferences, authentication history, individual approvals or session transcripts. Codex supports a Git-ignored local AGENTS.override.md; it must explicitly read the shared AGENTS.md because same-directory discovery selects only one of them. Contributor setup is documented in CONTRIBUTING.md.

The duplicate Cursor rule has been removed; tools that support AGENTS.md can use the shared file. No custom private agent-memory filenames, agent runtime dependency, global configuration change or new migration feature is introduced. Existing public Git history is unchanged. Private instructions remain excluded by both Git ignore rules and the publication allowlist.

Local guidance validation passed: 116 fixture tests, self-test, three-locale validation, 71 documentation link targets plus shell examples, Git-ignore/private-file checks and worktree/history publication checks. No migration runtime or catalog code changed. Native discovery follows the official protocol; no additional LLM session was launched to test startup. Runtime/manual acceptance tickets retain their existing status. The detailed i18n design below describes planned product behavior beyond the implemented help/sample foundation.

## Internationalization design and implementation status

Status: KM-013 locale foundation is implemented in 3.3.0-dev.1 and Ready for test. Help/static samples support en/zh-Hant/zh-Hans. Development 3.3.0-dev.6 catalogs all owned runtime text with English diagnostics; bootstrap/framework/external messages retain original text by design. The rest of this design describes the target full i18n scope, not completed runtime behavior.

### Initial language scope

| Language | Canonical locale | Purpose |
| --- | --- | --- |
| English | en | Default, canonical source catalog and fallback. |
| Traditional Chinese | zh-Hant | Initial Traditional Chinese interface, shared across supported regional aliases. |
| Simplified Chinese | zh-Hans | Separately reviewed Simplified Chinese interface. |

This is a proposed initial product scope, not a claim about market popularity. Use script tags rather than equating a script with a single country. Traditional and Simplified Chinese require independent wording review; do not publish an automatic character-conversion output as an accepted translation.

Code, comments, identifiers and canonical developer documentation use English. Reviewed catalogs can localize owned user-facing text. Tool-owned diagnostic log messages remain English.

### Target full-interface behavior

Translate owned menus, prompts, help descriptions, progress labels, safety warnings, cancellation/error guidance, run-catalog headings and difference.txt labels. Preserve raw macOS/Python/subprocess diagnostics as received, with a translated explanatory wrapper when useful. Do not claim arbitrary operating-system output is translated.

Keep these stable and untranslated:

- CLI flag names, mode tokens FULL/KOREADER/LIBRARY/AUDIT and numeric menu selections.
- JSON keys/status/phase values, report and archive filenames, run IDs, checksums and device fingerprints.
- Book/font paths, metadata contents and technical identifiers such as device_id.
- Exact destructive confirmation syntax such as DELETE RUN_ID. Translate the instruction, not the required command.
- ISO timestamps and existing byte units/number representations in this first release; full cultural date/number formatting is deferred.

SOURCE and TARGET must remain visibly identifiable in translated text, e.g. a translated role name followed by (SOURCE) or (TARGET). Never translate user/device data or change migration decisions based on language.

### Proposed CLI and locale resolution

Locale selection/help/list commands now work in 3.3.0-dev.1. Migration commands accept the preference; shared presentation and core workflow/recovery are partially localized in 3.3.0-dev.5 while unconverted low-level/per-file/maintenance text remains English:

```bash
python3 koreader-bridge.py --locale en --help
python3 koreader-bridge.py --locale zh-Hant --mode full --dry-run
python3 koreader-bridge.py --locale zh-Hans --list-runs
python3 koreader-bridge.py --list-locales
python3 koreader-bridge.py --locale zh-Hant --preview-ui
```

Resolution order: explicit --locale; KOBO_MIGRATE_LOCALE environment preference; terminal language environment (LANGUAGE, LC_ALL, LC_MESSAGES, LANG); English fallback. Respect ordered LANGUAGE preferences. Do not execute macOS settings commands or read a Kobo's copied language setting to infer the operator's preference.

Normalize common case/encoding/separator variations. Alias examples:

| Input | Result |
| --- | --- |
| en, en_US.UTF-8, en-CA | en |
| zh-Hant, zh_TW.UTF-8, zh-HK, zh-MO | zh-Hant |
| zh-Hans, zh_CN.UTF-8, zh-SG | zh-Hans |
| zh without an explicit script/region | en with a concise notice; ask users to select an explicit script |
| C, POSIX, unsupported environment locale | en |
| Unsupported explicit --locale | Usage error before creating run folders or accessing devices |

An explicit script takes precedence over a conflicting region. Region aliases share one reviewed script catalog initially; regional vocabulary variants can be introduced later. Set locale once at startup. Do not mutate process-wide locale settings or switch language mid-transfer.

A small bootstrap parse must resolve --locale before building translated help/error descriptions and before run/device setup. --list-locales must work without a Kobo, creating runs, or loading private runtime artifacts. Raw argparse diagnostics may retain their original text; owned guidance and descriptions are translated.

### Architecture and files

Use Python's standard library and UTF-8 JSON catalogs. No runtime translation service, AI API, downloaded model, third-party package or translator compilation tool is required.

Proposed layout:

```text
kobo-koreader-migrate.py       # message rendering/output adapter; stable entry point
locales/
  registry.json              # reviewed tags, native names, aliases and plural-rule IDs
  en.json                    # canonical English messages
  zh-Hant.json
  zh-Hans.json
scripts/check_locales.py      # deterministic schema/coverage/placeholder checks
tests/test_i18n.py
docs/TRANSLATING.md
```

Initially keep the small runtime adapter in the main script rather than coupling i18n to a broad migration-code refactor. Distribute the whole repository with locales/. If the English catalog is absent or invalid, fail with a short built-in English explanation before accessing devices. Update installation docs so a lone copied script is not presented as the complete multilingual distribution.

Use stable English message IDs with named placeholders, for example migration.wait_for_device with {role}, rather than translating concatenated fragments or already-formatted f-strings. Keep comments/context for translators in schema-supported metadata. English catalog text is the canonical message source; avoid maintaining duplicate English dictionaries that drift.

Allow declarative plural variants, initially one/other for English and other-only for Chinese. Select variants through vetted code rule IDs, never eval or executable catalog expressions. Future languages with additional plural rules require a reviewed rule implementation and tests, not an unsupported promise that every language needs only a new file.

Catalog validation must reject duplicate JSON keys, wrong schema/value types, invalid IDs, mismatched placeholders, attribute/index placeholder traversal, unexpected nested formatting and terminal control/ANSI injection. Permit only explicitly supported formatting syntax. Load only registered catalog paths beside the script; locale input must never become an arbitrary file path or execute code.

Missing noncritical translations fall back to the complete English message. An unreadable/invalid selected translation falls back to the English catalog with one warning. Invalid canonical English messages stop startup safely. Supported release catalogs must have complete message coverage, especially all safety prompts; runtime fallback is a recovery feature, not a substitute for completed translations.

### Console and log separation

The current LogTee copies the same bytes to screen and log. Refactor owned messages through an event emitter before translating them; do not translate text after LogTee has duplicated it.

An event carries an English message ID, severity and named parameters. Render the selected locale for the console and English for the log. Preserve original stdout/stderr routing and progress flushing. Keep raw external-tool diagnostics separate and explicitly labelled; they may be in the operating system's language.

Exceptions should preserve an English representation for existing diagnostics while carrying a stable message ID/parameters for localized presentation. MigrationCancelled, migration failures and rollback failures must remain distinguishable. Do not globally monkeypatch print/input or replace arbitrary substrings.

Render all candidate translations before any device mutation. If a selected translation cannot format, use its validated English message; a translation defect must not trigger a partially completed migration. Ensure graceful output on non-UTF-8 streams, without renaming or changing Unicode filenames on devices. Use Unicode-aware layout or avoid width-sensitive table padding for CJK headings.

Add an optional ui_locale field to modern run.json and human-report metadata, while retaining English machine-schema values and accepting older runs without that field. No personal locale preference file or network telemetry is introduced.

### Input and safety behavior

- Continue accepting y/yes/n/no in every language. Add the explicit Chinese equivalents for yes/no through a reviewed input policy; never derive affirmative meaning from arbitrary translated text.
- Empty responses retain existing safe defaults. Unrecognised input reprompts; there is no new automatic-yes option.
- Numeric menus and typed DELETE RUN_ID confirmations stay exact and language-independent.
- Translate warnings about source/target roles, whole-runtime replacement, credentials, device mismatch, identity cloning, cleanup and recovery together with their explanatory context.
- FULL still includes books/reading data/default root fonts, KOREADER remains directory-only, and target-only books are retained by default. Checksums, backups, locks, rollback and standalone offline operation do not change.

### Implementation tickets and order

| Ticket | Phase | Deliverables | Acceptance |
| --- | --- | --- | --- |
| KM-013 | Locale foundation | Registry/catalog schemas, bootstrap selection, aliases, fallbacks, safe formatting and plural selection. | All three locales resolve deterministically; invalid input cannot access arbitrary files; startup errors occur before device activity. |
| KM-014 | Output and error integration | Console/English-log emitter, owned CLI/help/progress/error text, localized difference/catalog labels, additive ui_locale metadata. | No language-dependent migration decisions; English diagnostics and machine-schema values remain stable; no hardcoded owned UI text omitted from inventory. |
| KM-015 | Three reviewed catalogs | Complete en, zh-Hant and zh-Hans text; shared terminology and safety review. | 100% required message/placeholder coverage; each destructive prompt reviewed in context; no inferred approval from translated wording. |
| KM-016 | Validation and regression | check_locales.py, publication allowlist updates for exact locale/doc/tool paths, CI and parameterized language tests. | Catalog errors fail CI; unknown JSON/device files remain blocked; all existing migration tests plus multilingual safety regressions pass. |
| KM-017 | Documentation and language expansion | English contributor/translation guide, examples, language-status table and manual acceptance instructions. | A contributor can add a supported-rule language using catalog/registry changes and checks; release readiness and pending human review are explicit. |

Implementation order: KM-013 -> KM-014 -> KM-015 -> KM-016 -> KM-017, with focused tests alongside each phase. Test English migration behavior immediately after output routing changes, before integrating all translations. KM-013 is Ready for test. The initial validator, exact publication allowlist and foundation regression checks are implemented as dependencies; KM-014 slice 1 adds shared routing and a synthetic multilingual safety matrix; remaining extraction, full KM-016 coverage and KM-015/KM-017 work are pending.

### Verification matrix

1. Selection: flags/env precedence, ordered preferences, aliases, conflicting script/region, ambiguous zh, C/POSIX, unsupported locales and traversal attempts.
2. Catalog safety: missing/corrupt catalog, duplicate keys, missing/extra entries, placeholder mismatch, invalid formatting, plural forms and control characters.
3. Presentation: owned help/menu/error/progress/cleanup/catalog/difference text in all three languages; English tool-owned log messages; raw external text preserved and marked.
4. Semantics: compare equivalent synthetic workflows in all languages across FULL/KOREADER/LIBRARY/AUDIT, saved-source reuse and target restore. Device trees must match after excluding documented timestamps/random run IDs.
5. Safety: default-No and invalid answers never authorize writes; same-device rejection, compatibility refusal, checksum failure, rollback, cleanup typed confirmation and cancellation remain intact in every language.
6. Compatibility: old source/target snapshots and statuses remain usable; new ui_locale is optional. Test the existing minimum supported Python version via CI.
7. Output/privacy: Unicode filenames, CJK layouts, redirected output, non-UTF-8 streams, secret/path scanning of locale files, explicit publication allowlist and no copied run/device data.
8. Standalone: run tests/self-test without AI credentials/services or network access. No real Kobo is required for automated tests. Physical acceptance/sign-off remains separate.

Do not translate tests through an LLM at runtime. Development translation assistance does not replace human wording review, especially for destructive prompts.

### Adding languages later

Add a registered tag/native name, a UTF-8 catalog, reviewed aliases and supported plural-rule ID; run checks, preview every menu and submit a PR for review. Maintain translation completeness/status explicitly. Incomplete new languages stay experimental and must not be advertised as fully supported.

Do not auto-enable every JSON file found in locales/. Additional languages, right-to-left layout, regional vocabulary/date/number formatting, broad README translations and localization of developer publishing tools are separate scope decisions. Update the allowlist intentionally for each new public language file rather than allowing arbitrary JSON uploads.

### Design references

- Python gettext documents catalog/fallback/plural concepts and LANGUAGE/LC_ALL/LC_MESSAGES/LANG environment discovery: https://docs.python.org/3.12/library/gettext.html
- W3C language tags explain language/script/region distinctions and BCP 47 conventions: https://www.w3.org/International/articles/language-tags/
- Python format-string syntax informs the deliberately restricted named-placeholder validator: https://docs.python.org/3.12/library/string.html#format-string-syntax

These references inform the design; this plan chooses source-reviewable JSON catalogs rather than requiring compiled gettext .mo files.


## Documentation organization

README.md is the concise entry point for installation, essential mode/data behavior, supported platforms, partial locale status and document navigation. Complete user, recovery, troubleshooting, developer and maintainer details now live in five topic guides under docs/. Shared AGENTS.md remains the agent entry point; this organization introduces no new agent-memory convention or migration runtime behavior.

The publication allowlist adds only the five exact reviewed Markdown paths; other docs/data paths remain blocked and all guide content still receives secret/path scanning. A regression covers both allowed paths and rejection of unknown/private paths or private content. Local validation passed: 117 tests, self-test, three-locale validation, 99 documentation link targets and 27 shell examples, plus worktree/history privacy and whitespace checks. Migration runtime and locale assets are unchanged. These results cover the local documentation batch; hosted CI for it requires publication. Physical/manual acceptance status is unchanged.


## Post-merge documentation

Following PR #1, the default main checkout contains the complete implementation. Installation, CI badge scope, contributor base-branch instructions and release-preparation guidance now target main. This is a documentation-only correction; runtime/catalog behavior and all pending human acceptance tickets remain unchanged. Local checks passed: 100 document link targets, 27 shell examples, live main CI badge, publication privacy/history and whitespace. Runtime, catalogs, scripts and tests are unchanged; the full fixture suite was not repeated for this documentation-only correction.

## KM-014 slice 1 — shared output routing

Status: Ready for controlled testing as a scoped part of In progress KM-014, development 3.3.0-dev.3. The published 3.3.0-dev.2 ZIP/tag is unchanged. Adds explicit message-ID/parameter contracts, scoped console/English-log rendering, shared confirmations/progress/run/catalog/cleanup/difference labels, additive ui_locale metadata and 94 extracted entries per locale. Typed input rules and data/decision schemas stay stable; no LLM or network dependency.

The remaining message inventory is in docs/DEVELOPMENT.md. At slice 1, menus and basic inspection/space checks were pending; slice 2 below adds them. Detailed errors/metadata/plugin diagnostics, raw diagnostic labelling and human catalog review remain pending. Existing physical/manual acceptance tickets retain their status. This slice does not authorize device operations, cleanup of real backups, publication or merge.

Local slice validation passed 154 tests (16 new UI routing/workflow cases), self-test, 3x94 locale validation and worktree/history privacy checks. Slice 1 merged as PR #6 and main CI 39179925642 passed all six jobs; manual translation/hardware acceptance remains pending. These results do not change older tickets to Done.

## KM-014 slice 2 — menus and basic inspection

Status: Ready for controlled testing as part of In progress KM-014, development 3.3.0-dev.4. Adds translated mode/identity/conflict menus, physical-model hints/confirmation and basic device/space summaries, including a LIBRARY capacity line. Adds 37 entries per locale (131 total) with explicit placeholder contracts. The plugin-specific configuration indicator is removed from console/logs; legacy saved metadata, generic plugin audits and whole-runtime verification remain compatible. Existing defaults, retries, model/fingerprint checks, space formulas and all device decisions remain unchanged.

Detailed errors, metadata/plugin diagnostics, raw diagnostic labelling and remaining workflow messages are the next extraction work; KM-015 human wording review is pending. No physical-device acceptance or publication/backup deletion permission follows from this ticket.

Slice 2 merged as PR #7 after 166 local tests/3x131 locale checks and all 12 push/PR jobs passed. All six [merged-main jobs](https://github.com/gh-slee/koreader-bridge/actions/runs/39183640983) also passed. This establishes automated evidence for slice 2 only; human wording review and hardware acceptance remain pending.

## KM-014 slice 3 — workflow, recovery and selected refusals

Status: Ready for controlled testing as part of In progress KM-014, development 3.3.0-dev.5. Adds 117 IDs (248 entries per locale) for migration/saved-source/target-restore plans, backup/verification/eject/identity notices, archive heartbeats, recovery guidance, five cancellation reasons and 36 selected refusals. Structured exceptions keep English string args; display rendering uses IDs and labels raw unconverted details without replacing text.

Safety acceptance: numeric/yes-no defaults, device/fingerprint guards, backup/capacity/integrity checks, paths and machine schemas remain stable. Exit 2 still means failed but rolled back; 3 means recovery required. Synthetic failure/changed-device tests must show the same file results/statuses in all three languages. Fixtures do not authorize real device or recovery-backup operations.

Remaining extraction: low-level errors, startup/argparse diagnostics, cleanup protection reasons/maintenance errors and detailed scan/comparison/per-file output. Raw labels cover integrated exception/warning/diskutil sites only. KM-015 human review and full coverage remain pending. Slice 3 merged as PR #8 after 175 local tests/self-test/3x248 locales/privacy checks. All 12 push/PR jobs and six merged-main jobs (39262795019) passed. These are automated results for slice 3 only; human wording/hardware acceptance is pending.

## Localization completion and combined acceptance (3.3.0-dev.6)

KM-014/KM-015/KM-016: Ready for test. The owner requested completing localization first and validating everything together at the end. No per-slice human sign-off is inferred. Adds 123 IDs (371 entries per locale), including all remaining owned runtime errors, maintenance/cleanup reasons, per-file output, scan/plugin warnings, self-test notices and custom argument checks. Editorial wording is reviewed independently for each catalog; final human wording acceptance remains pending.

Stored exception args, warning/reason strings, lock labels, paths, machine tokens and JSON schemas remain English/original. Structured diagnostic joining preserves localized children without changing English logs. Exact confirmation syntax and safety/backup/capacity/integrity/lock/rollback decisions are unchanged. Combined local validation passed 184 tests (nine new), self-test, 3x371 locale checks, worktree/history privacy and whitespace checks, 73 public doc file links and 30 bash examples. Changed Python parses with 3.9 grammar; hosted CI for this new scope remains pending.

Deliberate original-text boundaries: safe locale-bootstrap failures/fallback notices, Python-generated argparse/tracebacks and external process/database diagnostics. This does not promise translation of user data or Python itself. KM-017 expansion guidance and unrelated queued features remain outside this implementation. Combined human acceptance and physical FULL/library/recovery testing remain pending.
