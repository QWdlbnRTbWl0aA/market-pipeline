# Studio preliminary implementation

Studio is independently runnable. HTTP brief intake (`POST /api/briefs` and
`POST /api/library/briefs`, JSON with `Idempotency-Key`) saves a passive library
entry. Opening, refreshing, importing or editing an entry never generates images,
calls a model or publishes a broker message. The Hebrew UI shows the normalized
brief and the complete original Product JSON. All initial content fields are
optional: save any bounded brief and explicitly click **התחלת סקיצות** to authorize generation.

Configured Product delivery uses only `/api/library/briefs`, with a persistent
outbox, exact saved payloads, bounded retries and duplicate suppression. Its
receiver must be upgraded before enabling the connection. See
[Studio library deployment and existing-brief backfill](studio-library.md).
Product `product.json` fields are normalized by the intake adapter; the dashboard
JSON import also maps Product concept/customer/job/deliverable fields. A batch
`studio-handoff.json` manifest is not an individual brief. Visual examples still
require uploaded/pasted or embedded images; Etsy URLs are never fetched.

Existing active projects and their paid ledgers are preserved. Previously queued
human-authorized generation is not canceled or replayed by this feature. The core
workflow tests retain a legacy direct-call fixture path; the public HTTP routes
always use passive library admission, regardless of fields in the submitted JSON.

## Run and review

```sh
python3 deploy/prepare.py --state /tmp/market-pipeline-state --configs /tmp/market-pipeline-config
python3 deploy/launch.py studio --state /tmp/market-pipeline-state --config /tmp/market-pipeline-config/studio.json
```

Open `http://127.0.0.1:8096/`. Use `--bind 0.0.0.0` on the launcher for LAN
access and configure `allowed_hostnames` for DNS names. This is an initial,
trusted-network interface without authentication/TLS; use a protected proxy or
network boundary before production exposure. No firewall or host accounts are
changed by preparation. The separate systemd template defaults to loopback,
has no credentials and only writes the Studio state directory. Existing
installed services are not modified by source changes.

No initial content field is mandatory, including style/visual direction. Partial,
empty and plain-text JSON briefs are accepted; malformed types, credentials and
oversized input are still rejected. Optional details can be edited before start.
Legacy `needs_information` entries appear ready and can start without an offline
state migration. Intake remains passive and never incurs model calls.

The Hebrew RTL dashboard uses soft colours and collapsed secondary detail.
Each of three samples has like/dislike buttons physically on its left. One comment
area applies to the entire batch. Mark all three, then submit for regeneration;
local votes do not make provider requests. A shared spinner covers asynchronous
understanding/generation. Accepted/rejected history stays available; Studio compiles
the generator prompt from the complete feedback rather than forwarding raw comments
alone. The professional loop also presents three samples with explicit expensive
consent. Legacy single-sample API actions remain for saved-client compatibility,
but are not exposed in the current UI.

Explicit human start queues three sketches (default 320×420 mock SVGs;
development OpenAI supplies low-quality 1024×1024 PNG concept boards). Iteration
uses unique historical accepted/rejected samples and comments, not repeated votes
from cloned frames. Attribute contrasts and actual visual observations inform
short model-authored preference summaries, uncertainties, cited sample IDs and
the next image direction. Shared attributes across positive/negative examples
are confounders, not automatically dislikes. Refresh preserves saved state;
unsent comment drafts remain browser-local.
Deterministic guards protect explicitly retained attributes from invented
dislikes and reduce unsupported confidence when there is no positive/negative
contrast. They quote source comments rather than inventing product direction.
The browser preserves a pending submission in session storage and resumes its
exact idempotency key after refresh, including a response lost after acceptance.

Start over archives the complete interaction and generations' references in a
gzip snapshot, then clears the working rounds. A compact negative summary
(counts, notes and archive provenance) accompanies subsequent requests. Even
previously accepted samples from an abandoned direction become negative context.
The original source brief, generation requests, responses, SVGs and archives
remain intact. Context samples/notes are bounded; full history is not deleted.

Generate final product requires an accepted sketch, explicit expensive-loop
consent, dimensions, units, DPI, colour, format and bleed settings. The mock
professional generator returns exactly three samples. Further professional
rounds require consent again; the dashboard warns about the expensive loop and
offers return to three sketches. Settings are metadata plus SVG dimensions;
professional print preparation/bleed rendering is not implemented by the mock.
SVG and PNG target settings are supported. Pixel dimensions are bounded to
64–8192. OpenAI development always returns draft PNG boards at 1024×1024;
target size/DPI/bleed are saved production requirements, not print-ready output.

Final approval requires choosing an accepted professional sample. It saves
`approved-product.json`, a downloadable ZIP (SVG/PNG, metadata, draft notice) and
`listing-handoff.json`. Approval is immutable. The listing handoff always has
`blocked_not_wired` / `etsy_api_called: false`. There is no Etsy client, credential
loader or selectable real Etsy publisher. Development artifacts are not sale-ready.

## Brief reference images and optimized prompts

