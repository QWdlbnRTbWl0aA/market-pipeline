# Development log

## 2026-10-11 — pre-deployment preparation

User clarified that there is no production deployment, no daily preparation
cap or two-week operating period. OpenAI development/testing remains $2 total;
Etsy follows provider policy with a 5% reserve. User selected one repository and
the dedicated `market-pipeline` application account, then added the new SSH key.

Created a fresh publication repository from the previously verified collector,
analyzer, controller and product source/test components. Preserved private
repositories and checkpoints. Updated admission for optional daily caps,
provider-percentage reserve, one unknown-quota bootstrap request and tracking
without a fixed expiry. Forced standard OpenAI service tier; made credential
paths deployment-specific. Added clean independent launchers, graceful shutdown,
systemd unit rendering, preflight, safe state migration and publication guards.

Functional tests use synthetic local inputs. A real-file offline migration
accounted for nine completed analysis receipts and 14 paid ledger entries,
preserving $0.1570365 accounting and collector history without requests. SSH
authenticated as the requested GitHub account. Unit syntax verification passed.
No Etsy/OpenAI/model-generation/email call or money spent by this preparation.

Deep audit scanned original working files and all Git objects against known
credential values; no exact match was found. Literal-secret candidates were
reviewed as an SMTP documentation placeholder. Fresh history excludes legacy
objects and runtime outputs. Final detailed counts/results live outside source;
see docs/verification.md for the concise reviewed record.

Remaining deployment acceptance: provision the dedicated account/layout,
install and test systemd isolation under that account, activate intended settings
with migrated accounting, and authorize GitHub publication. Current legacy
development processes have not been promoted or replaced by this preparation.

## 2026-10-12 — authorized GitHub publication

User explicitly authorized pushing after sanitation confirmation. Rechecked the
clean committed tree, all 139 Git objects and four known local credential values:
no findings. Target remains `QWdlbnRTbWl0aA/market-pipeline`. Remote discovery
returned Repository not found, so publication is waiting for the empty repository
to be created or made accessible. Push approval persists; no further approval is
needed once access is available. No source, paid API or service/runtime changes
were made. Audit reports remain outside source.

## 2026-10-12 — GitHub publication completed

User supplied the provisioned repository URL. Remote discovery confirmed an
empty accessible repository. Rechecked 118 files, every Git object and the four
known local credential values; no secrets or generated artifacts were found.
The authorized atomic push published `main`, `prepare/first-deployment` and
`deployment-candidate-20261011` through the dedicated SSH identity. Recorded
completion in documentation and checked remote refs against the local commits.
Runtime state and private legacy repositories were not published or changed.
This was publication only; daemon installation and actual production deployment
remain separate. Audit and publication receipts remain outside source.

## 2026-10-12 — network and machine privacy republication

User identified real network addresses in tests, deleted/recreated the remote,
and authorized correction and republication. Replaced those fixtures with
reserved documentation addresses and example domains. Removed the local
hostname default; explicit runtime configuration still supports chosen network
names. Extended sanitation to addresses, hostnames, personal paths, filenames
and unreachable Git objects; keep the observed environment inventory private.
Rebuilt a fresh publication history so earlier commits cannot expose the removed
network details. Preserved the old repository privately. Functional verification,
all-object and archive audit receipts are stored outside source. No collection,
paid/model-generation, email or running-service changes were required.

## 2026-10-12 — Controller/collector authentication generation fix

User requested a committed and pushed fix for the deployment token format.
Changed preparation to generate 32 random bytes as 64 lowercase hexadecimal
characters. Added a regression that failed before the fix and now passes both
the real Controller sender validation and collector authentication validator,
using a synthetic transport with no network request. Verified owner-only file
permissions and retained the existing-token preservation test. All 224 offline
tests passed. Documented that previously generated incompatible token files
require explicit deployment rotation; no existing runtime token was changed.
Secret/environment audits passed; detailed test/audit results remain outside
source. No services were restarted and no source/paid/model/email calls occurred.

