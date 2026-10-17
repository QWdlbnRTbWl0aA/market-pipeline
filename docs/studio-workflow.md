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
5. Three mockups composite exact approved pages into frame, flat-paper, stack and bundle
   views. Reusable procedural desk/wall scenes provide texture, alpha shadows and a frame mat; these are illustrative templates, not photographic backgrounds. Stacks retain their backing pages in perspective, and bundle views display separate actual pages. Scale, placement and perspective are editable; the backend also supports
   normalized crops. Alpha masks/shadows are deterministic. Named templates are
   saved and reusable across products. Presets load editable values; subsequent edits, including zero positions, remain authoritative. Saving a preset retains the current edits. The explicit automatic-layout button restores centered defaults; ordinary updates preserve settings. Template use makes zero generative calls.
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

## Verification

```bash
python3 tools/test.py
python3 tools/studio_workflow_smoke.py --output /path/outside/source/studio-smoke
```

The smoke uses an already installed Firefox/geckodriver and a temporary loopback
fixture server. It exercises the Hebrew mobile UI through customer/Studio downloads
with synthetic rasters/text and zero paid, Etsy or SMTP calls. Live trials must reconcile prior spend and preserve exact provider receipts. Inspect all five holiday subjects/symbols, both paper sizes, mockups and copy; physical proof and final human approval remain separate acceptance steps. Google/model-comparison access must be tested with the configured account before relying on it.
