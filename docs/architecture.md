# Architecture and code map

The repository contains source, synthetic fixtures, tests and operating guides.
Installed releases, private configuration and all generated data live elsewhere.
No service imports another service's credentials. Shared Python helpers are under
`services/common`; each daemon has its own entry point, configuration and state.

## Follow a collection through the pipeline

1. Collector accepts a dashboard/manual/scheduled query, admits every request
   against saved provider quota, and writes immutable raw files plus a normalized
   snapshot and finalization receipt.
2. The independent analyzer watchers discover successful saved cycles. Intake
   rebuilds the relevant historical listing/shop pool; deterministic evidence
   processing precedes local or explicitly enabled paid inference.
3. Search refinement delivers proposals to Controller. Controller records named
   cycles, decisions and optional bounded collector operations; it does not load
   Etsy keys. Market insights separately delivers opportunities to Product.
4. Product validates market evidence and performs independent product definition,
   retrieves bounded visual references, and saves exact briefs. Optional SMTP
   and passive Studio HTTP delivery use separate durable outboxes.
5. Studio saves briefs in a library. Nothing generates until a human starts it.
   Its UI then drives design, print assembly, mockups and listing copy. Final
   approval prepares local deliverables; Etsy publishing remains blocked.

## Where to change behavior

| Area | Files / modules | Purpose |
|---|---|---|
| Collector entry/API/UI | `services/collector/etsy_app/__main__.py`, `server.py`, `services/collector/static/` | Local dashboard, scheduler and HTTP contracts |
| Collector collection | `collection.py`, `core.py`, `quota.py`, `entities.py`, `history.py`, `control.py` | Source calls, request admission, observations, tracking/cycles and controlled jobs |
| Analyzer entry/orchestration | `services/analyzer/analyzer/services.py`, `production_config.py` | Independent watchers, service policy and durable work lifecycle |
| Analyzer input/evidence | `saved_intake.py`, `history.py`, `pool.py`, `normalize.py`, `research.py`, `opportunities.py`, `evidence_quality.py` | Legacy/modern saved intake, pooled candidates and scoped evidence |
| Analyzer outputs | `lifecycle.py`, `delivery.py`, `automatic_mail.py`, `adapters/` | Completed-work identity, HTTP retries, mail and replaceable model adapters |
| Controller | `services/controller/pipeline_control/` | `server.py` HTTP timeline; `controller.py` proposals; `cycles.py` named profiles; `admission.py`/`tracking.py`/`comparison.py` controlled experiments and evaluation |
| Optional app supervision | Controller `supervisor.py` | Bounded process supervision; do not run duplicate children alongside systemd |
| Product | `services/product/product_service/` | `server.py` intake; `definition.py`/`briefing.py` grounded definitions; `visual_references.py` references; `studio_delivery.py`/`automatic_mail.py` independent outboxes |
| Studio entry and state | `services/studio/studio_service/__main__.py`, `server.py`, `core.py`, `briefs.py`, `storage.py` | Passive intake, scoped assets, revision/idempotency checks and project history |
| Studio production | `workflow.py`, `production.py`, `memory.py`, `references.py` | Inventory, printable raster/vector/PDF assembly and approved preferences |
| Studio mockups | `lifestyle.py`, `mockup_board.py`, `direct_edit.py`, `generated_images.py` | Concept planning, persistent cards/locks, current full-image final edits and original output gallery |
| Studio provider policy | `providers.py`, `model_roles.py`, `openai_dev.py`, `dev_budget.py`, `credentials.py` | Image/text adapters, allowed roles, exact bodies and preserved budget admission |
| Historical Studio recovery | `refinement.py`, `planning_recovery.py`, `mockup_geometry.py` | Explicit version-1 recovery / bounded syntax repair and saved concept geometry; not the new final-edit path |
| Studio UI | `services/studio/studio_service/static/` | `app.js` project/batch UI; `workflow.js` manufacturing stages; `lifestyle.js` guided mockup cards |
| Shared helpers | `services/common/pipeline_budget.py`, `pipeline_openai.py`, `pipeline_mail/` | Shared Analyzer/Product accounting, bounded paid calls and independent SMTP outboxes |
| Deployment | `deploy/` | Prepare missing configs, render independent units, preflight, migrate into new destinations and upgrade installed settings explicitly |
| Developer tools | `tools/` | Full tests, publication/secret/environment audits, provider-key CLI, pool audit and current browser smoke runners |

The table uses paths relative to each service package where a full path is not
repeated. Tests live beside their owning service; `tests/` at the root verifies
cross-service delivery, deployment, migration, credentials, budgets and publication.
Test helpers may be reused across files; those imports are intentional.

## Compatibility is not dead code

Default mock providers remain useful for credential-free verification. Legacy
saved collector snapshots and analyzer completion receipts exist in deployed data.
Studio version-1 jobs and the original sample-loop APIs are retained for recovery;
new real mockup final edits use version 2. Do not remove these paths or their tests
without a separately planned data/contract migration. Public budget re-exports
also preserve existing imports. The obsolete separate browser sample-loop runner
has been replaced by the current workflow runner; reference upload and vote checks
remain covered there.

See [configuration](configuration.md), [delivery](delivery.md),
[Studio workflow](studio-workflow.md) and [verification](verification.md) next.
