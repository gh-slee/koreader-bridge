# KOReader Bridge desktop design
Operate mode: a native Mac utility for deliberate, recoverable reader migration.
- NavigationSplitView sidebar: Migration, Backups, Cleanup, Settings.
- System typography and semantic colors, teal accent, native grouped forms, tables, toolbar and sheets. Follow system light/dark appearance.
- Migration configuration is separate from active progress. Core questions interrupt in a focused sheet; destructive confirmations default to decline.
- One active backend operation. Conflicting actions and settings changes are disabled. Cancellation requests graceful core interruption, never a forced kill.
- Empty screens explain the next action. Sample readers are opt-in, clearly labelled and isolated from real workspaces.
- Keyboard navigation, labelled symbols, selectable paths, scalable text and a resizable minimum window are required. Avoid decorative dashboards and invented metrics.
- Product defaults and actual capabilities outrank visual novelty. InkKit is the architectural reference; no InkKit user state or branding is copied.

## Desktop layout
- Page content and activity use a centered column capped at 1000 points with 24-point horizontal gutters. Native grouped forms retain their own readable column; tables and action panels share the outer column.
- Empty states fill the available content viewport and center in both axes. The activity footer fills the detail pane and stays at the bottom.
- Backup/cleanup tables have explicit flexible height, balanced columns and full-ID help. Selected actions sit in one bounded panel; action groups reflow at narrow widths, and difference summaries use an adaptive grid.
- Review all four pages at 940x680, 1120x800 and 1440x900 in light/dark appearance, including empty, selected, protected, long-content and library states.
