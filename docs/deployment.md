# Independent daemon deployment

## Prepared layout

- Account/group: `market-pipeline`, non-root service account.
- Immutable code: `/opt/market-pipeline/releases/<commit>`;
  `/opt/market-pipeline/current` selects a verified release.
- Writable files: `/var/lib/market-pipeline` with one directory per stage and a
  shared `paid-ledger`/local cache. Collector configuration is
  `/var/lib/market-pipeline/collector/config.json`.
- Independent settings: `/etc/market-pipeline/{analyzer,controller,product,studio}.json`.
- Secrets: root-managed owner-only files in `/etc/market-pipeline/credentials`.
  `etsy.env` contains only literal `export ETSY_API_KEY=...` and
  `export ETSY_API_SECRET=...`; `openai.env` contains only
  `export OPENAI_API_KEY=...`. Shell commands/expansion are never executed.
- Logs: systemd journal; runtime files use an owner-only umask.

`deploy/launch.py` starts exactly one service using an allowlisted environment.
Inherited keys, collector environment and proxy variables are discarded.
Systemd `LoadCredential` exposes Etsy credentials only to the collector and
OpenAI credentials only to the two analyzer daemons in normal production units.
The analyzer paid adapter opens its credential only after admission. Controller
loads neither Etsy nor OpenAI credentials. Product defaults to real local Ollama
definition; its optional independent OpenAI provider requires a `briefing` policy
and units rendered with `--with-product-paid`. That option gives Product only its
own `openai.env` delivery and access to the existing shared paid ledger, never
collector credentials. See [Product definition configuration](product-definitions.md).
Studio uses an independent
OpenAI credential only in explicitly enabled development mode. Optional units
rendered with `--with-mail` expose `gmail_smtp.env` to Market Analyst and Product;
no other daemon receives SMTP credentials. See [automatic mail](mail.md).

Collector credential validation uses the kernel's read-access decision and
descriptor metadata, with no expected UID, GID or exact permission-mode value.
Service-manager-owned, group-readable credential copies are supported. The
supplied credential directory must be protected by the service manager or
operator. The loader rejects symlinks, nonregular files, files writable by the
group, access permissions for others, and content beyond its 8 KiB bound. It
parses only literal Etsy key/secret assignments and never executes shell text.
FIFO opens are nonblocking so invalid inputs cannot hang startup. Validation
does not change ownership/permissions or bypass an actual read-access denial.

The shared Controller/collector control token is 64 lowercase hexadecimal
characters, generated from 32 random bytes. Preparation preserves an existing
token file. A token created with the earlier URL-safe generator must be replaced
explicitly during deployment with a valid shared token; rerunning preparation
does not rotate it. Both services must read the same owner-only token file.

Each unit runs independently with restart limits, graceful SIGTERM, restricted
filesystem writes, no capabilities and `NoNewPrivileges`. No `Requires` or
`PartOf` joins their failure lifecycles. Model availability and HTTP delivery
failures are explicit saved states. The systemd manager supervises the daemons;
the application process supervisor is optional and must not launch duplicate
processes alongside systemd.

## Install procedure (administrator action)

The preparation work does not create accounts, install units or alter host
permissions. Before installation an administrator provisions the chosen
`market-pipeline` account/group, release path, state and independent configuration
directories. The account needs no interactive login or sudo privileges.

1. Stop legacy writers, keeping original code and output directories intact.
   Confirm no collection or paid call is in flight. Take an offline backup of
   state and record the selected release/checksums.
2. Migrate into **new** destinations with `deploy/migrate_state.py`; it accepts
   existing collector data/config, analyzer output, paid ledger, product data and
   optional controller state. Example argument names:

   ```sh
   python3 deploy/migrate_state.py --state /new/state --configs /new/configs \
     --collector /old/collector-data --collector-config /old/collector.json \
     --analyzer /old/analyzer-output --ledger /old/paid-ledger \
     --product /old/product-data --controller /old/controller-state
   ```

   The migration copies raw files, requests, quota state, schedule and completed
   receipts; rebuilds physical identity aliases; verifies unchanged paid ledger
   bytes; and records accounting. Existing destinations are rejected. A failed
   partial migration must remain parked; repeat into another new destination.
   Preserve pending/failed jobs for explicit reconciliation; do not retry them
   automatically. Omit `--controller` only if none exists.
