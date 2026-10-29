# KOReader Bridge desktop design
Operate mode: a native Mac utility for deliberate, recoverable reader migration.
- NavigationSplitView sidebar: Migration, Backups, Cleanup, Settings.
- System typography and semantic colors, teal accent, native grouped forms, tables, toolbar and sheets. Follow system light/dark appearance.
- Migration configuration is separate from active progress. Core questions interrupt in a focused sheet; destructive confirmations default to decline.
- One active backend operation. Conflicting actions and settings changes are disabled. Cancellation requests graceful core interruption, never a forced kill.
- Empty screens explain the next action. Sample readers are opt-in, clearly labelled and isolated from real workspaces.
- Keyboard navigation, labelled symbols, selectable paths, scalable text and a resizable minimum window are required. Avoid decorative dashboards and invented metrics.
- Product defaults and actual capabilities outrank visual novelty. InkKit is the architectural reference; no InkKit user state or branding is copied.
