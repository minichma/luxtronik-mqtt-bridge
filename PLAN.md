# Implementation plan

Target: read-only Luxtronik 2.1 / FW 3.92 → MQTT, running on openHABian
as a systemd service. The same Python application must run on Windows for testing.
Architecture and secret handling: [AGENTS.md](AGENTS.md), [docs/secrets.md](docs/secrets.md).

## Milestones

1. **Foundation — done:** architecture, external secrets, config, and GitHub origin.
2. **Protocol — verified on V3.89.3:** XML login/navigation/GET and sanitized fixtures;
   FW 3.92 remains unverified.
3. **Bridge — done:** Python 3.9+, mappings, typed readings, retries, and safe shutdown.
4. **MQTT — done:** retained values, quality/timestamps, Last Will, freshness, and
   recovery; eight sensors verified live. openHAB example supplied.
5. **Deployment — done:** enabled systemd service on openHABian under a dedicated
   account; Windows console support. All 44 tests pass on Windows and Linux.

## Remaining acceptance

Obtain FW 3.92 fixtures, compare readings against its UI, and complete a 24-hour
soak including outages. Keep this separate from the successful V3.89.3 deployment.
See [validation](docs/validation.md) for evidence and limitations.
