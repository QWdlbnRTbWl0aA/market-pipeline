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
