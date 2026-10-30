# Development guide

## Native desktop development

Current development source is **1.1.0-dev.1**. [Desktop architecture](DESKTOP_ARCHITECTURE.md) describes IPC, storage/lifecycle and safeguards; [Mac instructions](MACOS.md) document local signing and distribution.

```bash
python3 scripts/build_macos_app.py --launch
python3 scripts/verify_macos_app.py "/path/to/KOReader Bridge.app"
xcrun swiftc -swift-version 5 -typecheck -target arm64-apple-macos14.0 -import-objc-header macos/WindowCapture.h macos/KOReaderBridgeApp.swift macos/NativeChecks.swift
```

Each build uses a fresh ignored output directory; caches/sample batches stay in `.local/`. The app bundles only explicit sources and its pinned runtime, retaining runtime licenses. Actual native integration covers persistence/unknown fields, FULL preview/copy, exact restore, saved-source, both LIBRARY policies, typed sample deletion and final decline. USB discovery/eject is simulated. Report actual app launch, visual inspection and real-user/hardware validation separately.

[Home](../README.md) · [Usage](USAGE.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Maintaining](MAINTAINING.md)

Implementation and verification reference for contributors. Read CONTRIBUTING.md for the review workflow and AGENTS.md for shared agent rules.

The canonical entry loads the existing engine through an explicit adjacent-file import, preserving argv and cwd. Both entries call the shared cli() exception/exit boundary, resolve the same script-relative run root and use identical project/device locks. Locale validation also loads that engine through the canonical entry. AST/source-coverage tests intentionally inspect the shared engine; its cli() fallback is the explicit English process boundary. Historical records and lock/output prefixes are not renamed.

## Tech stack

The runtime is a Python CLI, with no third-party Python packages, hosted backend or model service.

| Layer | Technology | Role |
| --- | --- | --- |
| 🐍 CLI and orchestration | Python 3.9+ · `argparse`, `pathlib`, `dataclasses` | Modes, paths, confirmations and operation plans. |
| 📦 Archives and integrity | macOS `ditto` · `zipfile` · `hashlib` / SHA-256 | Capture/extract trees, inspect ZIP members and verify archived/copied bytes. |
| 💾 Device and process control | macOS `diskutil`, `sync` · `subprocess` · `fcntl` | Safe eject, filesystem flush, subprocess progress and OS-backed locks. |
| 🗂️ Records and diagnostics | UTF-8 JSON · Python `sqlite3` | Run state, snapshots, difference reports, manifests and read-only KOReader statistics checks. |
| 🌐 Locale foundation | UTF-8 JSON catalogs · Python `string` / `unicodedata` | Reviewed locale selection, named placeholders and safe English fallback. |
| 🧪 Tests and CI | `unittest` · temporary fixtures · GitHub Actions | Migration/recovery/privacy regressions across macOS/Linux and three Python versions. |
| 🛠️ Maintainer tooling | Git · GitHub CLI (optional) | Reviewed feature-branch publication and PR creation; unnecessary for migration. |

Reading metadata and plugins are transferred as files. Lua is not an execution dependency of this tool. GitHub and Shields.io serve README badges only; the migration CLI does not contact those services.

## Project layout

```text
koreader-bridge.py        canonical CLI; loads the adjacent shared engine
kobo-koreader-migrate.py   shared migration/management engine and compatible legacy CLI
bridge_desktop_helper.py  bounded desktop protocol adapter over the shared engine
bridge_devices.py         read-only model/USB discovery and connection-bound role validation
locales/                 registry and reviewed UTF-8 catalogs
scripts/                 locale/privacy checks, source-package preparation and PR helper
tests/                   synthetic migration, management, locale and privacy regressions
docs/                    user, recovery, troubleshooting, development and maintainer guides
.github/workflows/       CI matrix
.githooks/               optional local pre-push guard
AGENTS.md                shared agent development rules
TRACKER.md               feature roadmap and i18n design
ACCEPTANCE.md            human verification checklist
runs/                    private generated data; ignored by Git
```

