# Studio: product, mockups and listing copy

The implemented proposal keeps the soft Hebrew mobile UI and three-option review,
adding a versioned content inventory, real image editing, print assembly, reusable
mockups, listing review, customer downloads and editable preference memory.

## Workflow

1. Import stays passive. Code extracts Product's explicit inventory or supplied
   deliverables. Components explicitly declared as one sheet/page keep their internal content on that page; separate-page content remains separate. Any partial brief can start; scope/style omissions become editable
   assumptions. Content, printed text, family, style and assumptions can be edited.
2. **Start sketches** compares three directions for the **same representative
   page/item**, rather than a bundle collage. Real revisions send accepted pixels
   to the image-editing endpoint with aggregate feedback. Explicit current brief
   instructions override recurring preferences.
3. **Approve direction and produce** binds the accepted image hash, inventory and
   print specification. Choose A4/Letter, DPI, margins, bleed and colour, with
   explicit cost consent. Font/RTL/provider-size checks precede calls. Each
   illustration is generated separately; text/instruction pages make no image call.
4. Code assembles individual PNGs, complete PDFs, editable SVG layout sources and
   small previews. Typography is separate from generated artwork. PDF Media/Trim/
   Bleed boxes use physical dimensions. Native artwork pixels must satisfy print
   DPI; upscaling cannot pass this check. Text clipping, counts, corrupt files and
   missing content block approval. Human visual review is required; physical
   print-proof confirmation is recorded separately.
5. Guided mockups use a responsive card gallery. Each card owns its visible sample,
   editable description, expandable exact image prompt and verbal comments. Shared
   notes apply to **unlocked** cards. Start with 1–10 cards; the plus card adds a
   slot and × removes it from the active set while retaining saved history/files.
   Approve is a persistent on/off **lock**, not a vote to generate it again. Locked
   cards keep their exact pixels and prompts and skip both conceptual planning and
   rendering. Unlock before editing. Concept locks approve the displayed pixels;
   pending comments can remain for final refinement without paid regeneration.
   Changed scene/composition prompts still need applying or reverting before
   approving that image. Saving, deleting and locking make no model calls.
   Apply comments is one action: cheap text/vision understands all unlocked/new
   cards, then generates their sketches. Suggest X more appends, plans and renders
   only the new cards, leaving existing unlocked and locked images unchanged. For activities this may mix supervised
   family use, a table/floor spread, an illustrated usage storyboard, paper-stack
   material detail and a clean product hero. Roles adapt to the real product;
   paper/cardstock scenes describe buyer printing options, not shipped contents.
   When every remaining concept is locked, Finalize requests explicit consent
   and starts the first professional round in the amber **final refinement**
   workspace. It retains the same card layout and a persistent costly-loop warning.
   Apply corrections requests consent again for every subsequent professional
   round. New supported final edits send the complete displayed image and exact
   latest correction to the selected professional image model. There is no
   interpretation call, crop reinsertion, page overlay or automated visual-score
   gate. Scene descriptions stay internal in this stage. Separate optional final
   batch notes start empty; old concept-planning defaults do not override edits.
   Working outputs use medium quality (1152×768 landscape, equivalent area for
   other aspect ratios). Every original provider image appears in an open gallery
   even when later validation, accounting or the batch fails. Visibility is not
   approval. Locking a new direct result requires explicit human confirmation of
   the correction, visual quality and actual product content. Regenerated product
   pixels are not certified as deterministic source compositing. Locked cards skip
   further calls. A free previous-version action can select an earlier reference
   without modifying history. Optional separately consented high-quality export
   uses 1536×1024 landscape or equivalent area and requires fresh human review.
   Concept rendering retains source-placement checks and concept-only locking;
   final direct editing never reapplies those page overlays to the returned image.

6. After mockup approval, an explicit action generates two titles, one description
   and thirteen tags from the actual manifest and saved evidence. Code validates
   title/tag limits, duplicates and obvious quantity contradictions, then attaches
   a verified file/format/DPI section. Human edits are saved before approval.
