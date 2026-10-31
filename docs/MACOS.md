# KOReader Bridge for macOS

The SwiftUI app uses the existing offline Kobo migration core.

## Build and launch

Build: python3 scripts/build_macos_app.py

The builder prints the path to a new .app and keeps older builds. Open the app in Finder or use open with the printed path.

The app requires Apple Silicon and macOS 14+. To build it, you also need Apple command-line Swift tools and Python 3.9+. The first build downloads a CPython runtime and verifies its pinned checksum. The finished app includes Python and can launch without a network connection or shell Python.

## Choose readers

The Migration page refreshes connected readers automatically. Enable Choose from connected readers to keep both Kobos connected and select their roles from the menus. Each entry shows its model and volume. The app refuses to use the same reader for both roles.

Native version metadata identifies the model. The macOS USB storage graph and serial comparison associate it with the mounted reader. Volume names and plug order do not prove identity.

If identification is wrong or unknown, choose Correct model…. The sheet shows native and USB information and lets you select a known model or enter one. You must confirm the physical model. Unknown, conflicting or overridden labels also require confirmation during execution, with No as the default.

A model correction cannot bypass missing or mismatched USB identity, separate source and target roles, build compatibility or backups. Reader selections and correction approvals last only for the session. Reconnecting or changing identity requires a fresh selection; a saved model label does not restore approval.

To use the original sequential workflow, disable Choose from connected readers. Connect only the requested reader, one at a time, and enter its physical model when asked. The CLI keeps this workflow and its safeguards. Connected-reader mode needs readable native identity and a verified USB-to-volume association. If either is unavailable, reconnect or use sequential mode; changing the model label cannot establish identity.

## Review and migrate

Preview changes starts a read-only plan directly in connected-reader mode. Start migration opens a review of the physical roles and scope. FULL/KOREADER also require you to acknowledge that the source KOReader build can run on the target; the checkbox starts unchecked.

By default, the app keeps TARGET identity or creates one if it is missing. KOReader identity options also lets you generate a new identity or clone the source. Cloning needs a separate acknowledgement.

Back up and prepare captures and verifies the required archives automatically. Ready to migrate then shows the selected roles and asks for permission to write. Pressing Return selects Cancel migration. Unknown, conflicting and manually corrected models still need explicit confirmation. Sequential mode, restoration and typed deletion keep their original prompts.

The app verifies source archives before target writes and safely ejects each reader after its phase. Backups lists existing batches. Choose a private existing CLI output folder in Settings to reopen them. Saved-source reuse and exact-target restore use the selected target in connected-reader mode, with the original snapshot identity checks. Cleanup shows protection rules before deletion and requires exact typed confirmation.

## Samples, storage and language

Try sample readers creates synthetic data in a separate private workspace without accessing USB volumes. Leave sample session returns to the real output folder.

Preferences are saved in the current account's Application Support/KOReader Bridge. Unknown fields are preserved. The selected output folder stores runs/<run-id>/ using the existing CLI schemas. Keep these folders private: backups can contain credentials and reading history.

Settings → Language switches the interface immediately between English, Traditional Chinese and Simplified Chinese. The app remembers the choice when reopened. New core operations use that language; existing activity keeps its original language. External and technical diagnostics, model names, batch IDs and paths stay unchanged. Settings also shows runtime and build details.

## Distribution status

Local builds use ad-hoc signing and have no Developer ID signature or notarization. They are development builds; there is no App Store or public DMG release. Intel packaging is not implemented.

Public distribution still requires a maintained runtime update process, Developer ID, hardened-runtime review, signing of nested code, notarization and stapling, release verification and controlled hardware acceptance.
