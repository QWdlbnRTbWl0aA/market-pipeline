# Repository and development-state maintenance

Keep source easy to navigate without deleting operational history or disguising
regressions. Current contracts are in README/architecture/configuration and service
guides. Git history retains superseded implementation notes; private evidence and
runtime state do not belong in Git.

## Classify before deleting

| Artifact | Treatment |
|---|---|
| Python bytecode, stopped synthetic browser states, copied test fixtures | Disposable after verification; retain useful test logs/screenshots |
| Unapproved derived preview exports | Removable when original source assets/history remain available and no process uses the export |
| Inactive private research reports, captured raw evidence, old recovery receipts | Checksum-verified archive with a manifest/index; verify every regular file before pruning unpacked copies |
| Active Studio projects, paid request/response caches, budget/unknown-outcome ledgers | Preserve in place; do not shrink by removing historical rounds or resetting accounting |
| Collector raw runs, quota/schedule history, analysis/offer/delivery receipts | Preserve operational provenance; archive only under an explicit retention/migration plan |
| Credentials, installed configuration, production state, live logs/PID files | Protected; cleanup does not authorize modification, deployment or service restart |
| Historical private Git archives / known-good checkpoints | Retain outside the publication repository |

A folder called `test-output` is not proof that its contents are disposable. Follow
actual configuration, process command lines and saved receipt references first.
Do not inspect or publish credential values as part of inventory.

## Safe sequence

1. Record current Git commit/branch, service state, disk usage and exact proposed
   deletion/archive roots. Protect all active roots and current report output.
2. Separate reproducible fixtures from real paid/source artifacts. Use explicit
   allowlists, reject symlink roots and never traverse outside the approved tree.
3. For evidence archival, record entry names, sizes, modes, timestamps and SHA256;
   verify archived contents and unchanged originals before removing unpacked copies.
   Keep archive hash, manifest and a short index outside Git. Restore into a new
   review directory, never over active ledgers/state.
4. Re-run relevant offline suites and browser flows. Keep recovery/security/quota/
   budget tests while those contracts exist. Removing an obsolete test runner
   requires preserving any unique supported checks in the replacement.
5. Clear regenerable bytecode/fixture states after tests finish. If compacting Git
   objects, preserve refs, reflogs and unreachable objects; do not rewrite shared
   history or erase checkpoints merely for a small size gain.
6. Report measured allocated-byte savings separately from logical file sizes and
   archive compression. Account for new archives; host-wide free-space changes
   can include unrelated writers. Record files/tests removed and coverage kept.
7. Run publication sanitation across working files and **all** Git objects. Commit
   coherent changes on a housekeeping branch; merge/deploy only when authorized.

## Documentation ownership

- README is the entry point/current status, not a chronological assignment report.
- AGENTS contains durable contributor rules and links, not copied test transcripts.
- Architecture maps modules and integration boundaries.
- Configuration/deployment describe safe defaults, explicit activation and upgrades.
- Studio workflow is current behavior; historical recovery has a separate guide.
- Verification reports current checks and limitations. Old observations remain in
  Git/private evidence instead of contradictory "not deployed/not published" text.
- DEVELOPMENT_LOG records concise changes; older detail is recoverable through
  `git log -- DEVELOPMENT_LOG.md` and `git show <commit>:DEVELOPMENT_LOG.md`.

No general-purpose destructive cleanup command is shipped. Maintenance decisions
are scope/state dependent; private transaction manifests record actual deletions.
