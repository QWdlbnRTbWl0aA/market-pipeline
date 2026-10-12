# Studio preliminary implementation

Studio is independent of collection, analysis and Product. It receives a saved
brief through `POST /api/briefs` (JSON, `Idempotency-Key` required), or through the
dashboard's form/import control. The saved Product-service `studio_brief.json`
is supported: vision, customer, customer job and deliverables normalize into the
Studio contract. Missing visual direction or other requirements are requested
from the human. Product's existing outbox is unchanged; automatic producer
delivery is a future integration, not an installed production connection.

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

The minimum brief describes concept, audience, purpose, deliverables and visual
direction. These are deterministic presence/placeholder checks, not an assertion
that arbitrary descriptions are artistically sufficient. Missing information
creates a short human message plus structured brief in a durable broker outbox.
The default mock broker records it locally, with a delivery receipt. Publication
failure does not trigger generation or discard the request; automatic broker
attempts are bounded at three. Messages are visible in the project details.

Sufficient briefs queue exactly ten 320×420 mock SVG sketches. Review each as
accept, reject or accept with comments; save feedback independently or generate
the next ten. Acceptance with comments requires text. Iteration includes current
accepted references and their comments, prior rejected references and whole-set
feedback. All-rejected rounds can still generate alternatives. Refresh preserves
saved state; feedback typed but not saved remains browser-local.
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
offers return to ten sketches. Settings are metadata plus SVG dimensions;
professional print preparation/bleed rendering is not implemented by the mock.
Only SVG is currently supported. Pixel dimensions are bounded to 64–8192.

Final approval requires choosing an accepted professional sample. It saves
`approved-product.json`, a downloadable ZIP (SVG, metadata, mock disclaimer) and
`listing-handoff.json`. Approval is immutable. The listing handoff always has
`blocked_not_wired` / `etsy_api_called: false`. There is no Etsy client, credential
loader or selectable real publisher. These mock artifacts are not sale-ready.

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
for inspection. Explicit retry may regenerate; it is not automatic billing-safe
reconciliation with a future provider.

`ports.py` defines independent Generator, Broker and Listing contracts. Current
configuration accepts only mock/mock/mock/blocked. The generator request
contains structured brief, sample count, accepted/rejected assets with SHA256
and comments, compact negative context, archive references, latest feedback and
professional settings. Implementing real providers later requires explicit
budget admission, provider identity/provenance, output formats, failure and
unknown-outcome reconciliation, and prompt-injection controls. Mock layouts
prove workflow only, not generative quality or reference synthesis. No LLM,
email or Etsy API is called in this version.

The launcher drops inherited credentials; Studio also refuses provider/collector
credential environment names and credential-shaped intake fields. SVGs have a
strict safe markup whitelist and no remote resources. HTTP mutations reject
foreign origins; Host validation, body limits, revision checks, CSP and scoped
asset lookup protect the initial interface. Real broker transport/authentication
and real model credential loading are deliberately pending provider selection.

## API actions

Read `/api/projects` and `/api/projects/<id>`. Submit JSON with `revision` to
`POST /api/projects/<id>/actions/<action>`, with an `Idempotency-Key`. Actions:
`update_brief`, `save_feedback`, `next_sketches`, `start_over`, `generate_final`,
`next_professional`, `back_to_sketches`, `approve_final`, `retry_generation`.
Review payload: `reviews: {sample_id: {decision, comment}}` and `comments`.
Professional generation requires `consent_expensive: true`; final generation
also requires `settings`. Approval requires `candidate_id`. Assets use
`/api/projects/<id>/asset/<sample_id>`, approved ZIP uses `/download`.

Run `python3 tools/test.py` for all components, or Studio's independent unittest
suite. All providers are offline mocks. Browser smoke verification exercises the
actual static UI against a fresh standalone service, separate from production.
