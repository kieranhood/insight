# Starlink dish integration (task 1.4)

Status: desk research, 2026-11-05. **Nothing here has been checked against the on-board dish yet.**
Everything marked *Unverified* must be confirmed on board (see "Open items").

Spec: `openspec/changes/add-internet-wifi-monitoring/specs/integrations/starlink/spec.md`.
Design: D9 (Starlink dish, gRPC at `192.168.100.1:9200`, optional, 30 s) and the Risks section.

## Summary

- The dish (including Flat High Performance and maritime kits) runs an **unofficial, undocumented,
  unauthenticated gRPC server** on plain-text HTTP/2 at **`192.168.100.1:9200`**. Every call is
  the single unary RPC `SpaceX.API.Device.Device/Handle`. Its `Request` message holds a `oneof`
  that selects one of more than 100 operations, **reads and writes mixed together**
  (`get_status`, `get_history` … but also `reboot`, `dish_stow`, `dish_set_config`, `factory_reset`).
- **Server reflection is enabled.** As recently as firmware `2026.10.09.mr88722.2`, community
  projects pulled the full protoset from the dish with `grpcurl … describe`. So Insight can get
  the protos at runtime, or pin a protoset it captured itself.
- `get_status` gives: connectivity state (via `outage.cause`), obstruction fraction and
  `currentlyObstructed`, PoP ping latency and drop rate, throughput, about 19 alert booleans
  (thermal throttle and shutdown, motors stuck, mast not vertical, water detected, slow
  Ethernet …), hardware and software versions, uptime, software-update state, Ethernet speed
  and disablement (account) code.
- **The list of recent outages and their causes is only in `get_history`** (`outages[]`: cause,
  start, duration). The status response carries only the *current* outage. Insight must poll both.
- **The dish does not timestamp alerts.** Insight can record only the time it first saw an alert,
  to within one poll interval.
- **Reachability through a Peplink is the main risk.** Reaching `192.168.100.1` from the LAN needs
  Peplink-side setup: the WAN "Starlink" integration, or the older "Management IP Address" on the
  DHCP WAN. On top of that, Peplink routes `192.168.100.1` only while the Starlink WAN is healthy,
  **unless an *enforced* outbound policy rule** pins it to the Starlink WAN. Without that rule the
  dish becomes unreachable exactly when Starlink is failing, which matters for the spec's
  "dish unreachable" scenario. Recent Peplink firmware also offers a **gRPC proxy** on the Peplink
  LAN address (port 9200 + WAN ID).
- The interface has changed and broken clients several times: fields removed (2021, 2022), a
  latency=0 bug (late 2024), a proto package rename (May 2025), location blocked by policy
  (May 2026). The design's "optional" class fits.
- Starlink's official APIs (Enterprise Management/Telemetry API) are **cloud-only** and need an
  enterprise account, so the spec excludes them.

## Interfaces

| Interface | Official? | Insight class | Auth | Notes |
|---|---|---|---|---|
| Dish gRPC, `192.168.100.1:9200`, `SpaceX.API.Device.Device/Handle` (unary) | No. Undocumented, reverse-engineered by the community | **optional** | None | Plain-text HTTP/2 (h2c). Server reflection is enabled. This is the only interface Insight should use. It also has a bidirectional `Stream` RPC, which Insight should not use. |
| Peplink "gRPC proxy to Starlink", `<Peplink LAN IP>:(9200 + WAN ID)` (example: WAN1 → `:9201`, WAN2 → `:9202`, USB → `:9205`) | Peplink feature (firmware 8.5.0+), set on the hidden support page | **optional** (same protocol, just relayed) | None on the gRPC side | A Peplink-supported alternative to routing `192.168.100.1`, and useful with more than one dish. The WAN-ID mapping differs by model. Whether it keeps working while the Starlink WAN health check fails is *Unverified*. |
| Dish gRPC-web on `:9201` | — | not used | — | **Unverified / not found.** No source found documents a gRPC-web service on the dish. The "9201" mentioned in Insight's task is most likely the Peplink proxy port for WAN1. |
| Dish web page, `http://192.168.100.1/` (port 80) | Starlink's local browser app | not used (discovery only) | None | A single-page app that calls the same gRPC API. Its page title is *Unverified*. |
| Starlink router gRPC, `192.168.1.1:9000` | No | not used | None | Exists only when the Starlink router is in use (not in bypass). Same `Handle` RPC, router-side operations. |
| Peplink router's own Starlink integration (WAN "Starlink" pairing, firmware 8.4+) | Peplink | belongs to the Peplink adapter | Peplink API | Peplink shows dish details (throughput, latency, obstruction) in **InControl 2 (cloud)**. Whether the Peplink *local* API exposes any dish fields is *Unverified*; see `docs/integrations/peplink.md`. Firmware 8.5 adds "obstruction awareness", which keeps the WAN up through short obstruction drops. That affects Peplink health-check evidence. |
| Starlink Enterprise API (Management API and Telemetry API, `starlink.com/api/public/...`, docs at `starlink.readme.io`) | **Yes** | **excluded** (spec: "does not use cloud-only Starlink services") | OIDC client-credentials service account. Enterprise and Business accounts only, access through an account manager | Cloud-only. Useless when the internet is down, and it needs account credentials. Documented here only to record that it was considered and rejected. |