The script uses the directory containing it as the default output root. No dependency installer, package manager or hosted service is needed for migration. Keep locales/ with the script in clones and source archives. Generated data and private local instructions are outside the publication allowlist.

## Tests and validation

Run from the repository root, without a Kobo:

```bash
python3 scripts/check_locales.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 koreader-bridge.py --self-test
python3 scripts/check_publication.py --worktree --history
```

Tests use temporary synthetic devices and mock USB/eject operations. On macOS, an additional test uses real ditto for FULL migration, saved-source reuse and exact TARGET restoration on temporary directories. It never reads a physical Kobo; other test hosts skip that fixture.

Reader discovery tests supply an isolated USB storage graph. Cover native/USB agreement, shared/unknown product codes, manual model corrections, serial mismatch, duplicate roles, unsafe identity files, reconnection tokens and identity replacement at the final write boundary. Native checks drive actual selection/correction state and dual-reader synthetic workflows through the bundled helper. Do not use host ioreg or physical readers as automated fixtures. Model mappings are offline interoperability facts; references are the current Calibre Kobo driver and koboutils device table, with newer hardware revisions reviewed separately. A known name is not hardware migration certification.

Add meaningful tests for changed behavior and safety boundaries. Documentation-only work needs relative-link/anchor checks, CLI/example verification, shell syntax checks and publication privacy review. The publication helper independently runs its mandatory full checks before uploading.

Run scripts/check_locales.py after any catalog/registry change. The published 3.3.0-dev.6 and current candidate catalogs each contain 371 extracted message entries (36 in the historical 3.3.0-dev.2 foundation); validation does not substitute for human translation review. Keep mode tokens, flags, JSON schemas and destructive confirmation semantics language-independent.

## Validation and release status

