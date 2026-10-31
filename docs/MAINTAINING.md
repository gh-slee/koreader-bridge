# Maintainer guide

[Home](../README.md) · [Usage](USAGE.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Maintaining](MAINTAINING.md)

Use this guide to prepare repository changes and releases. You still need authorization before uploading data, merging changes or publishing a release.

## Publication privacy

Backups can contain plugin API credentials, device identifiers, reading history, annotations and book filenames. Logs/manifests/reports can also reveal personal information. Keep `runs/` private, including runs stored with a custom `--backup-dir`. Do not attach raw archives, device databases, settings or reports to public issues. Share a minimal redacted reproduction using synthetic files.

`.gitignore` excludes runtime batches, copied Kobo trees, sidecars, books, fonts, databases, common credentials/private keys and local private notes. Publication additionally checks **the staged Git blobs and reachable history**, because ignoring a file does not untrack it or remove prior commits.

```bash
# Before the first Git commit, check candidate public source files.
python3 scripts/check_publication.py --worktree

# Before committing/pushing, check actual index and history.
python3 scripts/check_publication.py --history

# Install this repository's pre-push guard in this clone.
git config --local core.hooksPath .githooks
```

The guard allows only reviewed source/docs/test paths and detects common secrets/personal absolute paths without printing matching values. It is a heuristic defence, not a guarantee that all personal data can be detected. Review staged diffs and commit author identity. The history guard requires GitHub user noreply author/committer emails, with one exception: merge commits may use the exact public platform committer address `noreply@github.com` used by GitHub PR test merges. Authors still need user noreply addresses; personal and lookalike emails remain blocked. Commit messages are scanned too. New public file paths require an intentional allowlist update. CI checks after upload; the local hook is the guard before upload. Hooks can be bypassed, so maintainers must also follow [CONTRIBUTING.md](../CONTRIBUTING.md).

Private instructions remain prohibited even if force-added: the guard checks index blobs and each locally reachable commit, including files deleted from the latest tree. Isolated Git regression fixtures cover root/nested AGENTS.override.md and local notes. Retain allowlist entries needed to inspect historical public paths after removing those paths from the current tree. History remediation requires separate review; moving or deleting a current file does not erase earlier commits.

Before each publication, review the exact staged diff, commit range, destination and public PR text, report current validation/privacy findings, and obtain the applicable operator's approval. Changed scope needs renewed approval; credentials, helper flags and earlier approvals are not consent for another push. Stage only explicit reviewed public paths. Never upload private instruction contents as evidence. The guard does not detect every secret, personal fact or sensitive semantic detail; human review remains necessary.

## PR helper

Maintainers can use GitHub CLI; migration does not need it. Sign in through its browser and OS credential-store flow. Never print tokens or paste credentials into source, logs, issues or an AI chat.

Use the [canonical PR template](../.github/pull_request_template.md) for creation and updates. Build its summary/file groups from the actual base-to-head diff and current behavior. Keep local checks, CI runs, independent QA/reviews and pre-PR validation separate. Link exact CI revisions/runs only after observing them; report pending/not-run/failed checks. Developer self-testing is not independent QA. Handoffs preserve actual commands, counts/skips, review provenance, risks and gaps. Humanizer may improve wording while retaining required headings and evidence.

Before opening a PR, report the publication and privacy checks, locales, tests, self-test and any required native build, launch and visual checks. Name the reviewed revision and explain gaps. This project does not inherit an image approval requirement from another project. Existing approval and manual/device acceptance rules still apply. The template and its validator check structure; they cannot verify claims or grant permission.

When authorized to publish a committed, clean feature branch, prepare and validate a reviewed English PR body, then run:

```bash
python3 scripts/check_pr_description.py --body-file /tmp/pr-body.md
python3 scripts/publish.py --repository OWNER/REPO \
  --title "Explain the change" --body-file /tmp/pr-body.md
```

Use the repository identity shown by origin. The helper checks the destination, branch, working-tree cleanliness, PR content, privacy, locales, tests and self-test. It saves the validated Markdown in a private temporary file and performs a normal push. It passes `--body-file` explicitly when creating a PR or replacing its title and body, without autofill. Replace the complete description after material changes; keep session notes out of it. The helper cannot merge, force-push or publish releases, and it does not replace the operator's approval requirements.

## Release readiness

Before a release, verify the intended commit, version/changelog, complete source distribution and required human acceptance. Include locales/ even for English; do not advertise a single downloaded Python file as a complete installation.

The README clone command and CI badge target main. Download instructions must distinguish the currently published testing package from unpublished candidate source. Keep installation instructions and badge scope aligned with the actual default/release branch when release policy changes. Do not advertise nonexistent binaries, package-manager packages or hardware certification.

Confirm that user/developer links work in a clone and an extracted source archive. Keep public instructions generic, and keep personal preferences, credentials and session histories local. Existing public Git history is not erased by reorganizing current files. Release publication, merge and remote deletion are separate authorized actions; the helper does not perform them.

