# openHAB example

Install MQTT binding and JSONPath transformation, then adapt the broker and device
ID in `luxtronik.things`. The example subscribes to JSON state and availability;
`luxtronik.items` and `luxtronik.rules` expose whether the reading is usable.

Unchanged values are not republished. Do not expire them by their old observation
timestamp: use availability and quality. For commands configure a channel's
`commandTopic` as the writable reading's `/value` topic with `retained=false`.
Use the JSON topic for authoritative state: `/value` also carries incoming commands
before they are validated. Inspect the reading's `possible_values` and `/result`.
These examples have not been imported into the user's openHAB instance.
