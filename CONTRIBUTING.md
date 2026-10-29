# Contributing

Current source uses `koreader-bridge.py`; the adjacent `kobo-koreader-migrate.py` remains the shared engine and compatible CLI. Keep both and the locale assets in distributions. Test both entry names when changing startup, locking or packaging.

Start with README.md for usage and AGENTS.md for shared development guidance. Use TRACKER.md when planning features and ACCEPTANCE.md for manual verification. Public code, comments and canonical developer documentation use English; owned user-facing translations belong in reviewed locale catalogs.

## Runtime requirements

All features must run as standalone offline code. AI-assisted development is welcome, but the released tool must not depend on inference APIs, downloaded models, model servers, agent frameworks or an active assistant session.

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

Report the tool/macOS/Python versions, mode, expected behavior and a minimal synthetic reproduction or redacted message. Do not attach actual books, serials, settings, databases, raw logs, manifests or archives. Follow SECURITY.md for sensitive findings.

Contributions are under the MIT License. Do not add copied KOReader/device assets or third-party books/fonts/plugins.

## Native macOS development

Build/launch: `python3 scripts/build_macos_app.py --launch`. Verify the actual app: `python3 scripts/verify_macos_app.py "/path/to/KOReader Bridge.app"`. Tests use isolated synthetic readers and capture only the app's own window. See [Mac instructions](docs/MACOS.md) and [desktop architecture](docs/DESKTOP_ARCHITECTURE.md).

Preserve CLI behavior/schemas and core validation. Add malformed-input and workflow regressions for protocol changes. Never automate real-reader writes. Keep binaries, preferences, runtime/research caches, raw outputs and private notes out of Git; manually review synthetic screenshots before publication.
