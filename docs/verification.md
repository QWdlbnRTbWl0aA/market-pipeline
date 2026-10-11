# Preparation verification — 2026-10-11

## Functional results

218 standard-library tests passed: collector 92, analyzer 75, product 15,
controller 22, deployment/policy/publication/migration 14. The suite covers
file persistence, pagination/exclusions, raw provenance, DQA, quota/recovery,
independent analysis, credential separation, bounded paid admission, idempotent
delivery, refinement comparisons, indefinite tracking, product briefs/drafts
and process recovery. Fixtures and mock responses are explicitly synthetic.

Five actual local daemon processes started independently, served health or
heartbeat status, terminated cleanly on SIGTERM and restarted without creating
collection requests or modifying the test paid ledger. All rendered systemd
units passed `systemd-analyze verify` under installed systemd 255. JavaScript
syntax verification passed.

A separate smoke test served **real saved files**, copied through the offline
migration: 20 saved runs, successful snapshot read, fresh request counters and
5% quota reserve. The observed 5,000 provider limit produced a 250-request
reserve and a 4,750 effective ceiling. No Etsy requests were generated. The
migration preserved 14 paid ledger entries ($0.1570365) byte for byte and
accounted for all nine completed analysis receipts. Original artifacts remained
unchanged. Ollama's installed model was verified using its read-only tags route.

This preparation made no Etsy/OpenAI inference/SMTP requests, no Ollama
generation requests and spent $0. It did not assess or claim improved analysis
quality. Existing evidence gaps are retained rather than filled with invented
demand, listing purchases or sales.

## Sanitation and GitHub

Original repositories: 12,132 working files and 608 Git objects scanned, including
unreachable objects. Compared four known local credential values without
printing them. No exact credential match. Five literal-secret findings were
the same documented SMTP placeholder (current README and four historical
blobs); reviewed and classified. Original repositories remain private and are
not publication sources.

The publication repository has fresh object history and a reviewed source/test/
documentation allowlist. Runtime artifacts, original Git objects, keys and local
configuration are excluded. Pattern/full-object auditing, exact local credential
comparison and archive inspection are run again on the final committed tree.
The local pre-push guard and CI repeat offline publication checks.

The dedicated SSH key is mode 600 outside source. GitHub authenticated it as
`QWdlbnRTbWl0aA`. Reading the selected remote returned “Repository not found”;
the remote must be created or made accessible before publication. Nothing was
pushed and no remote repository was created.

## Remaining acceptance

The current legacy development chain is unchanged. The new candidate is not
installed under `market-pipeline`: that account and `/opt`, `/etc`, `/var/lib`
deployment layout are not provisioned. A development preflight passed using the
existing user and migrated temporary state; the actual deployment preflight
correctly reports missing account/configuration. Test root and rendered units
remain outside source. Test/smoke processes were stopped.

Before declaring an installed deployment ready: provision the designated
account, migrate with writers stopped, install the units, verify credential/
filesystem isolation under that account, then enable the chosen daemons and
settings. GitHub repository provisioning and explicit push authorization remain
separate. These are deployment/publication steps, not a two-week waiting period
or a new daily spending cap.
