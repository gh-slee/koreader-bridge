# Native desktop architecture

SwiftUI handles navigation, forms, tables, file selection and confirmation sheets. AppKit handles Finder integration, app termination and captures of the app's own rendered content. InkKit is the reference for architecture and UX. The implementation uses KOReader Bridge's migration core and its own device and configuration logic.

## Backend communication

The app starts a bundled, pinned Python interpreter through Foundation.Process, using an absolute executable path, isolated mode and a minimal environment. Each helper process handles one allowlisted request. Ordinary operations return bounded, versioned JSON. Migration streams bounded progress and explicit prompts before returning a final response.

stdout carries only protocol messages. Diagnostics strip control sequences and common secret tokens. Unexpected failures return a generic error without a traceback.

The available operations are health, devices, catalog, details, cleanup_plan, create_demo and execute. Protocol v1 adds optional readerSession and typed workflow readers while preserving older callers. New clients receive physical connection choices; callers without readerSession keep the earlier hint-only discovery response.

Execute maps allowlisted typed options to existing CLI arguments and adapts reader selection and presentation. It cannot run arbitrary commands, modules or code, edit arbitrary files or execute Lua. Previews are the default, and writes still require confirmation.

## Reader identity

bridge_devices.py reads bounded native .kobo/version metadata through no-follow descriptors and maps model codes locally. It queries a bounded, timed macOS IOUSBHostDevice storage subtree, matches BSD device numbers to mounted filesystem device numbers and compares serials in memory. Shared or unknown product IDs do not establish a unique model.

Native/USB model conflicts require confirmation. Unreadable or duplicate identity, ambiguous storage ancestry and mismatched USB serials leave a reader unselectable. Discovery responses omit raw serials and fingerprints.

Connection tokens are HMACs keyed by a random per-app-session value over the mount, native identity and USB connection metadata. The app assigns tokens to roles explicitly. Reconnecting, remounting or changing metadata invalidates the selection and its approval.

Manual model correction needs a native confirmation sheet and another default-No confirmation during execution. It changes the role's model label without changing physical identity. The adapter accepts only currently discovered tokens and rechecks them at core confirm_device and safe_eject boundaries.

Existing core checks still cover fingerprints, same-device refusal, locks, capacity, archives, paths, compatibility, backups and rollback. The app archives and verifies SOURCE before the TARGET phase; it does not introduce direct copying without a backup. Sequential CLI behavior and run/snapshot schemas stay unchanged.

Mount and unmount notifications, plus a three-second idle refresh, update reader choices. Active migrations pause idle discovery. Synthetic sessions use marked, isolated directories and an explicit fake USB graph instead of host inventory.

## Operation lifetime and storage

Each app instance permits one active operation and disables conflicting controls. Core project and device locks also coordinate with other app and CLI processes. Stop sends SIGINT so the core can cancel or recover gracefully. The app never force-kills a writing backend, and active work blocks closing or quitting.

Ordinary requests time out after 60 seconds, runs have a 24-hour deadline, and pending core confirmations expire after 15 minutes. Wait for recovery to finish before disconnecting, even when it is slow.

Preferences preserve unknown fields and refuse to overwrite corrupt data or future formats. New private host directories use 0700 and files use 0600. Device data stays in the chosen private workspace and never enters the application bundle.

The build bundles only explicit inputs and checksum-pinned, relocatable CPython. It excludes caches, research, device data, real archives and local instructions.

## Synthetic verification and captures

The helper creates private sample directories with simulated discovery and eject, plus confined archive paths. These tests use the actual core migration, archive and restore functions and real ditto. They cannot certify firmware, rendering, fonts or physical hardware.

The developer launch flag --test-root selects isolated preferences. --integration-test exercises the actual Swift Process transport, synthetic workflows and persistence, then captures the app's own view in light and dark appearance. It captures no other windows or private reader data.

Captures first use a public CoreGraphics shim that checks the window belongs to the current process. It cannot capture other processes. A targeted system-capture fallback and a labelled NSView fallback are available. Incomplete NSView captures must not be reported as complete screenshots. The CoreGraphics API is deprecated on newer SDKs and is used only for development verification.

## Per-operation migration review

Protocol v1 accepts optional typed `config.review` only for explicitly bound migration or saved-source workflows. Its fields are `rolesConfirmed`, `compatible`, `identity` (`preserve`, `new`, `clone`) and `cloneConfirmed`. Boolean values must be actual booleans; unknown fields and invalid choices are rejected.

The review applies to this request's physical reader tokens. Approval is never saved in preferences or reused for another request. FULL/KOREADER writes require compatibility acknowledgement, and cloning requires explicit acknowledgement. Preserve creates a new identity only when TARGET has none.

The adapter reuses only reviewed start, role, compatibility and identity choices. Reusing a role still revalidates the connection and selected model. It never automatically answers the final migration question, model exceptions, restoration, deletion or unrecognized prompts. Source and TARGET backups must still be verified, and identity is checked again before writes.

Read-only connected previews skip redundant review and compatibility questions. Callers without `review`, including the CLI and sequential desktop mode, keep existing behavior and schemas.

## Native localization

During the explicit-input build, reviewed `macos/locales/{en,zh-Hant,zh-Hans}.json` catalogs become standard `.lproj/Localizable.strings` resources. The app looks up the chosen bundle directly, so Settings → Language updates all four pages and owned sheets without restarting. The locale environment also reaches native SwiftUI controls.

Preferences keep the selected language and unknown fields. Each core request receives a fixed locale; existing output and saved diagnostics are not translated again.

Native labels use explicit keys and named placeholders. Device warning codes and owned helper progress and prompt IDs are separate from compatible English diagnostics. Cleanup protection keeps the core's structured reason ID. The UI never guesses localization IDs from rendered core text.

Machine schemas, model names, user data and paths, old raw reasons and external diagnostics keep their original form. Unsupported locales or missing resources fall back to English. Catalog parity and placeholder checks reject incomplete build inputs.