## Read-only request allowlist

`Handle` multiplexes reads and writes, so the network protocol gives no read-only guarantee.
Insight must enforce one in code: the adapter should only be able to *build* the request
variants listed below. No generic "send this request" path, and a unit test that checks the set
of `oneof` names the adapter can produce.

**Allowed (read-only):**

| `Request` oneof field (number) | Response oneof | Use in Insight |
|---|---|---|
| `get_status` (1004) | `dish_get_status` | Main poll: state, obstruction, alerts, latency, throughput, versions, uptime |
| `get_history` (1007) | `dish_get_history` | Outage list with causes, about 15 min of one-second latency, drop, throughput and power samples, UX event log |
| `get_device_info` (1008) | `get_device_info` | Cheap reachability and identity check (id, hardware and software version) |
| `get_diagnostics` (6000) | `dish_get_diagnostics` | Hardware self-test result, `stowed`, alerts, disablement code (optional, low rate) |
| `dish_get_obstruction_map` (2008) | `dish_get_obstruction_map` | Optional: map of where the sky is blocked (for example "own superstructure"). Large, poll rarely. |
| `dish_get_config` (2011) | `dish_get_config` | Optional: snow-melt and power-save settings (context only) |
| gRPC server reflection service (`grpc.reflection.v1alpha.ServerReflection`) | — | Only if Insight resolves protos at runtime |

Not needed: `get_location` (1017). It returns `PermissionDenied: Disabled due to policy` on most
plans since May 2026, and it is privacy-sensitive. `dish_get_context` (2003) and `get_ping` (1009)
are router-oriented or not implemented on the dish (*Unverified*). Leave them out.

**Insight must never send** (non-exhaustive; anything not on the allowlist is forbidden):
`reboot`, **`dish_stow`** (an *empty* `{"dish_stow":{}}` **stows** the dish, because `unstow`
defaults to false), `dish_set_config`, `dish_power_save`, `dish_inhibit_gps`, `dish_inhibit_rf`,
**`dish_clear_obstruction_map`** (wipes the learned map), `factory_reset`, `dish_factory_reset`,
`reset_button`, `software_update`, `update`, `set_per_vehicle_config`, `set_sku`, `set_trusted_keys`,
`set_test_mode`, `dish_set_emc`, `dish_set_max_power_test_mode`, `dish_activate_rssi_scan`,
`dish_aviation_test`, `dish_start_test_mode_server`, `restart_control`, `fuse`, `toggle_mode`,
`enable_debug_telem`, `initiate_remote_ssh`, `iq_capture`, `get_heap_dump`, `self_test`,
`speed_test` / `start_speedtest` / `report_client_speedtest` (these use satellite bandwidth),
`ping_host`, `tcp_connectivity_test`, `udp_connectivity_test`, `run_iperf_server`, `authenticate`,
`start_unlock` / `finish_unlock`, `signed_request` / `sensitive_request`, `user_reported_issue`,
every `wifi_*` and `transceiver_*` request, and the `Stream` RPC.

## Data availability

