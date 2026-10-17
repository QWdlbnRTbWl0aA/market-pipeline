# Studio: entry points and current behavior

Studio consumes saved Product briefs and produces human-approved digital product
assets. It is independent of Collector and never loads Etsy credentials or
publishes listings. Start with the [workflow](studio-workflow.md) for daily use,
[configuration](configuration.md) for provider activation, and
[historical recovery](studio-recovery.md) for old jobs.

## Passive library

`POST /api/library/briefs` is Product's configured intake. `POST /api/briefs`
and manual form/JSON imports are also passive. Use an `Idempotency-Key`; repeated
identical delivery returns the existing project. All initial brief content fields
are optional. Product metadata, actual reference links and embedded reference
images are retained. Browsing, importing and pre-generation edits do not call a
model, fetch remote examples, publish broker messages or reserve money.

The Hebrew RTL dashboard shows the saved brief. **התחלת סקיצות** explicitly starts
three representative sketches. Like/dislike are mutually exclusive and toggle
off; one shared batch comment drives the next round. The manufacturing workflow
then separates printable inventory, print settings, mockups and listing copy.
Real paid mode never silently substitutes mock template artwork after failure.

## Run independently

```sh
PYTHONPATH=services/studio python3 -m studio_service serve --data /tmp/studio-state --config config/studio.example.json --host 127.0.0.1 --port 8096
```

This uses mock providers and an external state directory. For daemon credential
separation use `deploy/launch.py studio`; see [deployment](deployment.md).
Production defaults bind loopback. Any trusted-network exposure needs explicit
Host configuration/binding and operator access control; do not expose unrelated
reports or directory contents.

## HTTP contracts

| Route | Purpose |
|---|---|
| `GET /health`, `/api/runtime` | Liveness, configured providers and budget metadata |
| `GET /api/projects`, `/api/projects/<id>` | Saved library and one project's state |
| `GET /api/projects/<id>/progress` | Lightweight polling; no inference or full-history serialization |
| `POST /api/projects/<id>/actions/<action>` | Revision-checked, idempotent human actions |
| `GET /api/projects/<id>/files` and `.../files/<token>` | Scoped printable/mockup assets, using explicit saved records |
| `GET /api/projects/<id>/generated-images` and `.../generated-images/<token>` | Original provider images even after job/validation/accounting failure |
| `GET /api/projects/<id>/payloads` and `.../payloads/<token>` | Exact project-scoped API bodies/status without credentials |
| `GET /api/projects/<id>/download`, `.../customer-download` | Approval-gated Studio/customer packages |
| `/api/preferences`, `/api/templates` | Explicitly saved scoped preferences and mockup templates |

Actions require the current `revision`, an `Idempotency-Key`, and any required
consent/approval data. See `core.py`, `workflow.py` and `mockup_board.py` for the
allowlists and validation. Typical current actions include `start_sketches`,
`approve_direction`, `approve_product`, `apply_mockup_comments`, `suggest_mockups`,
`finalize_mockup_board`, `toggle_mockup_lock`, `export_mockup_board`,
`approve_mockups`, `generate_listing` and final copy approval.

Legacy sample-loop actions/assets remain supported for saved-state compatibility,
not as a second current UI. Existing jobs retain their original paid-step identity
and saved request body. Recovery never authorizes collection or paid resubmission.

## State and safety

The data root contains `projects/`, `development-openai/` (ledger, exact requests,
provider responses and step cache), preferences/templates and broker artifacts.
Keep all of it outside source. Atomic writes, file locks, revision checks and
semantic receipts prevent duplicate work. Preserve all paid ledgers and unknown
outcomes; changing configuration does not replenish budget or rewrite responses.

Studio defaults to mock providers and the legacy $1 setting. The explicitly
migrated current trial has a $25 total ceiling, including previous usage and
existing allocations. See [policy](policy.md). Development-only understanding
logs contain observable feedback summaries, not private reasoning; the browser
reports aggregate spending per project. No model output is proof of commercial
quality, correct anatomy, product fidelity or a physical print proof.

Same-origin/Host checks, bounded intake, credential-shaped field rejection,
scoped asset routes, CSP and safe SVG/reference handling are enforced in code.
Broker and real Etsy listing integration are not implied by final approval:
listing handoffs remain blocked. Tests use synthetic fixtures; current browser
verification is in [verification](verification.md).
