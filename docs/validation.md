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

- Both controllers report firmware 3.92.3 through read-only SHI input registers
  10400–10402 (TCP 502, unit 1). Their Lux_WS LOGIN responses are JSON objects
  with type/items/id fields; the current XML parser rejects them.
- Both bridge services are active/running with zero systemd restarts, but report
  repeated ProtocolError and retained MQTT availability offline. Retained firmware
  readings still contain V3.89.3 and are stale, not evidence of successful polling.
- Catalog/fixture coverage is based on V3.89.3 German/English captures: 271 mapped
  readings on the larger model and 195 on the older model. Coverage under 3.92.3
  remains unverified. No settings were changed during compatibility testing.
- The deployment uses two systemd template instances on openHABian/Python 3.9.2,
  external credentials/config/state, and an MQTT 5-capable broker.
- Change-only publishing and same-value command/readback behavior are verified.
  Changed-value writes have test coverage with a fake controller, not live hardware.
- Runtime warning/error logs are rate-limited and capped at three 1 MiB files per pump.
- openHAB 4.0.4 has two MQTT Things, 56 suffixed comparison Items, 31 channels and
  five JavaScript transforms. In heatpump.items, 26 original Items use MQTT links
  with autoupdate=false. Their retained states are not fresh while bridge
  availability is offline. Nine legacy
  links remain for missing data/write support or non-equivalent energy counters.
- Live channel-link enumeration and Thing status need authenticated REST access;
  on-disk links are verified. A full host log filesystem limits log-based checks.
  Generic repository examples are not installed; site artifacts remain external.

## Outstanding verification

- Implement and verify FW 3.92.3 JSON protocol support, then restore live MQTT
  publishing and recheck openHAB values. Real-hardware login failure behavior.
- A 24-hour soak including outages.
- Full broker integration suite for the current build and deployment of bundled mappings.
- Authenticated openHAB Thing/link checks and equivalence of remaining legacy readings.
