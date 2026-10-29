# Security and privacy

This tool handles private device files; the native desktop app is a development build. Only the current development version receives fixes; older copies should not be assumed to contain current safety checks.

## Reporting

Do not post secrets, ebooks, raw device backups, unredacted logs, reading history, databases or serial numbers in public issues. Prefer a synthetic reproduction with the version, affected operation and a description of the failure. If GitHub's private vulnerability reporting is enabled for this repository, use its Security tab to report sensitive findings privately. Otherwise do not disclose exploit details or private data in public; request a private reporting route from the maintainer.

Credential exposure requires revocation/rotation of affected credentials. Removing a file from Git or adding it to `.gitignore` does not revoke a secret or remove it from existing history.

## Safety boundaries

- SOURCE is not intentionally modified. Lua is never executed and plugins are not invoked.
- Target changes follow backups and confirmations; archive hashes, paths, symlinks and collisions are checked.
- Device fingerprint checks and OS locks protect participating workers. Old workers and other programs may not honour those locks.
- Caught failures attempt rollback. Power loss, disconnection and hardware failure may need manual recovery.
- Backups are not encrypted. Store them privately, including output roots outside the repository.
- Publication checks enforce a source-file allowlist and common secret/path heuristics. They cannot prove that arbitrary text is free of personal data. Review staged content and history before upload.

Do not weaken path validation, fingerprint guards, confirmations or backup requirements to work around an error. Preserve original artifacts while investigating a recovery failure.

## Native application boundary

The app bundles a checksum-pinned CPython runtime and invokes an allowlisted helper through Foundation.Process. It does not expose a shell, arbitrary commands, plugins or Lua. stdout is bounded versioned JSON; prompts are bound to their pending request. Core identity, archive/path, capacity, lock and recovery protections remain active. Common secret tokens are redacted from displayed diagnostics; private raw recovery logs must not be published.

New host directories use 0700 and files 0600. Existing output folders are not recursively chmodded. Unknown preference fields and run data are retained; malformed/future preferences are not overwritten. Backups are unencrypted and may contain credentials.

There is no telemetry, runtime downloader or launch-time network requirement. Build-time runtime acquisition is pinned by size/SHA-256; maintainers must audit/update the lock for security fixes. Local ad-hoc signing is not Developer ID authentication or notarization. The development app has no App Sandbox entitlement; validation/OS permissions are not a claim of sandbox isolation.

Public screenshots must be manually inspected sample-only captures with no personal paths or metadata. Synthetic USB discovery/eject does not certify hardware, rendering or recovery after power loss.
