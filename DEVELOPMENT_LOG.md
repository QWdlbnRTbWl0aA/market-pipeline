# Development log

This file summarizes the current source changes. Detailed historical assignment
reports and runtime evidence belong outside source. Earlier chronological entries
remain available in Git (`git log -- DEVELOPMENT_LOG.md`; the pre-housekeeping
version is in commit `b9f4fdb`). Installed production releases/state are separate.

## 2026-10-17 — housekeeping branch

Published the latest Studio corrections to `main`, then isolated maintenance on
`housekeeping/2026-10-17`. No production deployment or merge is part of this work.

- Replaced chronological/outdated README, AGENTS and Studio guidance with current
  service boundaries, module ownership, configuration, verification and maintenance
  guides. Historical Studio recovery is separate from the current full-image flow.
- Reduced this log to current change summaries; Git retains prior detailed entries.
- Removed 28 unused imports across 20 files. Kept intentional budget compatibility
  exports and all saved-data/recovery code.
- Made paid analysis explicitly disabled in the example configuration; the mock
  Studio example now declares its full current configuration. Installed settings,
  credentials and ledgers are not modified.
- Declared Pillow and Python CI setup instead of relying on an implicit installed
  dependency. No local tools/packages were installed.
- Retired one obsolete browser runner; retained its upload/paste and toggle checks
  in the current workflow smoke. All 492 unit/integration tests remain relevant
  and are retained rather than deleting security/recovery coverage.
- Deleted identified disposable browser states, copied test clones and an old
  unapproved preview export. Checksum-verified inactive research/development
  evidence was compacted into private archives. Both paid live Studio projects,
  all their history/caches/ledgers and historical known-good archives were retained.

Final offline validation passed all 492 unit/integration tests, the consolidated
Hebrew workflow browser flow (including migrated input/vote checks) and the direct
image-edit browser flow. An intermediate smoke assertion used a CSS class where
the current UI exposes aria-pressed; the check was corrected and the complete
browser flow passed. Local documentation targets/anchors and whitespace checks
passed. Credential-aware sanitation found zero findings. No paid/source inference,
production operation or package installation was performed.

Transaction manifests, measured allocation savings, test logs, sanitation reports
and the emailed summary are private. Generated artifacts stay out of Git.

## Latest Studio corrections retained

- `b9f4fdb`: human scene descriptions/prompts/comments survive lossy planning;
  explicit edits reach the image request and override stale defaults. Rejected
  actions retain browser drafts. Saved human wording can be recovered without
  generation; old images are not represented as satisfying changed instructions.
- `3440dec`: original returned images remain visible despite validation/accounting/
  job failure. New final edits use complete displayed pixels and exact comments,
  without crop reinsertion/page overlays/visual-score gating. Human review stays
  mandatory; previous-image selection and cached-response recovery are free.
- Earlier version-1 recovery remains supported for saved jobs, including immutable
  artifacts, independent card completion, paid identity and unknown-outcome holds.
