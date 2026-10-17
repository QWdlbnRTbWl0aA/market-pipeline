# Studio historical recovery

New professional mockup edits use version 2 (`direct_edit.py`). This guide exists
because saved version-1 jobs and their paid receipts still require recovery.
Do not run old correction/crop/compositing paths for a new final edit, or remove
them/tests as unused code before an explicit saved-state migration.

Preserve the data root, paid ledger, requests/responses and immutable artifacts.
Inspect phase, operation status and unknown billing before any recovery. Display
all original responses regardless of validation; display does not approve them.
The current full-image path is described in [Studio workflow](studio-workflow.md).

The following version-1 behavior is retained for historical recovery only; it is
not used for new real final edits. Historical jobs persist `refinement_version: 1`. Their per-card
`.plan.json`, `.provider.png`, `.layers.json`, `.review.json` and final record
retain resolved instructions, cropped input/output provenance, immutable source
hashes and visual check results. Paid API bodies remain in the existing payload
viewer. Placement uncertainty blocks promotion before another comparison call;
visual failure records the attempt and retains the previous displayed candidate.
A successful comparison still requires human lock/approval. No model guarantees
correct anatomy, product fidelity or inferred geometry; ambiguous pages remain
blocked instead of being fabricated. Protected pixels outside a local edit are
copied from the reviewed source (resampled to the working canvas). Cropped edits
retain the source's detail before magnification; output dimensions preserve its
aspect ratio within 16-pixel API increments.

The card gallery uses candidate/hash-addressed file URLs, so a completed edit
loads new pixels without a browser reload. No extra inference is caused by polling.

`restore_mockup_round` is an explicit, revision-checked, idempotent project action
with `round_id`. It restores a complete saved final round for the current product
and active card IDs, including that request's comments. All cards reopen for
review; downstream approvals are invalidated. Pending jobs and finalized products
cannot be restored. Prior board/cards/comments are captured in `restorations`;
all later rounds, assets, interactions and paid receipts remain unchanged. It does
not queue work, send mail, publish events or modify the paid ledger.

### Independent card completion and invalid-region recovery

Each targeted-refinement card publishes its saved result as soon as it completes;
other cards can continue. Progress polling reloads project metadata at card
completion boundaries so new pixels appear while the batch is still running.
A malformed correction plan records a card-level failure and preserves its old
image. It never causes a full-image fallback or automatic paid retry, and it does
not block other edited cards. Budget/unknown-outcome blocks still stop further
requests. New compiler schemas require positive region width/height; code also
checks finite coordinates and page bounds. Legacy saved `edit_box` plans remain
readable and invalid zero-area rectangles remain rejected.

For a card with invalid bounds, choose **סימון אזור התיקון בתמונה**, then drag a
rectangle over the relevant part of its current sample. Mouse/touch coordinates
account for image letterboxing. This saves notes/bounds only, without inference.
Apply corrections is a separate consented action. When comments/reference match,
the selected bounds reuse the saved paid interpretation, avoiding another planning
call. A successfully applied manual region expires after that correction; future
edits are not accidentally restricted to an old selection. Already completed,
unchanged siblings are excluded while changed/failed cards are processed.

A failed legacy batch exposes **הצגת תוצאות שכבר הושלמו · ללא חיוב**. Its
`recover_mockup_results` action verifies current product/cards/comments and saved
candidate hashes/provenance, publishes the already completed results and records
unfinished card errors. It does not instantiate providers, queue work, run a
worker tick or write the paid ledger. The failed operation and recovery receipt
remain durable. The real generation error stays visible rather than being
replaced by generic advice to retry. Completed paid assets never need regeneration
merely to make them visible.
