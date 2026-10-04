# Lux_WS evidence and limits

## Hardware observations

Read-only captures and same-value write verification cover two
Luxtronik 2.1 controllers reporting **V3.89.3**. German captures exist for both;
the larger navigation was also captured after the user switched it to English.
Raw captures remain external. Sanitized bilingual fixtures reproduce observed
structure without addresses, credentials, serials, or actual history timestamps.

The public web client served by the controller (`Webserver/Lux.js`) establishes:
- `ws://<controller>:8214/`, subprotocol `Lux_WS`, `LOGIN;<password>` → Navigation.
- `GET;<navigation id>` → Content. Settings/timers may omit the root name.
- `REFRESH` → values for the currently selected page, without names.
- `SET;set_<field id>;<raw value>` stages a setting without a response.
- `SAVE;1` → Content; a subsequent GET verifies actual state.

A captured information GET contained 83 value nodes and REFRESH contained 73,
all unchanged, with ten omitted. REFRESH is not changed-only. The bridge caches
omitted observations without changing their timestamp and reloads full pages at
the schedule interval to detect history/metadata changes. Repeated GET allocates
page-local IDs; unrelated fields and different schedule pages can reuse IDs.
Timer grouping nodes may have no ID. Duplicate named paths select their first item.

Automatic WebSocket pings caused sessions to close at 20 seconds. With pings
disabled, successive 30-second refreshes work in one session. Application request
and freshness timeouts detect unresponsive connections.

The controller declares writable fields via `raw` plus type/constraints. Observed
sliders provide min/max/step/div; combos provide raw-code/label options; timers
encode start minutes in the low 16 bits and end minutes in the high 16 bits. The
bridge follows these observed types, revalidates before writing, and never elevates
access. The live write check submitted the existing value unchanged and verified
unchanged readback. Mocks exercise changed values and failure paths.

## Naming and coverage

The 271 canonical topic mappings use the controller's English wording, expanded
where abbreviated. Numeric instances become separate levels. German paths and
English choice labels are paired by matching captured page structure, not transient
IDs. Both supplied pumps' captured information/settings fields are covered, plus
all captured heating/hot-water/swimming-pool timer views. Fields absent on a model
produce no topics. The access-code page and remote-control image/buttons are not
telemetry or exposed commands.

Abbreviation expansions are informed by the manufacturer's
[controller manual](https://www.alpha-innotec.cz/wp-content/uploads/2019/02/controller-part-2-2.pdf)
and [comfort-board manual](https://www.alpha-innotec.cz/wp-content/uploads/2019/02/manual.pdf).
The English labels remain available verbatim in the English mapping paths.

## Firmware gap

The [ioBroker implementation](https://github.com/civiale/iobroker.luxtronik2ws/blob/main/main.js)
reports 3.92.2 with JSON. Older XML implementations include
[BenPru's probe](https://gist.github.com/BenPru/ec463ea835fb705b070939c793196f2e)
and [wp2reg-luxws](https://github.com/hansmi/wp2reg-luxws).
These are community implementations, not a manufacturer protocol specification.
FW 3.92 must be tested independently; do not infer its encoding from version numbers.
There is no legacy TCP fallback, speculative JSON handling, or generic write sender.
