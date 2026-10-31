# Security and privacy

KOReader Bridge handles private files from your readers. The native desktop app is still in development. Fixes go into the current development version; older copies may lack newer safety checks.

## Reporting

Do not post secrets, ebooks, raw device backups, unredacted logs, reading history, databases or serial numbers in public issues. Prefer a synthetic reproduction with the version, affected operation and a description of the failure. If GitHub's private vulnerability reporting is enabled for this repository, use its Security tab to report sensitive findings privately. Otherwise do not disclose exploit details or private data in public; request a private reporting route from the maintainer.

If credentials are exposed, revoke or rotate them. Deleting a file or adding it to `.gitignore` leaves both the credentials and earlier Git history unaffected.

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

Connected-reader discovery reads only bounded native identity metadata and macOS USB storage ancestry; it does not scan books or open the reader database. Serial comparison stays in helper memory. Discovery returns a session-keyed opaque token, model/warning/storage display fields, never the raw serial or fingerprint. Selected connections are revalidated at core write/restore/eject checks. Manual model correction requires confirmation and cannot repair missing/mismatched identity. Device metadata and USB descriptors are consistency checks, not cryptographic hardware attestation; other software and physically spoofed devices are outside this trust boundary. Sequential CLI operation retains its existing fingerprint guards.

The app creates new host directories with permissions 0700 and files with 0600. It does not recursively change permissions in existing output folders. It preserves unknown preference fields and run data, and refuses to overwrite malformed preferences or formats from a newer version. Backups are unencrypted and may contain credentials.

There is no telemetry, runtime downloader or launch-time network requirement. Build-time runtime acquisition is pinned by size/SHA-256; maintainers must audit/update the lock for security fixes. Local ad-hoc signing is not Developer ID authentication or notarization. The development app has no App Sandbox entitlement; validation/OS permissions are not a claim of sandbox isolation.

Public screenshots must be manually inspected sample-only captures with no personal paths or metadata. Synthetic USB discovery/eject does not certify hardware, rendering or recovery after power loss.

Connected-reader migration review is scoped to one operation and the selected USB connections. Consolidating ordinary prompts does not grant blanket consent: model exceptions and final writes still stop, required archives are verified, and connection identity is rechecked before writes. Restore and deletion keep their dedicated confirmation rules. The CLI does not inherit desktop review choices. UI language changes do not alter safety decisions, paths, identifiers or stored backup schemas.
