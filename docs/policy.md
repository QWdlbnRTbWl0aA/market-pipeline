# Budgets, provider limits and evidence

## Development/testing spending

The shared budget is $2 **total**, including the existing ledger's charges and
uncertain reservations. `daily_usd: null` and `daily_calls: null` mean no local
daily restriction. Rolling dates do not reset total spending. An experiment can
reserve four bounded calls; this is a per-experiment envelope, not ten calls/day.
Unknown paid outcomes stop admission until explicit reconciliation. Neither
deployment, rollback nor a fresh process may reset that accounting.

Model rates and conservative token bounds are explicit in
`services/common/pipeline_openai.py` and Studio's provider/budget modules. They
are configured accounting assumptions, not a claim about current vendor prices
or the billing dashboard. Updating a model/tier/rate requires checking provider
contracts and the corresponding reservation tests. No cache discount is assumed
unless explicitly accounted for; retries/redirects are not implicit.

Studio has a separate explicitly authorized **$25 total trial**, including all
prior Studio usage and existing allocation ceilings: comparison $4, production
$10, mockups $3, listing $2 and trial $6. The legacy default remains $1 for old
configurations. Neither copying a trial example nor creating a new data directory
is permission to reset prior charges. Unknown outcomes remain fully reserved.
The budget CLI can explicitly migrate an existing ceiling while reconciling an
operator-confirmed prior total. See [Studio workflow](studio-workflow.md).

## Etsy admission

Etsy applies QPS and rolling 24-hour QPD limits per key; live allowance is read
from provider response headers. See [Etsy rate limits](https://developers.etsy.com/documentation/essentials/rate-limits/).
The allowed local ceiling is provider QPD minus `ceil(QPD * 0.05)`. There is no
additional configured application daily cap in the prepared policy. Example:
5,000 QPD → 250 reserved → at most 4,750 counted local requests per rolling
window, further constrained by observed provider remaining allowance.

No allowance is invented before headers exist: one paced bootstrap request is
permitted, then further requests stop if headers remain unavailable. Admission
is rechecked before every sequential request. Conservatively space requests and
respect provider per-second remaining, waiting a full second plus a buffer on
exhaustion. Discovery pagination, shop follow-ups and tracking share quota.

At daily thresholds, wait in bounded increments and recheck the saved rolling
window before sending. Keep observed remaining separate from projected local
recovery: provider bucket timing and other users of the key are unknown. A real
401/403/429 challenge parks the run, persists cooldown/provenance and is not
automatically retried. Other clients sharing the key can consume allowance
between our observations; local protection cannot guarantee their behavior.

## Readiness and evidence

Preparation is not restricted to a two-week calendar. Tracking cohorts have no
automatic expiry, and intake does not impose a default fourteen-day history
window. Software tests can establish deployment readiness immediately.
They cannot establish commercial demand. Multi-day comparable observations are
required before reporting trends; minimum evidence rules preserve honesty and
do not impose a software deployment waiting period. Shop-wide sales, views and
favorites are scoped proxies; missing listing purchases, conversion, verified
demand and total market supply remain missing.
