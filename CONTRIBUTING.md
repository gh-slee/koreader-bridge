# Contributing

Current source uses `koreader-bridge.py`; the adjacent `kobo-koreader-migrate.py` remains the shared engine and compatible CLI. Keep both and the locale assets in distributions. Test both entry names when changing startup, locking or packaging.

Read README.md for usage and AGENTS.md for development rules. Check TRACKER.md before planning a feature, and use ACCEPTANCE.md for manual tests. Write public code, comments and canonical developer documentation in English. Put translated interface text in the reviewed locale catalogs.

## Runtime requirements

Every feature must work as standalone offline code. You may use AI while developing it. Users must not need inference APIs, downloaded models, model servers, agent frameworks or an active assistant session to run the tool.

Preserve the existing mode semantics and data protections described in AGENTS.md. Use disposable synthetic devices and never execute device Lua. Fixture tests do not authorize physical-device operations or real backup deletion.

## Development workflow

1. Check existing issues and the tracker before a substantial change. Keep PRs focused and describe the problem and intended behavior.
2. Create a feature branch from an up-to-date main and target main with your PR. The complete development implementation is available on main.
3. Implement the change and add meaningful regressions for changed behavior or safety boundaries. Update relevant documentation and feature/acceptance status; update version/changelog when runtime behavior changes.
4. Run checks appropriate to the change. For runtime, catalog, test or guard changes, use the commands below. Documentation-only changes need link/example/privacy checks.
5. Inspect the exact staged diff and reachable history. Keep credentials, private instructions and device artifacts out of Git; use explicit file paths when staging.
6. Publish your reviewed branch to the appropriate fork or repository and submit a PR with changes, validation and limitations. Agents acting on someone's behalf must follow that person's publication authorization; these instructions grant no upload or merge permission.
7. Wait for maintainer review and required human acceptance. Do not infer release or hardware readiness from CI alone.

```bash
python3 scripts/check_locales.py
python3 -m unittest discover -s tests -p 'test_*.py'
python3 koreader-bridge.py --self-test
python3 scripts/check_publication.py --worktree --history
git diff --cached
```

Tests use temporary fixtures. On macOS, the actual ditto fixture exercises archive/restore behavior without reading a physical Kobo. Run it when changing those workflows. Linux CI validates fixtures, not Linux device migration.

## Working with coding agents

Use the shared [AGENTS.md](AGENTS.md) and [coding-agent setup guide](docs/DEVELOPMENT.md#coding-agents). The latter explains optional official Codex local instructions and worktree behavior. Contributors remain responsible for reviewing and validating AI-assisted changes.

## Publication privacy and maintainer tooling

Keep private data and local instructions out of Git. Review staged content and reachable history with the publication guard before uploading. See the [maintainer guide](docs/MAINTAINING.md) for the exact email/allowlist policy, local pre-push hook, PR helper and release preparation. Publication still requires the applicable operator authorization.

## Reporting and licensing

When reporting a problem, include the tool, macOS and Python versions, the mode and what you expected to happen. Provide a small synthetic reproduction or a redacted message. Keep actual books, serials, settings, databases, raw logs, manifests and archives out of the report. Follow SECURITY.md for sensitive findings.

Contributions are under the MIT License. Do not add copied KOReader/device assets or third-party books/fonts/plugins.

## Native macOS development

Build/launch: `python3 scripts/build_macos_app.py --launch`. Verify the actual app: `python3 scripts/verify_macos_app.py "/path/to/KOReader Bridge.app"`. Tests use isolated synthetic readers and capture only the app's own window. See [Mac instructions](docs/MACOS.md) and [desktop architecture](docs/DESKTOP_ARCHITECTURE.md).

Preserve CLI behavior/schemas and core validation. Add malformed-input and workflow regressions for protocol changes. Never automate real-reader writes. Keep binaries, preferences, runtime/research caches, raw outputs and private notes out of Git; manually review synthetic screenshots before publication.

## Pull request descriptions

Use the [canonical PR template](.github/pull_request_template.md) when opening or updating a PR. Start with the problem and resulting behavior, then explain the changes in a few focused bullets. Group related files and use repository-relative paths. Report local checks, remote CI, independent review and required pre-PR validation separately, including checks that have not run. Include compatibility details, material risks and reviewer guidance where needed. UI evidence must show current synthetic data. Remove unused optional sections; a small change should have a short description.

Validate the final body with `python3 scripts/check_pr_description.py --body-file /tmp/pr-body.md`. Pass the same complete Markdown through `--body-file`; do not rely on commit-message autofill. Editorial/Humanizer guidance cannot remove required sections or weaken technical precision. This structure does not certify claims or grant publication permission.

For native UI changes, update all three catalogs under `macos/locales/`, run `python3 scripts/check_native_locales.py`, and verify the built app with isolated sample readers. Check language switching, reopening preferences, translated confirmation wording and compact-window layout. Do not translate user data, schema tokens or infer message IDs from diagnostic strings. See [desktop architecture](docs/DESKTOP_ARCHITECTURE.md).
