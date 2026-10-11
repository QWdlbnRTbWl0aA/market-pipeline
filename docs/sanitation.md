# Publication sanitation

Publication is checked before every push, across the working tree, filenames and
all Git objects, including unreachable objects. Replacing only the current files
is insufficient if an older commit still contains machine details.

## Rules and permitted fixtures

- Reject known credentials, private keys/tokens and tracked runtime/generated
  artifacts. Do not print matched credential values.
- Reject real-style IPv4 and IPv6 literals, including private/CGNAT, link-local,
  global and IPv4-mapped IPv6 addresses. Allowed fixtures are loopback/wildcard
  binds and the reserved documentation networks `192.0.2.0/24`,
  `198.51.100.0/24`, `203.0.113.0/24` and `2001:db8::/32`.
- Use `.example`, `.test`, `.invalid` or reserved example domains for fake
  hostnames. Reject private DNS names and unapproved hostnames in endpoint URLs.
  Public provider domains used by the application/docs are explicitly allowed;
  this includes DataDome's challenge-detection domain, supported by its
  [official documentation](https://docs.datadome.co/docs/javascript-tag).
  Domain exceptions are reviewed code, not arbitrary scanner bypasses.
- Reject personal home/Windows-profile paths and host-specific mount/workspace
  paths. Exact observed machine paths supplement those patterns. Standard daemon
  paths under `/opt/market-pipeline`, `/etc/market-pipeline`,
  `/var/lib/market-pipeline` and `/etc/systemd/system` are portable deployment
  design and remain allowed; they are not personal checkout locations.
- Persist observed short/FQDN hostnames, interface addresses and home/checkout
  paths in an owner-only inventory outside Git. The file is never imported by
  analyzer/collector business code. No credential is loaded by environment
  discovery. CI applies generic rules and discovers its own environment; local
  pre-push additionally uses the saved private machine inventory.

Negative-test values are assembled at runtime, not written as private-looking
literals into source. Tests cover address families, escaped personal paths,
hostnames, filename matches, unsafe inventory permissions and unreachable Git
blobs. Actual environment values are never test fixtures.

## Clean republication

After removing machine literals, run functional tests and a working-tree audit.
Export only the reviewed source into a new repository with no object alternates
or legacy refs. Audit its committed objects and publication archive against the
private environment inventory and known credential values. Push explicit new
branches/tags only to the user-recreated empty remote; verify their hashes.
Keep the old repository privately for rollback/reference, separate from the
publication source. Runtime data and paid/quota accounting are unchanged.

These checks detect the listed patterns and observed values; they do not claim
to identify every arbitrary personal name/path/encoding. Update the private
inventory when using a different host and review any new public-domain or
portable-path exception before publication.
