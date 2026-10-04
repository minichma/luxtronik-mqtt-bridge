# Validation status

## Application

- 57 configuration/model/controller/service tests pass, including bundled catalog
  loading with an invalid external mapping copy present.
- Both 271-entry language catalogs load directly from the built 0.2.0 wheel in an
  isolated process without checkout or config-directory mappings.
- Ruff lint/format checks and wheel build pass.
- Full-suite MQTT integration verification is incomplete: disposable broker startup
  stalls. Tests cover command/replay handling, reconnects, broker outages and Last
  Will, but their presence does not establish a passing result for the current code.
- The bundled-mapping build is not yet deployed to the live bridge services.

## Live installation

- Two V3.89.3 controllers use German mappings. English coverage uses sanitized
  captures. The larger pump exposes 271 readings / 137 writable fields; the older
  pump exposes 195 readings / 78 writable fields.
- The deployment uses two systemd template instances on openHABian/Python 3.9.2,
  external credentials/config/state, and an MQTT 5-capable broker.
- Change-only publishing and same-value command/readback behavior are verified.
  Changed-value writes have test coverage with a fake controller, not live hardware.
- Runtime warning/error logs are rate-limited and capped at three 1 MiB files per pump.
- openHAB 4.0.4 has two MQTT Things, 56 suffixed comparison Items, 31 channels and
  five JavaScript transforms. In heatpump.items, 26 original Items use MQTT links
  and have verified non-NULL/non-UNDEF states with autoupdate=false. Nine legacy
  links remain for missing data/write support or non-equivalent energy counters.
- Live channel-link enumeration and Thing status need authenticated REST access;
  on-disk links are verified. A full host log filesystem limits log-based checks.
  Generic repository examples are not installed; site artifacts remain external.

## Outstanding verification

- FW 3.92 hardware/encoding compatibility and real-hardware login failure behavior.
- A 24-hour soak including outages.
- Full broker integration suite for the current build and deployment of bundled mappings.
- Authenticated openHAB Thing/link checks and equivalence of remaining legacy readings.
