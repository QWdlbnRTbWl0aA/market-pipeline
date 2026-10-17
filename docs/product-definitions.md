# Grounded analysis and Product definitions

The Analyzer selects business-validation hypotheses from saved collection
artifacts. Its initial product direction is input to an independent Product
definition, not the final Studio specification. Neither stage establishes listing
purchases from shop-wide sales. Discovery hypotheses remain separate from
history-qualified opportunities; a shortfall is preferable to padded ideas.

## Evidence and selection

The Analyzer retains bounded verbatim description sections, including late
content/format/use specifications, with normalized-description SHA and extraction
spans when truncated. Saved listing URLs, original creation time, observation
time, native prices, engagement and raw provenance accompany examples. Model
context deduplicates repeated examples instead of replacing descriptions with
short introductions. Ranking considers magnitude, independent favourite-positive
shops, concentration and evidence after removing the leading shop. Original
age is exposure context, never a sales-velocity estimate. Broad query-wide groups
receive a prioritization penalty; the model must distinguish actual product
mechanisms and consider counterevidence. All full assessments remain saved.

OpenAI final stages now default to `medium` reasoning; cheap local/low-cost
classification precedes the stronger stage. `paid.reasoning_effort` can explicitly
select `low`, `medium` or `high`. Priced final models are `gpt-6.1-sol` and
`gpt-6-astra`; the latter costs five times as much at standard text rates and is
an explicit configuration choice. Rates and reasoning support are documented by
[OpenAI for Sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and
[Astra](https://developers.openai.com/api/docs/models/gpt-6-astra).
Token bounds and conservative cost admission
still apply before credentials or HTTP, including the cache-write input premium.
No paid images are admitted. Saved
images, when present, are interpreted locally; metadata alone is not visual evidence.

## Default Product output

`run` and the ordinary HTTP worker use handoff recipe
`product-handoff-v4.2-visual-references`, retaining the independently cached
`product-definition-v4.1-grounded` text-definition recipe.
For each recommendation they save:

- Exact request, started marker, raw model response and provider usage metadata.
- `product.json`: original Analyzer direction, measured context, real references,
  full independent definition and backward-compatible Studio requirements.
- `brief.md` and **one standalone `brief.html` for that product**, with the same
  specification, embedded visual reference board and actual Etsy example links. There is no batch dashboard,
  automatic hosting, remote image loading or directory publication.
- A batch `studio-handoff.json` containing the complete exact briefs, not only
  directory pointers. SMTP and passive Studio delivery still use the exact saved
  per-product JSON with their existing independent outboxes.

The definition names the audience, customer task, actual product mechanism,
complete component inventory/quantities/content, first-sketch composition and
exact visible text, original proposed style, package/source formats and objective
acceptance checks. Design choices are proposals. Examples are saved source
content: quotes must match a supplied title/description, URLs are attached by
code, and independent shops must be compared when available. Missing references,
unresolved placeholders, invented URLs, inconsistent quantities and unknown
citations fail validation rather than produce a generic deliverable.
The local Ollama adapter splits inventory from the remaining specification and
derives unit counts from explicitly enumerated contents. It attaches real source
quotations in code. This makes local generation easier to validate; it does not
certify semantic quality or turn an inadequate local response into a deliverable.

Product generates no artwork. A separate legacy `define` command and
`enhanced_enabled` promotion policy retain earlier experimental wireframe
compatibility; they are not required to use the new default definition path.
Do not enable the legacy path to obtain the improved briefs.

## Product visual references

Product selects up to three of the evidence listings already chosen for the brief.
It preserves their `images` metadata, prefers an available saved CDN URL, and,
when missing, reads `og:image`/`twitter:image` from that exact public listing page.
It downloads only still PNG/JPEG/WebP from `i.etsystatic.com`; no Etsy API calls,
credentials, search-engine fallback, challenge bypass, redirects or general URL
fetching are supported. Public DNS addresses are validated and pinned for TLS.
Each example costs at most one bounded listing-page read and one image read;
there are at most three references per brief. Responses and decoding are bounded.

Pillow is required when this option is enabled; Product validates the runtime
before starting new definition inference. It makes a fresh metadata-free JPEG at
at most 512×512 pixels and 80 KB. Thumbnails are embedded as `reference_images`
data URLs, with `visual_references` mapping each image to its evidence/listing/shop,
original listing and CDN URLs, hashes, dimensions, citation purpose and exclusions.
The standalone HTML embeds the same images, so viewing it makes no image-server
requests. Product's exact email/Studio JSON includes these images automatically.
Studio's existing passive intake saves them without generation or inference;
visual interpretation happens after the user's explicit sketch action. Product
does not claim that a thumbnail was visually inspected by its text-only model.

The normal CLI/HTTP path enables visual references by default, including old
configurations that omit the option. To change policy, add to Product JSON:

```json
"visual_references": {
  "enabled": true,
  "allow_listing_pages": true,
  "max_images": 3,
  "timeout_seconds": 10
}
```

Set `allow_listing_pages: false` for CDN retrieval from saved metadata only, or
`enabled: false` for deliberate text-only operation. The internal Python
`process` function retains an opt-in `visual_settings` argument for callers that
require saved-data-only operation; the CLI and worker supply the policy explicitly.
Legacy experimental `enhanced_enabled` uses its previous output contract and
does not automatically add a board; use the default path for new briefs.

Failures are recorded under `visual_reference_status`; unavailable images are
shown explicitly, never replaced with generic artwork. `ready` means images were
attached, not that visual or commercial quality has been assessed. Text definitions
remain readable if retrieval fails. Successful/failed per-brief receipts are
reused; an interrupted attempt requires an explicit new revision. HTTP 401/403/429
also creates a durable host block under the Product output root's `visual-access/`.
New products and restarts retain it. An operator must review/resolve the cause and
explicitly archive the applicable block before any new attempt; code never does
that automatically. Old revision receipts remain immutable.

An existing grounded brief can be enriched without definition, API inference,
email, Studio delivery or generation, preserving the source and using a new folder:

```bash
PYTHONPATH=services/product python3 -m product_service enrich-visuals \
  --brief /path/to/saved/product.json --output /path/to/new-visual-revision \
  --definition-config /path/to/product-config.json
```

No existing completed brief is backfilled or hosted automatically. The explicit
preview server must allow inline `data:` images in its CSP, and continue allowing
only the requested HTML route rather than exposing its output directory.

## Configuration and installation

Existing Product configurations with `enhanced_enabled: false` automatically use
the new default definition path after the code is deployed and Product restarted
by the operator. They default to the installed `gemma3:4b` Ollama model. Add an
independent `briefing` object to select the local provider explicitly:

```json
{"provider":"ollama","model":"gemma3:4b","ollama_url":"http://127.0.0.1:11434"}
```

For stronger Product definitions, replace **only that object** with:

```json
{
  "provider": "openai",
  "model": "gpt-6.1-sol",
  "paid": {
    "enabled": true,
    "daily_usd": null,
    "daily_calls": null,
    "total_usd": 2,
    "max_output_tokens": 6000,
    "max_input_token_bound": 50000,
    "reasoning_effort": "medium",
    "timeout_seconds": 240,
    "ledger_root": "/var/lib/market-pipeline/paid-ledger"
  }
}
```

Alternatively preview an upgrade from the saved Analyzer's existing ledger,
model and budget policy, without credentials or requests:

```sh
python3 deploy/upgrade_config.py --configs /etc/market-pipeline --enable-product-openai
```

Review the copied limits and add `--apply` to write a versioned configuration
backup and the Product provider choice. Mail/Studio settings and ledger bytes
are preserved. This does not install the paid Product unit or restart anything.
The installed small local model may fail the stricter definition contract;
use the stronger provider for reviewed deliverable quality rather than relaxing
validation to accept generic or inconsistent local output.

The ledger root **must be the existing Analyzer ledger**. The currently approved
budget is $2 total including prior spending. A narrower optional `development`
envelope may be configured, but existing envelope limits cannot be silently
enlarged/reset. The user lifted the earlier $0.50 sub-limit for this assignment;
omit that sub-envelope from new-call policy while preserving all its ledger
entries and reservations. Existing installations retain saved settings until an
operator explicitly changes them.
Do not create an empty ledger to bypass prior spending, unknown reservations or
provider blocks. Product has no dependency on an Analyzer process or its config;
both providers share only the file-locking accounting library and configured
ledger. Direct CLI use accepts `--definition-config /path/to/product.json`.
The Product credential adapter accepts only its dedicated `openai.env` file and
never sources a shell or opens Etsy credentials. Inherited API credential values
remain forbidden. `PIPELINE_PRODUCT_OPENAI_KEY_FILE` names the separately
delivered file; the launcher sets it from its credential directory without
reading the file.

For systemd paid Product, render units with `--with-product-paid` (and
`--with-mail` if already using mail). Only the Product unit additionally receives
`LoadCredential=openai.env` and write access to the shared paid ledger. Default
units remain local-only for Product. Review/install the rendered units using the
existing [deployment procedure](deployment.md); code changes do not install units,
modify production settings, restart services or backfill old jobs automatically.

Production mail/Studio settings are preserved. A code pull does not enable a paid
Product provider, change budgets, send old mail, or regenerate completed briefs.

## Failure, repeat triggers and rollback

Completed jobs return saved results without inference. Each component response
is saved before validation; fixing a mechanical validator permits revalidation
without paying again. An interrupted started marker without a saved response
holds the job for explicit investigation. There is no automatic model retry or
provider fallback. Failed definitions do not queue mail or Studio delivery.
Provider calls default to a bounded 240-second timeout (configurable 30–300
seconds). A timeout preserves the full unknown-cost reservation; increasing a
timeout does not authorize resending that earlier request.

By default any unknown paid outcome blocks further admission. An operator may
explicitly set `paid.allow_held_unknown: true` to admit **different request
identities** while unknown calls remain charged at their full conservative
maximum. Under-held or malformed reservations still block admission, as do
provider access blocks, cooldowns and reservation overruns. The same unknown
identity cannot be resent. This option does not recover the failed definition,
release credit, change the total limit, or enable automatic inference retries.
It is suitable for a separately authorized revised recipe when sufficient total
allowance remains; keep the original uncertainty visible for reconciliation.

Recipes have changed, so newly analyzed inputs get new identities. Completed
HTTP intake receipts and delivery histories remain durable; old jobs are not
silently reprocessed. For a deliberate re-evaluation use a new isolated output
root or a newly versioned source analysis, retaining all earlier receipts and the
same paid ledger. Archive old derived assessments/offer registries/caches outside
active roots when explicitly requested; never delete raw collection history or
the shared budget ledger. Roll back code/config together and retain the new
derived output for inspection; do not replay mail or Studio delivery as part of
rollback.

Functional tests use injected synthetic providers and mock SMTP only. Semantic
acceptance requires reading the actual generated brief against the saved examples;
schema success alone is not evidence of a useful business opportunity.