3. Move the verified migrated state/settings into the designated layout. Keep
   code root-owned/read-only; grant the app account only the required runtime
   directories. Credentials remain root-managed mode 600, independently
   provisioned rather than copied into source. Existing collector saved daily
   phrases, scheduling preference and unlimited result bounds are retained.
4. Run `python3 deploy/render_units.py --output /temporary/unit-directory`.
   Validate using `systemd-analyze verify /temporary/unit-directory/*.service`.
   Install the generated unit files into `/etc/systemd/system` and run
   `systemctl daemon-reload`. This step requires administrator access.
5. Run `python3 deploy/preflight.py`. Review all settings/ports and ensure
   `gemma3:4b` is available through local Ollama. Keep paid work disabled until
   the migrated total ledger is verified. Enable it explicitly in the analyzer
   runtime JSON only within the remaining $2 development/testing allowance.
   Automatic refinement execution and enhanced product generation also have
   independent settings/review records; they are not silently enabled by install.
6. Start each `market-pipeline-<service>.service` independently; names are
   `collector`, `search-refiner`, `market-analyst`, `controller`, `product`, `studio`.
   Check their state/journal and health endpoints. Collector launch defers
   deployment-day catch-up; enabling a future daily schedule should not trigger
   an unintended historical collection. Analyzer cursor floors and migrated
   completion receipts prevent old paid work being repeated.
7. After account-level smoke/restart verification, enable the desired units for
   boot. Perform separately bounded live functional trials only when requested.

The collector binds all IPv4 interfaces for LAN/Tailscale access. Its dashboard
accepts the connection's IP and loopback localhost; supply an explicit
comma-separated `PIPELINE_DASHBOARD_HOSTNAMES` service environment for other
configured DNS names. Personal Tailscale suffixes are not hardcoded in source.
For systemd, set that variable in the optional local
`/etc/market-pipeline/dashboard.env` file. Keep actual network names in that
runtime file; there is no machine-specific hostname default in published code.
Its dashboard
is an operator interface: keep it on trusted network paths or put authenticated
TLS access in front before public exposure. Controller/product bind loopback;
mutations reject browser-origin requests. No firewall or host network change is
performed by these scripts.

Studio is a new optional mock stage; preparing its configuration/state/unit does
not deploy it or wire Product's existing outbox. Its unit binds loopback on 8096
and uses no credentials. See [Studio](studio.md) for intake and trusted-network
dashboard access. Existing deployments can prepare the new files without
overwriting their previous settings, then activate only Studio after review.

For an existing installation, source pull/release selection does not merge runtime
settings. Follow the README's **Upgrade an existing deployment** procedure and
`deploy/upgrade_config.py` preview/apply steps for automatic mail. Render SMTP-enabled
units only after provisioning the dedicated credential. This preserves state and
does not migrate or reset any paid, quota, completion, mail or offer ledger.
Studio uploads and development image observation require system-visible Pillow;
`/usr/bin/python3 -I -c 'import PIL'` checks availability without installing it.
Core mock operation does not need it. No Studio generation belongs to the automatic
search→analysis→Product→email chain in this release.

## Operations and rollback

Analyzer delivery limits, terminal failure events, optional broker relay and
delivery-only recovery are described in [delivery.md](delivery.md). Recovery
must use saved output and preserve inference IDs/receipts and paid accounting.

Health: collector `/api/health` on 8090; controller `/health` on 8094; product
`/health` on 8093; Studio `/health` on 8096. Analyzer heartbeat/cursor files are under
`analyzer/lifecycle`. Saved delivery status and controller timeline distinguish
analysis, delivery, tracking and product failures. Monitor heartbeat freshness,
parked work, quota waits and budget reservations; `systemctl` alone does not
prove successful business processing.

To roll back code, stop only the affected units, record in-flight/unknown work,
select the previous verified code release and restart with the **current** state.
Never restore an earlier paid ledger, Etsy request/quota history, completion
receipt, intake or delivery identity. These prevent overspend and duplicates.
Do not run legacy and new watchers concurrently against the same inputs.
Migration and activation are separate hold points: review migration accounting
before requests, and account-level isolation before boot enablement.

Prepared units are syntax-validated locally. Source-workspace process tests do
not verify OS security controls under the actual designated account. Installed
production release acceptance and the new Studio deployment are separate checks.
