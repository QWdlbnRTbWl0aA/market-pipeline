# Studio manufacturing workflow

Studio turns a saved Product brief into original printable files, mockups and
listing copy through explicit human approvals. It remains independent of
collection/analysis and never publishes a real Etsy listing. For HTTP/state
contracts see [Studio](studio.md); for old jobs see [recovery](studio-recovery.md).

## Human workflow

1. **Library and brief.** Product delivery/manual JSON/form intake is passive.
   All initial fields are optional; complete Product inventory, text, actual Etsy
   links and embedded visual references are retained. Upload/paste up to three
   examples at the beginning of the cycle; bound size/dimensions and strip metadata.
   Product owns bounded external reference retrieval. Browsing/import does not
   fetch images or call any model.
2. **Design direction.** Explicit Start sketches produces three low-cost
   representative concepts. Mark like/dislike and submit shared batch comments.
   Studio compiles the brief, feedback/history and approved scoped preferences;
   no hardcoded subject/template substitutes for real paid output. Votes toggle
   and are mutually exclusive. Starting over retains compact negative context.
3. **Printable product.** Review the inventory, exact visible text, style and
   representative item. Choose paper formats, size/DPI/margins and explicitly
   approve generation. Separate illustration units are generated; text, geometry
   and A4/Letter PDF assembly are deterministic. Product files have a separate
   human visual approval and physical print proof remains an operator check.
4. **Mockup concepts.** Start with 1–10 product-aware cards. Cheap text/vision
   planning should propose diverse gallery roles: usage, spread, storyboard,
   stack and hero where appropriate. Apply comments understands and renders only
   unlocked/new cards; Suggest X more adds only new ideas/sketches. Delete removes
   a card from the active set, retaining history. Approve is an on/off lock.
   Locked cards never regenerate. Concept-only confirmation may acknowledge an
   unresolved page-placement issue; it does not certify final product fidelity.
5. **Professional refinement.** Once all concepts are locked, explicit Finalize
   starts the visibly distinct expensive loop. Each new version-2 edit sends the
   complete displayed image and exact per-card correction to the selected vetted
   image model. Scene descriptions remain internal. There is no verbal rewrite,
   crop reinsertion, page overlay or visual-score visibility gate. Separate final
   batch notes start empty; old concept defaults do not silently override them.
   Human confirmation must check the correction, visual quality and actual product
   content. Locks are hash-bound and skip subsequent calls. Going back to concepts
   retains final history, images and feedback.
6. **Optional export.** Working edits use medium quality, about 1152×768 landscape
   or equivalent area/aspect ratio. An optional separately consented high-quality
   export uses about 1536×1024; it is not an automatic extra paid round. Review and
   lock exported images again. Mockups are promotional assets, not print files.
7. **Listing and delivery.** Generate/review titles, description and tags from
   approved contents. Final approval creates the customer/Studio package and a
   blocked listing handoff. No real Etsy listing request is wired.

## Preserve human inputs and every original output

Editable descriptions, advanced prompts and comments are durable human input,
separate from the planner's compiled scene. Candidates retain `requested_scene`
and explicit `scene_overrides`. Description-only edits become the exact image
prompt instead of being cancelled by an old hidden English prompt. Explicit card
edits/notes take priority over shared gallery defaults. Failed actions retain
unsaved browser drafts. Exact compiled requests remain inspectable.

Every original returned provider image appears in an open project-scoped gallery,
even if later dimensions/count validation, usage settlement or another card fails.
Corrupt payloads get an error/download instead of disappearing. Rendering a
successful image does not imply approval. Completed cards publish independently;
lightweight non-overlapping polling updates images without a page refresh.

New finals persist `refinement_version: 2` and `renderer_version: direct-edit-v1`.
Their input receipt records the exact reference hash, comments and output settings;
the saved PNG is the original API output. `placement_status: human_review_required`
records human review rather than falsely claiming deterministic source compositing.

## Lifestyle setup and recovery

`config/studio.example.json` is safe mock mode. The full trial shape is in
`config/studio.trial.example.json`: explicit paid mode, real image adapters,
`lifestyle_mockups: true`, and separate planning/sketch/final-image roles. Config
copying is not authorization to spend. Existing settings/ledgers are never reset.

Current OpenAI routing uses the configured Flare draft/product image model and a
separately configured vetted Sunburst final-image adapter. Cheap planning and
listing copy are separate text roles. The final picker requires both a configured
credential and explicit `mockup_final_images` permission. It cannot select text,
Ollama or arbitrary cheap sketch models. Google/comparison adapters are separate
configured options for supported generation; account access must be verified.
They are not silently substituted into the implemented OpenAI final-edit route.

Use [the credential CLI](../tools/provider_keys.py) to add/update/remove provider
files outside Git. Run `python3 tools/provider_keys.py --help` for current commands.
The launcher passes only paths for the requested service; discovery checks metadata,
not values. Review [configuration](configuration.md) and [deployment](deployment.md)
before changing an installed process.

Studio's legacy default is $1; the current authorized trial is **$25 total** with
existing allocations (including **$3 for mockups**). Charges/reservations across
all products and prior use count. Preserve/reconcile the existing ledger before an
explicit migration, for example using the actual operator-confirmed prior total:

```sh
PYTHONPATH=services/studio python3 -m studio_service authorize-budget --data "$STUDIO_STATE" --total-usd 25 --prior-total-usd "$CONFIRMED_STUDIO_TOTAL_USD" --reason "Explicit authorized ceiling migration with prior usage preserved"
```

Do not initialize a fresh ledger when prior spending exists. Budget admission is
conservative and precedes key loading/HTTP. Unknown outcomes retain their full
reservation and block new calls; inspect/provider-reconcile rather than retrying.
Status and exact request bodies stay visible. No SDK retries or silent mock fallback.

Free previous-image selection/restoration never generates or changes ledger
entries. Explicit unchanged-job recovery reuses its saved paid responses and
completed siblings. Preserve all later assets and feedback. Historical version-1
region/crop recovery has its own [guide](studio-recovery.md); do not replay it as
an implicit fallback for new jobs.

## Verification and limits

[Offline checks](verification.md) use synthetic images/text and temporary servers.
They verify flow, input preservation, provider wire contracts, budgets, locks,
partial completion and recovery. They do not prove image-model adherence, demand,
commercial quality, final anatomy or printer output. Development understanding
logs contain evidence summaries, never private reasoning. Preference updates need
human scope/approval; related scenes never become global preferences implicitly.
