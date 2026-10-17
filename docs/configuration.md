# Configuration ownership and activation

Only sanitized `*.example.json` files belong in `config/`. Examples describe
settings; they do not authorize requests, new spending or public exposure.
`deploy/prepare.py` rewrites standard state paths and creates missing files only.
It never merges examples over installed settings or resets history/ledgers.

| Example | Installed location | Defaults and activation |
|---|---|---|
| `collector.example.json` | `/var/lib/market-pipeline/collector/config.json` | Daily scheduling disabled; unlimited bounds are `null`; 5% quota reserve; historical exclusions enabled. Manual requests still require Etsy credentials. |
| `analyzer.example.json` | `/etc/market-pipeline/analyzer.json` | Local Ollama, two independent HTTP outputs; paid inference/mail disabled. Set model/digest for the installed Ollama model. |
| `controller.example.json` | `/etc/market-pipeline/controller.json` | Read/record proposals; automatic experiment execution disabled. |
| `product.example.json` | `/etc/market-pipeline/product.json` | Local definition inference; bounded real reference retrieval; mail and Studio delivery disabled. |
| `studio.example.json` | `/etc/market-pipeline/studio.json` | Mock images/broker, passive intake, no paid calls, listing blocked. |
| `studio.trial.example.json` | Explicit private Studio trial config | Real image/text routes, guided mockups and $25 ceiling; requires separate authorization, correct prior accounting, credentials and provider roles. Never copy it over live config automatically. |

Defaults are validated in Collector `core.py`, Analyzer `services.py` /
`production_config.py`, Controller configuration loading, Product
`configuration.py`, and Studio `server.py`. Read validators before adding keys;
several contracts reject unknown settings deliberately.

## State and credentials

The launcher takes `--state`, `--config`, optional `--port` / `--bind` and
`--credential-directory` (or systemd's `CREDENTIALS_DIRECTORY`). It creates an
allowlisted process environment. Credentials are literal assignments parsed by
code, never sourced as shell commands.

| File | Authorized consumers |
|---|---|
| `etsy.env` | Collector only |
| `openai.env` | Explicit paid Analyzer/Product routes through separate paths |
| `studio-openai.env` or separately delivered `openai.env` | Explicit paid Studio; never collector credentials |
| `studio-google.env` | Configured Studio Google adapter |
| `gmail_smtp.env` | Configured Market Analyst and Product mail outboxes |
| `control-auth` in state | Collector/Controller shared 64-character lowercase hexadecimal control token |

Keep values outside Git and command arguments. Credential loaders enforce regular
bounded readable files and reject unsafe links/permissions/content; do not replace
that policy with host-specific UID/GID expectations. Model discovery inspects
credential availability without opening secret values. Paid adapters load keys
only after budget admission. Account-specific provider access must be verified
separately before relying on it.

## Turn on only the intended integration

- Collection/scheduling: supply Collector credentials, inspect saved dashboard
  settings, then explicitly enable the desired daily or named-cycle schedule.
- Paid analysis/definition: configure the selected priced model, separate key
  delivery and the existing shared $2 development ledger. Product's provider and
  qualification/promotion controls are independent. See [definitions](product-definitions.md).
- SMTP: preview/apply `deploy/upgrade_config.py --enable-mail`, then install units
  rendered with `--with-mail` after provisioning SMTP credentials. See [mail](mail.md).
- Passive Product → Studio: upgrade Studio first and explicitly enable the exact
  `/api/library/briefs` endpoint. Backfill saved briefs without inference/mail if
  needed. See [library delivery](studio-library.md).
- Studio paid trial: daemon units can separately deliver credentials with
  `--with-studio-ai` / `--with-studio-google`; these flags do not enable generation
  or change budget. Preserve its existing state/ledger; explicitly authorize any
  ceiling migration and reconcile prior spend, then configure providers/roles.
  Starting a daemon or importing a brief never starts generation. See
  [Studio workflow](studio-workflow.md).

The full independent development launcher pattern is:

```sh
python3 deploy/launch.py studio --state /tmp/market-pipeline-state --config /tmp/market-pipeline-config/studio.json
```

Use `controller`/`product` with their respective files, and `search-refiner` /
`market-analyst` with `analyzer.json`. Each is a separate process. Binding all
interfaces, installing units and modifying firewalls are explicit operations;
examples do not expose reports or arbitrary directories.
