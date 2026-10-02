# Lux_WS evidence and verification gap

Research date: 2026-10-01. These are community implementations, not a manufacturer
protocol specification.

## Local observation

On 2026-10-01, the authorized controller reported **V3.89.3**, German UI. Its
public web client and authenticated read-only probes confirmed `ws://<host>:8214/`,
`Lux_WS`, `LOGIN`, XML `Navigation`, and `GET;<discovered information ID>` returning
full XML `Content`. A second GET also returned complete information. `REFRESH`
returned partial `values`; the bridge uses full GET cycles instead.

The content root has no ID. Sections repeat their names, and `Eingänge/HD` appears
twice with different types. Preserve these quirks in sanitized fixtures. Login
rejection and session longevity remain unverified on hardware. Initial one-shot
tests verified five readings and orderly offline status on exit. Final deployment
verified eight readings in consecutive cycles (see validation.md). Keep installation
addresses, credentials, and raw captures external.

## Published implementations

| Primary source | Evidence | Limitation |
| --- | --- | --- |
| [civiale/ioBroker adapter](https://github.com/civiale/iobroker.luxtronik2ws) and [implementation](https://github.com/civiale/iobroker.luxtronik2ws/blob/main/main.js) | Reports testing on 3.92.2. Connects on 8214 with `Lux_WS`, sends `LOGIN` and `GET`, and decodes JSON. | A report of compatibility, not independent verification of this controller. |
| [BenPru Python probe](https://gist.github.com/BenPru/ec463ea835fb705b070939c793196f2e) | Uses port 8214 and `Lux_WS`, then parses XML navigation/content and follows discovered IDs. | Older example; not evidence for the exact 3.92 wire format. |
| [hansmi/wp2reg-luxws](https://github.com/hansmi/wp2reg-luxws) | Existing Go protocol/client and Prometheus exporter; reports testing on 3.85.6. | Different firmware and output system. |
| [sieukrem/luxtronik2-ws-api](https://github.com/sieukrem/luxtronik2-ws-api) | Reverse-engineered client traverses the web interface's menu hierarchy. | Does not establish compatibility with this controller. |

Conclusion: implement the observed XML variant. The conflicting JSON claims remain
unresolved for FW 3.92; do not infer compatibility from version numbers. Support
only fixture-backed formats and fail explicitly on unknown responses.

Do not hard-code IDs from sample controllers. Confirm whether reads require
`GET`, `REFRESH`, or a particular sequence, whether refreshes contain partial
updates, and whether the server requires Origin or other handshake headers.
Confirm what login failure looks like instead of assuming an open socket means
authentication succeeded. Determine whether multiple clients are tolerated.

The project requirement establishes that port 8889 is unavailable. This project
does not depend on generalized claims about when the legacy API disappeared.

References are for research, not vendored implementations. Before adopting code
or a library, review its maintenance, license, dependencies, and actual firmware
coverage, and record a commit/version alongside the resulting fixtures.
