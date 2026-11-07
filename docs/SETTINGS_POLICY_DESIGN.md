# Target hardware settings and portable settings policy: design (KM-008, KM-009)

Status: **Proposed design; no runtime code.** It records which KOReader settings depend on the reader's hardware, how they would be found without running Lua, and the policy that KM-008 (preserve TARGET hardware settings) and KM-009 (settings-only migration) would implement. The owner has not yet decided the [open questions](#open-questions). This document does not authorize device access.

Related: [TRACKER.md](../TRACKER.md) (KM-008, KM-009), [resume design](RESUME_DESIGN.md), [development guide](DEVELOPMENT.md).

## Problem

FULL and KOREADER back up TARGET's whole KOReader runtime and then replace it with SOURCE's, including `.adds/koreader/settings.reader.lua`. The only key handled separately today is `device_id`, through the identity choice (preserve, new or clone). Every other setting comes from SOURCE.

For two readers of the same model, that is usually what people want. For different models it moves values that describe the old reader's hardware: frontlight levels and NaturalLight calibration, rotation and gyro behavior, page-turn button mapping, display DPI, dithering and color-panel switches, and sleep-cover handling. After the migration, TARGET can start with a dark or wrongly tinted light, inverted buttons, a wrong DPI or a sleep cover that no longer wakes it. Users must then find and reset each option by hand.

LIBRARY does not touch settings, and stays unchanged.

## Goals and non-goals

Goals:

