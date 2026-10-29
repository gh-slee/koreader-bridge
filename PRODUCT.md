# KOReader Bridge
## Platform
Native macOS desktop application and compatible offline Python CLI.
## Users and purpose
Kobo owners moving an installed KOReader setup, supported books and reading data between readers, with inspectable plans and retained recovery copies.
## Workflows
Preview and migrate FULL/KOREADER/LIBRARY/AUDIT; inspect local batches, reuse a saved source, restore a target snapshot, and review protected cleanup.
## Constraints
Preserve existing core validation, schemas, locks and rollback. SOURCE stays read-only. No runtime LLM, network or shell dependency. No non-Kobo support or universal plugin compatibility claim.
## Stack
User-specified Swift and SwiftUI with AppKit. A bundled, pinned CPython runtime executes the existing standard-library engine through a bounded versioned JSON helper.
## Visual direction
User-specified InkKit architectural and native UX reference: sidebar navigation, native forms/tables, explicit review, private backups. Existing KOReader Bridge branding is retained; this is an operational tool, with adaptive system appearance and SF Symbols.