7. Final approval binds exact product/mockup/copy versions. A customer ZIP contains
   printable PNG/PDF files and instructions; a separate Studio ZIP adds sources,
   mockups, manifest and listing JSON. Etsy remains `blocked_not_wired`.

The first manufacturing layout is **one illustration or instruction page per
inventory unit**, suitable for the proposed holiday picture bundle, colouring pages
and guides. Source constraints are retained; arbitrary complex activity/grid
geometry is not independently verified from natural language. Use a dedicated
layout template before claiming automated manufacture of such products. Review
semantic quality, symbols, accessibility, physical printing and commercial claims.
SVG sources contain raster illustration assets and editable text, not vectorized
illustrations or embedded fonts. Synthetic test images prove file/workflow
contracts, not artwork quality. No default mock output becomes a real product.

## Providers and accounting

In explicit trial mode, `sketch_provider` / `professional_provider` accept `openai`
or `gemini`. `draft_model` / `professional_model` choose priced OpenAI
`gpt-image-2.5-flare` (default) or `gpt-image-2.5-sunburst`. Drafts use low quality,
professional previews medium, production high. Both generation and JSON editing
use actual local image bytes. Native size derives from the print spec and follows
provider edge/pixel constraints. Sizes above 2560×1440 are experimental at OpenAI;
actual returned dimensions are validated. Account access requires a live trial.

`gemini-nano-banana-2.1` uses stateless Interactions, 1K sketches and 4K production.
No search tools, external reference URLs or automatic provider fallback. Only
completed model-output image blocks are used; thought blocks are not delivered
images or displayed reasoning. OpenAI supplies the separately admitted cheap
text/vision and listing calls. Google output accounting conservatively prices all
output tokens at its image rate, including cheaper text/thinking tokens.

Optional `sketch_provider: "comparison"` compares Flare/Nano/Flare on identical
briefs and accepted pixels. Both protected credential files must exist before any
comparison call. Record model provenance, correction rounds and cost per accepted
result; do not select a winner from fixture images or price alone.

Image prompts use a bounded projection of render-relevant content; raw market evidence stays in immutable intake/request files. Requirements and inventory are deduplicated, while source-only subject/style details are preserved. Exact credential-free JSON bodies remain in the project-scoped API panel. Each
operation owns its first body; validator/code recovery reuses completed paid
steps. A provider/model change during recovery requires a new explicit operation.
Downloaded bodies can contain private image bytes; keep them outside Git.

