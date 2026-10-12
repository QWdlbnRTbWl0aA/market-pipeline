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
