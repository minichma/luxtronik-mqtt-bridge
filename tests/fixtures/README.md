# Fixture provenance

`v3_89_3/de` and `v3_89_3/en` preserve paired German/English XML navigation,
information, settings, and timer pages captured from an authorized V3.89.3
controller on 2026-10-02. IDs, operating values, history dates, and hardware
identifiers are synthetic. No addresses, credentials, or serials remain.

Preserved quirks include repeated section names, page-scoped/reused IDs, timer
section nodes without IDs, missing Content root names, duplicate HD/control paths,
and read/write metadata. REFRESH fixtures contain unchanged and omitted fields.
The first duplicate path is selected. Tests synthesize login failures, unknown IDs,
changes, and write responses; a same-value live SET/SAVE confirmed the transaction
shape. These fixtures do not establish FW 3.92 compatibility.