Field paths use proto names inside `DishGetStatusResponse` (`S.`), `DishGetHistoryResponse` (`H.`),
`DishGetDiagnosticsResponse` (`D.`) and `GetDeviceInfoResponse` (`I.`). They come from the protoset
for firmware `2026.10.09.mr88722.2` and from `starlink_grpc.py`. In proto3 JSON, any field at its
default value is omitted (see the fixtures README).

| Spec requirement / item | Availability | Field(s) | Notes |
|---|---|---|---|
| **Identifies the Starlink link** (engineer marks a Peplink WAN as Starlink; WAN state, health checks, latency, loss and failover attributed to Starlink) | **Not from the dish** (Peplink and probe data) | — | Comes from the Peplink adapter. The dish can confirm *which* terminal it is (`S.device_info.id`) and record per-dish identity, but it cannot tell which Peplink WAN it sits on. |
| **Checks the dish is reachable** | **Available** (with Peplink setup) | TCP connect to `:9200`, then `get_device_info` | Use a TCP or gRPC check, not ICMP; whether the dish answers ping is *Unverified*. **Caveat:** without the enforced outbound rule, Peplink stops routing to `192.168.100.1` when the Starlink WAN fails its health check, so "dish unreachable + WAN down" may be a Peplink artefact, not dish evidence (see Reachability). |
| Scenario: dish unreachable while the Starlink WAN is down → both are evidence of an outage | **Partially** | as above | Valid evidence only if the enforced outbound rule (or the proxy) is set up. Insight should record which reachability path is configured. |
| **Online state** | **Available** | `S.outage` present → `S.outage.cause` (`DishOutage.Cause`: `UNKNOWN, BOOTING, STOWED, THERMAL_SHUTDOWN, NO_SCHEDULE, NO_SATS, OBSTRUCTED, NO_DOWNLINK, NO_PINGS, ACTUATOR_ACTIVITY, CABLE_TEST, SLEEPING, SKY_SEARCH, INHIBIT_RF`). `outage` absent → connected. Also `S.disablement_code` (`OKAY`, `NO_ACTIVE_ACCOUNT`, `BLOCKED_COUNTRY`, `ROAM_RESTRICTED`, …), `S.is_snr_above_noise_floor`, `S.is_snr_persistently_low`, `S.ready_states.*` | The old `state` field was removed in 2021. starlink-grpc-tools derives `state` from `outage` the same way. New cause values can appear, so treat unknown values as "not connected, cause unknown". |
| **Obstruction fraction** | **Available** | `S.obstruction_stats.fraction_obstructed`, `.currently_obstructed`, `.time_obstructed`, `.valid_s`, `.patches_valid`, `.avg_prolonged_obstruction_duration_s`, `.avg_prolonged_obstruction_interval_s`, `.avg_prolonged_obstruction_valid` | Whether `fraction_obstructed` is a share of sky area or of time is not documented. The per-direction `wedge_*_fraction_obstructed` fields were **removed in 2022**. For direction, use `dish_get_obstruction_map` (`num_rows`, `num_cols`, `snr[]`, `map_reference_frame` FRAME_EARTH/FRAME_UT). On a yacht that turns, the reference frame matters (*Unverified*). |
| Scenario: significant obstruction fraction **and** recent outages caused by obstruction | **Available** (two calls) | `S.obstruction_stats.*` + `H.outages[]` where `cause == OBSTRUCTED` | See `tests/fixtures/starlink/get_status_obstructed.json` and `get_history_obstruction_outages.json`. |
| **Recent outages and their causes** | **Available** (in `get_history` only) | `H.outages[]` → `cause`, `start_timestamp_ns`, `duration_ns`, `did_switch`. Also `H.event_log.events[]` (`severity`, `reason` such as `EVENT_REASON_OUTAGE_OBSTRUCTED`, `start_timestamp_ns`, `duration_ns`), `H.event_log.current_timestamp_ns` | How far back `outages[]` goes, and the **timestamp epoch** (Unix or GPS), are *Unverified*. Compare `event_log.current_timestamp_ns` with the host clock to calibrate. starlink-grpc-tools does not parse `outages`, so no open-source parser has been tested against it here. The bulk `obstructed` / `scheduled` sample arrays were removed in 2021. |
| **Latency** | **Available** | `S.pop_ping_latency_ms` (latest), `H.pop_ping_latency_ms[]` (1 Hz, about 900 samples) | Round-trip time to the Starlink PoP, not to the internet. Reported 0 in `get_status` on late-2024 firmware (bug, fixed by about Jan 2025). Missing or 0 while the drop rate is 1 means no reply. |
| Packet loss (extra; the spec takes it from Peplink) | **Available** | `S.pop_ping_drop_rate`, `H.pop_ping_drop_rate[]` | A fraction from 0 to 1. Omitted from JSON when 0. |
| **Throughput** | **Available** | `S.downlink_throughput_bps`, `S.uplink_throughput_bps`, `H.*_throughput_bps[]` | *Actual use*, not capacity. Also `S.dl_bandwidth_restricted_reason` / `ul_…` (rate-limit reason) and `S.eth_speed_mbps`. |
| **Active alerts** (overheating, motor, power faults) | **Available** (as booleans, no times) | `S.alerts.*`: `motors_stuck`, `thermal_throttle`, `thermal_shutdown`, `mast_not_near_vertical`, `unexpected_location`, `slow_ethernet_speeds`, `slow_ethernet_speeds_100`, `install_pending`, `is_heating`, `power_supply_thermal_throttle`, `is_power_save_idle`, `dbf_telem_stale`, `low_motor_current`, `lower_signal_than_predicted`, `obstruction_map_reset`, `dish_water_detected`, `router_water_detected`, `upsu_router_port_slow`, `no_ethernet_link`. Also `D.alerts.*`, `S.reboot_reason` (e.g. `REBOOT_REASON_THERMAL_POWER_CUT`) | **Partially for "power faults":** there is no general power-fault alert, only PSU thermal throttle, `upsu_router_port_slow`, `low_motor_current` and power draw (`H.power_in[]`). Motor alerts likely do not apply to the motorless Flat High Performance dish (*Unverified*). Alerts get added and removed (`roaming`, `moving_while_not_mobile`, `moving_fast_while_not_aviation` and `moving_too_fast_for_policy` are gone), so iterate the message's fields rather than hard-coding them. |
| Scenario: alert (thermal throttling) recorded as an event **with its time** | **Partially** | `S.alerts.thermal_throttle` | The dish gives no alert start time. Insight must timestamp at the first poll that sees it (≤ 30 s resolution) and emit a clear event when it goes away. `H.event_log` covers outage and some Ethernet/SNR alerts, but no dish thermal reason was found in `EventReason`. |
| **Stowed state** | **Available, may not apply** | `S.outage.cause == STOWED`, `S.stow_requested`, `D.stowed`, `S.alignment_stats.actuator_state` (`ACTUATOR_STATE_TILT_TO_STOWED`), `S.has_actuators` | The Flat High Performance has no actuators (`HAS_ACTUATORS_NO` expected, *Unverified*). If so, it is never "stowed" and the field adds little on this yacht. |
| **Hardware and software versions** | **Available** | `S.device_info.hardware_version`, `.software_version`, `.id`, `.bootcount`, `.build_id`, `.manufactured_version`. `Response.api_version` (e.g. 28 in Dec 2024, 37 in Jun 2025, 43 in Aug–Sep 2026) | The Flat HP hardware string is *Unverified* (known examples: `rev3_proto2`, `mini1_pez_proto1`). Store `api_version` + `software_version` with every snapshot for fixture pinning. |
| **Uptime** | **Available** | `S.device_state.uptime_s` (uint64 → JSON string) | `H.current` (sample counter) also resets on reboot. Use either to detect reboots. `S.reboot_reason` gives the cause. |
| Software update in progress (extra) | **Available** | `S.software_update_state`, `S.software_update_stats.*`, `S.swupdate_reboot_ready`, `S.seconds_until_swupdate_reboot_possible`, `S.alerts.install_pending` | Useful for explaining planned reboots. |
| **Survives loss of the optional source** | **Design requirement**, supported | `Response.api_version`, reflection failures, missing message types | Failure signals: TCP refused or timeout, gRPC `UNAVAILABLE` / `DEADLINE_EXCEEDED` / `PERMISSION_DENIED` / `UNIMPLEMENTED`, a reflection lookup of `SpaceX.API.Device.Device` failing, or `dish_get_status` missing from the response. Any of these → monitoring failure + "insufficient information". |
| **Does not use cloud-only services** | **Available** | local gRPC only | No account or internet needed. The local interface is what Starlink's app uses for local debugging (e.g. sideloaded updates when the dish cannot reach the network). Whether `get_status` and `get_history` keep answering normally with no satellite connection is very likely but *Unverified on board*. |

