# Analyzer output delivery and recovery

Analysis completion, HTTP delivery and product readiness are separate states.
Delivery uses saved artifacts and never generates inference, modifies collector
settings or queries the source. The research recipe and inference identity are
unchanged by this correction.

## Payload and receiver contracts

`outbound.json` remains the original immutable analysis artifact. The sender
creates a deterministic `outbound-wire.json` containing precisely the same JSON
fields in compact form, preserves `delivery_id`, and records source/wire hashes
and byte counts in each numbered delivery receipt. Receivers keep their five
million byte limit. Oversize compact JSON is rejected locally before HTTP and
parked as a permanent failure; the sender does not truncate evidence or increase
the receiver limit.

The supplied two oversize artifacts shrink from about 5.19 MB to 2.77 MB by
serialization alone. Compact delivery is also compatible with a previously
acknowledged pretty-printed body: both receivers compare JSON content when the
same delivery ID has a different byte hash. Equivalent JSON is a duplicate;
changed content is a collision. Existing persisted receipts remain unchanged.

Market Insights local previews can contain `product_brief: null`, because their
local classification stage does not author final briefs. Product acknowledges
and durably retains those completed previews, marking them
`awaiting_product_brief`. Neither the deterministic nor enhanced Product path
generates products/model calls from such incomplete previews. Null briefs in a
final/provisional report and malformed nested objects remain invalid. HTTP
handlers return bounded errors instead of dropping connections: validation
errors are 400, oversize bodies 413, and unavailable intake storage 503.

## Retry policy

The optional `delivery` object in independent analyzer JSON has these defaults:

```json
{
  "max_attempts": 5,
  "retry_base_seconds": 30,
  "retry_max_seconds": 3600,
  "max_payload_bytes": 5000000,
  "failure_events": {
    "enabled": false,
    "endpoint": null,
    "max_attempts": 3,
    "retry_seconds": 60
  }
}
```

Connection failures/timeouts, HTTP 408/425/429 and server errors are transient;
501/505, other HTTP rejections, invalid local artifacts and redirects are
permanent. Transient failures use exponential backoff and honor `Retry-After`.
The attempt limit includes the first attempt; preflight rejections have a receipt
with `request_attempted: false`. Attempts are reserved durably before sending so
uncertain/crashed sends cannot evade the cap. Successful 2xx acknowledgments are
never retried automatically.

Permanent failures stop immediately as `permanent_failure`. Exhaustion becomes
`retries_exhausted`. Both are parked by the watcher cursor while preserving
analysis completion, outbound data, IDs, quota/paid accounting and every receipt.
Changing delivery settings does not change inference identity. Legacy numbered
attempts count toward the limit: a job with hundreds of attempts is parked on
upgrade and requires explicit delivery recovery. Restart does not reset its cap.
Pending watcher retries remain bound to the saved job rather than recomputing
an inference identity from current model settings. Explicit historic delivery
recovery can continue below the watcher's initial collection-time floor.

## Failure events and optional broker integration

Every terminal delivery failure publishes one durable
`analysis_delivery_failed` event per delivery generation into
`<output_root>/delivery-failures/<event_id>.json`. The event contains IDs, counters,
failure status, last HTTP/error type and a reference to the retained artifact;
it does not contain listing content or credentials. Repeated watcher triggers
do not create repeated failure events. This local outbox is always available,
including when broker integration is disabled.

For optional broker integration, set `failure_events.enabled` and an HTTP
`endpoint` for a numeric-loopback broker relay. The relay may adapt the event to
the chosen broker; a broker/protocol is not assumed and no SDK/account setup is
required. The sender supplies the event ID as `Idempotency-Key`. The relay must
persist before acknowledging and deduplicate by that ID. This is at-least-once
publication: a lost acknowledgment can cause a repeated send with the same ID.

The relay publisher has its own persisted finite retry budget, respects
`Retry-After`, and retains `*.publication.json` outcomes beside the immutable
events. It processes events independently of watcher cursors, including parked
jobs, with at most one bounded HTTP attempt per poll and a nonblocking publisher
lock. Relay failure does not regenerate analysis or discard the failure event.
Disabled integration performs no publication HTTP. Native broker adapters can
replace the relay transport without changing the inference/delivery contracts.

## Explicit recovery and deployment hold

Deploy a verified release of analyzer, Controller and Product code first. Merely
moving the release symlink does not reload modules in existing processes. Verify
each affected daemon is actually running the selected release before recovery.
Preparation and tests do not install releases or restart production daemons.

After reviewing a failed job and repairing its receiver/configuration, run as
the application account using the analyzer daemon's clean launch environment.
Invoke one saved job from the analyzer component directory, for example:

```sh
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 -m analyzer.services \
  --config /etc/market-pipeline/analyzer.json \
  --service market_insights --recover-delivery JOB_ID \
  --reason 'Reviewed receiver repair; retry original saved output'
```

Use `search_refinement` for the other service. Replace `JOB_ID` with the
reviewed job's actual hexadecimal ID. Recovery archives the prior state/reason
in a numbered receipt, starts a new bounded delivery generation, keeps cumulative
attempt counts and every original artifact, and attempts one delivery immediately.
It reopens an existing watcher cursor only if delivery is still pending. A
successfully delivered job is a no-op. It never reads collection artifacts,
constructs models, repeats inference or changes paid accounting. Do not use
`--retry-failed` for delivery recovery; that option targets analysis.

The six supplied jobs were recovered only in disposable evidence copies against
fresh local receivers: all six acknowledged, five previews waited for briefs,
and the original evidence hashes remained unchanged. Production recovery and
service activation remain explicit operational actions.
