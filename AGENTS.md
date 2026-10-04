# Architecture and working rules

Apply throughout the repository. The project supports readings and validated writes.

## Documentation and continuity

Keep **AGENTS.md and README.md up to date on every relevant change**, in the same
change as the implementation or deployment work. Review both before finishing:
update AGENTS for architecture, module responsibilities, invariants, workflow, and
handoff information; update README for user-visible behavior, configuration,
commands, compatibility, and limitations. Do not leave contradictory instructions.
Update affected docs/examples when their claims change.
Maintain current evidence and outstanding verification in docs/validation.md;
distinguish files installed, service running, and behavior actually verified.
Documentation describes the current state only. Replace obsolete statements rather
than appending dated updates, migration narratives, or change histories. Use Git
history for past changes. Preserve applicable compatibility and rollback guidance.

At the start of work, read this file, README.md, and relevant detailed docs;
inspect git status and existing changes before editing. Preserve unrelated work.
Use the structure below when extending the project; avoid parallel implementations,
temporary diagnostics in production code, and reorganizations without a concrete
need. Document any changed boundaries here so another agent can resume without
conversation history. Keep operational handoff notes outside source when they
contain site configuration; never copy secrets or raw captures into documentation.

## Repository structure and responsibilities

| Location | Responsibility |
| --- | --- |
| `src/luxtronik_mqtt/cli.py`, `__main__.py` | CLI configuration, check/discover/once/run entry points |
| `config.py` | Layered configuration validation and external secret loading |
| `protocol.py` | Bounded XML/JSON parsing, navigation, snapshots, refresh merging, write metadata |
| `controller.py` | Lux_WS sessions, page selection, sampling, serialized controller writes/readback |
| `model.py` | Value normalization, constraints, command encoding, scalar representation |
| `publisher.py` | MQTT connection/subscription options, retained state, change detection, topic manifest |
| `service.py` | Read/command orchestration, reconnects, availability, cancellation and shutdown |
| `compat.py`, `logging_config.py` | Platform/runtime compatibility and bounded logging |
| `config/` | Generic base/device examples; no actual site config |
| `src/luxtronik_mqtt/mappings/` | Versioned German/English catalogs bundled in the wheel |
| `deploy/` | Versioned-release installer and systemd template |
| `tests/` | Unit/controller/service tests, disposable broker integration, sanitized bilingual fixtures |
| `tools/` | Offline mapping builder and Windows launcher; no credentials or live capture output |
| `examples/openhab/` | Generic consumer examples, separate from the deployed site configuration |
| `docs/` | Protocol evidence, deployment/secrets/validation guides, concise remaining work |

Module filenames without a directory above are under `src/luxtronik_mqtt/`.
Keep protocol/model logic independent of MQTT transport; service coordinates the
layers. Put localized paths/translations in mappings rather than transport code.
Treat topic IDs, config schema, units and command semantics as consumer contracts:
document migration and rollback when changing them. Regenerate both language
catalogs together and check sanitized fixture coverage; do not hand-edit one locale
into a different topic hierarchy. Runtime dependency changes must keep pyproject.toml,
uv.lock and deployment requirements.lock consistent.

## Controller protocol

Use Luxtronik 2.1 Lux_WS on configurable port 8214. Never probe or fall back to
legacy ports 8888/8889. The parser accepts bounded XML and JSON navigation,
content, REFRESH and write metadata. XML behavior is verified with V3.89.3
captures; deployed live checks pass against the current V3.92.3 controllers. SHI
firmware reads work on port 502, but SHI is not implemented by this bridge. Reject
unknown formats instead of guessing encodings.
SHI firmware reads work on port 502, but SHI is not implemented by this bridge.
Reject unknown formats instead of guessing encodings.

Use LOGIN and discovered navigation IDs. Keep one information connection and, if
needed, one settings/schedules connection per heat pump. GET selects a page and
builds its ID index; REFRESH updates the selected page between selections.
Information/settings poll every 30 seconds; schedules are scanned every 300 seconds.
Every schedule scan also reloads full information/settings metadata and history.
After schedule scans, reselect settings so subsequent polls use REFRESH.
IDs are transient and reused for unrelated fields across pages: never persist them
or deduplicate globally by ID. Rebuild the index after GET and every reconnect.

REFRESH contains unchanged values and omits some static fields. Keep omitted
fields with their original observation timestamps; do not invent fresh observations.
The first occurrence of a full path or repeated ID within a page wins. Later
duplicates are ignored; equal values alone never identify duplicates. History rows
use positional topics, retaining the actual dated navigation path in JSON.

Disable automatic WebSocket pings: the observed controllers closed connections
at the 20-second ping interval. Request timeouts and a monotonic freshness deadline
provide liveness checks. Bound frame size (1 MiB), depth, item count, and queues.

## Configuration and language mappings

Keep actual configuration and credentials outside source. Two external configuration
layers plus bundled language mappings:
- Shared base: broker, timing, write enablement, state root.
- Bundled language mappings: full localized paths, page selection, canonical English
  hierarchical topic IDs, types, units, and English choice translations.