## Reachability from the LAN

Typical install: dish (bypass mode, or without the Starlink router) → Peplink WAN port (DHCP; typically a CGNAT
`100.64.0.0/10` address, or public on some business plans) → yacht LAN, with Insight on the LAN. The dish sits
at `192.168.100.1` on the WAN side and is **not on any LAN broadcast domain**.

What is needed, in order of preference (setting names as reported on the Peplink forum; check them
against the on-board firmware):

1. **Pair the WAN as Starlink.** *Network → WAN → (bottom of page) "Starlink"*: pair the Starlink
   connection with its WAN (firmware 8.4+; a Starlink logo appears next to the WAN). Community
   reports say this alone makes `192.168.100.1` reachable from Peplink LAN clients on current
   firmware, in both router and bypass modes, with no Management IP.
   - Older firmware: on the DHCP WAN's settings, enable **"Management IP Address"** (exposed with
     the "?" next to the hostname field) and give it an address in `192.168.100.0/24` other than
     `.1` (e.g. `192.168.100.100/24`). The cause was that the Peplink ARPs the DHCP gateway instead
     of the dish (fixed in special build 8.1.1s118, April 2021, then in mainline firmware).
   - Classic "static route `192.168.100.0/24` via WAN" (the generic Starlink and third-party-router
     advice) is reported **not supported on Peplink WAN interfaces** for at least Balance models.
     The design's Risks entry and Migration step 6 should name the Peplink mechanisms above
     instead.
