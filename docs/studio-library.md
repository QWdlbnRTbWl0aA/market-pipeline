# Product to passive Studio library

Product can deliver saved individual `product.json` briefs over HTTP. Studio
stores the complete brief, displays it in its Hebrew library, and identifies
bounded input using deterministic code; all initial content fields are optional. Intake, browsing, refresh, duplicate
delivery and pre-generation metadata edits perform no model calls, image
generation, paid reservations, external image downloads or broker publication.
Only the explicit **התחלת סקיצות** action starts generation after required fields
are complete. New manual form/JSON imports use the same passive behavior.

The Product setting is optional and disabled in old configurations:

```json
"studio_delivery": {
  "enabled": true,
  "endpoint": "http://127.0.0.1:8096/api/library/briefs",
  "max_attempts": 5,
  "retry_seconds": 60
}
```

The endpoint must be a loopback HTTP address with this exact passive route.
An old Studio returning 404 fails permanently; Product never falls back to the
old `/api/briefs` behavior. Upgrade Studio before enabling Product delivery. Both
HTTP intake routes in the new release are passive; posted auto-start fields
cannot override this. Existing human-started projects/queued generations retain
their state; imports do not cancel or repeat that work.

## Existing deployment

1. Install the tested source release using the normal deployment procedure.
   Restart the upgraded Studio through the administrator's normal service controls.
   Check that `/health` responds and the new passive library intake is installed.
   Service startup is independent; Product does not require or start Studio.
2. Preview the additive setting change, then apply it explicitly:

   ```bash
   python3 deploy/enable_studio_library.py --config /etc/market-pipeline/product.json
   sudo python3 deploy/enable_studio_library.py --config /etc/market-pipeline/product.json --apply
   ```

   The helper preserves unrelated configuration, owner and permissions and writes
   a `.json.before-studio-library` backup. It makes no requests and starts no
   services. Product promotion-review identity excludes this transport-only setting.
3. Restart Product through the normal administrator procedure. New saved briefs
   are independently queued for library delivery. Completed intake receipts can
   queue their existing briefs without rerunning Product definition or mail.
   Existing standalone Product output can be imported explicitly as below.

## Import existing saved briefs without analysis or definition

From the installed release's `services/product` directory, under an account with
access to saved Product state, use a clean environment as required by Product:

```bash
sudo -u market-pipeline env -i PATH=/usr/bin:/bin LANG=C.UTF-8 \
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -m product_service deliver-studio \
  --data /var/lib/market-pipeline/product \
  --config /etc/market-pipeline/product.json
```

This scans completed `studio-outbox` and `definition-outbox` results, queues exact
individual briefs and attempts their passive delivery. It does not run Collector,
Analyzer, Product definition, SMTP or any model. Zero-product/insufficient-evidence
results create no library entry. This cannot manufacture the briefs absent from
today's zero-recommendation analysis.

Product stores `studio-delivery/<payload-sha256>/payload.json`, `delivery.json`,
numbered attempt records and terminal `failure-event.json`. Studio derives one
entry from that same idempotency key. Bounded retries, including a response lost
after successful receipt, cannot create duplicate entries or start generation.
Delivery failure does not change the saved Product brief or block its email.

To explicitly retry a terminal failure after repairing its cause, add
`--recover BRIEF_SHA256 --reason 'Receiver upgraded and checked'` to the
delivery-only command. It retains previous attempts/recovery receipts, resets the
per-recovery attempt allowance and uses the configured passive endpoint. Already
delivered briefs cannot be reset for resending through this command.

For manual single-brief delivery, POST `product.json` with a stable
`Idempotency-Key` to `/api/library/briefs`. Do not POST the batch handoff manifest.
The UI has a library refresh button; reading the library never initiates work.
Reference images remain optional embedded/uploaded raster data, not fetched Etsy
links. This wiring does not add automatic pictures or Etsy publishing.

## Hold and rollback

Disable `studio_delivery.enabled` and restart Product to hold future deliveries.
Already imported entries remain saved, and Studio stays independently runnable.
Do not clear delivery receipts, library state or paid ledgers. An older Studio
must not serve the new library UI against old automatically generating code;
keep frontend/backend from the same release. Rollback does not authorize replay
of completed definitions, inference, SMTP delivery or human-started generation.
