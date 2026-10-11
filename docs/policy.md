# Budgets, provider limits and evidence

## Development/testing spending

The shared budget is $2 **total**, including the existing ledger's charges and
uncertain reservations. `daily_usd: null` and `daily_calls: null` mean no local
daily restriction. Rolling dates do not reset total spending. An experiment can
reserve four bounded calls; this is a per-experiment envelope, not ten calls/day.
Unknown paid outcomes stop admission until explicit reconciliation. Neither
deployment, rollback nor a fresh process may reset that accounting.

Rates are explicit for the Responses API's standard service tier: `gpt-6-luna`
input/output $0.10/$0.50 per million tokens; `gpt-6.1-sol` $2/$10 for the bounded
short-context calls. Verified 2026-10-11 against [OpenAI pricing](https://developers.openai.com/api/docs/pricing).
The adapter explicitly requests `service_tier: default`, charges input
conservatively without assuming cache discounts, limits output tokens and
reserves worst-case spend before loading the key or sending. Token reservations
must cover the actual model/tier; changing models/pricing requires code and tests.
Paid images are disabled until their token cost can be reserved; saved images
can be processed locally. Provider retries and redirects are disabled.

The inherited ledger at preparation recorded $0.1570365 across 14 calls, with
no unknown outcomes; $1.8429635 remained. This is an observation of local
accounting, not an assertion about unrelated API use or the billing dashboard.

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