## 2026-10-12 — legacy analyzer query-context compatibility

User authorized the compatibility correction, regression tests, commit and push;
explicitly excluded deployment, production-state changes and failed-job recovery.
Saved intake now recovers absent/null `settings.niches` from saved
`queries[*].niche`, retaining the source locations in derived provenance. Modern
settings, including an explicit empty niche list, remain authoritative. Research
evidence handles a null niche list defensively. Source hashes and the research
recipe version remain unchanged so existing job identities are preserved.

The initial regression run reproduced failures before the correction. Eight new
tests cover the early 48/48/24-row snapshot structures, missing optional listing
fields, query relevance, null settings/context, authoritative modern settings,
immutable source bytes and job identity. Both services complete with synthetic
local responses and delivery transports; repeated triggers perform no duplicate
inference/delivery, and existing failed jobs remain parked without explicit retry.
All 232 offline tests passed: collector 92, analyzer 83, product 15, controller
22 and repository 20. Read-only deterministic checks on the three original saved
development snapshots and a newer snapshot also passed; original snapshot/DQA
hashes were unchanged. Detailed test and privacy-audit results remain outside
source. No production files, jobs or services were changed. No actual inference,
collection, paid API or email requests were made.

## 2026-10-12 — authorized workspace cleanup

User authorized removal of temporary files and obsolete versions, compaction of
saved data and reduction of old reports. Kept this GitHub-backed checkout as the
maintained source. Archived eight private legacy/preparation trees, including
unpublished Git history and staged changes, raw snapshots/DQA, accounting,
controller state, historical configurations and reports. Verified SHA256 for all
29,656 retained files and exact archive coverage, then rechecked sources before
removing the obsolete working copies. Removed disposable browser profiles and
Python caches. An indexed private archive and concise cleanup report remain
outside source; 20 original collection runs have an offline index. Allocated
workspace usage fell from 3.26 GiB to 0.57 GiB, reclaiming about 2.69 GiB.

Retained a retirement notice and failing legacy launcher at the old collector
working-directory location because existing shells still use it. No production
files, services or security settings were changed. The collector was already
failed during inspection; its credential-validation repair is a subsequent
assignment. Updated instructions to reflect the user's completed deployment and
the archived private checkpoints. No collection/inference/paid/email calls were
made. Archive verification receipts and restore instructions remain private.

## 2026-10-12 — portable Collector credential validation

User reported valid systemd LoadCredential copies rejected by the Collector
launcher and required a portable correction without host-specific identities,
paths or observed permission-mode values. The previous check required the file
owner to equal the process UID and rejected every group permission. Regressions
for differing manager ownership and group-readable delivery both failed before
the fix. The loader now relies on kernel read admission, retains descriptor-based
regular-file/symlink/size checks, permits read-only group access, and rejects
group-write and access for others using symbolic permission bits. It uses a
nonblocking open to reject FIFOs without hanging and checks the actual read bound.
Literal assignment parsing and credential separation remain unchanged.

Nine new offline regressions cover delivery ownership/group readability,
existing private files, unsafe permissions, symlinks/directories/FIFOs, actual
access denial, bounded literal parsing, non-disclosure and component separation.
All 241 tests passed: collector 92, analyzer 83, product 15, controller 22 and
repository 29. Synthetic metadata models alternate credential ownership; no
privileged chown, OS account creation, actual systemd activation or real secret
loading was used in functional tests. Full-object credential/privacy audits
passed. Reports remain outside source. Production configuration/state, installed
releases and services were not changed; no collection/inference/paid/email calls
were made. The source correction still requires a separately authorized deploy.

## 2026-10-12 — durable analyzer delivery correction

User supplied offline failure evidence and authorized investigation, correction,
validation, commit and push. Six completed undelivered jobs had hundreds of
attempts. Two original 5.19 MB outbound artifacts exceed the receiver limit but
fit at 2.77 MB with compact JSON. Five Market Insights jobs are local previews
with null product briefs, which crashed Product validation. Evidence also shows
receivers loading an earlier release; release activation alone does not reload
existing daemon processes.