2. **Add an enforced outbound policy rule.** *Advanced → Outbound Policy*: add a rule with Source
   *Any*, Destination *192.168.100.1* (or `/24`), Protocol *Any*, Algorithm **Enforced** → the
   Starlink WAN, placed at the top. **Without it, when the Starlink WAN fails its health check (or
   another WAN is primary), the Peplink stops routing to `192.168.100.1`.** Reported May 2023 and
   repeated in 2025–2026 threads. That is exactly when Insight most needs dish detail, and it
   produces false "dish unreachable" evidence.
3. **Alternative: Peplink gRPC proxy.** `http://<peplink>/cgi-bin/MANGA/support.cgi` → **"Enable
   gRPC proxy to Starlink (TCP 9200 + WAN ID)"** (firmware 8.5.0+). Insight then targets
   `<Peplink LAN IP>:<9200+WAN ID>` instead of `192.168.100.1:9200`, so no route is needed. Since
   2026-09 the support page shows the port per WAN. Behaviour when the WAN is unhealthy is
   *Unverified*.
4. **If Insight sits behind another router** (e.g. a UniFi gateway on a separate subnet), traffic
   from non-Peplink subnets to `192.168.100.1` was reported dropped. The working fix was a transit
   VLAN plus a static route on the downstream router pointing at the Peplink. Simplest is to put
   Insight on a Peplink-served LAN or VLAN.

Insight's adapter settings should therefore take a **target `host:port`** (default
`192.168.100.1:9200`; for the proxy, `<peplink>:920N`), not a fixed address. The install
checklist should include items 1 and 2, or 3.

When the Starlink router is still in the chain (not bypassed), the Peplink is double-NATed behind
it, and `192.168.100.1` is normally reachable through the Starlink router. This setup is not
expected on board.

## Polling & limits

- No rate limit is documented. Community tools poll status every 1–60 s for years without reported
  problems. D9's **30 s for `get_status`** is reasonable.
- `get_history`: the dish keeps **about 15 minutes** of one-second samples in ring buffers (cut from
  12 h in Aug 2021). Poll every **5 min** (it must be under 15 min) and use `H.current` (total
  samples since boot) to take only new samples. A drop in `current` means a reboot.
