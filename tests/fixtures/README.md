# Fixture provenance

`v3_89_3_de`: reduced XML fixtures based on read-only captures from the authorized
test controller on 2026-10-01, reporting **V3.89.3**, German UI. IDs are replaced,
navigation and readings reduced, and runtime counters made synthetic. No addresses,
serials, or credentials remain. Repeated `GET` returned full `Content`; `REFRESH`
returned partial `values`, so the bridge uses full `GET` each cycle.

Preserved quirks: `Content` has no root ID; section names appear twice; units are
embedded in value strings. The refresh fixture documents the observed alternative,
which the production decoder deliberately rejects as an incomplete sample.
The duplicate `Eingänge/HD` labels reproduce a live ambiguity: discovery flags it,
and selecting that path fails rather than choosing an arbitrary input. Unrelated
configured readings can still be published.

Failure frames used in tests are synthetic. Login failure behavior and all FW 3.92
behavior remain unverified on hardware. These fixtures are not FW 3.92 evidence.
