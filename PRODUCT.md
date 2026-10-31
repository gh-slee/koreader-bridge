# KOReader Bridge

## Platform

Native macOS desktop application and compatible offline Python CLI.

## Users and purpose

Kobo owners use the tool to move an installed KOReader setup, supported books and reading data between readers. They can inspect the plan before copying and keep recovery copies afterward.

## Workflows

Preview and migrate FULL/KOREADER/LIBRARY/AUDIT; inspect local batches, reuse a saved source, restore a target snapshot, and review protected cleanup.

## Constraints

Preserve existing core validation, schemas, locks and rollback. SOURCE stays read-only. No runtime LLM, network or shell dependency. No non-Kobo support or universal plugin compatibility claim.

## Stack

The app uses Swift and SwiftUI, with AppKit for Mac behavior. A bundled, pinned CPython runtime runs the existing standard-library engine through a helper with bounded, versioned JSON messages.

## Visual direction

InkKit is the requested reference for architecture and Mac UX: sidebar navigation, native forms and tables, explicit review and private backups. Keep KOReader Bridge branding. Use the system appearance and SF Symbols for this operational tool.