- An opt-in **portable** policy for FULL/KOREADER that keeps TARGET's values for listed hardware keys and takes everything else from SOURCE.
- The current behavior stays available, and remains the default, as the **exact** policy (a full clone of SOURCE's settings, apart from the identity choice).
- Parse settings only with the existing bounded Lua data-literal parser (`parse_lua_data`, KM-007). Never evaluate, compile or execute Lua, and never edit a whole table with a regular expression.
- Refuse, instead of guessing, when either settings file cannot be parsed or a hardware value has an unexpected shape.
- Keep rollback, resume and restore working: the TARGET runtime backup already contains the original settings file.
- Give KM-009 the same key classes, so settings-only migration and the portable policy agree.

Non-goals:

- Translating values between models (for example scaling frontlight levels or remapping rotation). Hardware keys keep TARGET's own value or are left unset; they are never converted.
- Merging per-book reading data. Sidecar and central metadata stay governed by KM-007's report and the existing copy plan.
- Non-Kobo devices (KM-021 to KM-023).
- Making KOReader's own settings menus or defaults part of the policy.

## Evidence basis

All key evidence comes from KOReader **v2026.07.1** (released 2026-08-01): the source tree at <https://github.com/koreader/koreader/tree/v2026.07.1>. References below are `path:line` in that tree. A key is listed as hardware-specific only when its source shows it is read by device, panel, light, input or sensor code, or is only offered on hardware with that feature. Settings keys can change between KOReader releases, so implementation must re-check this list against the release it targets and record that release in tests.

- `reader.lua:39-40` opens global settings as a LuaSettings table at `<data dir>/settings.reader.lua`. On Kobo the data directory is `.adds/koreader`.
- LuaSettings writes a `-- <path>` comment line followed by `return <table>`, with keys in sorted order (`frontend/luasettings.lua:273` calls `dump(self.data, nil, true)`; `frontend/util.lua:1144` adds the header). `parse_lua_data` accepts that form today; nested tables (for example `natural_light_config`) become nested dictionaries.
- Some plugins keep their own files under `settings/`, for example `plugins/batterystat.koplugin/main.lua:17` (`settings/battery_stats.lua`) and `plugins/autostandby.koplugin/main.lua:21` (`settings/autostandby.lua`).

## Key classes

| Class | Meaning | Portable policy |
| --- | --- | --- |
| **H** (hardware) | Describes or calibrates this reader's hardware | Keep TARGET's value; if TARGET has none, leave the key unset |
| **I** (identity) | `device_id` | Unchanged: the existing preserve/new/clone choice |
| **S** (schema) | `last_migration_date` | Comes with the runtime that is installed (see [schema marker](#schema-marker)) |
| **O** (other platform) | Read only by non-Kobo platform code | Keep TARGET's value; if TARGET has none, leave it unset. These do nothing on a Kobo, so keeping TARGET's state is the smallest change |
| **P** (portable) | Everything else, including unknown keys | Take SOURCE's value, as FULL/KOREADER do today |

Unknown keys are portable on purpose. FULL/KOREADER already copy them, so the portable policy changes only the keys this document lists. Adding a key to class H later is a reviewed change with a test.

### Class H: lighting

| Key | Evidence | Why hardware |
| --- | --- | --- |
| `frontlight_intensity` | `frontend/device/kobo/powerd.lua:62-68`, `:212` | Saved and restored by the Kobo power driver; light ranges and panels differ between models |
| `is_frontlight_on` | `frontend/device/kobo/powerd.lua:68`, `:213` | Light state saved by the same driver |
| `frontlight_warmth` | `frontend/device/kobo/powerd.lua:70`, `:215` | Warmth exists only on NaturalLight/ComfortLight PRO models |
| `natural_light_config` | `frontend/device/kobo/powerd.lua:149-150`; `frontend/ui/widget/naturallightwidget.lua:288` | NaturalLight mixer calibration, read only when `hasNaturalLight()` is true; a nested table |

### Class H: orientation and sensors

| Key | Evidence | Why hardware |
| --- | --- | --- |
| `closed_rotation_mode` | `frontend/device/generic/device.lua:352`, `:664` | Rotation saved at exit and restored at start; panel orientation differs between models |
| `lock_rotation` | `frontend/ui/elements/screen_rotation_menu_table.lua:71-74` | Rotation lock offered in the rotation menu |
| `input_ignore_gsensor` | `frontend/ui/elements/screen_rotation_menu_table.lua:38`, `:53` | Gyro handling; only some models have an accelerometer |
| `input_lock_gsensor` | `frontend/ui/elements/screen_rotation_menu_table.lua:56`; `frontend/device/generic/device.lua:325` | Gyro lock applied by device start-up code |

### Class H: physical buttons

| Key | Evidence | Why hardware |
| --- | --- | --- |
| `input_invert_page_turn_keys` | `frontend/ui/elements/physical_buttons.lua:16`, `:30` | Page-turn button mapping; only models with buttons |
| `input_invert_left_page_turn_keys` | `frontend/ui/elements/physical_buttons.lua:13`, `:33` | Left-button mapping |
| `input_invert_right_page_turn_keys` | `frontend/ui/elements/physical_buttons.lua:13`, `:45` | Right-button mapping |
| `left_right_keys_turn_pages` | `frontend/ui/elements/physical_buttons.lua:55-58` | Button role choice |
| `input_no_key_repeat` | `frontend/ui/elements/physical_buttons.lua:69`; `frontend/device/devicelistener.lua:429` | Key-repeat handling for physical keys |
| `pageturn_power` | `frontend/device/input.lua:955`; menu entry limited to `Device:isKobo() and Device:hasKeys()` (`frontend/ui/elements/filemanager_menu_order.lua:60`) | Page-turn buttons act as power while suspended |

### Class H: display panel

| Key | Evidence | Why hardware |
| --- | --- | --- |
| `screen_dpi` | `frontend/device/generic/device.lua:338-341`; `frontend/ui/elements/screen_dpi_menu_table.lua:17` | DPI override applied at device start; panels have different densities |
| `custom_screen_dpi` | `frontend/ui/elements/screen_dpi_menu_table.lua:10`, `:35` | The custom DPI value behind that override |
| `dev_no_hw_dither` | `frontend/device/generic/device.lua:368`; `frontend/apps/filemanager/filemanagermenu.lua:640`, `:664` | Hardware dithering switch, depends on the panel and SoC |
| `dev_no_sw_dither` | `frontend/device/generic/device.lua:363-368` | Software dithering switch tied to the same capability |
| `dev_startup_no_fbdepth` | `frontend/apps/filemanager/filemanagermenu.lua:597-600` | Framebuffer depth at start-up |
| `color_rendering` | `frontend/ui/elements/screen_color_menu_table.lua:16`; `frontend/ui/elements/filemanager_menu_order.lua:105` | Color rendering on color e-ink panels |
| `no_cfa_post_processing` | `frontend/device/kobo/device.lua:703` | Color-filter-array processing on Kobo color panels |
| `mxcfb_bypass_wait_for` | `frontend/device/kobo/device.lua:680-681` | Kobo display-driver refresh workaround |
| `low_pan_rate` | `frontend/device/generic/device.lua:275`; `frontend/ui/elements/screen_eink_opt_menu_table.lua:15` | E-ink panning refresh rate |

### Class H: covers and indicators

| Key | Evidence | Why hardware |
| --- | --- | --- |
| `ignore_power_sleepcover` | `frontend/ui/elements/common_settings_menu_table.lua:221-224` | Sleep-cover handling; covers and hall sensors differ between models |
| `ignore_open_sleepcover` | `frontend/device/kobo/device.lua:1733` | Wake-on-open handling in the Kobo driver |
| `enable_charging_led` | `frontend/ui/elements/common_settings_menu_table.lua:56-62`, offered only when `Device:canToggleChargingLED()` | Charging LED, present only on some models |

### Class O: other platforms

Read only by Android, Kindle, reMarkable, PocketBook or emulator code, so they do nothing on a Kobo: `android_ignore_back_button`, `android_ignore_volume_keys`, `android_screen_timeout`, `disable_android_fullscreen`, `haptic_feedback_override` (Android only: `frontend/ui/elements/common_settings_menu_table.lua:340-352`), `kindle_hall_effect_sensor_enabled`, `remarkable_hall_effect_sensor_enabled`, `pb_ignore_b288_quirks` and `emulator_fake_wifi_connected`.

### Candidates kept portable for now

These are related to hardware but are also personal reading choices. This design keeps them in class P and asks the owner (see [open questions](#open-questions)):

- `full_refresh_count`, `night_full_refresh_count` (`frontend/ui/uimanager.lua:23`, `:732-735`): full-refresh frequency, a trade-off between panel ghosting and speed.
- `refresh_on_pages_with_images`, `refresh_on_chapter_boundaries`, `no_refresh_on_second_chapter_page` (`frontend/ui/elements/refresh_menu_table.lua:110-121`): refresh preferences.
- `night_mode`: a reading preference, although some models implement it in hardware.
- `auto_suspend_timeout_seconds`, `auto_standby_timeout_seconds` (`plugins/autosuspend.koplugin/main.lua:189-192`): power-saving choices.
- `fm_rotation_mode` (`frontend/ui/elements/screen_rotation_menu_table.lua:10`, `:22`): the file browser's preferred rotation.
- Wi-Fi and USB options (`auto_disable_wifi`, `wifi_enable_action`, `mass_storage_disabled` and similar): behavior choices rather than hardware descriptions.

### Separate settings files

- `settings/battery_stats.lua` (`plugins/batterystat.koplugin/main.lua:17`) holds battery history for one physical battery. In the portable policy, keep TARGET's file, or leave it absent when TARGET has none.
- Every other file under `settings/` is portable and follows the runtime copy, as today.

### Schema marker

`last_migration_date` records which of KOReader's one-time settings migrations have run (`frontend/ui/data/onetime_migration.lua:15-21`; v2026.07.1 sets `CURRENT_MIGRATION_DATE = 20260623`). It describes the settings file's format, so it must match the settings content, not the hardware:

- FULL/KOREADER install SOURCE's runtime with SOURCE's portable settings, so the marker comes from SOURCE in both policies. KOReader applies any remaining migrations itself on the next start.
- Settings-only migration (KM-009) keeps TARGET's runtime. It must refuse when SOURCE's marker is newer than TARGET's runtime can understand, because an older KOReader cannot undo newer migrations. See the open questions for how to compare.

## Policy behavior (KM-008)

Option: `--settings-policy exact|portable`, default `exact`. It applies only to FULL and KOREADER. LIBRARY refuses the option, and AUDIT and dry-run only report what would happen.

`exact` is today's behavior: SOURCE's `settings.reader.lua`, then the identity choice for `device_id`.

`portable`:

1. Before the final confirmation, read SOURCE's settings from the verified source archive and TARGET's from the verified TARGET runtime backup. Both must parse with `parse_lua_data` under the existing limits. The top level must be a table with string keys.
2. Build the result: start from SOURCE's table, replace every class H and O key with TARGET's value or remove it when TARGET has none, set `device_id` from the identity choice, and keep SOURCE's `last_migration_date`.
3. A class H value must be a boolean, number, string or a table of those (nested tables allowed within parser limits). Any other shape refuses the policy.
4. Show the result in the preview and difference report: which keys keep TARGET's value, which become unset and which came from SOURCE. Values of class H keys are shown; other values are not printed.
5. After the runtime replacement, write the merged table with a new deterministic Lua literal writer that follows KOReader's own format (header comment, sorted keys) and replaces the file atomically. Parse the written file again and require it to equal the planned table before continuing. A mismatch fails the migration and rolls back as today.
6. Apply the same rule to `settings/battery_stats.lua`.

Refusal rules: the portable policy refuses with an owned, catalogued error, before any TARGET write, when either settings file is missing, unreadable, too large, not a single returned table, or holds a hardware value of an unsupported shape. The user can rerun with `--settings-policy exact` or cancel. Nothing falls back silently.

Recovery: the TARGET runtime backup already holds the original settings, so rollback and `--restore-run` need no change. The runtime marker gains a `settings-applied` step after `identity-applied`, and resume (KM-002) must reapply the recorded policy and verify the written table's hash before it continues. Saved-source reuse (`--from-run`) takes class H values from the TARGET that is connected for that run.

Desktop: the review sheet adds the policy choice, defaulting to `exact`, with a short explanation. The choice is part of the request-scoped review and is never saved as consent.

## Settings-only migration (KM-009)

KM-009 keeps TARGET's whole runtime and transfers settings and resources. With the classes above:

- `settings.reader.lua`: class P from SOURCE, classes H and O from TARGET, `device_id` kept from TARGET unless the user asks for a new one. `last_migration_date` must pass the [schema check](#schema-marker).
- Portable files under `settings/`, and user-added resources such as fonts, dictionaries and styles, come from SOURCE, after backup.
- Plugins: only plugins that are not part of TARGET's runtime are candidates. Core plugins are never copied over TARGET's. Copied plugins are files only; they are never run.
- Refuse when TARGET has no KOReader runtime, when either settings file fails to parse, or when the schema check fails.

KM-009 keeps the same backup, verification, confirmation and rollback rules as FULL/KOREADER.

## Implementation slices (KM-008)

1. A `KOREADER_SETTINGS_KEYS` table (class and evidence release for each key) and a deterministic Lua literal writer with round-trip tests through `parse_lua_data`. No behavior change.
2. Read-only plan: `--settings-policy portable` with `--dry-run` reports kept, unset and copied keys in the difference report (JSON and text) and refuses the listed cases. Catalog new text in three locales.
3. Writes: apply the merged settings after the runtime replacement, verify by reparsing, record `settings-applied`, extend resume and rollback tests.
4. Desktop review option and typed IPC field.
5. Documentation, acceptance checklist and, after owner approval, hardware acceptance on two different models.

## Test plan

- Synthetic settings files for each class, nested `natural_light_config`, missing keys on either side, unknown keys, header comments and Unicode strings.
- Refusals: unparseable files, oversize input, non-table returns, unsupported value shapes, and LIBRARY with the option.
- Round trip: the writer's output parses back to the same table; the writer never emits executable code.
- Rollback after a failed settings write restores the original TARGET bytes; resume reapplies the recorded policy.
- `exact` output stays byte-identical to the current FULL/KOREADER result.
- No test reads a physical reader. Hardware acceptance is a separate, owner-approved step.

## Open questions

1. **Default policy.** Recommendation: keep `exact` as the default for compatibility, and have the preview suggest `portable` when SOURCE and TARGET models differ. Alternative: default to `portable` for different models.
2. **Refresh and power choices** (`full_refresh_count`, `night_full_refresh_count`, refresh options, `auto_suspend_timeout_seconds`, `auto_standby_timeout_seconds`). Recommendation: keep them portable (class P) in the first release, because they are reading choices; revisit after hardware acceptance.
3. **Class H key missing on TARGET.** Recommendation: leave the key unset so TARGET's KOReader uses its own default, rather than copying SOURCE's value for different hardware.
4. **Schema check for KM-009.** KOReader exposes `CURRENT_MIGRATION_DATE` only as a Lua source constant. Recommendation: read it from TARGET's `frontend/ui/data/onetime_migration.lua` with one bounded, anchored pattern (`local CURRENT_MIGRATION_DATE = <8 digits>`), treat a missing or ambiguous match as a refusal, and never execute the file. Alternative: compare the runtime version files (`git-rev`) and refuse unless TARGET is the same or newer.
5. **Which KOReader releases to support.** Recommendation: record the release this key list was checked against (v2026.07.1) and warn, without refusing, when a runtime's version is newer than the last checked release.
