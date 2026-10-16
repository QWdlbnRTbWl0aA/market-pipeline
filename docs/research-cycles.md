# History-aware opportunities and named research cycles

## Market analysis

Enable the new report recipe with `"opportunities": {"enabled": true}` in the
independent analyzer JSON. Research configurations loaded without this section
use the same conservative defaults. Explicit `enabled: false` retains the older
hypothesis recipe. Source changes do not update installed configuration or deploy
daemons. Existing completed jobs retain their receipts; intentional reanalysis
with a different recipe is a separate job, subject to the same ledger.

The pipeline is deterministic candidate grouping (up to 80) → tiered qualification →
previous-offer suppression → bounded refinement if more than ten remain → one
final model-authored product report. Up to twenty qualifying groups enter cheap
refinement; at most ten enter final briefing. Saved pictures, when present, are
interpreted by local Ollama in batches of two, at most ten pictures. URLs are
provenance only: analyzers never fetch them or call Etsy. No cloud images are sent.
No costly call runs when no candidate qualifies. With paid generation disabled,
Ollama may generate up to three model-authored preview briefs, one bounded request
per candidate. These are `local_preview`, never consume the durable offer registry,
and do not suppress candidates from a later paid-quality report. Invalid local
responses are recorded, without automatic inference retries. The target remains
five to ten for the full report; previews disclose their three-candidate cap.
Local briefing responses cannot certify design choices as observations: statement
bases become `design_hypothesis`, while rationale is rendered from saved candidate
content. Raw model responses remain unchanged. Citation and unsupported commercial
claim checks still apply to every brief. Paid model validation is unchanged.

Two evidence tiers allow a fresh niche to support discovery without pretending
that one observation establishes a trend:

- **`discovery_hypothesis`**: at least three independent shops, no majority shop,
  positive cumulative listing views/favorites in at least two shops, and at least
  two established shops with known age of 90 days, positive lifetime shop counters
  and active inventory. Conflicting counters and observed resets do not qualify
  a shop. At least 80% known native-currency prices and saved query-content matches
  are required, along with saved Etsy example URLs from at least two shops.
  Lifetime shop sales provide context only, never listing demand.
  Missing historical inventory, unknown cheap-price benchmarks and observed cheap
  crowding are explicit validation risks, not invented measurements. Recommendations
  must describe an original product experiment and retain cited examples.
- **`trend_supported`**: the existing stronger historical checks below remain
  required. This tier still does not verify listing purchases or profitability.

Set `opportunities.discovery_enabled: false` to require historical qualification
for every candidate. Existing JSON configurations pick up the new defaults on
release deployment; no configuration rewrite is required. Production state is not
migrated or modified by a source checkout. The new versioned recipe creates a
separate job on an explicit reanalysis; saved completed jobs and watcher cursors
remain intact and are not replayed automatically. Use an isolated output root and
local capture receiver to review development outputs before downstream delivery.

Historical qualification uses these adjustable defaults:

- At least three independent observed shops; no shop supplies over half a group.
- At least two shops with three comparable counter observations over seven days,
  positive shop activity and known age of at least 90 days. Counter resets and
  conflicting observations prevent qualification.
- The candidate represents at least 80% of each qualifying shop's active listings
  in both current and saved historical observations. Historical content/category
  must still match. Pairwise content similarity must be at least 0.35 and category
  consistency at least 80%. Missing or partial inventories are lower bounds.
- Annualized **whole-shop** transaction growth per current active listing is at
  least one. This is an inventory-level activity proxy, never allocated listing
  sales or a claim of actual annual purchases. A large mixed shop with 70 annual
  transactions and 100 listings does not establish demand for its individual art.
- Positive comparable listing engagement in at least two shops, with the existing
  three-observation/seven-day/no-reset qualification. Views/favorites remain proxies.
- At least 80% comparable price coverage in configured currencies; no more than
  60% at/below the configured cheap-price benchmark. No exchange rate is invented.
- At least 80% of the group matches a saved query's substantive content terms.

Priority combines listing trend, shop context, diversity, price position and
history depth. Previous assessment scores receive 30% weight with exponential
recency decay (30-day half-life); current evidence receives 70%. These transparent
weights prioritize validation, not probability of purchase or profitability.
Failed qualification remains failed regardless of an old strong score.

The consumer target is **five to ten new product-validation candidates**, each
labeled with its evidence tier and concrete product brief. Fewer are reported
when evidence or novel supply is insufficient; `target_count_met`, `shortfall`
and reason counts explain the gap. `listing_sales` remains null and verified
demand/thin-supply flags remain false. Broad marketplace supply and conversion
still need separate validation before commercial investment.

The analyzer saves immutable job evidence, source identity/provenance, dated
`market-assessments/*.json`, and a durable `market-assessments/offers.json` registry.
Concept identity uses normalized phrase tokens, with listing-overlap checks for
historical assessments. A cross-process lock serializes offer reservation across
market jobs. Completed reports and failed HTTP deliveries remain recoverable;
delivery-only recovery reuses the original output rather than resuggesting it.
Retain these files during migration and rollback. Do not reset the offer registry
or paid ledger to repeat suggestions. Full histories stay in saved evidence;
model/HTTP summaries contain bounded examples and intervals.

## Search refinement

The refiner reviews only the current query results. Generic words such as
`printable` alone cannot establish niche relevance; multiple query intents are
checked independently. Physical, unrelated, partial-match, description-only and
instruction-shaped content remain review flags, not automatic fraud labels.
An unchanged query is a control, not a recommendation. Query experiments retain
the original niche terms, add content modifiers supported by multiple shops, and
deduplicate word ordering, repeated words and simple English plurals. Specific
modifiers take precedence over ubiquitous format wording.

