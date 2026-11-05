# Starlink dish fixtures

**None of these files is a capture from a real dish.** They were all built by hand from the
documented proto fields. Replace them, or add captured versions next to them, once
the on-board dish has been polled (see `docs/integrations/starlink.md`, "Open items").

## Format

Each file is the canonical proto3 JSON form of a `SpaceX.API.Device.Response` returned
by `SpaceX.API.Device.Device/Handle`. This is the form `grpcurl` prints, and the form
`google.protobuf.json_format.MessageToJson()` gives with default options:

- field names are lowerCamelCase (`dishGetStatus`, `fractionObstructed`)
- 64-bit integers are JSON strings (`"uptimeS": "432000"`)
- enums are their names (`"cause": "OBSTRUCTED"`)
- NaN floats are the string `"NaN"`
- fields at their default value (0, false, empty, first enum value) are **omitted**. A missing
  `popPingDropRate` means 0, and a missing `outage` means the dish is not in an outage.
  It does not mean "unavailable".

Placeholder values: `id` is `ut00000000-00000000-00000000` and `hardwareVersion` is
`EXAMPLE_HW_REV`, because the real Flat High Performance hardware string is not
verified. `countryCode` is `XX`. The `softwareVersion` and `apiVersion` values are
real-world strings. Timestamps are Unix-epoch nanoseconds around 2026-11-05T10:00Z.
The epoch the dish really uses is **unverified**.

Every file was checked with `google.protobuf.json_format.Parse()` (strict, so unknown fields
are rejected) against the dish protoset archived for firmware `2026.10.09.mr88722.2`:
<https://github.com/clarkzjw/starlink-grpc-golang/tree/9d95e05/protoset> (commit `9d95e05`).

## Files

| File | Provenance | Scenario |
|---|---|---|
| `get_status_ok.json` | Constructed from documented proto fields: `DishGetStatusResponse` in <https://github.com/clarkzjw/starlink-grpc-golang/blob/9d95e05/proto/spacex_api/device/dish.proto>; field meanings from <https://github.com/sparky8512/starlink-grpc-tools/blob/52968df/starlink_grpc.py>. Shape cross-checked against the partial published `get_status` excerpt (firmware 2026.08.31, `apiVersion` 43) in <https://dev.classmethod.jp/en/articles/starlink-mini-15-second-handover/> | Connected (no `outage`), no alerts, about 0.2% obstructed, `popPingDropRate` omitted because it is 0 |
| `get_status_obstructed.json` | Constructed from documented proto fields (same URLs) | In an outage with `outage.cause = OBSTRUCTED`, `currentlyObstructed = true`, `fractionObstructed = 0.087`, 100% ping drop, no `popPingLatencyMs` |
| `get_status_thermal_alert.json` | Constructed from documented proto fields (same URLs; `DishAlerts.thermal_throttle`) | Connected but `alerts.thermalThrottle = true`, with reduced throughput and higher latency |
| `get_history_obstruction_outages.json` | Constructed from documented proto fields: `DishGetHistoryResponse`, `DishOutage`, `EventLog`/`UXEvent` in the `dish.proto` / `common.proto` above | Recent outages, mostly `OBSTRUCTED`. **Arrays are cut down to 10 samples**: the real buffer holds about 900 one-second samples, and the ring index is `current % len`. |

The outage list lives only in `get_history` (`dishGetHistory.outages`). That is why the
"recent obstruction outages" in the obstructed scenario are in
`get_history_obstruction_outages.json`, while `get_status_obstructed.json` carries only the
current `outage`.