At original brief intake, `reference_images` can contain up to three PNG/JPEG/WebP
data URLs. The Hebrew UI supports file upload and clipboard image-file paste. It
resizes before upload; the backend independently verifies still-image type,
20-million-pixel/2MB input bounds, strips EXIF/comments/metadata, and saves JPEGs
with longest edge at most 512px and at most 80KB each. Remote URLs and animated
images are refused. References are fixed for the project; subsequent feedback or
brief updates cannot replace them. Create a new project for different examples.
Old ten-sample rounds remain intact; the UI shows three and new batches have three.

Pillow is required for reference processing and development image observation;
no tool automatically installs it. It is available system-wide on the tested host.
Mock operation without references remains standard-library-only. OpenAI receives
small low-detail thumbnails for interpretation; the image generator receives the
Studio's optimized textual direction. Reference interpretation is cached once per
project and reused in subsequent batches. Generated previews are also downsized
before paid visual observation. `optimized-prompt.json` preserves the actual prompt
and feedback fingerprint; development preference logs contain observable evidence,
not private chain-of-thought. No additional provider is selected for production.

## Persistence and provider boundaries

State lives below `studio/projects/<id>/`: original brief, atomic `state.json`,
generation request/operation/response files, assets, compressed epoch archives
and approval package. Archive metadata includes hashes of both the compressed
file and its JSON body. Global `broker-outbox/` and `mock-broker/` record messages
and receipts. Intake and actions require idempotency keys; reuse with changed
input is rejected. Mutations require current project revision. Concurrent
generation workers lock independently of HTTP review. Interrupted or failed
generation is parked for explicit recovery; it never automatically repeats a
possibly chargeable request. Saved partial/completed responses remain available
for inspection. Explicit retry resumes the same operation. Completed paid image
steps are reused even when a downstream visual observation fails or its schema
is corrected. Cached HTTP responses avoid repeated paid inference. Unknown API
outcomes block all new calls until explicit accounting reconciliation; a retry
does not release a reservation. Mock generators may recompute deterministic assets.

`ports.py` defines independent Generator, Broker and Listing contracts. Current
configuration defaults to mock/mock/mock/blocked, with optional `openai_dev`
generation explicitly gated by `development_openai: true`. The generator request
contains structured brief, sample count, accepted/rejected assets with SHA256
and comments, compact negative context, archive references, latest feedback and
professional settings. Implementing real providers later requires explicit
budget admission, provider identity/provenance, output formats, failure and
unknown-outcome reconciliation, and prompt-injection controls. Mock layouts
prove workflow only. Email and Etsy API are not called by Studio.

The launcher drops inherited credentials; Studio also refuses provider/collector
credential environment names and credential-shaped intake fields. SVGs have a
strict safe markup whitelist and no remote resources. HTTP mutations reject
foreign origins; Host validation, body limits, revision checks, CSP and scoped
asset lookup protect the initial interface. Real broker transport/authentication
remain separate from the optional development OpenAI credential loader.

## OpenAI development mode and one-dollar envelope

Set `development_openai: true` and select `openai_dev` for sketch/professional
providers in a private runtime config. Pass `--credential-directory` containing
`openai.env` to the launcher; only a `STUDIO_OPENAI_CREDENTIAL_FILE` path is
forwarded, and only the admitted adapter opens it. No key is stored in config,
state, logs, arguments or browser responses. No collector credentials are opened.
Production examples/units stay mock-only with no Studio credentials installed.

The model allowlist uses `gpt-image-1-mini` (low, square PNG) for draft generation
and `gpt-4.1-mini-2025-04-14` for visual observation and structured feedback
understanding. Image observation describes **input boards**, not the five
individual paintings within each Hanukkah board. Cardinality is constrained
and validated. Only bounded low-detail local generated PNGs enter vision.
Image generation uses the learned direction and original brief rather than
hardcoding a subject or artistic style. No tools, redirects or SDK retries.

`development-openai/budget.json` is a hardcoded **$1 total Studio development
envelope**, across all products, agent tests and human UI use. It is independent
of the existing analyzer preparation ledger and never resets by day/restart.
All calls first reserve conservative integer-microdollar cost: UTF-8 byte token
bounds plus framing, 4096 vision tokens per bounded square image, explicit text
output cap, and a conservative low-image output allowance. Cross-process locks
serialize admission. Provider usage settles the reservation at standard rates
without assuming cached-input discounts. Unknown outcomes retain their maximum
charge and stop all new calls. Never delete/move/reset this ledger to refill it.
At insufficient budget the feedback/history remain saved, samples stay available,
and generation stops with a readable message. Full payment-provider billing
reconciliation and future professional-quality rates remain separate work.

