# Validation record

Bundled-mapping change: 57 configuration/model/controller/service tests pass,
including loading with an invalid external mapping copy present. Both 271-entry
language catalogs load directly from the built 0.2.0 wheel in an isolated process,
without checkout or config-directory mappings. Ruff lint/format and wheel build
pass. The full suite stalled during disposable broker startup and was stopped;
MQTT integration was not revalidated for this change. The new wheel has not been
deployed to the live bridge services.

As of 2026-10-03:

- **59 tests pass** on Windows/Python 3.13 and Linux/Python 3.11. Real Mosquitto 2
  integration covers MQTT 5 noLocal/retention behavior, validated writes/readback,
  uncertain-write recovery without replay, broker restart, and crash Last Will.
  Unit tests cover both complete language catalogs, XML bounds, duplicates,
  refresh omissions, choices/ranges/timers, cancellation, and bounded log rotation.
- Ruff lint/format checks pass; the 0.2.0 wheel builds successfully.
- Read-only live scans found **271 readings / 137 writable fields** on the larger
  heat pump and **195 readings / 78 writable fields** on the older one. Both report
  V3.89.3 and are configured in German. English mappings come from an authorized
  English capture of the larger controller and are tested against sanitized fixtures.
- Both systemd template instances are enabled/running on openHABian (Python 3.9.2),
  with zero restarts. The former single-instance service is stopped and disabled.
  Its eight retained readings and metadata were cleared; legacy availability stays offline.
  Per-device credentials are root-owned 0600; config/state/secrets remain external.
- A 65-second observation after deployment saw 32 and 26 changed JSON readings,
  **zero unchanged JSON repeats**, and both instances online. Their full retained
  snapshots contain 271 and 195 JSON readings plus scalar value subtopics.
- Live MQTT same-value commands returned `unchanged` for both pumps. No operating
  settings were changed. An earlier direct same-value SET/SAVE verified the wire
  transaction and unchanged readback. Changed-value writes are tested with a fake
  controller and real disposable broker.
- Neither running instance created an error log during verification. Runtime logs
  are warning/error only, rate-limited, and capped at three 1 MiB files per device.
  Existing unrelated host logs were not deleted or reconfigured.

On 2026-10-04, separate site configuration files were copied directly into openHAB:
two Things, 56 `_xxnew` Items (31 MQTT channels), and five JavaScript transforms.
Original files remained unchanged. Local channel-link and conversion checks passed;
openHAB 4.0.4 was active and its feature registry recorded JavaScript scripting as
started. Live item values/Thing status are still unverified: REST requires credentials
and the full host log filesystem limited log-based verification. The repository's
generic examples were not imported; deployed artifacts remain outside source.

**Remaining:** FW 3.92 hardware/encoding validation, a 24-hour outage-inclusive soak,
real-hardware login failure behavior, and live openHAB Thing/item verification.
The live broker was not restarted or upgraded; it already supports MQTT 5.