The published CLI **1.0.0** is the first stable compatibility baseline following the published [1.0.0-rc.1](https://github.com/gh-slee/koreader-bridge/releases/tag/v1.0.0-rc.1). It retains both CLI names and the shared implementation; the final version update changes metadata and documentation, not migration algorithms, schemas or safety decisions. Support/validation limits and incomplete physical/manual checks remain explicit follow-up. Every release artifact requires its own exact-commit tests, package verification, CI and publication review; earlier results do not certify later bytes. See the [version policy](MAINTAINING.md#versioning-and-first-stable-release) and [release criteria](../ACCEPTANCE.md#first-stable-release-gates). Old 3.x snapshots remain covered by the existing cross-version regression; real private backups are never test inputs.

RC1 was published on 2026-10-21 from `aaedb78f2b2233ffe91ad42ae8ea9fb312860052`. Its baseline passed 185 tests (including the macOS ditto fixture), self-test, 3x371 locales, privacy/history and documentation checks. All six [exact merged-main CI jobs](https://github.com/gh-slee/koreader-bridge/actions/runs/39527788861) passed. Its independently extracted 35-file package matched Git, and the two uploaded assets were downloaded and verified against the reviewed local bytes. This evidence applies to RC1; later source commits require their own validation and hosted CI. Synthetic checks did not use physical devices or real backups.

The earlier published testing package is [3.3.0-dev.6](https://github.com/gh-slee/koreader-bridge/releases/tag/v3.3.0-dev.6), from `96efe762cc1263cf3afa1500f6d98012dfe82ee8`. Its baseline passed 184 synthetic tests and all six [exact merged-main jobs](https://github.com/gh-slee/koreader-bridge/actions/runs/39270917210); the released extraction later passed the same 184 tests and 24 command checks. A connected-device KOREADER transfer passed full manifest verification, identity preservation and safe eject; startup and opening an existing TARGET book were confirmed. FULL preview refused insufficient space before writes. This is scoped evidence only, not a stable release or full feature/hardware/human-language acceptance. New candidate changes require fresh tests and hosted CI; older jobs do not certify them.

The following entries describe historical development/release evidence.

The [**3.3.0-dev.2 experimental pre-release**](https://github.com/gh-slee/koreader-bridge/releases/tag/v3.3.0-dev.2) was published on 2026-10-18 from commit `721e2cad01c7c2811baeb9bd3fff424bba87f275`. Its [main CI](https://github.com/gh-slee/koreader-bridge/actions/runs/39155468946) passed all six macOS/Ubuntu Python 3.9, 3.12 and 3.14 jobs. The release baseline passed 123 local tests, self-test, locale and privacy checks. Connected-device target recovery and saved-source KOREADER transfer passed full manifest verification; basic KOReader operation was confirmed. Broader hardware acceptance, FULL book migration and the remaining manual checklists are still pending. This is not a stable release.

The development branch adds an offline [source-package helper](MAINTAINING.md#local-package-preparation-and-verification) and synthetic package-safety regressions. CI prepares and checks a source ZIP for its checked-out commit without uploading it. This helper was not included in the older 3.3.0-dev.2 ZIP; it is included in the later published 3.3.0-dev.6 package and candidate source. Local follow-up validation passed 138 tests (including 15 package tests), self-test, locale and worktree/history privacy checks. The helper was merged as PR #5; its [merged-main CI](https://github.com/gh-slee/koreader-bridge/actions/runs/39165980479) passed all six jobs. Its extracted smoke checks do not rerun the full unit suite or establish hardware acceptance; new changes need their own test results.

[PR #1](https://github.com/gh-slee/koreader-bridge/pull/1) merged into main on 2026-10-16 as [564234e](https://github.com/gh-slee/koreader-bridge/commit/564234e2256bb6a64085cc10a4d3c5535322313e). Its [main-branch CI run](https://github.com/gh-slee/koreader-bridge/actions/runs/38918881111) passed all six macOS/Ubuntu Python 3.9, 3.12 and 3.14 jobs. Linux checks fixtures only. The pre-merge documentation commit dedc884 passed 117 local tests plus self-test and locale validation, and all twelve push/PR CI jobs.

New changes require fresh validation. Temporary fixtures and the real macOS ditto round trip do not establish hardware compatibility. KM-011/KM-005/KM-001/KM-003/KM-013 remain Ready for test; see [manual acceptance](../ACCEPTANCE.md). KM-014 owned-runtime extraction is ready for the combined acceptance round in 3.3.0-dev.6; final human catalog review remains pending. Follow the current [CI runs](https://github.com/gh-slee/koreader-bridge/actions) and [open pull requests](https://github.com/gh-slee/koreader-bridge/pulls) for subsequent changes.

## Coding agents

The root [AGENTS.md](../AGENTS.md) is the shared source of agent guidance using the [AGENTS.md open format](https://agents.md/). Keep it concise and link task-specific documentation rather than duplicating it in multiple vendor rule files. Contributors remain responsible for understanding, testing and reviewing AI-assisted changes.

For personal Codex defaults, use its documented user-level AGENTS.md. For private project-specific instructions, Codex supports a Git-ignored AGENTS.override.md. At one directory level, Codex selects the override instead of AGENTS.md; a local override must explicitly read the public AGENTS.md to retain this project's shared rules. This is a Codex feature, not a universal private-file standard. See [official instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Codex's local managed worktrees automatically copy an ignored AGENTS.override.md. Other ignored files require deliberate .worktreeinclude configuration; ordinary clones, manual Git worktrees and remote environments do not gain this behavior. See [official worktree documentation](https://learn.chatgpt.com/docs/environments/git-worktrees). This project needs no extra private Markdown loader or worktree include file for its local override. Private instructions and credentials must never be added to a public commit.

Create private guidance only after confirming that both root and nested AGENTS.override.md paths are ignored and untracked. The local override must begin with this exact line:

```text
Before working, explicitly read ./AGENTS.md.
```

Keep personal preferences, operator authorization boundaries and concise current state in that private file. Replace stale branch/check/pending-work facts rather than appending transcripts. Never store credentials there or copy its contents into public guidance. Do not create custom OWNER.md/HANDOFF.md memory files. Keep shared rules in AGENTS.md; consolidate duplicate vendor instructions into references while preserving useful tool-specific activation and settings. No global Codex configuration change is required.

Other assistants have their own discovery and subagent inheritance rules. Delegate only when requested, and give each agent a bounded task and the applicable guidance; do not assume conversation inheritance. Development guidance never changes the migration tool's offline runtime requirements.

### Fresh-session verification

Start a new session with this repository as its working directory. Paste the following verification prompt; it does not authorize edits, device operations or publication:

```text
Verify this repository's agent setup without modifying files or publishing anything.
1. Identify instruction files supplied through startup discovery, separating them
   from files you explicitly read during this verification. If discovery provenance
   is unavailable, say so; do not infer discovery merely from a file's existence.
2. Follow any local override's instruction to read ./AGENTS.md explicitly.
   Summarize the shared stack, relevant validation commands and safety boundaries.
3. If private guidance is active, report only its effective response-language and
   publication-approval requirements. Do not quote private text, session notes,
   credentials or personal paths. Report missing guidance without inventing it.
4. Report the current branch, HEAD commit and working-tree status. Identify pending
   work without treating old approvals or checks as permission or fresh evidence.
5. State whether this is an actual fresh-session check or only a static file audit.
   If this is a worktree, verify destination guidance and branch/state separately.
```

After creating a local managed worktree, verify its ignored guidance and current branch/state at the destination. Ordinary clones, remote environments and manual worktrees need deliberate local setup; do not assume private files transferred. A successful file/ignore test does not prove startup discovery, precedence, agent compliance or worktree copying. Record a fresh-session or managed-worktree result only after actually performing that check.

### Public language policy

Canonical documentation, owned public code, comments and docstrings use English. Preserve original license terms, attribution and quoted source/user text. Locale catalogs, multilingual regression fixtures and necessary compatibility strings are intentional exceptions. Do not change stored application data or remove supported languages to eliminate non-English characters. Review translated heading anchors and executable examples when translating documentation.

There is no automated English-language guard. A CJK search can help review canonical prose, but cannot prove English grammar or translation accuracy; blanket non-ASCII bans would also reject valid names, symbols and localization fixtures.

## Feature and locale work

Use [TRACKER.md](../TRACKER.md) for feature criteria and the i18n design. Follow the requested ticket scope; a backlog entry is not authority to start implementation or access devices. Use [ACCEPTANCE.md](../ACCEPTANCE.md) for human feedback and [CHANGELOG.md](../CHANGELOG.md) for behavior changes. This documentation organization adds no new runtime feature or complete translation claim.

## Shared output routing (KM-014 slice 1)

Development 3.3.0-dev.3 adds a ContextVar-scoped UIOutput adapter. Explicit message IDs and named values render separately for the selected console locale and English diagnostic log. UIMessage retains its English string representation so existing helper contracts and technical comparisons do not depend on the selected language. Do not translate already-formatted output or monkeypatch print/input. A nested ui_session binds the original stdout/stderr plus the run log; it resets in finally on every exit. Emitters bypass LogTee to avoid duplicate/localized log entries. Legacy print/external diagnostics still pass through the tee unchanged until extracted.

UI_MESSAGE_FIELDS inventories the integrated IDs and exact named parameters. Canonical missing/mismatched fields fail at catalog load. Both renderings are computed before either stream is written; all integrated templates are pre-rendered before run creation/device access. A translation formatting failure falls back to English. Filenames, model labels, statuses and other technical data are never translated; original Unicode data can legitimately occur in an English log. Severity and output channel are explicit and preserve stdout/stderr routing. Typed responses are never logged. Shared yes/no defaults, numeric choices and exact cleanup tokens remain unchanged.

| Surface | Coverage and boundary |
| --- | --- |
| Help/prompts/menus/custom argument checks | Catalogued; exact numeric/yes-no/destructive tokens unchanged |
| Runtime errors and status/progress lines | All owned MigrationError/MigrationCancelled/log_status sites use IDs; raw OS/library diagnostics remain original |
| Cleanup protection reasons and scan/plugin warnings | Structured string subclasses render from IDs; their stored JSON strings remain English |
| Restore/rollback detail groups | Nested messages retain IDs and English string compatibility through joining |
| Difference/catalog/device/space reports | Owned headings/labels localized; paths and category/status/operation tokens retain stable values |
| Startup and Python framework output | Locale bootstrap failures/fallback notices and Python-generated argparse/tracebacks are deliberate English/original-text boundaries |

run.json and difference.json gain optional ui_locale metadata. No status/category/phase tokens or recovery schemas are renamed; old runs remain accepted. difference.txt is localized human presentation. This historical slice did not complete extraction. Development 3.3.0-dev.6 completes owned runtime extraction; human review remains pending. All text is static UTF-8 JSON and ordinary offline Python code; there is no runtime translator or AI dependency.

Synthetic regressions compare all four modes, saved-source reuse, exact target restore, final default-No, rollback after writes, cleanup tokens and exit states across the three locales. Stream tests cover English logs, Unicode/ascii output, no duplicate tee entries, fallback, parameter contracts and context cleanup. These do not establish physical-device acceptance or human translation sign-off. New hosted CI results require publication of this branch.

Local slice evidence: 154 tests passed (16 new shared-output/workflow tests), self-test, all 94 messages in each of three catalogs and publication worktree/history checks. Slice 1 merged as PR #6; [merged-main CI](https://github.com/gh-slee/koreader-bridge/actions/runs/39179925642) passed all six macOS/Ubuntu Python matrix jobs. This is evidence for slice 1, not later commits.

## Menu and inspection integration (KM-014 slice 2)

Development 3.3.0-dev.4 adds 37 explicit message contracts (131 catalog entries per locale). Mode/identity/conflict headings and labels, physical-model hints/retry/confirmation, inspection fields and capacity summaries use the shared adapter. English diagnostic wording is retained for existing fields; LIBRARY adds a capacity summary. The plugin-specific configuration indicator is removed from both output streams and catalogs; legacy DeviceInfo/manifest metadata remains compatible. Generic plugin audits and whole-runtime archive/verification still cover plugin settings without executing Lua. No message is matched/replaced after rendering.

Model names, versions, paths, masked serial hints, sizes and operation tokens stay unchanged. Display-only yes/no/unknown values are nested message references; DeviceInfo and machine JSON still contain the original data. New static catalogs have full extracted-ID coverage but require human wording review. Number/unit formatting remains the existing representation; this slice does not introduce cultural date/number formats.

Input defaults, policy tokens and unavailable identity retries retain their existing branches. Space formulas, reclamation assumptions, margins and '<' comparisons stay unchanged; the LIBRARY expression is named for display without changing its value or its position before TARGET backup/writes. Raw error details, metadata/plugin diagnostics, caught-failure/rollback descriptions and remaining phase notices are still pending extraction. No full KM-014/KM-015/manual hardware sign-off is implied.

Slice 2 merged as PR #7; 166 local tests and 3x131 locale checks passed. All 12 push/PR jobs and six [merged-main jobs](https://github.com/gh-slee/koreader-bridge/actions/runs/39183640983) passed. Human wording review and hardware acceptance remain pending; this CI result does not establish evidence for later changes.

## Workflow and recovery integration (KM-014 slice 3)

Development 3.3.0-dev.5 adds 117 explicit message/placeholder contracts (248 entries per locale): core migration, saved-source and exact-target-restore notices/plans; backup and full-file verification summaries; eject and identity notices; archive subprocess heartbeats; recovery success/blocked/failure guidance; five cancellation reasons and 36 selected refusals. English strings retain their existing wording. Numeric defaults, category/mode/status/phase/action tokens, path values, backup/capacity formulas and write/rollback branches are unchanged.

Exception arguments can carry UIMessage, whose actual string content remains English. exception_detail retrieves that structured argument only for presentation; it never infers an ID by matching rendered error text. Unconverted exceptions and warning/diskutil details at integrated call sites use diagnostic.raw, an identity template in English and an explicit untranslated-diagnostic label on Chinese consoles. Legacy per-file output and maintenance/low-level exceptions remain pending; this is not full error translation. Raw diagnostic values are preserved, not sanitized.

The root UI scope reports pre-run KeyboardInterrupt once and re-raises it with ui_reported; the CLI wrapper retains exit 130 without duplicating that message. Interrupts before locale parsing still use the English fallback. Run cancellation/failure/recovery codes and durable statuses remain unchanged.

Nine new temporary-fixture tests cover structured exception English args/JSON values, raw Unicode details and no tee duplication, subprocess heartbeat/eject commands, refusal before device access, successful rollback, changed-device write refusal, secondary rollback failure, exact-restore undo/guard and pre-run interrupt context. Existing all-mode, source-reuse, restore, default-No and archive tests remain required. Slice 3 passed 175 local tests/self-test/3x248 locales/privacy checks, then merged as PR #8. All 12 push/PR jobs and six [merged-main jobs](https://github.com/gh-slee/koreader-bridge/actions/runs/39262795019) passed. This is evidence for slice 3 only; human wording/hardware acceptance remains pending.

## Owned-runtime localization completion (3.3.0-dev.6)

All remaining owned runtime exception sites, per-file scan/compare/copy/archive status lines, maintenance/cleanup reasons, scan/plugin warnings, self-test notices and custom argument-combination errors now have explicit IDs. The change adds 123 entries (371 per locale) and reviews terminology independently for English, Traditional Chinese and Simplified Chinese. This is an editorial pass, not human acceptance. Human wording and hardware validation will be combined at the end, as planned.

Keep stored data independent of language: UIMessage is an English str subclass with structured values. Cleanup protection reasons, plugin/scan warnings, lock labels and exception args serialize as the same English strings; source and target machine schemas do not acquire translated values. diagnostic_detail distinguishes an actual UIMessage from raw data by type, never by matching text. join_diagnostics nests message values instead of flattening a recovery error group. Display-only True/False labels preserve English log wording and bool values in records.

Boundary: locale asset validation cannot depend on the catalog it is validating. Invalid/unsupported/missing assets therefore retain safe English bootstrap errors/fallback notices. Python-generated argparse headings/usage/type/choice errors and tracebacks, external process/database text, machine tokens and user data are also preserved. Custom project-owned argument-combination errors use bundle.render before run/device access. Do not monkeypatch gettext/argparse internals or translate rendered English with search/replace.

Source-coverage regressions reject uncatalogued runtime exception/status sites and custom parser errors; only blank/decorative print calls are allowed in runtime functions. Minimal module-wrapper fallback output is deliberate. Fixture tests also compare cleanup protection/JSON, warnings, plan/device bytes, malformed ZIP refusal, busy locks, CLI refusal and grouped recovery diagnostics across all three locales. Combined local validation passed 184 tests (nine new), self-test, 3x371 locale checks, worktree/history privacy and whitespace checks, 73 public documentation file links and 30 bash examples. Changed Python parses with 3.9 grammar; new hosted interpreter CI is pending publication. Human wording/hardware acceptance remains separate and deferred to the final combined round.

Editorial policy: preserve SOURCE/TARGET, mode/flag/status/category tokens and exact confirmation syntax; distinguish restoring a saved snapshot from automatic rollback and manual recovery. Review placeholders, negation, retained-versus-overwritten files and action timing in all three catalogs. Each language is maintained independently; script conversion alone is not an accepted review. Additional-language contribution guidance remains KM-017.

### PR authoring handoff

Use the [canonical PR template](../.github/pull_request_template.md) and [maintainer publication workflow](MAINTAINING.md#pr-helper). Supply the actual diff scope, implemented behavior, compatibility, commands/results/skips and independent-review provenance. Keep self-testing, CI and human/hardware acceptance distinct; mark unavailable evidence explicitly. Rebuild the complete description when implementation or review changes. Required structure takes precedence over prose-polishing preferences.