Pricing basis: [official model pricing](https://developers.openai.com/api/docs/pricing),
[image generation](https://developers.openai.com/api/docs/guides/image-generation)
and [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini).
Recorded cost is a conservative usage-based estimate, not an invoice.

Development-only `reasoning-log/<operation>.json` records the bounded aggregate,
observable conclusion, evidence IDs, uncertainties, provider and completion/failure
status after feedback. It does not request or expose private chain-of-thought.
Read it from the collapsed UI panel or `/api/projects/<id>/reasoning` (disabled
outside development). Browser `console.log` reports cumulative per-product cost,
global charged/reserved total, remaining budget and unknown outcomes after updates.

The synthetic [Hanukkah Product handoff](../examples/studio-hanukkah-brief.example.json)
defines five printable watercolor wall pictures: menorah, dreidels, doughnuts,
oil jug/olive branch and a holiday composition. It is testing data, not market
evidence. The initial three boards preview whole bundles; separate print files
are a future production output, not something the draft adapter claims to create.

## API actions

Read `/api/projects` and `/api/projects/<id>`. Submit JSON with `revision` to
`POST /api/projects/<id>/actions/<action>`, with an `Idempotency-Key`. Actions:
`update_brief`, `save_feedback`, `next_sketches`, `start_over`, `generate_final`,
`next_professional`, `back_to_sketches`, `approve_final`, `retry_generation`,
`review_sample`, `replace_sample`. The latter two also require `candidate_id`.
Review payload: `reviews: {sample_id: {decision, comment}}` and `comments`.
Professional generation requires `consent_expensive: true`; final generation
also requires `settings`. Approval requires `candidate_id`. Assets use
`/api/projects/<id>/asset/<sample_id>`, approved ZIP uses `/download`.

Run `python3 tools/test.py` for all components, or Studio's independent unittest
suite. Functional tests use offline transports/mocks. Browser smoke requires a
mock health endpoint and refuses to run against paid mode. It exercises the
actual static UI against a fresh standalone service, separate from production.

## Diagnosing generic previews and inspecting requests

A `mock` provider draws fixture SVG templates, not semantic images from a brief.
Source updates do not change installed configuration. Check `/health` or the
always-visible provider line in the UI. To use the existing development adapter,
set these three fields in the private Studio configuration:

```json
{
  "development_openai": true,
  "sketch_provider": "openai_dev",
  "professional_provider": "openai_dev"
}
```

Keep the other existing configuration fields. The launcher must receive
`--credential-directory` with the protected `openai.env`; a systemd deployment
must load that credential explicitly. An administrator can add this drop-in to
`market-pipeline-studio.service` during a separately authorized deployment:

```ini
[Service]
LoadCredential=openai.env:/etc/market-pipeline/credentials/openai.env
```

The launcher takes systemd's `CREDENTIALS_DIRECTORY` and forwards only the
`STUDIO_OPENAI_CREDENTIAL_FILE` path. Do not export the secret into the unit
or pass a key as an argument. The default Studio unit does not install credentials. This is development mode with the existing $1 envelope, not a way to
reset or increase it. Keep the same state directory and ledger; retain unknown
reservations. Restarting/upgrading an installed service requires a deployment
operation, not merely pulling source. No configuration changes are made by the UI.
Existing mock samples stay in history; a newly submitted batch uses the currently
configured provider. Generation failures never fall back to mock templates.

Budget and provider status stay visible outside collapsed details, even in mock
mode. Round count follows generated rounds; the start-over epoch is separate.
Like/dislike selection is visible, exclusive, and a second click clears it.

The **הבקשות שנשלחו ל־API** panel lists saved calls for the selected project.
Select a call to inspect its exact endpoint/body and download the JSON body.
`GET /api/projects/<id>/payloads` lists metadata; append `/<call-id>` to inspect or
`/<call-id>/body` to download. The canonical download matches the submitted HTTP
body; authentication headers are never exposed. Dispatch markers distinguish
prepared/unconfirmed calls, attempted calls with unknown outcome, and received
responses. Legacy calls without a marker are explicitly labeled unrecorded.
These statuses do not imply successful content validation. No new calls occur
when viewing payloads. Reference-image data URLs can be present in exact vision
payloads; treat downloaded payloads as private artifacts, never commit them.

Rich source brief structure, edited normalized fields, accepted/rejected metadata,
individual comments and shared batch comments reach the image prompt. The
compiled prompt is bounded at 20KB; oversized context fails explicitly before
image generation rather than silently dropping brief content.
Explicit current edits/feedback take priority over conflicting original fields.


Legacy briefs saved before passive library imports may have no `library_import`
flag. The API now exposes these old information-stage entries as ready library
entries with the complete original brief; the UI offers Start sketches for every
`brief_ready` entry. Merely clicking a library title only opens it. Generation
still requires Start sketches, so library browsing never makes a paid call.

For a runtime with real AI providers and no mock notification transport, set
`broker_provider: "file"`. This transport persists actual human-facing messages in
`broker-inbox/<event-id>.json`, with idempotent receipts and collision rejection.
It is a local durable inbox, not a hosted message-broker integration. Sketches,
professional samples and feedback understanding can all use `openai_dev`; Etsy
publishing remains blocked regardless of these settings. Mock providers remain
available for offline tests and explicit mock configurations only.