Every proposed experiment includes its source query, added terms, observed
listing/shop support, expected effect and comparison criteria. Local-only rationale
is rendered from those facts; model labels remain unverified. Only selected group
examples receive semantic classification, not the entire result set. Reports
disclose truncation and never infer query exhaustion from a bounded first sample.
Actual saved Etsy listing URLs and provenance are included in evidence; no URLs
are invented or fetched. Recommendations do not modify collector settings.

## Search cycles and operator interface

On dashboard `/v1`, enter trial keywords/shops/limit, enter a readable cycle name,
then select **Start a new named cycle**. This saves a separate profile: up to four
phrases and five selected shops, with no exclusions so identities can be revisited.
The original daily collector configuration is separate. Disable its daily button
if replacing that legacy schedule with named cycles; creating a cycle does not
silently rewrite it. Selected shops can be copied from saved-run findings into the
trial shop-ID field before finalizing a profile.

Each profile preserves its name, exact parameters and checksum, daily/weekly
cadence, manual override, observations and reason for cadence changes. Profiles are
small indexes; full listing/shop identity sets are immutable per-run artifacts
under `controller/cycle-observations/{cycle_id}/{source_run_id}.json`. Retain both.
Profiles are immutable: create another named profile for different parameters. The browser can
find profiles by name or keywords. Starting a fresh niche preserves finalized ones.
Daily/Weekly override automatic detection; Automatic cadence removes the override.
Pause stops future admission. Finalize preserves that profile for weekly monitoring.
First scheduled collection is due tomorrow; weekly activation is due seven days
after the decision. Controller `execution_enabled` must be true for submissions.

Automatic weekly transition requires at least three assessments on distinct UTC
dates spanning seven days. **Every observation in the latest stabilization window**
must be complete, nonempty, comparable, add at most 2% new relevant listings/shops,
and have identical nonempty refinement recommendations. Daily samples therefore
need a full week of stable observations, not just three consecutive days.
Missing query/shop paths, truncation, exclusions and unstable recommendations
cannot establish exhaustion. New relevant content returns automatic cycles to
daily; a manual override remains authoritative. The refiner reports novelty only;
the Controller independently verifies saved snapshots, hashes and completeness
before changing a cycle's cadence.

Collection admission retains finite bounds: 100 requests, up to 20 shop follow-ups
and at most ten pages per keyword/shop path. Page allowance is reduced with more
paths to keep total request demand within 100. These are upper bounds, not new
Etsy allowances: existing QPS/QPD protection and the 5% reserve still apply to every
request. A large search may be truncated and remain daily until a narrower complete
profile is selected or an operator explicitly chooses weekly cadence.

Jobs are durably reserved before HTTP. In-flight collections block subsequent
slots; missed slots are not burst-replayed. Unknown submissions are held for
**Check saved submission**, which performs an authenticated local collector GET
and validates the original request checksum, without making Etsy calls or blindly
resending. Access challenges pause the cycle and require saved-evidence operational
review. Existing independently reviewed daily tracking cohorts are unchanged.

Controller routes: `POST /cycles`, `POST /cycles/{cycle_id}/decision` and `GET /status`.
Collector exposes the same-origin `/api/pipeline` proxy; its independent launcher
points it to the fixed loopback Controller. The public analyzer intake remains
saved artifacts only and never receives collector credentials.

**Deferred:** no standalone scheduled weekly aggregate trend-analysis/reporting
service is implemented. Weekly collections still trigger the existing independent
per-collection analyzers, using saved observation/assessment history.

## Development budget and recurring estimate

This change used zero paid development calls. For authorized development trials,
the example paid policy adds `development: {"id":"market-history-development",
"total_usd":0.5}`. This sub-envelope shares the existing ledger and $2 total cap;
it cannot replenish prior spend, change its registered allowance or ignore unknown
outcomes. Admission precedes key loading. Keep the same development identity
across restarts. Removing the development restriction later is an explicit
configuration decision; preserve all ledger records. Studio's separate $1 envelope
is unchanged. The final output ceiling is 4,000 tokens for concise briefs.

Illustrative standard-tier costs, using [official GPT-6 Luna pricing](https://developers.openai.com/api/docs/models/gpt-6-luna)
($0.10 input/$0.50 output per million) and [GPT-6.1 Sol pricing](https://developers.openai.com/api/docs/models/gpt-6.1-sol)
($2 input/$10 output per million), checked 2026-10-13:

| Stage | Assumed input/output tokens | Approximate cost |
|---|---:|---:|
| Market cheap shortlist, only when needed | 12,000 / 1,000 | $0.0017 |
| Market final briefs | 12,000 / 3,000 | $0.0540 |
| Refiner cheap | 6,000 / 600 | $0.0009 |
| Refiner final | 6,000 / 800 | $0.0200 |
| Both services per successful collection | — | $0.0766 |

About **$2.30/month per daily cycle**, or **$0.33/month per weekly cycle** (30 and
4.33 executions). These are workload assumptions, not measured production costs;
reasoning/output length and context size can change the result. Empty, insufficient,
duplicate and cached work can cost less. Paid admission uses UTF-8 bytes plus
framing as a conservative input-token bound, so its reservation is deliberately
larger than this estimate. With a 90,000 input bound and 4,000 output cap, two cheap
and two final calls reserve at most $0.462 per cycle. Existing paid balances and
the optional sub-envelope may block admission earlier. Local Ollama compute,
Studio/Product generation, infrastructure and external API costs are excluded.
