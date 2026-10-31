# Troubleshooting

[Home](../README.md) · [Usage](USAGE.md) · [Recovery](RECOVERY.md) · [Troubleshooting](TROUBLESHOOTING.md) · [Development](DEVELOPMENT.md) · [Maintaining](MAINTAINING.md)

Check the recorded phase and run status first. If recovery is uncertain, keep the backups. Do not bypass identity, archive or path checks to continue.

## Common messages

| Message or symptom | Action |
| --- | --- |
| Waiting for SOURCE/TARGET | Choose USB Connect on the Kobo. Check the data cable and that macOS mounted a volume containing `.kobo/`. Connect only the requested device. Ctrl-C cancels waiting. |
| More than one Kobo mounted | Disconnect the other Kobo and restart. The tool refuses ambiguous device selection. |
| Model hint differs from the physical model | Logs may have been copied. Enter the physical label and verify the role. Do not treat the log hint as proof. |
| No device fingerprint | Check that the device's `.kobo/version` is present/readable. The tool refuses writes without an identity guard. |
| Statistics pending WAL data | Disconnect safely, open/quit KOReader cleanly, reconnect and retry. Do not delete database WAL files to silence the warning. |
| Long archive/hash/comparison | Read the latest phase/heartbeat. Large CBZ/EPUB files and slow USB storage can take time. Avoid unplugging during active writes. |
| Insufficient Mac/target space | Choose another local backup root or free space intentionally, then rerun the preview. |
| Cancelled before target modification | A No/empty response declined a confirmation. Existing backups remain; this is a normal cancellation, not a failed copy. |
| Archive/manifest verification failed | Keep originals, do not edit manifests to bypass checks. Recapture SOURCE or select a known valid batch. |
| Device changed/disconnected | Stop. Reconnect the original device and inspect the run/backups. The tool refuses rollback onto a different device. |
| `needs-recovery` | Keep all artifacts. Reconnect the original TARGET; inspect reports and try a verified `--restore-run ... --dry-run` if a complete modern snapshot exists. Otherwise recover manually from backups. |

When copying, restoration or verification fails, the tool attempts automatic rollback while the original TARGET is connected. Power loss, forced termination, hardware failure or disconnection can prevent recovery. A checksum checks the captured bytes; it cannot tell whether settings make sense or are compatible.

## Exit codes

Exit code `0` covers success, a completed audit or preview, and ordinary cancellation; check `run.json` for the result. Code `1` indicates an error; the run record tells you whether TARGET may need recovery. Code `2` means an operation failed and rolled back successfully, or the argument parser rejected a command before a run began. Code `3` means rollback failed or is incomplete and recovery is needed. Code `130` records an uncaught user interruption. An interruption caught during copying inside a transaction may return the rollback code instead.

## Reporting a problem

Use [GitHub Issues](https://github.com/gh-slee/koreader-bridge/issues) for reproducible bugs and feature requests. Include the tool/macOS/Python versions, mode, expected result and a minimal synthetic reproduction or redacted error message. Never upload actual books, device backups, serials, raw settings, databases or unredacted logs/reports.

For sensitive security findings, follow [SECURITY.md](../SECURITY.md) instead of disclosing private data in a public issue. The repository is maintained by its [project contributors](https://github.com/gh-slee/koreader-bridge/graphs/contributors); contribution instructions are in [CONTRIBUTING.md](../CONTRIBUTING.md).
