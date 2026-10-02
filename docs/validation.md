# Validation record

As of 2026-10-02:

- **44 tests passed** on Windows / Python 3.13 and Linux / Python 3.11.
  Coverage includes XML parsing, missing/invalid values, duplicate paths, changed
  IDs, credential redaction, retained topics, a process-crash Last Will, broker
  restart, stale detection, and orderly shutdown despite cancellation races.
- Ruff lint/format checks pass; wheel and source distribution build successfully.
- Actual openHABian: Raspberry Pi OS 11, 32-bit armhf, Python 3.9.2, systemd 247.
  An isolated virtualenv runs the bridge without changing system Python.
- `luxtronik-mqtt-bridge.service` is enabled and running as `luxtronik-mqtt`.
  Controller credentials reside outside source, mode 0600 root-owned, delivered
  through systemd's credential directory. State is mode 0600 under the service account.
- The real German **V3.89.3** controller and supplied MQTT broker were tested.
  Two fresh complete cycles containing eight good readings were observed with
  availability online after final deployment: three temperatures, compressor
  hours/starts/running status, total heat, and total input energy.
- The host's `/var/log` filesystem is full and its journal reported truncation.
  MQTT delivery was verified directly; existing logs were not removed.

**Not yet validated:** FW 3.92, the 24-hour firmware acceptance soak, login failure
behavior on real hardware, and importing the reference configuration into openHAB.
Tests of failure cases use a fake controller and disposable broker; the shared
live broker and controller settings were not disrupted.
