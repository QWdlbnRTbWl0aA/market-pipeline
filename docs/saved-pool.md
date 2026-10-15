# Market candidate pool

Collection exclusions reduce requests and newly retained rows. They must not
reduce Market Insights to evaluating only those additions. A successful collection
now triggers an as-of pool rebuild through the saved-file intake abstraction.
Search refinement still evaluates the actual current query results and its query
history; pooled records do not make a truncated or deduplicated query complete.

Market Insights reads eligible finalized successful snapshots and matching DQA in
`saved_runs_root`. It unions digital discoveries matching any current niche,
selected shops, taxonomy and price bounds. Pagination/result bounds and fetch
exclusions do not truncate this pool. Legacy broad-query collections can contribute
matching content to a more specific current query. Conflicting explicit named
cycles do not introduce new candidate identities into each other. Tracking updates
known identities; unrelated tracking does not introduce candidates without a
saved discovery or approved cohort. Count probes and future/failed collections
are excluded. Missing query intent does not authorize a global niche import.

Each identity uses its latest saved observation, retaining that observation's
date and source run. Older values remain historical observations, never new
measurements. If its latest saved observation fails the current filters, an old
matching version does not qualify it for import. Listing engagement and whole-shop
counters stay separate. Same-time counter conflicts remain visible to DQA.
Saved images retain their source run directory; no image URL is fetched.

Every market job saves `saved-pool.json`, also present in normalized metadata,
with source snapshot hashes, membership, actual observation dates, mechanical
normalization counts and issues. The pool manifest participates in inference
identity. Reports and automatic email distinguish collection additions, historical
members and total pooled listings/shops. Source snapshots, prior reports, paid
ledgers, offer suppression and delivery receipts are not changed.

No configuration field is required to enable pooling in the corrected code.
Historical development collections must already have been migrated into the
configured saved-artifact root. The analyzer cannot see offline archives elsewhere
or data it lacks permission to read. Do not clear collector fetch history to
compensate for missing migration: that would cause unnecessary collection requests.
The pool is rebuildable from immutable source artifacts and has no database.

An installed watcher does not automatically rerun completed collections on upgrade.
A new collection uses the pool. A deliberately authorized single-report invocation
can analyze a saved collection with corrected intake; it may use paid inference and
delivery, so do not use that to diagnose coverage. Existing delivery-only recovery
does not reanalyze or rebuild already completed payloads.

For credential-free, no-inference diagnostics, after installing the corrected
source, run as an account that can read saved artifacts:

```bash
python3 tools/analyzer_pool_audit.py \
  --runs /var/lib/market-pipeline/collector/runs \
  --run SAVED_RUN_ID \
  --output /tmp/market-pipeline-pool-audit.json
```

The audit only writes its designated output; it never delivers mail/HTTP, calls
models, starts collection, or changes source/analysis state. It reports default
deterministic qualification with a USD price reference, not custom deployed policy
or prior-offer suppression. Pool size alone cannot guarantee ten recommendations:
the current policy also requires multi-shop, comparable listing and shop history,
inventory context and price evidence. Insufficient evidence stays explicit rather
than being replaced with invented business claims.
