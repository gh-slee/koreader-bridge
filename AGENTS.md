# Agent instructions

These instructions apply to coding agents. Read README.md for usage and CONTRIBUTING.md for the contribution workflow. KOReader Bridge has a SwiftUI/AppKit Mac app and a compatible Python 3.9+ standard-library CLI. The app bundles pinned CPython and uses bounded JSON IPC. Linux CI checks fixtures only.

## Find task context

- Read the current code and the documentation relevant to the requested change. Use README.md for quick start, docs/USAGE.md for CLI behavior, docs/RECOVERY.md for backup/restore, docs/DEVELOPMENT.md for implementation/testing, docs/MAINTAINING.md for publication, TRACKER.md for feature criteria and ACCEPTANCE.md for manual acceptance.
- Work only within the requested scope. A backlog entry is not authorization to operate devices, delete backups or start another feature.
- Follow existing standard-library patterns: pathlib for paths, argparse for CLI options and unittest with temporary fixtures. Keep machine schemas and stable CLI tokens compatible.
- Public code, identifiers, comments and canonical developer docs use English. Translate owned UI text only through reviewed locale catalogs; diagnostic logs and machine schemas stay English.

## Runtime and data safety

- Every feature must run offline as ordinary code without an LLM, AI API, model download, agent framework or active development session. AI assistance is for development only.
- Preserve FULL, KOREADER, LIBRARY, AUDIT and dry-run. FULL includes supported books, reading data and default root fonts; KOREADER copies only the entire KOReader tree.
- FULL/KOREADER replace the whole runtime after backup. Retain TARGET-only library files outside that tree. FULL rejects selective library scopes and keep-target conflicts.
- Keep SOURCE read-only. Before TARGET writes, require identity checks, compatibility/role confirmations, sufficient space, verified source archives and TARGET rollback backups.
- Device model logs are hints, not hardware proof. Require readable fingerprints and reject the same device in both roles.
- Never evaluate device Lua or execute copied plugins. Keep path, ZIP, symlink, integrity, lock and rollback protections intact.
- Keep normal cancellation distinct from migration and recovery errors. Do not selectively preserve hardware settings or merge reading metadata without an implemented, tested policy.
- Use koreader-bridge.py as the canonical CLI; retain kobo-koreader-migrate.py as the shared engine and compatible legacy entry. Keep both files and locales together. Both entries must share run roots, locks, safety decisions and exit handling. Record versions in code/logs/JSON; generated data stays in runs/<run-id>/ under the selected project root.
- Runtime UI after locale loading uses explicit catalog IDs for owned errors/prompts/progress/warnings/cleanup reasons and custom parser checks. Keep exception args, saved warning/reason strings, machine tokens and diagnostic logs English. Preserve structured children through diagnostic_detail/join_diagnostics; never infer IDs from rendered text. Raw external diagnostics, Python parser/traceback text and locale-bootstrap failures are deliberate original-text boundaries. Human wording/hardware acceptance remains pending.

## Native desktop

- Read docs/DESKTOP_ARCHITECTURE.md and docs/MACOS.md. Reuse core validation; IPC must not expose arbitrary code/commands/files.
- Keep stdout bounded JSON, typed allowlists, request-bound prompts, redaction, private storage and graceful stop. Never force-kill a real writing backend.
- Connected-reader mode uses bridge_devices.py native metadata, USB storage ancestry and session-bound tokens. Model overrides require explicit confirmation and cannot bypass identity failures. Keep raw serials/fingerprints out of discovery output; revalidate selected connections at core write/restore/eject boundaries. Tests use explicit isolated USB graphs, never host inventory.
- Native UI text lives in macos/locales/{en,zh-Hant,zh-Hans}.json; validate with scripts/check_native_locales.py. Keep semantic helper/warning IDs separate from English diagnostics. Connected-reader review is request-scoped; never auto-answer final writes or model exceptions, or persist consent. CLI/sequential/restore/delete confirmations remain.
- Build with scripts/build_macos_app.py; verify actual bundled workflows with scripts/verify_macos_app.py and isolated samples. Report automated, launch, visual and hardware/user evidence separately.
- Bundle explicit sources/pinned runtime only; retain licenses. Ad-hoc is not notarized. Keep binaries/caches/fixtures ignored; public screenshots must be manually inspected sample-only content.
- Do not rewrite historical release capabilities or GitHub metadata without scoped authorization.

## Verify changes

For runtime, catalog, test or publication-guard changes, run the relevant checks:

```bash
python3 scripts/check_locales.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 koreader-bridge.py --self-test
python3 scripts/check_publication.py --worktree --history
```

- Exercise both CLI names and cross-entry saved-run/restore compatibility when changing startup or packaging. Preserve historical package verification, archive bytes and lock identities.
- Use disposable temporary fixtures. Tests have no authorization to access physical Kobos or delete real recovery data. Run the macOS ditto fixture when changing archive/restore behavior.
- Run checks that cover the change. Documentation-only work needs link, CLI example and privacy checks; repeat runtime tests only when the change gives you a reason.
- Report what you observed and what remains unverified. Fixture and CI results do not validate physical devices. Keep acceptance tickets Ready for test until a human signs off.

## Deliver and publish

- Keep the public tracker, acceptance status and relevant docs current. Update the version/changelog when runtime behavior changes.
- Keep credentials, books, device data, runs and local instructions out of Git. Stage explicit public paths; inspect staged blobs and reachable history with the publication guard.
- Obtain appropriate user authorization before external publication or other consequential actions. Use a feature branch and PR; no automatic merge, force push, remote deletion or release publishing.
- Before a permitted push, verify origin and use scripts/publish.py with the exact OWNER/REPO and a reviewed English PR body. Never bypass a failing publication guard.
- Every PR creation or description update follows the [canonical template](.github/pull_request_template.md). Derive it from the actual base-to-head diff and current implementation/docs/evidence. Keep focused bullets, meaningful module summaries and separate local/CI/independent-review/pre-PR status. Humanizer wording edits preserve required structure, facts, risks and uncertainty.
- Validate the final Markdown with scripts/check_pr_description.py --body-file before submission; pass those exact reviewed bytes with gh pr create/edit --body-file or an explicit API body. Never use commit-message autofill. Replace the complete body after material changes. Handoffs supply actual commands, revisions/results/skips, review provenance and gaps; self-tests are not independent QA. No new agent roles, device authority or approval exceptions are implied.
- Start fresh sessions in the repository. Use the [session verification prompt](docs/DEVELOPMENT.md#fresh-session-verification); distinguish discovered instructions from explicit reads and static checks from actual session/worktree tests. Verify destination branch and guidance after a worktree transfer.
- If delegation is requested, give each agent a bounded task and the applicable instructions/context; do not assume every tool inherits the parent's full conversation. Delegation does not broaden permissions.
