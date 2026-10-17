# GitHub publication preparation

Target: `QWdlbnRTbWl0aA/market-pipeline`, using the dedicated
`github-market-pipeline` SSH alias. SSH credentials/configuration and host-key data
stay outside source. This is the publication repository; the remote is provisioned
and current `main` is published. Production deployment remains a separate action.

Use explicit feature/housekeeping branches for review; do not merge into `main`
or deploy as an implicit part of cleanup. Release tags identify verified code;
runtime ledgers and state are preserved independently. Private legacy Git archives
are not publication sources. Historical repository recreation/preparation notes
remain in Git rather than current operating instructions.

The local pre-push hook requires explicit publication authorization, the exact
remote and a clean audit. It is installed with repository-local
`git config core.hooksPath .githooks`. No global Git/SSH settings are repurposed.

Before an authorized push:

```sh
python3 tools/test.py
python3 tools/publish_check.py --output /outside-source/publication-audit.json
git remote -v
```

After authorization and a clean audit, push the intended branch
explicitly with `MARKET_PIPELINE_ALLOW_PUSH=yes`; do not use `--mirror` or
`--all`. Remote creation, visibility, branch protection and push remain external
publication actions, separate from preparation.

The audit scans the working tree, ignored files and every reachable/unreachable
Git object, checks private-key/token patterns and rejects tracked runtime,
credential, generated and large files. `secret_audit.py` additionally supports
exact comparison with known local credentials in an independent offline audit
process; it never prints matched values. It is not imported by business services.
The publication archive is inspected separately. Unknown secret formats cannot
be ruled out solely by deterministic patterns; an external secret scanner may
be added later without weakening this guard.

Publication privacy also rejects non-example IPv4/IPv6 addresses, private DNS
names, observed machine names and personal absolute paths. Loopback/bind
addresses, reserved documentation networks/example domains and the explicitly
portable daemon layout are allowed. Actual dashboard names belong in local
runtime configuration. An owner-only environment inventory, captured outside
source, supplements generic checks and survives changes in local network names.
The pre-push hook and CI use these checks through `publish_check.py`.

```sh
python3 tools/environment_audit.py --output "$HOME/.local/state/market-pipeline-publication/environment.json"
```

The scanner auto-discovers local names/addresses/home/checkout paths; it loads
that inventory by default when available, or `MARKET_PIPELINE_ENVIRONMENT_FILE`
for an explicit private location. Missing/insecure explicitly configured files
fail closed. Machine values never belong in scanner tests: synthetic rejected
fixtures are assembled at runtime so test source remains publishable.

See [sanitation policy](sanitation.md) for scope and approved exceptions.

CI installs the declared Pillow dependency and runs offline functional tests
and publication checks with no API keys and read-only repository permissions.
