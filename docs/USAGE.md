# User guide

Commands in this guide target current source via `koreader-bridge.py`. Keep the adjacent `kobo-koreader-migrate.py` engine and `locales/` together. The old script remains a compatible command; published RC1/3.x packages only provide that older entry. CLI flags, backup schemas, default output root and locks are shared.

[Home](../README.md) · [Usage](USAGE.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Maintaining](MAINTAINING.md)

Start with the README quick start, then use this guide for the macOS CLI's modes and options. Review which data each mode changes before approving writes.

## Requirements and compatibility

| Requirement | Details |
| --- | --- |
| Computer | macOS with `ditto`, `diskutil` and `sync` available. |
| Python | Python 3.9 or newer. No `pip install` is needed for migration. The published review commit passed CI on Python 3.9/3.12/3.14 on macOS/Linux; see [project status](DEVELOPMENT.md#validation-and-release-status). Linux jobs validate fixtures, not device migration. |
| Devices | Two Kobo readers mounted as USB storage, connected **one at a time**. A renamed volume is detected by its `.kobo/` directory. |
| Identity | Both readers must have a readable `.kobo/version` file. The fingerprint prevents using the same device as both SOURCE and TARGET and guards subsequent writes. |
| KOReader | FULL and KOREADER require an existing SOURCE installation with `reader.lua`, `frontend/` and `plugins/`. LIBRARY does not install KOReader. |
| Space | Enough Mac space for source and target backups; enough target space for the planned replacement/copies. ZIP compression savings are not assumed. |

Choose which reader is SOURCE and which is TARGET, then confirm each physical model. KOReader logs provide only a model hint because a previous clone may have copied another reader's log. You can use two readers of the same model, but the tool refuses identical fingerprints.

FULL and KOREADER copy the SOURCE runtime version and settings. The operator must confirm that this KOReader build is compatible with the TARGET hardware. The tool does not install a fresh model-specific build or automatically preserve hardware-specific settings. Support for entering a model label is not a claim that every Kobo model has been tested.

Windows and Linux device migration are not supported. Linux CI runs fixture tests only. This tool does not migrate Kindle, Android, Nickel accounts, Kobo firmware, DRM licences or Kobo's internal database.

## Choose a mode

Running without `--mode` opens an interactive menu; FULL is its default.

| Mode | Entire `.adds/koreader` | Books and external reading data | Root `fonts/` | Writes to Kobo |
| --- | --- | --- | --- | --- |
| FULL | Clean replacement from SOURCE | Included, original relative paths | Included by default; `--no-fonts` disables it | After backups and final confirmation |
| KOREADER | Clean replacement from SOURCE | No copying outside KOReader | No copying outside KOReader | After backups and final confirmation |
| LIBRARY | Retains installed runtime/global settings | Selected using flags or prompts | Optional | After backups and final confirmation |
| AUDIT | Plans full runtime replacement | Selected using flags or prompts | Optional | Never |

```bash
# Everything supported, including books and reading state.
python3 koreader-bridge.py --mode full

# Entire KOReader directory only.
python3 koreader-bridge.py --mode koreader

# Books + reading data, retaining TARGET's installed KOReader.
python3 koreader-bridge.py --mode library --books --no-fonts

# Only custom root fonts.
python3 koreader-bridge.py --mode library --no-books --fonts

# Detailed read-only inspection and planning.
python3 koreader-bridge.py --mode audit --books --fonts
```

FULL always includes supported books and reading data. `--no-books`, `--no-reading-data`, directory scopes and `keep-target` conflicts are rejected in FULL. Use KOREADER or LIBRARY for selective work.

**FULL retains TARGET-only books outside KOReader.** It replaces SOURCE-matching files that differ, and skips identical payload files. It replaces the entire `.adds/koreader` tree, so TARGET-only files/settings/central reading metadata **inside that tree** are removed after backup. KOREADER has the same whole-directory behavior, including any books or fonts already stored inside that tree.

## How it works

```mermaid
flowchart LR
    S["SOURCE Kobo<br/>Read only"] --> M["Mac<br/>Capture and verify"]
    M --> T["TARGET Kobo<br/>Plan and back up"]
    T --> C{"Confirm?"}
    C -->|Yes| W["Copy and verify"]
    C -->|No| X["Cancel before writes"]
    W -->|Caught failure| R["Attempt rollback"]
```

Connect **one Kobo at a time**. SOURCE is ejected before TARGET is requested; the Mac holds the captured data between devices. A successful migration ends with safe eject. The tool never evaluates device Lua files or executes copied plugins.


1. Disconnect both readers. Launch the tool and select the mode.
2. Connect only **SOURCE**, choose USB connection on the Kobo and press Return when requested.
3. Inspect the displayed mount, model hint, KOReader version and masked serial hint. Enter/confirm the physical SOURCE model using the device's settings or your own verified information.
4. The tool checks paths, plugins and SQLite statistics, scans supported files, checks free space, then captures source archives with SHA-256 manifests. SOURCE files are not changed by the tool.
5. Wait for `Ejected successfully.` and `Unplug SOURCE now.` Disconnect SOURCE.
6. Connect only **TARGET**, choose USB connection and press Return when requested. Confirm the physical TARGET model. For whole-runtime copying, confirm build compatibility.
7. Review the payload plan and `difference.txt`. Select the TARGET KOReader identity policy when applicable. The tool verifies source archives and creates TARGET rollback backups.
8. At the **final** `Proceed with the planned migration? [y/N]:` prompt, type `y` and Return to allow writes. Empty input means No. Declining is a normal cancellation; TARGET is not modified.
9. Keep TARGET connected during copying and verification. On success, wait for safe eject and then disconnect it.
10. Open KOReader on TARGET and check several books, reading progress, annotations, fonts and plugins. Keep backups until your physical-device acceptance checks are complete.

Model flags provide labels in advance but do not bypass confirmations:

```bash
python3 koreader-bridge.py --mode full \
  --source-model "Kobo Clara BW" --target-model "Kobo Libra Colour" --dry-run
```

The model names in that command are examples; this hardware pair has not been tested. Physical-model confirmation lets you correct a stale or incorrect log hint. It does not bypass identity checks.

## Language support

| Language | CLI tag | Development coverage | Review boundary |
| --- | --- | --- | --- |
| English | en | Canonical owned help, runtime, reports, errors and custom argument checks | Final end-to-end acceptance |
| Traditional Chinese | zh-Hant | All extracted owned runtime text, per-file progress, cleanup reasons and warnings | Final human wording/end-to-end acceptance |
| Simplified Chinese | zh-Hans | Independent catalog with the same owned-message coverage | Final human wording/end-to-end acceptance |

The published 1.0.0-rc.1 package and the current core/desktop source contain 371 catalog entries per locale. The older 3.3.0-dev.2 ZIP has the original 36-message help/sample foundation. All owned runtime MigrationError/MigrationCancelled messages and status lines use explicit IDs; custom argument-combination checks render through the selected bundle before any run/device access. Complete human wording review remains tracked acceptance follow-up; see the validation limits in ACCEPTANCE.md.

Diagnostic logs, machine-schema values, fingerprints, category/status/operation tokens and original paths stay English/original as appropriate. English logs can contain Unicode filenames or external data. External command/database diagnostics and unexpected exceptions are preserved and labelled as raw details on Chinese consoles. Python-generated argparse headings/usage/type/choice errors and tracebacks can remain English; invalid/missing locale assets or unsupported locale selection deliberately use safe English bootstrap diagnostics. No locale text is trusted or evaluated before validation.

These commands need no Kobo and do not create runs/logs/backups or inspect existing run data:

```bash
python3 koreader-bridge.py --list-locales
python3 koreader-bridge.py --locale zh-Hant --help
python3 koreader-bridge.py --locale zh-Hans --preview-ui
python3 scripts/check_locales.py
```

`--preview-ui` displays a static translated mode menu and confirmation examples, then exits. It never asks for approval or starts an operation. The published 3.3.0-dev.6 package and candidate source also localize the actual mode, identity and conflict menus while preserving numeric keys/defaults and mode tokens; older 3.3.0-dev.2 lacks that runtime coverage. Python argparse headings/usage diagnostics can also remain English. `--preview-ui`/`--list-locales` cannot be combined with migration operations/settings.


Locale priority is `--locale`, then `KOBO_MIGRATE_LOCALE`, then the first nonempty terminal variable among `LANGUAGE`, `LC_ALL`, `LC_MESSAGES`, `LANG`, then English. Ordered colon-separated language preferences are supported. Common aliases include `en_US.UTF-8` -> `en`, `zh_TW.UTF-8`/`zh-HK`/`zh-MO` -> `zh-Hant`, and `zh_CN.UTF-8`/`zh-SG` -> `zh-Hans`. An explicit script wins over a conflicting region. Bare `zh` is ambiguous and falls back to English with guidance to choose a script; an unsupported explicit `--locale` is a usage error before device/run access.

Missing individual translations use English. Missing/invalid selected translations fall back to the whole English catalog with a warning. A missing/invalid canonical English catalog or registry stops startup safely. Catalog validation rejects duplicate keys, unsafe controls/format fields and invalid schema/placeholder/plural definitions. No code is evaluated from locale data. On non-UTF-8 streams, help/preview and messages routed through the shared output adapter use escaped characters instead of failing on encoding. Python bootstrap/traceback output outside the adapter is not covered by that guarantee.

The locale validator requires complete coverage of all extracted message IDs for all registered languages; source-coverage regressions additionally prevent owned runtime errors/status calls from bypassing IDs; bootstrap/framework/external text is an explicit boundary. CI and the publication helper run it in addition to tests/privacy checks. Publication allows only the four exact initial locale JSON files; arbitrary JSON files, device reports and additional language files remain blocked until deliberately reviewed. Final human acceptance and the future language-expansion guide are tracked separately in TRACKER.md.

Integrated confirmations still accept only y/yes/n/no (case-insensitive); empty input keeps the displayed default and invalid input retries. A question with `[y/N]` still defaults to No. Numeric menu keys and exact `DELETE RUN_ID` syntax remain unchanged. Do not infer support for Chinese affirmative answers. The adapter logs English prompts but never records typed answers.

In the published 3.3.0-dev.6 package and candidate source, run.json and difference.json have an additive `ui_locale` field. Statuses, operations, phases, category keys, fingerprints and archive paths remain stable; older records without ui_locale remain readable. difference.txt uses the selected locale while retaining stable action tokens and original file paths. Cleanup reasons and owned error details render from IDs while their stored string values stay English. Basic device/model/space checks are translated in development 3.3.0-dev.4; their diagnostic log text remains English. Model/version/path values and serial hints are preserved; labels and yes/no/unknown display values are localized. SOURCE/TARGET roles stay visible. Device inspection uses generic runtime information without a plugin-specific configuration indicator. FULL/KOREADER still include plugin files in the whole-runtime archive and file verification.


Development 3.3.0-dev.5 also translates core migration and saved-source/target-restore plans, backup/verification/eject notices, archive subprocess heartbeats, recovery instructions, five cancellation reasons and 36 selected refusals. Exception string values and machine data remain English. Structured refusals render through their message IDs; unconverted exception/warning/diskutil details routed through the new adapter are explicitly labelled as untranslated raw diagnostics on Chinese consoles and retain their original log text. This label is not a translation or a sanitization guarantee. Development 3.3.0-dev.6 completes the remaining owned scanner/comparison, maintenance, path/archive/statistics/locking and legacy-run messages; older published builds retain their earlier partial coverage.

Exit semantics are unchanged: 0 for success/normal cancellation (inspect run status to distinguish), 2 when a failed operation was rolled back, 3 when recovery is required, and 130 for interruption handled at the run/CLI boundary. No locale changes confirmation defaults, device guards, backup/integrity checks or recovery decisions. A changed/disconnected device still blocks automatic writes and requires inspection of the saved backups.


Development 3.3.0-dev.6 adds 123 entries and an editorial consistency pass across all three catalogs. Restore and automatic rollback use distinct terms. Display-only booleans localize while keeping English True/False in logs and actual bool values in records. Cleanup reasons and owned scan/plugin warnings retain their English string content for JSON compatibility; newly generated messages render from IDs. A plain warning string read from older JSON is preserved as raw data without matching its text to guess a translation ID. Confirmation tokens remain y/yes/n/no, numeric choices and exact DELETE RUN_ID.

## Books, metadata and fonts

### Book discovery

The scanner recognises filename extensions without regard to case. It does not inspect every file's contents or provide a complete DRM inventory. Built-in extensions are:

```text
epub kepub pdf cbz cbr cb7 cbt cba
mobi azw azw3 azw4 prc pdb fb2 fb3
djvu djv txt rtf doc docx html htm xhtml md
chm odt tif tiff xps oxps
```

Compound `.fb2.zip` is also recognised. `.kepub.epub` is found through its `.epub` suffix. Copying a format does not prove that KOReader on TARGET can open it. Unsupported extensions are not silently treated as books; the scan report includes unrecognised files.

Hidden/system folders are excluded from ordinary book scanning. Symlinks are skipped or rejected by the relevant safety checks. Generic ZIP archives, standalone image collections and extensionless books are not included automatically.

Use explicit extensions for other formats, and review the dry run:

```bash
python3 koreader-bridge.py --mode library --books --no-fonts \
  --extra-extension png --extra-extension zip --dry-run
```

Adding `zip` includes ordinary ZIP files within the chosen scan scope; it does not inspect them to determine whether they contain ebooks.

### Reading data

When books and reading data are enabled, adjacent sidecar directories follow their books. Examples:

```text
Books/title.epub             -> Books/title.sdr/
Books/title.kepub.epub       -> Books/title.kepub.sdr/
Comics/issue.cbz             -> Comics/issue.sdr/
```

Supported central metadata locations under `.adds/koreader` are `docsettings/`, `hashdocsettings/` and legacy `history/`. FULL/KOREADER include these through the runtime archive. Unscoped LIBRARY can copy these metadata trees without replacing the entire runtime. Lua files are copied/read as text; they are never evaluated.

The tool copies metadata without merging it. Scoped LIBRARY scans omit unfiltered central metadata to protect unrelated reading state. If you keep a conflicting TARGET book, the tool also skips its source sidecars and central metadata for that transfer. Different editions can have incompatible reading state even at the same path, so review the file plan.

### Fonts

Custom root fonts live at `fonts/` relative to the Kobo root, for example `fonts/MyFont.ttf`. Root font copying recognises `.ttf`, `.otf`, `.ttc` and `.otc`. Fonts inside `.adds/koreader/fonts/` are part of the whole KOReader tree and are copied in FULL/KOREADER regardless of the external-root font option.

### Directory scopes

Use SOURCE-relative directories, without a leading slash:

```bash
python3 koreader-bridge.py --mode library --books --no-fonts \
  --include-dir Books --include-dir Comics --exclude-dir Books/Temporary --dry-run
```

Repeat flags as needed. Target-only reporting uses the same scope and extension rules. Scopes are supported in LIBRARY/AUDIT, not FULL. Saved snapshots retain their original discovery scope.

## Conflicts and target identity

Payload files are compared by size and SHA-256. Identical files are skipped. Different files at the same relative path are governed by:

| Policy | Result |
| --- | --- |
| `overwrite` | Back up existing TARGET content, then replace it with SOURCE content. Used by FULL/KOREADER; optional in LIBRARY/AUDIT. |
| `keep-target` | Keep different existing TARGET files; still copy missing files. Protect associated reading metadata. LIBRARY/AUDIT only. |

```bash
python3 koreader-bridge.py --mode library --books --no-fonts \
  --conflict keep-target --dry-run
```

For whole-runtime migration, choose one KOReader `device_id` policy:

1. Preserve TARGET's existing identity (recommended; if absent, generate a new one).
2. Generate a new TARGET identity.
3. Clone SOURCE identity exactly.

This policy changes KOReader's ID; the Kobo hardware serial stays unchanged. The tool verifies the copied tree before adjusting identity and cache data. It copies other hardware-specific settings from SOURCE. Selectively preserving those settings is still planned.

## Command-line reference

Use `--help` for the definitive help text.

| Option | Purpose |
| --- | --- |
| `--locale TAG` | Select en/zh-Hant/zh-Hans for help and UI samples; otherwise detect terminal preferences. |
| `--list-locales` | List registered language options without accessing devices or runs. |
| `--preview-ui` | Show a read-only translated mode/confirmation sample and exit. |
| `--mode full\|koreader\|library\|audit` | Select a mode; otherwise show the menu. |
| `--dry-run` | Preview with no Kobo writes or ZIP creation. |
| `--source-model NAME`, `--target-model NAME` | Provide physical model labels; confirmations remain required. |
| `--books`, `--no-books` | Include/exclude books in selective modes; FULL always includes them. |
| `--fonts`, `--no-fonts` | Include/exclude root fonts; FULL default is include. |
| `--reading-data`, `--no-reading-data` | Copy or omit reading metadata with books in LIBRARY/AUDIT. |
| `--conflict overwrite\|keep-target` | Policy for different existing payload files. |
| `--include-dir DIR` | Scan a SOURCE-relative directory; repeatable. |
| `--exclude-dir DIR` | Exclude a SOURCE-relative payload directory; repeatable. |
| `--extra-extension EXT` | Add a case-insensitive book extension; repeatable. |
| `--backup-dir PATH` | Project/output root; default is script directory. |
| `--from-run RUN_ID` | Reuse a verified saved SOURCE; connect TARGET only. |
| `--restore-run RUN_ID` | Restore the recorded original TARGET state. |
| `--list-runs` | Show saved batches/status without devices. |
| `--cleanup` | Preview eligible old batches; no deletion by itself. |
| `--keep-successful N` | Keep N newest successes during cleanup, minimum 1. |
| `--delete-run RUN_ID` | Explicit eligible deletion selection with `--cleanup`; repeatable. |
| `--self-test` | Small offline non-destructive self-test, then exit. |
| `--version`, `--help` | Show version/help, then exit. |

`--preview-ui`, `--list-locales`, `--from-run`, `--restore-run`, `--list-runs` and `--cleanup` are mutually exclusive operations. The main migration workflow is interactive; there is no unattended `--yes` switch.

## FAQ

### Will FULL erase all books on TARGET?

It retains TARGET-only books outside `.adds/koreader`. Different SOURCE-matching payload files are backed up and replaced. The entire KOReader tree is replaced, including TARGET-only content inside it. [Review the mode table](#choose-a-mode).

### Will it find every ebook?

Discovery uses recognised filename extensions and your selected scope. Extensionless, unsupported or DRM-managed content is not guaranteed. [See formats and exclusions](#books-metadata-and-fonts).

### Where do fonts go?

Custom device fonts stay in root `fonts/`. KOReader's internal fonts stay inside `.adds/koreader/fonts/`; whole-runtime modes include that tree.

### Does running it require ChatGPT, an LLM or an internet connection?

No. Migration, validation, backups and cleanup use ordinary offline code. Obtaining the project and using optional GitHub publication tooling require network access. Copied plugin configurations are not executed.

### Does cleanup delete backups immediately?

`--cleanup` alone previews eligibility. Actual deletion needs explicit `--delete-run` selections and the exact typed confirmation. [See retention rules](RECOVERY.md#backup-cleanup).

### Can I use only the Python script, or migrate from Windows/Linux?

Keep `locales/` with the script, including for English. Device migration requires macOS. Linux CI validates synthetic fixtures only; Windows migration is unsupported.

## Limitations

- Extension-based scans cannot guarantee discovery of every ebook, DRM file, image folder or extensionless document.
- Reading data is copied, not semantically merged; different editions and metadata locations can cause conflicts.
- FULL/KOREADER replace the runtime and source settings. Selective target hardware-setting preservation is not implemented.
- `.kobo/version` is fingerprinted as a whole; a firmware change can change that fingerprint and block an older exact restore. There is no unsafe bypass option.
- There is no interrupted-transfer resume, default library mirror deletion, wireless sync, scheduled cleanup or unattended migration.
- Physical testing and human sign-off are still needed to assess live-device safety and usability. Check the recorded feature status before relying on untested behavior.

Planned work includes interrupted-transfer recovery, optional exact library mirroring, content-assisted discovery, reading-data conflict reports, portable hardware settings, settings-only migration and a separate archive verifier. These remain backlog items until implemented/tested.

## Menu and inspection translation (development slice 2)

Mode choices remain 1=FULL, 2=KOREADER, 3=LIBRARY and 4=AUDIT; empty input defaults to FULL. Identity choices remain 1=preserve TARGET, 2=new and 3=clone SOURCE. The identity default is preserve when available and new otherwise; selecting unavailable preserve retries. LIBRARY conflict choices remain 1=back up/overwrite and 2=keep TARGET. FULL/KOREADER still refuse keep-target.

A log model hint may be stale. Check the physical reader and confirm its model/build compatibility, even when the hint matches. Empty input in the physical-model text field can select its displayed hint, but the subsequent yes/no confirmation still defaults to No. Names remain plain ASCII model labels and are not translated.

Backup capacity remains 110% of estimated bytes plus 100 MiB. Runtime replacement capacity remains 110% of source/runtime+payload bytes plus 50 MiB, using current free bytes plus the replaced runtime's size. LIBRARY retains its existing 110% copy-size plus 50 MiB check and now displays a summary before rejecting insufficient space. These margins and refusals are language-independent; additional report text does not free space or authorize writes.
