# openHAB example

Adapt the broker definition (or reuse an existing MQTT Bridge), then copy the
`.things`, `.items`, and `.rules` files into the corresponding openHAB config
directories. Install MQTT and JSONPath add-ons. Configure broker credentials in
the existing broker Thing, not in this repository.

The temperature channel extracts `value` and assigns °C. Separate channels expose
quality and observation time. The rule sets `Luxtronik_OutdoorFresh` only when
availability, quality, and timestamp all permit use; automations must check it.
An offline Thing does not guarantee that a retained Item value is cleared.

This is a reference configuration, not automatically installed into openHAB.
Check it against the target openHAB version; channel syntax is documented in the
[MQTT binding](https://www.openhab.org/addons/bindings/mqtt/).
