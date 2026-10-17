# Verification

## Current baseline

The 2026-10-17 housekeeping baseline has **492 offline unit/integration tests**:

| Suite | Tests | Main responsibilities |
|---|---:|---|
| Collector | 94 | Quota admission, pagination/exclusions, observations, scheduler, control jobs and mobile dashboard contracts |
| Analyzer | 144 | Legacy/modern intake, pooled history/evidence, independent jobs, budgets, stable completion and bounded delivery |
| Product | 45 | Grounded full definitions, references, passive Studio outbox and recovery |
| Controller | 32 | Proposals, cycles, experiments, tracking, admission and supervision |
| Studio | 126 | Passive briefs, feedback, print assembly, model contracts, budgets, locks, original image visibility and historical recovery |
| Cross-component/deployment | 51 | End-to-end HTTP/mail fixtures, credential separation, daemon configuration/migration and publication |

All existing tests are retained: none were exact duplicate bodies, and recovery
paths still protect saved operational data. The old separate sample-loop browser
runner was removed because it targeted the superseded UI flow. Its reference
upload/paste and vote checks are covered by the current workflow runner.
Counts are a dated baseline; actual command results are authoritative as code evolves.

## Commands

Install declared dependencies in your managed environment, then:

```sh
python3 tools/test.py
```

The runner isolates each component's unittest discovery so same-named test modules
do not collide. Run an individual suite from `services/<component>` using
`python3 -m unittest discover -s tests -v`; run root integration tests from the
repository root. The complete suite requires Pillow; no keys or model server are
needed. Synthetic fixtures/temporary HTTP and SMTP transports never call Etsy,
OpenAI, external SMTP or Ollama generation.

Optional browser checks require an **already installed** Firefox/geckodriver:

```sh
python3 tools/studio_workflow_smoke.py --output /tmp/studio-workflow-smoke
python3 tools/studio_workflow_smoke.py --lifestyle --targeted-refinement --output /tmp/studio-recovery-smoke
python3 tools/studio_direct_edit_smoke.py --output /tmp/studio-direct-edit-smoke
```

Each starts an isolated temporary fixture server, uses synthetic providers and
stops its processes. Output paths must be outside source. The first covers print
assembly/template mockups/listing delivery; lifestyle mode also covers edited scene
preservation and rejected-action drafts; targeted mode verifies historical recovery.
The direct-edit flow exercises the actual image-adapter wire contract using an
offline transport, exact Hebrew notes, human approval and visible returned images
after dimension validation failure. Browser fixtures are disposable after review;
retain concise logs/screenshots and remove their generated state when finished.

## Configuration, deployment and publication

`deploy/prepare.py`, configuration upgrade helpers, migration, credential loaders
and independent unit rendering have offline regression coverage. Preflight can
validate an actual installed account/layout; synthetic tests do not prove that a
particular production host, firewall, provider account or permission policy works.
This checkout is separate from installed releases. Housekeeping does not install,
restart, migrate or recover production services.

From a clean committed tree:

```sh
python3 tools/publish_check.py --output /tmp/market-pipeline-publication.json
```

Use `tools/secret_audit.py` for optional offline exact credential comparisons and
private environment inventories without printing values. The publication hook
and CI also scan reachable/unreachable Git objects and reject generated data,
private paths, network details and secrets. See [sanitation](sanitation.md).

CI declares Python 3.12 and installs the repository's Pillow requirement before
running the full suite. A local successful run is not a claim that a future
hosted CI job or real account-level deployment has already run.

## What functional checks do not establish

- Passing fixtures do not certify market demand, thin supply or commercial success.
- One saved observation cannot establish a historical trend or listing sales.
- Synthetic model responses cannot prove paid image quality, anatomy, instruction
  adherence or product fidelity; human review and actual print proof are separate.
- SMTP acceptance is not proof of inbox placement; delivery may land in spam.
- No cleanup/test result authorizes paid calls, collection, deployment or recovery.

Private raw evidence, transaction manifests and dated test reports remain outside
Git. Earlier development/deployment observations are recoverable in history;
they are not current claims of account provisioning, remaining credit or publication.