- `get_device_info`: use as the reachability probe (cheap). `get_diagnostics`: every 5–10 min.
  `dish_get_obstruction_map`: hourly or on demand (the response is a float grid; size *Unverified*).
- Timeouts: 5 s per call (starlink-grpc-tools uses 10 s as a hang guard). Reuse one channel, and on
  `UNAVAILABLE` rebuild it once and retry once (starlink-grpc-tools does the same).
- Load on the dish from these rates is negligible as far as anyone reports (*Unverified*).

## Compatibility & fragility

Firmware rolls out automatically and often. One archive holds more than 100 dish protosets from
late 2024 to Oct 2026, roughly one to several a month. Known breaking or semantic changes:

| When | Change | Effect on clients |
|---|---|---|
| 2021-08 | History buffer cut from 12 h to 15 min | Poll history every < 15 min |
| 2021-10 | `state`, `snr`, bulk `scheduled` / `obstructed` stopped being populated, later removed | Tools crashed. State now derived from `outage` |
| 2022-11 | `wedge_fraction_obstructed` / `wedge_abs_fraction_obstructed` removed | No per-direction obstruction in status. Use the obstruction map |
| 2024-11 → ~2025-01 | `pop_ping_latency_ms` reported 0 in `get_status` (bug) | Fallback: take latency from `get_history` |
| 2025-05 | Proto file and package path renamed `spacex/api/...` → `spacex_api/...` (service name `SpaceX.API.Device.Device` unchanged) | Reflection by **file name** broke. Resolve by **symbol** instead |
| 2025–2026 | Alerts removed (`roaming`, `moving_*`), new ones added (`no_ethernet_link`, water detection, …). New status fields (battery and power-source stats for Mini, `signal_quality`, …) | Iterate fields dynamically and ignore unknown fields |
| 2026-05 | `get_location` → `PermissionDenied: Disabled due to policy` on most plans | Do not depend on location |

Design consequences: pin fixtures by `api_version` + `software_version`; parse defensively (treat
missing as the proto3 default, accept unknown enum numbers); have a parser test suite per captured
firmware; any structural surprise → monitoring failure + "insufficient information" (already in
the design).

## Python implementation notes

- **Transport:** `grpcio` (Apache-2.0, currently 1.85.x, Python ≥ 3.10; Insight is on 3.12).
  `grpc.aio.insecure_channel("192.168.100.1:9200")` fits the asyncio scheduler. No TLS and no
  credentials.
- **Message classes, two options:**
  1. **Runtime reflection** (what starlink-grpc-tools recommends): `yagrc` (Apache-2.0, 1.1.3)
     or `grpcio-reflection` + `google.protobuf` `descriptor_pool` / `message_factory`. Resolve
     by symbol `SpaceX.API.Device.Device`, never by file path (2025-05 rename). Cache the
     resulting `FileDescriptorSet` on disk, so a dish that later turns reflection off still works.
  2. **Pinned protoset/pb2 generated by Insight**: capture `grpcurl -plaintext -protoset-out
     dish.protoset 192.168.100.1:9200 describe SpaceX.API.Device.Device` on board, and generate
     with `grpc_tools.protoc --descriptor_set_in`. Recommended: pinned protoset as primary, with
     reflection as a diagnostic to detect drift.
- **Licences:** `sparky8512/starlink-grpc-tools` and its PyPI package `starlink-grpc-core`
  (module `starlink_grpc`, 1.2.5) are **Unlicense (public domain)**. They can be used as a
  dependency or copied. Its `status_data()` already maps state, alerts and obstruction, but it
  **does not parse `outages`**, and it also contains write helpers (`reboot`, `set_stow_state`,
  `set_sleep_config`, `set_gps`, obstruction-map reset). If Insight uses it, wrap only the read
  functions. `clarkzjw/starlink-grpc-golang` (proto archive and changelog) is **GPL-3.0**, so do
  **not** copy its `.proto` or generated files into Insight. Use it as a reference only. `Eitol/starlink-client`
  (MIT, PyPI `starlink-client`) and `ewilken/starlink-rs` (MIT/Apache-2.0) are other references.
  The protos themselves are SpaceX's and unpublished. Extracting them from the yacht's own dish
  avoids depending on third-party copies.
