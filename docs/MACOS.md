# KOReader Bridge for macOS
Development SwiftUI app for the existing offline Kobo migration core.
Build: python3 scripts/build_macos_app.py
The builder prints a fresh .app path and preserves older builds. Open that .app in Finder or use open with its printed path.
Requires Apple Silicon and macOS 14+. Building needs Apple command-line Swift tools, Python 3.9+, and a first-build download of the checksum-pinned CPython runtime. Launching needs no shell Python or network.
Use Migration to choose scope and preview changes. Confirm reader roles and compatibility at the core prompts. Only connect the requested reader, one at a time. Backups shows existing batches; choose a private existing CLI output folder in Settings to reopen them. Saved-source and exact-target restore buttons require the appropriate snapshot files. Cleanup previews protection before deletion and requires exact typed confirmation.
Try sample readers creates explicitly synthetic data in a separate private workspace; Leave sample session returns to the real output folder. Sample readers do not access USB volumes.
Preferences save to the current account's Application Support/KOReader Bridge. Unknown preference fields are retained. The selected output folder holds runs/<run-id>/ using existing CLI schemas. Keep these folders private; backups can contain credentials and reading history.
The native app interface is English; core workflows support en, zh-Hant and zh-Hans. Runtime/build details are visible in Settings.
Local builds are ad-hoc signed, not Developer ID signed or notarized. They are development builds, not an App Store or public DMG release. Public distribution requires a maintained runtime update process, Developer ID, hardened-runtime review, signing nested code, notarization/stapling, release verification and controlled hardware acceptance. Intel packaging is not implemented.