## Versioning and first stable release

The first stable public compatibility baseline is **1.0.0**, following the published **1.0.0-rc.1** and internal source candidates. This is an explicit one-time numbering reset from the earlier 3.x development series, continuing the same implementation. Existing published tags, release bodies and assets remain unchanged; check the release list for actual publication.

SemVer compares 1.0.0 below 3.3.0-dev.6. Do not select the current release by greatest tag or assume automatic Latest selection handles this reset. Public notes must explain the transition, link the intended release explicitly and distinguish the latest *published* package from unpublished source. The CLI does not auto-update. Creating tags/releases or selecting GitHub Latest still requires exact-scope publication approval; prereleases stay marked prerelease/not Latest, and the approved stable release must be explicitly selected as Latest.

The reset changes the runtime VERSION and resulting version metadata, not CLI tokens/options, confirmation defaults, mode scope, exit semantics, schema versions or the run-directory layout. Version strings in old run/manifest records are provenance, not a numerical minimum-version check. Supported valid 3.x snapshots must remain readable subject to the existing schema/identity/path/integrity checks. Do not rewrite old records, regenerate their manifests or delete snapshots to match the new number. Cross-version synthetic tests cover saved-source reuse and exact TARGET restore.

For 1.0.0, the public compatibility surface includes documented CLI flags/modes, exit meanings and supported versioned run/snapshot/manifest schemas. Console wording/progress formatting is human presentation, not a parsing API. Supported-host limits remain macOS/Python 3.9+ for device operations; Linux CI validates fixtures only. Do not claim every device/build/plugin is compatible: physical roles and SOURCE build compatibility still require operator confirmation. Any later incompatible contract change requires a major-version decision; compatible features use minor versions, fixes use patches. This policy begins with the new 1.x sequence; historical numbering remains documented rather than retroactively changed. See [SemVer](https://semver.org/).

Before stable publication, review the [release criteria and validation limits](../ACCEPTANCE.md#first-stable-release-gates), fix known blocking defects, freeze an exact candidate and run normal checks plus package prepare/verify. The 1.0 baseline keeps all modes and uses scoped KOREADER hardware evidence; incomplete successful FULL/LIBRARY physical copying and remaining comprehensive human review are prominently disclosed acceptance follow-up. Do not mark those tests passed or silently broaden supported hardware. Final publication approval must cover these limits as well as the exact commit/assets/public metadata/privacy. Version/changelog/notes must match the final source; revalidate the exact stable package. A source version is not publication evidence, and source-push approval does not grant release approval.

## Local package preparation and verification

The helper is included in the published [1.0.0-rc.1 package](https://github.com/gh-slee/koreader-bridge/releases/tag/v1.0.0-rc.1), the earlier 3.3.0-dev.6 package and this source snapshot. The older 3.3.0-dev.2 pre-release predates the helper. Preparing a new candidate never modifies a published release or its assets.

Use Python 3.9+ and Git in a reviewed clone containing `scripts/prepare_release.py`. No GitHub CLI, network, Kobo, third-party Python package or AI service is needed. Commit reviewed public changes first if they should be included. The explicit ref selects Git objects: modified, untracked and ignored working files are never packaged. Selecting an older commit deliberately excludes later changes. Only execute extracted smoke checks from code you have reviewed; the publication guard is not a sandbox for arbitrary code.

```bash
python3 scripts/check_publication.py --history
python3 scripts/prepare_release.py prepare --ref HEAD
```

Source declaring the KOReader Bridge project name must include the canonical entry; its adjacent engine remains required. Historical refs without that declaration are still supported. Verification derives prefix and available entry points from the selected Git tree, not the numerically greatest version or working files. Existing package records/ZIPs are never renamed.

The preparation command:

1. Resolves the exact local commit and reads its guarded tracked files, rejecting symlinks, submodules, unsafe content and missing required runtime/locale/documentation assets. It reads VERSION as a literal without importing source code.
2. Builds a ZIP containing a single `koreader-bridge-VERSION/` directory for source containing the canonical entry, preserving ordinary/executable modes. Historical source without it retains the `kobo-koreader-migrate-VERSION/` prefix. Timestamps and entry order are fixed; byte-for-byte reproducibility across different compression-library versions is not promised.
3. Compares every ZIP member against Git before extracting it into a disposable directory. It checks local Markdown/HTML file links and runs locale validation plus version/help/list-locales, Traditional Chinese preview and self-test through both entries (11 checks). Historical source uses its original legacy entry (six checks). No full unit suite or hardware test is implied; run the normal development checks separately.
4. Creates `.local/releases/VERSION-COMMIT/` only after verification succeeds. It contains the ZIP, `SHA256SUMS` and local-only `PREPARATION.json` with the exact source commit and per-file hashes/modes/sizes. It never reads run/backup contents. Existing destinations are refused, including older preparation records; no overwrite or cleanup is attempted. Use `--output-dir` for another ignored/private parent if desired.

Reverify later using the printed directory and an independently chosen expected commit/ref (replace DIRECTORY and COMMIT):

```bash
python3 scripts/prepare_release.py verify DIRECTORY --ref COMMIT
```

Verification reads Git again, checks the ZIP against its checksum and record, rejects missing, extra or duplicate members, and reruns the extracted checks. A replaced checksum or preparation record cannot establish provenance on its own. Local Git objects are required. KM-010 tracks a separate standalone Kobo-backup verifier. For downloaded releases, `shasum -a 256 -c SHA256SUMS` detects mismatches with the supplied checksum; it does not authenticate the publisher.

CI runs preparation for its checked-out commit on all supported fixture hosts and Python versions. It does not upload packages or publish releases. Human publication review must still cover release notes, public metadata, exact commit/assets and remaining acceptance limitations. The helper does not generate or publish release notes, create tags, push branches or access the network/devices. Upload only the reviewed ZIP and checksum; keep PREPARATION.json local. A published pre-release invites controlled testing and is distinct from stable-release acceptance.

Release documents are immutable source snapshots. State the snapshot version without predicting its publication state; record publication facts only for releases that already exist, and pin example download commands to those actual assets. Link the release list for later packages. Before publication, check that command filenames and extraction directories exist in the linked release, and explain which version the examples install. Keep exact-commit validation evidence separate from newer source and from human/hardware acceptance. This avoids shipping a candidate whose own documents become false as soon as it is published.

Local builds may share a runtime version while carrying different source commits. Before another public release, assign a new version/tag and review its final commit and assets; do not reuse or replace the published pre-release tag/assets. No preparation result grants permission to publish.


## Repository identity and rename (KM-020)

The public project is **KOReader Bridge**, and the canonical repository is **`gh-slee/koreader-bridge`**. The existing `gh-slee/kobo-koreader-migrate` repository was renamed in place; no replacement repository or private source/data upload was used. The legacy CLI filename `kobo-koreader-migrate.py`, version, backup schemas and already-published archive names remain unchanged. Current source adds `koreader-bridge.py` as its canonical entry. Local checkout/output folders do not need to be moved.

Post-rename verification confirmed the same repository ID and all branch/tag refs, preserved 11 issue/PR identities and all three existing releases, and downloaded all six assets to compare SHA-256 with the pre-rename baseline. Release bodies/flags and asset names/sizes/digests remained unchanged. Both old and new Git URLs resolve to the baseline refs; the old API route resolves to the same repository. The existing exact-main CI still passes all six jobs. This is continuity evidence, not new source CI or human/device acceptance.

New clones use the canonical README command. For an existing clone, explicitly set and verify origin:

```bash
git remote set-url origin https://github.com/gh-slee/koreader-bridge.git
git remote -v
```

Use `--repository gh-slee/koreader-bridge` with `scripts/publish.py`. The active maintainer clone also uses this origin and GitHub CLI default. Audit other clones, CLI defaults and integrations separately. Update current clone/directory commands, CI badges, issue/contributor links and release/document links through reviewed source changes; do not rewrite historical Git commits or replace published assets. Repository About metadata is separate from source documents and should be reviewed when changed.

GitHub redirects cover web and ordinary Git operations. Do not recreate the old repository slug, because that can remove redirects. GitHub Pages URLs and references to hosted actions/reusable workflows require separate attention if used; this repository currently has no Pages site, consumes external checkout/setup actions and does not expose its own action or reusable workflow.

For any future rename, first review the exact old/new identity, verify availability/admin access, retain repository/ref/issue/PR/release/asset baselines and obtain approval. Rename the existing repository, update remotes/current links and verify continuity, downloads and exact-commit CI afterward. Keep private records and backups local. See [GitHub repository rename documentation](https://docs.github.com/en/repositories/creating-and-managing-repositories/renaming-a-repository) and the [GitHub CLI rename reference](https://cli.github.com/manual/gh_repo_rename). Renaming does not grant permission for a source push, release, device operation or backup cleanup.

## Native app distribution

Build with `python3 scripts/build_macos_app.py`. Maintain `desktop/runtime-lock.json` by reviewing CPython/standalone security and licenses, then updating version, release URL, byte count and SHA-256 together. Never bundle a maintainer's shell Python or personal environment.

Local builds use fresh ignored directories and ad-hoc signing. Public distribution needs an architecture/OS policy, maintained runtime, Developer ID, hardened-runtime/entitlement review, nested signing, notarization/stapling and reviewed DMG/ZIP download verification. Existing outputs/historical releases remain intact.

GitHub About/topics/release descriptions are separate metadata. Audit them, but do not change them without scoped authorization. v1.0.0 predates the native app and remains a CLI release.
