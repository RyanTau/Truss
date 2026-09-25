# Typed control validation (2026-09-25)

The capability discovery, staged protocol, value binding, native-service execution,
fresh-capability recheck and no-retry behavior are exercised by automated tests.
Home Assistant is represented by doubles; no physical device was controlled.
The complete suite passed 78 tests. Syntax, JSON, translation and package checks passed.

The real cached English LAYA checkpoint (`1c5edc1`) was also run offline on CPU
through `LocalModels.score` with a discovered catalogue containing:

- A thermostat supporting 16–30 C in 0.5 increments.
- A desk lamp with on/off and brightness in one-percent increments.
- A TV exposing HDMI 1, Channel 7 and News as selectable sources.

| Input | Model outcome | Gate at threshold 0.80 / margin 0.05 |
| --- | --- | --- |
| Turn on the desk lamp | Correct device, power=true; weakest stage 0.6261 | Blocked |
| Set the study thermostat to 19.5 degrees | Selected 19.0, not 19.5; weakest stage 0.0823 | Blocked |
| Set desk lamp brightness to 50 percent | Request stage chose wait | Blocked |
| Set the lounge television to channel 7 | Attribute stage chose wait | Blocked |
| Set the study thermostat to | Attribute stage chose wait | Blocked |
| Do not turn on the desk lamp | Attribute stage chose wait | Blocked |
| Select News on the lounge television | Request stage chose wait | Blocked |

These results establish that the path runs offline and the gate rejects weak or
incomplete decisions. They do **not** establish reliable real-world accuracy:
none of these examples reached the default execution threshold. Supported step
sizes can create larger score scales than the standalone synthetic demo, and the
model is sensitive to names, descriptions and wording. Inspect `truss_decision`
with the actual installation's entities before choosing a threshold. Lowering
the threshold does not fix an incorrect value selection.
