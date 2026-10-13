# Automatic Analyzer and Product mail

Each service has an optional `mail` object:

```json
{"enabled": false, "recipients": [], "max_attempts": 5, "retry_seconds": 60}
```

Enable this explicitly in both independent runtime configurations. With no
recipient override, `SMTP_TO` supplies the recipients. The dedicated credential
file is selected by `PIPELINE_SMTP_CREDENTIAL_FILE`; independent launchers set it
to the systemd credential copy named `gmail_smtp.env`. No other source/provider
credential filename is accepted. Export assignments are parsed, never sourced.
Mail is disabled by default; SMTP keys are not read when disabled or no delivery
is pending. Kernel readability supports protected service-manager-owned copies,
without assuming a UID/GID or a host-specific permission value.

Example runtime credential content (replace the placeholders outside Git):

```sh
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=465
export SMTP_TLS=ssl
export SMTP_USER=research@example.com
export SMTP_FROM=research@example.com
export SMTP_PASSWORD=REPLACE_ME
export SMTP_TO='team@example.com,design@example.com'
```

The shared standard-library mail transport is under `services/common/pipeline_mail`.
Analyzer and Product still run as separate daemons, with separate outboxes, intake
and credentials. Only `market-analyst` and `product` units rendered with
`--with-mail` load SMTP credentials. Plain units do not require that file and keep
working with mail disabled. Search Refiner does not send a third email.

Analyzer mail copies existing model-authored recommendation prose into a readable
report. Its `market-analysis.json` attachment is byte-identical to the canonical
`outbound-wire.json` prepared/sent to Product; it is not a separately generated
recommendation. Product mail includes the full textual specifications in its body
and byte-identical saved `product.json` attachments for every produced concept,
plus its exact `studio-handoff.json`. There is one Product email per collection,
not one email per concept. Enhanced definition review/promotion stays separate;
an unqualified or failed cycle sends an honest status and saved handoff, with no
invented complete brief. Studio HTTP intake/generation is not automatically called.

Outboxes live in `analyzer/mail-outbox` and `product/mail-outbox`. Identity is the
stage plus source collection ID. Immutable content, attachment hashes, stable
Message-ID, exact MIME bytes, frozen routing, attempts and results are saved before
delivery. SMTP acceptance is distinguished from final inbox delivery; spam filtering
is outside the service's receipt. Repeat triggers/restarts cannot resend an accepted
message. A changed recommendation for the same cycle is held as a content collision.

Activation timestamps prevent mailing the historic completed backlog. Product can
repair a newly received completed definition's missing mail queue without repeating
definition; Analyzer queues mail before recording its watcher completion. HTTP and
mail failures remain independent. Delivery-only HTTP recovery never dispatches
unrelated mail. Preserve activation markers and outboxes through upgrades/rollback.

Connection/pre-DATA transient failures retry within the configured finite limit.
Invalid routing, authentication and permanent SMTP failures stop. A timeout or
disconnect once mail DATA may have been sent has an unknown outcome: no automatic
resend. Partial recipient acceptance is held as well. Terminal failures have a
local failure event and require operator review, without another model/source call.

Explicit recovery, after checking provider/SMTP records:

```sh
PYTHONPATH=/opt/market-pipeline/current/services/common \
python3 -m pipeline_mail --outbox /var/lib/market-pipeline/product/mail-outbox \
  --recover MAIL_ID --reason 'Confirmed not accepted by SMTP'
```

For `unknown` or partial outcomes, `--confirm-unknown` explicitly acknowledges a
possible duplicate. The original body/routing is preserved; prior attempts and
recovery records remain. This recovery is scoped to one saved mail ID. It must run
with the dedicated SMTP credential file available to the app account. Do not
delete receipts or reset model/collection ledgers to force another message.
