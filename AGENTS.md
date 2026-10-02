# Project architecture and working rules

These instructions apply to the entire repository. Record changes to decisions
here, including their rationale, and update PLAN.md when milestones complete.

## ADR-001: Read-only Lux_WS integration

Accepted: target Luxtronik 2.1 firmware 3.92 using WebSockets with the exact
subprotocol `Lux_WS`. Port 8214 is configurable and verified on V3.89.3. Do not
implement, probe, or fall back to the legacy API on ports 8888/8889.

Expose readings only. Allow only verified authentication, navigation, and read
operations; do not implement a generic command sender in the public interface.
No controller settings, setpoints, operating modes, or service parameters may
be changed. Do not copy the write capabilities of upstream clients.

The V3.89.3 test controller confirms XML navigation/content, login, and full
information GET reads. Implement this verified variant; treat it as provisional
for FW 3.92 until authenticated fixtures and hardware tests are available.
Unknown encodings fail explicitly; do not add speculative JSON support based on
community claims. Authentication failure fixtures are synthetic. See
docs/protocol-research.md for evidence and limits.

## ADR-002: Standalone Python service

Accepted: Python with asyncio, separate from openHAB and ioBroker. Deploy on
openHABian as a systemd service; support Windows console execution for testing
using the same package, CLI, and configuration. Use a virtualenv with minimum
Python 3.9: the actual 32-bit Bullseye host uses Python 3.9.2. Do not replace system
Python. Development tools require Python 3.11+.
Dependencies: `websockets` for transport, `aiomqtt` for MQTT, and `defusedxml`
for XML. Use `tomli` and `async-timeout` only below Python 3.11; newer Python uses
its standard-library equivalents. This keeps both platforms on the same core.
Verify dependency APIs and supported versions when implementation begins; pin
the resolved dependency set in a lockfile. Do not add legacy Luxtronik libraries.
Verify dependencies and event-loop compatibility on both platforms. Keep systemd
integration outside the portable core; support graceful console shutdown on Windows.

Keep layers separate: configuration/secret loading, Lux_WS transport and session,
protocol decoding/discovery, typed readings/mapping, MQTT publishing, and service
lifecycle. Keep parsing and normalization pure and testable. A controller session
must have one reader and at most one outstanding request until response
correlation is proven. Discover IDs on every connection; never persist transient
controller IDs as stable sensor identities.

## ADR-003: Stable, explicit reading model

Accepted: map a verified menu path and locale to a configured stable sensor key
(e.g. `outdoor_temperature`). Do not derive public keys solely from ephemeral IDs
or flattened labels. Reject ambiguous configured mappings and duplicate keys;
unselected duplicate paths (such as Eingänge/HD) do not invalidate other readings. Unknown
readings can be inventoried but are not automatically assigned public topics.

Each reading carries value, unit, UTC observation timestamp, quality, and source
path. Parse full values, including decimal commas, units, booleans, durations,
and textual states using fixture-backed rules. Invalid numeric data becomes
`null` with quality `invalid`, never zero. No NaN or Infinity in JSON. An absent
configured reading is `null` with quality `unavailable`. Preserve raw values only
in explicitly enabled, sanitized diagnostics stored outside the source tree.

## ADR-004: MQTT v1 contract

Accepted: MQTT 3.1.1, QoS 1, retained readings and retained availability. Namespace
`luxtronik/<device_id>/v1`; the configured device ID must be stable and contain
no topic separators or MQTT wildcards. A deployment must have a unique client ID.

- `.../readings/<sensor_key>`: JSON object with `value`, `unit`, `observed_at`,
  and `quality`. `observed_at` is bridge receipt time in UTC, not controller time.
- `.../availability`: `online` or `offline`. Configure retained `offline` as
  the Last Will before connecting. Publish `offline` on startup and orderly stop.
- `.../metadata`: retained schema version, configured device ID, mapped sensor
  keys/units, and verified firmware if available; exclude credentials and serials.

Example reading (synthetic):
`{"value":7.5,"unit":"degC","observed_at":"2026-10-01T18:00:00Z","quality":"good"}`.

Publish online only after discovery and a complete successful polling cycle has
been published. Publish offline on controller disconnect or if no complete cycle
has succeeded within the freshness limit (initially 120 seconds). Individual
missing/invalid readings keep explicit quality; a complete cycle means all mapped
readings have an outcome, not that all values are good. A subscriber must check
availability, observation age, and reading quality: retained values alone are
not proof of freshness. QoS 1 permits duplicates; consumers must be idempotent.

On broker reconnect publish offline, then a newly collected cycle, then online.
Do not replay old values as fresh. Stop acquisition during broker outages; keep
no backlog and reconnect the controller before the next cycle. Clear obsolete
retained reading topics with empty
retained payloads when a mapping is deliberately removed, using an external
published-topic manifest; never erase unrelated topics.

## ADR-005: Polling and recovery

Accepted: start with 30-second cycles and 10-second operation timeouts; tune after
hardware verification. Never overlap cycles. Limit frame size (initially 1 MiB),
navigation depth, and discovered item count. Reconnect with exponential backoff
and jitter, capped at 60 seconds; use slower retries for authentication failures.
Reset backoff after a successful cycle, not merely a TCP connection.

Rediscover navigation and invalidate old IDs after reconnect. Treat malformed
frames, unsupported protocol formats, and timeouts as explicit failures. Never
silently claim healthy operation. Use monotonic time for freshness/deadlines and
UTC for published timestamps. Handle termination with an offline publish and
bounded shutdown. No unbounded retry queues or raw frame logging.

## ADR-006: Secrets and deployment

Accepted: actual configuration and credential files live outside the checkout.
Tracked configuration contains examples and external secret references only.
Secret-file paths come from environment variables or systemd's
`CREDENTIALS_DIRECTORY`; credential values do not.
Reject absent, empty, or unreadable required secrets with redacted errors; no
default controller password. Never log login messages, passwords, full config,
credential-bearing URLs, or raw authentication frames, including at debug level.

Use an openHABian systemd service with a dedicated unprivileged account, external
configuration under `/etc/luxtronik-mqtt-bridge`, and runtime state under
`/var/lib/luxtronik-mqtt-bridge`. Prefer systemd credentials where supported;
otherwise use restricted external secret files. Containers are not required.
Use restricted NTFS ACLs for Windows testing. See docs/secrets.md. MQTT supports
TLS with certificate verification; never disable verification as a workaround.
If Lux_WS only supports unencrypted WS, run it on a trusted, isolated LAN with
no internet exposure. The controller password travels unencrypted in that case.

## Verification and delivery rules

Implement against sanitized firmware-specific fixtures. Test parsing, missing
data, identity stability, reconnects, stale availability, credential redaction,
and broker failure using a fake controller and disposable MQTT broker. Keep live
hardware tests opt-in. No secrets or unredacted captures in fixtures or commits.
Do not claim deployment or FW 3.92 validation from mocks. No unnecessary tests
for documentation-only changes. Do not introduce cloud dependencies, controller
writes, or new discovery protocols without an explicit scope change.