- **Request building:** `Request(get_status=GetStatusRequest())` → `response.dish_get_status`.
  `Request(get_history=GetHistoryRequest())` → `response.dish_get_history`. Check
  `response.WhichOneof("response")` before reading.
- **Parsing:** use `MessageToDict(msg)` for raw-evidence storage (gives the same shape as the
  fixtures). Remember int64 values are strings, NaN is `"NaN"`, defaults are omitted, and
  `avg_prolonged_obstruction_interval_s` is NaN when there is no data. Unwrap history ring buffers
  with `index = current % len(array)`.
- **Safety:** one module builds requests. A test asserts the allowed `oneof` set, and a lint or test
  forbids `reboot`, `dish_stow`, `dish_set_*`, `*_clear_*`, `factory_reset` and similar names
  anywhere in the adapter.

## Discovery signatures

| Signature | Strength | Notes |
|---|---|---|
| Fixed IP `192.168.100.1` (the dish's address on every install) | Strong *in context* | Not on a LAN subnet. The active sweep must probe this host explicitly (or the Peplink proxy port), because a LAN sweep never finds it |
| TCP `9200` open, gRPC reflection lists service `SpaceX.API.Device.Device` | **Strong** (two independent checks) | Reflection is a read-only listing. Alternatively, a `get_device_info` answer with `id` like `ut…-…-…` |
| `Response.dish_get_status` present / `device_info.hardware_version` | Strong | Shows it is a dish, not a Starlink router (router answers on `192.168.1.1:9000`) |
| Peplink LAN IP with TCP `9201`–`9205` answering the same gRPC service | Strong | Means the Peplink proxy is enabled |
| HTTP `:80` on `192.168.100.1` serves the Starlink web app | Medium | Page title *Unverified* (expected "Starlink") |
| MAC OUI | **Not usable from Insight** | The dish is behind the Peplink WAN (routed), so Insight never sees its MAC. SpaceX holds OUI `00:26:12` (IEEE MA-L), but whether dishes use it is *Unverified*. The Peplink WAN-side ARP table might show it (*Unverified*) |
| mDNS / SSDP | None known | Not expected across the routed WAN boundary |

## Open items needing on-board verification

1. **Capture real responses.** `grpcurl -plaintext -d '{"get_status":{}}' <target> SpaceX.API.Device.Device/Handle`,
   the same for `get_history`, `get_device_info` and `get_diagnostics`, plus the protoset (`describe`).
   Record firmware, `apiVersion` and hardware string, and replace or add to the constructed fixtures
   (task 1.4 asks for a captured status response; **none exists yet**).
2. Peplink model and firmware. Which mechanism makes `192.168.100.1` reachable (Starlink pairing /
   Management IP)? Is the **enforced outbound rule** in place? Test with the Starlink WAN
   deliberately unhealthy (e.g. by disabling its health-check target) and check whether the dish is
   still reachable.
3. Whether the Peplink gRPC proxy exists on the on-board firmware, its port for the Starlink WAN, and
   whether it works while the WAN is down.
4. Whether `get_status` and `get_history` answer normally while the dish has no satellite service.
5. The epoch of `outages[].start_timestamp_ns` / `event_log` (Unix or GPS), and how far back `outages[]`
   goes.
6. Flat High Performance specifics: `hardware_version` string, `has_actuators`, whether stow or motor
   alerts can ever appear, and `mobility_class`.
7. Whether the dish answers ICMP (affects the reachability probe and the device-ping probe).
8. The page title on `http://192.168.100.1/` and whether anything listens on `:9201` on the dish itself.
9. Whether the Peplink local API exposes any Starlink-integration fields (coordinate with
   `peplink.md`).
10. The `dish_get_obstruction_map` reference frame and response size on a moving vessel.

## Sources

- sparky8512/starlink-grpc-tools (README, `starlink_grpc.py` field docs, `dish_control.py`, commit history; Unlicense), commit `52968df`: <https://github.com/sparky8512/starlink-grpc-tools>
  - field documentation: <https://github.com/sparky8512/starlink-grpc-tools/blob/main/starlink_grpc.py>
  - wiki, reflection and protoset: <https://github.com/sparky8512/starlink-grpc-tools/wiki/gRPC-Protocol-Modules>
  - commits: obsolete fields `79839c0` (2021-10), wedges removed `000e3a4` (2022-11), latency bug `3589733` / `a3860e0` (2024-11 / 2025-02), package rename `7ab4ad3` / `ac8210a` (2025-05/06), location note `beb55f3` (2026-05)
- clarkzjw/starlink-grpc-golang (protoset archive for `2026.10.09.mr88722.2`, decoded protos, CHANGELOG with grpcurl excerpts; GPL-3.0), commit `9d95e05`: <https://github.com/clarkzjw/starlink-grpc-golang>
  - `dish.proto`: <https://github.com/clarkzjw/starlink-grpc-golang/blob/main/proto/spacex_api/device/dish.proto>
  - `device.proto`: <https://github.com/clarkzjw/starlink-grpc-golang/blob/main/proto/spacex_api/device/device.proto>
  - CHANGELOG: <https://github.com/clarkzjw/starlink-grpc-golang/blob/main/CHANGELOG.md>
- Eitol/starlink-client (MIT): <https://github.com/Eitol/starlink-client>
- ewilken/starlink-rs ("unauthenticated gRPC HTTP/2 server … allows for server reflection"): <https://github.com/ewilken/starlink-rs>
- starlink-community knowledge base (dish `192.168.100.1:9200`, router `192.168.1.1:9000`, own-router routes): <https://github.com/starlink-community/knowledge-base/wiki>
- Published partial `get_status` (firmware 2026.08.31, `apiVersion` 43): <https://dev.classmethod.jp/en/articles/starlink-mini-15-second-handover/>
- Peplink forum:
  - gRPC proxy, `support.cgi`, "Enable gRPC proxy to Starlink (TCP 9200 + WAN ID)": <https://forum.peplink.com/t/port-forward-and-source-nat-for-starlink-dishy/49786>
  - Management IP, special firmware 8.1.1s118, static route not working: <https://forum.peplink.com/t/starlink-app-fix/34868>
  - Dish unreachable when the WAN is unhealthy, enforced outbound rule fix: <https://forum.peplink.com/t/unable-to-connect-to-starlink-gui-when-starlink-outbound-connection-is-lost/43620>
  - Management IP no longer needed with the Starlink WAN integration; outbound rule; proxy: <https://forum.peplink.com/t/starlink-management-ip-does-it-still-need-to-be-manually-set/60451>
  - Downstream router, transit VLAN: <https://forum.peplink.com/t/wan-starlink-mangement-ip-downstream-router-access-not-working/59353>
  - Dish access in bypass mode, Management IP `192.168.100.100`: <https://forum.peplink.com/t/how-can-i-access-the-starlink-dishy-management-once-in-bypass-mode/50598>
  - Firmware 8.4+ reports: <https://forum.peplink.com/t/starlink-app-dish-management-access-peplink/35125>
  - Balance static-route limitation: <https://forum.peplink.com/t/starlink-and-peplink-balance/32297>
- Peplink and Starlink integration, menu path, InControl 2 details: <https://5gstore.com/blog/2023/12/20/peplinks-integration-with-starlink/>
- Peplink 8.5 obstruction awareness: <https://rvmobileinternet.com/peplink-firmware-8-5-released-starlink-optimizations-minor-updates>
- Starlink Enterprise API: <https://starlink.readme.io/docs/getting-started>. Starlink support articles on API access and Telemetry API (JS-rendered; content seen via search snippets only): <https://starlink.com/support/article/2a140927-d1e3-de25-9a73-71e1410a76e9>, <https://starlink.com/support/article/90109cc2-c7ec-31ff-d160-0a87f16ef759>
- SpaceX OUI `00:26:12`: <https://maclookup.app/vendors/space-exploration-technologies>
- PyPI metadata: <https://pypi.org/project/starlink-grpc-core/>, <https://pypi.org/project/yagrc/>, <https://pypi.org/project/grpcio/>, <https://pypi.org/project/starlink-client/>