- Per-device file: base reference, stable ID, controller URL, language, and optional
  controller/runtime overrides. Derive MQTT prefix/client ID/state directory from ID.

Load catalogs using importlib.resources from the installed package, independent of
working directory and config location. Never require or deploy external mapping
copies. The legacy mappings_dir key is validated as text but ignored for compatibility;
new configs omit it. Keep catalogs in source and verify both are included in built
wheels. Mapping changes and rollback follow the application release.

Use paired German/English controller captures as the primary naming source. Expand
abbreviations using the manufacturer glossary; lowercase alphanumeric topic levels
contain no punctuation or spaces. Numbered devices/circuits have separate numeric
levels. Both language catalogs must contain the same topic IDs. Do not invent
mappings for hardware absent from the captured navigation. Missing device features
produce no topics; mappings cover all captured information, settings, and timers.
Access-code entry and remote-control buttons/images are not telemetry.

## MQTT contract (schema 2)

Require MQTT 5. Prefix is `<topic_root>/<device_id>`, default `luxtronik/<device_id>`.
Each mapped topic holds retained QoS 1 JSON with value, unit, observed_at, quality,
actual path, writable, and possible_values. Its `/value` subtopic holds a scalar;
null is the literal `null`. Choices use the captured English option text; numbers
use declared units. Invalid/missing controller values are never converted to zero.

Publish all available readings initially and on controller/broker reconnect. During
normal operation publish only semantic changes (value, quality, path, constraints,
or other metadata), excluding timestamp-only changes. Publish scalar state only
when its value/quality changes, or to correct/confirm a command. Unchanged timestamps
can be old: consumers check availability/quality, not age of the retained last-change
message. Availability is retained online/offline, emitted on transitions, with an
offline Last Will. Mark offline on disconnect or stale cycles (120 seconds default).

Use a per-device manifest to clear only obsolete retained JSON/scalar topics in the
owned prefix. Never erase unrelated topics. Broker reconnect discards queued commands
and starts controller discovery again; there is no telemetry or command backlog.

## Writable settings

Only expose supported fields with controller-declared write metadata. Re-read the
page before each write, resolve the current ID, and validate against current choices,
minimum/maximum/step/divisor or timer format. Implement observed combo, slider, and
timer types. Unsupported/incomplete metadata stays read-only. No arbitrary command
sender, access escalation, remote-control keystrokes, or guessed write addresses.

Subscribe to `/value` using MQTT 5 noLocal, retainAsPublished, and retainHandling=2.
This prevents state echoes and retained replays from becoming commands. Reject live
retained commands too. Commands are bounded scalar UTF-8 payloads, with a bounded
queue and expiry. Serialize reads and writes. SET stages a value; SAVE;1 returns
Content; GET readback confirms success. Never optimistically publish requested state
or retry uncertain writes. Same-value commands are no-ops. Publish non-retained
`/result` statuses. Read-only fields reject writes. Preserve actual state after errors.

## Runtime, secrets, and logs

Python 3.9+ with asyncio, websockets, aiomqtt, and defusedxml. Use tomli/async-timeout
below 3.11. Windows uses a Selector event loop. Keep layers separate and normalize
values with pure functions. Test tools require Python 3.11+ and real Mosquitto 2
(native or disposable Docker), including MQTT 5 subscription behavior.

Deploy one systemd template instance per device as an unprivileged service account.
Keep versioned virtualenv releases under /opt, config under /etc, and per-device
state under /var/lib. Use systemd LoadCredential or absolute external secret-file
paths. Environment variables contain paths only. Secret files are root-owned 0600;
Windows uses restricted NTFS ACLs. Never log credentials, raw frames, full config,
command payloads, or transport exception contents. Wire loggers remain disabled.

No per-reading or per-poll logs at any level. Runtime logs are warning/error only,
rate-limited per logger/severity to once per minute, with one 1 MiB rotating file and
two backups per device. No routine output to the system journal. Early startup
errors use stderr; the systemd unit additionally rate-limits journal output.

## Verification and delivery

Use the development commands in README.md. Run focused tests for changed behavior;
for cross-layer protocol/config/MQTT changes, run the full suite with real Mosquitto 2,
Ruff lint/format checks, and a wheel build. Documentation-only changes need link,
command and consistency checks, not a runtime test rerun. Test changed Windows and
Linux behavior as applicable; report unavailable checks instead of implying success.

Use sanitized bilingual fixtures. Test mapping coverage, duplicate selection,
refresh omissions, reconnect identities, numeric/choice/timer write validation,
readback, command echoes/replays, retained state, broker outages, cancellation,
and log bounds. Live verification must not change operating settings merely to test
a path; use unchanged-value checks unless a specific change is requested.
Do not claim FW 3.92 or a 24-hour soak from mocks or V3.89.3 tests. Keep site data,
raw captures, and secrets outside git. Do not push without the user's instruction.