Added deterministic compact wire artifacts while preserving original outbound
bytes, fields, IDs and inference identity. Receiver duplicate checks admit
equivalent JSON serialization without altering old receipts. Product stores
incomplete local previews as awaiting_product_brief without generating products
or invoking models; malformed final briefs remain invalid. Receivers return
400/413/503 for validation/size/storage failures rather than crashing requests.

Delivery now classifies transient/permanent failures, enforces configurable
finite attempts (default five), persists exponential backoff/Retry-After and
reserves attempts before HTTP. Permanent/exhausted work is parked with a durable
failure event and explicit delivery-only recovery. Old counts are not reset;
recovery archives prior state/reason and retains receipts/accounting. Added an
optional disabled-by-default HTTP broker-relay publisher with its own persisted
finite retry policy, idempotency keys and one nonblocking bounded send per poll.
No broker or SDK setup is assumed. Documented activation/recovery hold points.

All 267 tests passed: collector 92, analyzer 103, product 15, controller 22 and
repository 35. New tests cover retry classification/caps across restarts,
uncertain attempts, event publication, recovery without inference/source reads,
pending watcher retries bound to their saved job after model/configuration changes,
receiver validation, storage errors, size admission, semantic idempotency and
Product preview holds. Recovered all six supplied jobs only in disposable copies
through fresh loopback receivers: all acknowledged, one Controller receipt and
five Product holds, duplicate recovery skipped. Original evidence hashes and
outbound bytes remained unchanged; no actual inference/source/paid/email calls.
Private verification artifacts remain outside source. Production state, failed
jobs, release selection and services were not modified, recovered or restarted.

## 2026-10-12 — preliminary independent Studio

Added the independently runnable Studio, a sixth daemon template, mock-only
configuration and mobile approval dashboard. HTTP intake normalizes direct and
saved Product briefs, deterministically requests missing details, and writes
concise human-facing messages through a mocked broker with durable receipts.
No model provider or broker infrastructure was selected or installed.

Sufficient briefs queue ten low-resolution original mock SVG layouts. Saved
accept/reject/comment decisions, current positive references and previous negative
references accompany later rounds. Start over gzip-archives the full interaction
with file/content hashes and compacts it into negative context. Professional
generation requires final size/resolution/format settings and explicit costly-loop
consent, returns three mock samples, and supports returning to sketches. Final
approval saves a downloadable SVG/metadata ZIP and an always-blocked listing
handoff; no Etsy publisher or credential loader exists in Studio.

Added revision admission, intake/action idempotency, browser pending-request
recovery, concurrent worker locks, durable unknown generation holds and explicit
retry. Approval reserves its artifact before package writes so storage failure
recovery keeps its identity. SVG whitelisting, bounded JSON bodies, same-origin
mutations, Host admission and CSP protect the preliminary trusted-network UI.
A bounded near-limit upload drain avoids a socket-close race hiding HTTP 413.

Verification: all 287 offline tests passed (collector 92, analyzer 103, Product
15, Controller 22, Studio 20, repository 35); six local daemons started, stopped
and restarted independently. Firefox at mobile and desktop sizes passed eleven
workflow checks, including missing-information delivery, refresh persistence,
lost-response recovery without duplicate work, both feedback loops, compaction,
final approval and ZIP download. JavaScript syntax and the Studio systemd unit
also passed. Private reports, screenshots and generated fixtures stay outside
source. No application Etsy, paid-model, Ollama or email calls were made.

The separate mock dashboard remains available in development on port 8096 with
a synthetic example. Production files/services/accounts/firewall were untouched.
Product's current outbox is unchanged: briefs can be imported or POSTed, but
automatic production delivery is not activated. The mocks test interaction and
contracts, not generative quality or print production; provider selection,
authenticated production UI access and final Studio acceptance precede live
generation, broker transport and Etsy publishing.