Documentation verified for this implementation:
[OpenAI generation/settings/pricing](https://developers.openai.com/api/docs/guides/image-generation),
[JSON image editing](https://developers.openai.com/api/reference/resources/images/methods/edit),
[Google image generation](https://ai.google.dev/gemini-api/docs/image-generation),
[Google Interactions](https://ai.google.dev/api/interactions-api),
[Google pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Etsy titles](https://help.etsy.com/hc/en-us/articles/115015628707-How-to-Create-a-Listing),
[Etsy tags](https://help.etsy.com/hc/en-gb/articles/360000336307-How-to-Use-Tags-to-Get-Found-in-Search).

## Preferences and revisions

Preferences require explicit confirmation for this product, a named family or
the brand. They cite accepted/rejected sample IDs and hashes. Inspect, edit and
delete through the UI; revision checks and history prevent lost edits. Automatic
feedback analysis never silently promotes a suggestion to global memory. The
library filters by family. Test related briefs before claiming fewer interventions.

Selected-item corrections edit only those assets, reuse others, recompose exports
and invalidate downstream approvals. Editing mockups leaves print files alone;
editing copy leaves both unchanged. Returning to direction clears approvals but
preserves files/history. Metrics expose rounds, product versions, calls and cost.

## Trial budget migration

The proposal is **$25 total Studio trial usage**, including previous Studio use
and human experiments. Existing configurations retain $1 until explicitly migrated;
code updates never refill a ledger. The separate $2 Analyzer/Product budget is
unchanged. The $25 policy enforces allocation ceilings: comparison/directions $4,
production $10, mockups $3, listing $2, other text/vision/user trials $6.
Conservative reservations precede credentials/HTTP; usage settles afterward.
Unknown outcomes retain their full hold and block every new call.

Reconcile all prior Studio use, then stop the affected Studio through the normal
deployment procedure before changing its budget policy. Use its **existing** data:

```bash
PYTHONPATH=services/studio python3 -m studio_service authorize-budget \
  --data /var/lib/market-pipeline/studio --total-usd 25 \
  --prior-total-usd CONFIRMED_TOTAL \
  --reason 'Approved Studio workflow trial; existing usage retained'
```

Replace `CONFIRMED_TOTAL` with the user-confirmed cumulative prior Studio use. The optional `--prior-total-usd` adds only the difference above recorded completed charges, never subtracts charges, and refuses unknown outcomes. This retains calls, holds and authorization history. `--initialize-empty` is only
for explicitly declaring there is no previous Studio ledger/use. Never initialize
fresh state to omit historical costs. Review `config/studio.trial.example.json`,
retain allowed hosts/provider choices, and set `trial_total_usd: 25` in Studio's
independent config. Config alone cannot change an existing ledger's policy.
Never target the Analyzer/Product ledger.

## Credentials and deployment

The CLI uses hidden input or explicit `--stdin`; keys are never arguments/output.
It does no provider authentication or paid test:

```bash
python3 tools/provider_keys.py add --provider openai --directory /etc/market-pipeline/credentials
python3 tools/provider_keys.py add --provider google --directory /etc/market-pipeline/credentials
python3 tools/provider_keys.py update --provider openai --directory /etc/market-pipeline/credentials
python3 tools/provider_keys.py list --directory /etc/market-pipeline/credentials
python3 tools/provider_keys.py check --provider openai --local --directory /etc/market-pipeline/credentials
python3 tools/provider_keys.py remove --provider google --directory /etc/market-pipeline/credentials
```

Protected external files are `studio-openai.env` (`OPENAI_API_KEY`) and
`studio-google.env` (`GEMINI_API_KEY`). The launcher forwards paths only, preferring
scoped OpenAI with legacy `openai.env` fallback. No Etsy credentials are delivered.
Render optional `--with-studio-ai` / `--with-studio-google` systemd units, review,
install and explicitly restart only Studio. Default units remain credential-free.
The key CLI reports restart requirements and never restarts anything. Interactive
sessions may set `STUDIO_OPENAI_CREDENTIAL_FILE` / `STUDIO_GEMINI_CREDENTIAL_FILE`
to protected paths; do not export secret values.

Pillow/DejaVu Sans are required for manufacturing, and Pillow RAQM for Hebrew/
Arabic text. No tools install packages. New state includes `workflow-jobs/`,
immutable `products/<revision>/`, `mockups/<revision>/`, `preferences/`, `templates/`
and paid-step receipts. Existing imports get a read-only workflow projection until
a human action persists it. A source pull does not host, migrate, generate, send
email or restart services. Older running backends retain the legacy UI; the new
workflow activates only when `/api/runtime` advertises version 2.

Interrupted/failed jobs stop durably. Explicit retry resumes saved steps/assets;
unknown paid outcomes still require accounting reconciliation. Final approval is
reserved before ZIP writes and must recover using its original action/key. Roll
back code/config together; retain files, receipts and the paid ledger and never
replay jobs/mail. The existing mock/file broker remains abstracted independently.


## Lifestyle setup and recovery

Set `lifestyle_mockups: true` in Studio's independent configuration and retain
`development_openai: true`, the reconciled Studio ledger, the $25 trial limit and
its protected OpenAI credential delivery. The real trial example enables this
flag; existing configurations default to false, so pulling source does not start
paid work. No collection, Analyzer/Product delivery or import triggers mockups.
The text/vision planner uses the existing inexpensive OpenAI text route; image
concepts use `draft_model` at low quality, finals use the separately configurable
`mockup_final_model` (default `gpt-image-2.5-sunburst`) at medium quality for
working refinements and high quality only for explicit optional export. Both are
independently replaceable ports. The new final route edits the actual displayed
image, not its background-only predecessor. Existing saved legacy jobs retain
their original request/response contracts on explicit recovery. No Google credentials
are substituted into the OpenAI scene route.

Planning, concepts, surface checks and finals share the proposal's existing **$3
mockup allocation inside the $25 total**, including UI experiments. The per-stage
remaining allowance is visible; it is not additional credit. Every call reserves
before credential loading and settles from usage. Unknown outcomes block all new
calls. Completed steps and per-scene files are reused on explicit recovery. A
failed mockup job can be abandoned explicitly while retaining files and financial
holds. `refresh_mockup_geometry` refits saved concept images locally with zero API
calls, retaining the previous round. All model payloads/usage remain inspectable.
Internal large print images are validated and reduced to metadata-free ≤512px
previews before text/vision calls; the external reference-upload bounds remain.

New state is additive: `lifestyle/`, `mockup_design` rounds/feedback and its v2
`board` (stable card IDs, locks, deleted cards, final/concept snapshots) in project
state, and human-approved `scene-memory/` examples. Enabling guided mode blocks
legacy procedural images from new downstream approval; it does not delete those
images or existing copy. Older saved scenes appear as unlocked cards without
rewriting source state on reads. A different product version starts a fresh board
while preserving the previous board in history. The v1 API remains available for
explicit legacy recovery; the v2 UI uses card-level operations exclusively.
A new plan invalidates downstream mockup/listing approval;
copy itself can be reused after the new finals are approved. Preserve the recorded
pre-lifestyle checkpoint, current state, all source/scene artifacts and every paid
receipt on rollback. Older UI versions cannot fully interpret lifestyle state:
stop the affected daemon and review code/config and project state together rather
than blindly restoring an old version. Never roll back the paid ledger.

## Verification

```bash
python3 tools/test.py
python3 tools/studio_workflow_smoke.py --output /path/outside/source/studio-smoke
python3 tools/studio_workflow_smoke.py --lifestyle --output /path/outside/source/lifestyle-smoke
python3 tools/studio_direct_edit_smoke.py --output /path/outside/source/direct-edit-smoke
```

The smoke uses an already installed Firefox/geckodriver and a temporary loopback
fixture server. It exercises the Hebrew mobile UI through customer/Studio downloads
with synthetic rasters/text and zero paid, Etsy or SMTP calls. Live trials must reconcile prior spend and preserve exact provider receipts. Inspect all five holiday subjects/symbols, both paper sizes, mockups and copy; physical proof and final human approval remain separate acceptance steps. Google/model-comparison access must be tested with the configured account before relying on it.

The final image route uses JSON image edits with the exact complete displayed
image. Human review must verify preservation; model output is not a guarantee.
See [OpenAI image editing](https://developers.openai.com/api/reference/resources/images/methods/edit)
and [image prompting](https://developers.openai.com/api/docs/guides/image-prompting)
for the provider contract. Native quality does not prove sale readiness.

## Mockup actions, model roles and incomplete responses

The guided toolbar has Apply comments (understands and sketches unlocked/new
cards), Suggest X more (appends and sketches only those ideas), and Finalize
(all concepts locked, explicit consent, first professional image round). The
professional workspace retains card locks and uses Apply corrections for only
unlocked images. Disabled actions have focusable hover explanations.

Set Studio configuration provider roles explicitly:

```json
"provider_roles": {
  "openai": ["mockup_planning", "mockup_sketches", "mockup_final_images"]
}
```

Existing configs default to planning/sketch permission only. To enable the final
picker, explicitly grant `mockup_final_images` and select the vetted Sunburst
`mockup_final_model`; restart only Studio after changing its configuration.
Credential discovery checks only the configured provider file metadata, never key
values, unrelated credential directories, remote model catalogs or account APIs.
Only registered top-tier image-edit adapters with a locally available credential
and the final-image flag enter the picker. Provider account access is verified
only by a user-consented request. Removing a key removes eligibility on the next
refresh. Cheap text is pinned to GPT-4.1 mini and sketches to `draft_model`; neither
can inherit the final picker, text/reasoning model names or maximum effort.
Adding another final provider requires a real, priced, vetted image-edit adapter
and registry entry as well as its credential and usage grant. A flag never turns
a text-only or cheap model into a professional image adapter.

Planning schemas bound response lengths and allow enough output tokens, with
reservations charged to the same existing Studio envelope. Incomplete responses
are saved, billed once from usage and never automatically repeated. Development
console errors include the actual project-scoped provider response body, including
incomplete_details, output and usage, without credential/header values. Historical
saved planning failures are also inspectable without inference. A new explicit
Apply/Suggest action may replace a known failed mockup job while preserving all
its artifacts and charges. Unknown billing outcomes cannot be replaced this way.
Interrupted combined jobs reuse the cached plan and completed images on explicit
recovery. Changing model during recovery is rejected; start a distinct, consented
operation instead.

## Whitespace-tail planning recovery and progress polling

A saved provider response may contain a complete scene followed by thousands of
whitespace characters and reach the token cap without its final JSON closings.
Only for max_output_tokens, no provider error/refusal, a long terminal whitespace
tail and complete schema-valid scene values may Studio append missing container
closings. It never invents fields or finishes truncated strings/scenes. Count,
page identity, required fields, enums, lengths and duplicate keys are checked.
The original response remains immutable; a separate validation-recovery receipt
records its digest, the exact appended closings and the validated plan digest.
This is deterministic syntax recovery, not an assessment of scene quality.

Explicit Apply with identical failed-job inputs resumes that operation and reuses
its cached paid response and completed images. Changed inputs create a distinct
request. Unknown billing still blocks recovery. No automatic generation occurs
on restart, page load or merely validating a saved response.

The browser uses the small project progress endpoint with one in-flight poll and
a 1.5–5 second adaptive interval, rather than fetching full project/library data
every 800 ms. It reloads full project state when phase/job identity changes.
Polling GETs are local UI traffic, never provider inference or Etsy requests.

## Full-image final edits and historical recovery

New supported professional jobs persist `refinement_version: 2`. Each card's
`.input.json` records the exact comments, full reference hash and output settings;
the `.png` is the original API output with no pixel transforms. Completed cards
publish independently. New results use `renderer_version: direct-edit-v1` and
`placement_status: human_review_required`; approval is explicitly human and bound
to the current output hash. Original paid outputs are available project-scoped at
`/api/projects/<id>/generated-images` regardless of board/job status, with original
image bytes at the returned image ID route. Reading this registry performs no
inference, credential loading, accounting mutation or remote image requests.
The UI opens these originals throughout the workflow, including failure states.
Unknown billing holds continue to block further paid work, never image viewing.

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


### Human scene edits and compiled output

Editable card descriptions, advanced prompts and comments are the submitted human
input. Concept candidates preserve that input in `requested_scene`, separately
from the actual generated scene. Explicit `scene_overrides` remain authoritative
across later rounds. A changed description without a changed advanced prompt is
sent verbatim as the image prompt, so a stale hidden prompt cannot cancel it.
Cheap planning still selects other scene details and validates real page IDs.
Lock comparisons use the submitted input; exact compiled scene and API payload
remain available for inspection. A failed action keeps the browser's unsaved
text instead of replacing it with reloaded server values. Returning to concepts
retains later final assets/history and does not itself generate images.
