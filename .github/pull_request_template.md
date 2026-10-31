<!-- Canonical format for PR creation and updates. Replace guidance with facts.
Required: Change Summary, Files Changed, Testing & Evidence with all four evidence
categories. Remove unused conditional sections. Keep small changes short.
Use concise English and focused bullets. Humanizer must preserve this structure,
facts, risk and uncertainty. Never include private context, owner paths or data. -->

## Change Summary

<!-- Explain the problem and resulting behavior in one sentence. Use 2-6 focused
bullets for the changes and decisions a reviewer needs to understand. Leave out
marketing copy and session history. -->

## Files Changed

<!-- Bullets with backticked repository-relative paths and short explanations.
Group meaningful modules (roughly 3-10 for large changes), not the whole diff list.
Include significant additions/removals and interface or migration changes. -->

## Testing & Evidence

### Local Verification

<!-- Bullets: PASS / FAIL / NOT RUN, actual commands, relevant counts and skips.
Use synthetic data. Link safe detailed evidence rather than pasting logs. -->

### CI Verification

<!-- PASS / FAIL / PENDING / NOT RUN, exact revision and actual run links.
Distinguish push and PR checks. Unpushed code has no remote CI result. -->

### Independent QA / Architecture Review

<!-- Independently performed reviews only: scope, outcome and safe evidence links.
Use NOT RUN when none occurred. Developer self-testing belongs above. -->

### Required Pre-PR Validation

<!-- Report publication/privacy checks and the core/native checks required for this
source. For desktop changes, include build, launch and visual results. Use PASS /
FAIL / NOT RUN / N/A and explain gaps. Follow existing approval requirements.
Fixtures and automated UI checks do not replace hardware or human acceptance. -->

## Behavior & Compatibility

<!-- Conditional: visible behavior, implemented versus planned features, CLI/API/
schema/config changes, upgrade needs and whether existing data needs migration. -->

## Risks, Limitations & Rollback

<!-- Conditional: material risks, unsupported scope and recovery/rollback limits.
Reverting source does not automatically restore overwritten or migrated data. -->

## Reviewer Focus

<!-- Medium/large changes: 1-3 bullets on important decisions, behavior and risk. -->

## Screenshots / Visual Evidence

<!-- UI changes only: reviewed synthetic before/after evidence and what changed.
Keep screenshots aligned with current implementation; omit for non-UI changes. -->

## Related Issues / Documentation

<!-- Verified issue/spec/ADR/docs links only. Closes/Fixes only for completed scope;
use Refs for partial work. Never invent issues, approvals or reviews. -->
