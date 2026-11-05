# UniFi fixtures

Sample responses for the UniFi adapter (tasks 8.1–8.3). Background and field mapping: `docs/integrations/unifi.md`.

**None of these files were captured on board or from a controller by us.** Each one has one of three provenances:

- **copied from official documentation**: copied verbatim from a Ubiquiti document.
- **from open-source library/test fixtures**: copied from an MIT-licensed project at a pinned commit. Those projects describe them as captured, or as anonymised real payloads, and we have not checked that.
- **constructed from documented field list**: written by us for Insight's test scenarios, using field names from the sources named. **Not captured.** Values, model codes and firmware strings are made up.

The file name suffix gives the provenance: `.official-example`, `.aiounifi` / `.unpoller`, or `.constructed`.

## Official Network API (`/proxy/network/integration/v1`), reliable

| File | Endpoint | Provenance |
|---|---|---|
| `official-v1-devices.official-example.json` | `GET /v1/sites/{siteId}/devices` | **Copied from official documentation**, verbatim: the "List Adopted Devices" 200 example in https://developer.ui.com/network/v11.0.97/postman-collection.json. The values are generator placeholders (for example an AP model with `"features": ["gateway","switching"]`), not a real device. |
| `official-v1-info.official-example.json` | `GET /v1/info` | **Copied from official documentation**: "Get Application Info" 200 example, same Postman collection |
| `official-v1-devices.aiounifi.json` | `GET /v1/sites/{siteId}/devices` | **From open-source library/test fixtures**: `SWITCH_SUMMARY`, `AP_SUMMARY`, `MODEM_SUMMARY` in https://github.com/Kane610/aiounifi/blob/82d69b8d22956492e17269c9cb7e1e6add9577e9/tests/network/v1/test_devices.py. aiounifi labels them "As listed by a UCG Industrial on Network 10.6.106". The page envelope (`offset`/`limit`/`count`/`totalCount`) was added by aiounifi's `envelope()` test helper (`tests/network/v1/conftest.py`), not captured. |
| `official-v1-device-detail-switch.aiounifi.json` | `GET /v1/sites/{siteId}/devices/{deviceId}` | **From open-source library/test fixtures**: `SWITCH_DETAIL`, same file. It describes a USW Enterprise 8 PoE, but only ports 1, 3 and 9 appear, as upstream has it. |
| `official-v1-device-statistics-ap.aiounifi.json` | `GET .../devices/{deviceId}/statistics/latest` | **From open-source library/test fixtures**: `AP_STATISTICS`, same file. This is an AP, not a switch, but the schema is the same. |
| `official-v1-clients.aiounifi.json` | `GET /v1/sites/{siteId}/clients` | **From open-source library/test fixtures**: `HA_CLIENT`, `GUEST_CLIENT`, `VPN_CLIENT` in https://github.com/Kane610/aiounifi/blob/82d69b8d22956492e17269c9cb7e1e6add9577e9/tests/network/v1/test_clients.py. The envelope comes from the test helper. |
| `official-v1-sites.constructed.json` | `GET /v1/sites` | **Constructed from documented field list**: `Site overview page` schema in https://developer.ui.com/network/v11.0.97/openapi.json. The site UUID is aiounifi's test `SITE_ID`. |
| `official-v1-devices.constructed.json` | `GET /v1/sites/{siteId}/devices` | **Constructed from documented field list**: `Adopted device overview` schema, same OpenAPI spec. Two switches. `SW-Crew` is deliberately `OFFLINE`, to exercise the "switch goes offline" scenario. In the classic fixture it is shown online: the two files are different moments. |
| `official-v1-device-detail-usw24poe.constructed.json` | `GET .../devices/{deviceId}` | **Constructed from documented field list**: `Adopted device details`, `Port overview` and `Port PoE overview` schemas, same OpenAPI spec. This is the same 24-port PoE switch as the classic fixture, which shows what the official API **cannot** give: no watts, no LLDP, no counters. There is no `uplink` key because the parent is a non-UniFi router. That this field is absent on real controllers is **Unverified**. Port 12 has `poe.state: UP`, port 5 is `DOWN`, ports 17–26 have no `poe`. |
| `official-v1-device-statistics-usw24poe.constructed.json` | `GET .../devices/{deviceId}/statistics/latest` | **Constructed from documented field list**: `Latest statistics for a device` schema, same spec |
| `official-v1-clients.constructed.json` | `GET /v1/sites/{siteId}/clients` | **Constructed from documented field list**: `Wired client overview` schema (`macAddress`, `uplinkDeviceId`), same spec. The Ruckus AP is a wired client of `SW-Bridge`. The official API names no port. |

## Classic controller API (`[/proxy/network]/api/s/<site>/...`), optional

| File | Endpoint | Provenance |
|---|---|---|
| `classic-stat_device-us24p250.unpoller.json` | one element of `GET stat/device` → `data[]` | **From open-source library/test fixtures**: copied verbatim from https://github.com/unpoller/unifi/blob/dbabcae01ad86d10f0d6bde89b56e41e88cd8b11/examples/usw.json. This is a US-24-250W (`US24P250`) on firmware 4.0.42, with MACs anonymised upstream. It is a bare device object without the `{"meta","data"}` envelope. Port 24 is the uplink, with a per-port `lldp_table` entry. |
| `classic-stat_device-us16p150.aiounifi.json` | one element of `GET stat/device` → `data[]` | **From open-source library/test fixtures**: `SWITCH_16_PORT_POE` in https://github.com/Kane610/aiounifi/blob/82d69b8d22956492e17269c9cb7e1e6add9577e9/tests/fixtures.py. Converted from a Python dict literal to JSON with `ast` (no code executed). This is a US-16-150W on firmware 4.0.66. Bare object, no envelope. |
| `classic-stat_sta-wired-client.aiounifi.json` | one element of `GET stat/sta` → `data[]` | **From open-source library/test fixtures**: `WIRED_CLIENT`, same file. `gw_mac` and `sw_mac` referred to other fixtures in the source and were resolved to their literal values. |
| `classic-stat_device.constructed.json` | `GET stat/device` | **Constructed from documented field list**: the `TypedDevice`, `TypedDevicePortTable`, `TypedDevicePortTableLldpTable` and `TypedDeviceUplink` field lists in https://github.com/Kane610/aiounifi/blob/82d69b8d22956492e17269c9cb7e1e6add9577e9/aiounifi/models/device.py and `usw.go`/`types.go` in https://github.com/unpoller/unifi/tree/dbabcae01ad86d10f0d6bde89b56e41e88cd8b11. Shaped after the two open-source samples above. Scenario: `SW-Bridge` is a 24-port switch (`USL24P`, PoE on ports 1–16, SFP 25–26):<br>- port 12 has a Ruckus AP as LLDP neighbour, `poe_power: "7.12"`<br>- port 5 is down (PoE `auto`, not powering)<br>- port 7 has PoE `off`<br>- port 24 has the downstream switch `SW-Crew` as neighbour<br>- port 25 (SFP) is the uplink to the Peplink router (`is_uplink`, `uplink.port_idx`, `uplink_mac` = Peplink OUI, no `uplink_remote_port`)<br>`SW-Crew` (`USL8LP`) uplinks on its port 8 to SW-Bridge port 24 (`uplink_remote_port: 24`), and SW-Bridge lists it in `downlink_table`. `total_max_power` values are illustrative; their meaning is **Unverified**. |
| `classic-stat_device-lldp-device-level.constructed.json` | `GET stat/device` (abridged) | **Constructed from documented field list**: the device-level `lldp_table` shape (`TypedDeviceLldpTable`: `chassis_id`, `chassis_id_subtype`, `is_wired`, `local_port_idx`, `local_port_name`, `port_id`) in aiounifi `models/device.py` and `unpoller/unifi` `ubb.go` `LLDPTable`. This is the newer-firmware alternative to the per-port `lldp_table`, so the parser can be tested on both. Abridged on purpose: only identity fields and `lldp_table`. |
| `classic-stat_sta.constructed.json` | `GET stat/sta` | **Constructed from documented field list**: `TypedClient` in https://github.com/Kane610/aiounifi/blob/82d69b8d22956492e17269c9cb7e1e6add9577e9/aiounifi/models/client.py. Three wired clients: the Ruckus AP on SW-Bridge port 12, an NVR on port 7, and a laptop on SW-Crew port 3 with no `ip` or `hostname`. The last one reflects the **Unverified** possibility that IPs are sparse without a UniFi gateway. |

## Not yet present

- SNMP walks from the on-board switch models (IF-MIB, LLDP-MIB, POWER-ETHERNET-MIB, ENTITY-MIB). Capture them at commissioning for task 8.2.
- Any capture from the on-board controller. When one is added, sanitise MACs, serials, names and keys (`x_authkey`, `x_fingerprint`, `syslog_key` and similar), and label it "captured on board, <date>, Network <version>, firmware <version>".

## Licences

aiounifi: MIT, © 2018 Robert Svensson. unpoller/unifi: MIT, © 2018-2020 David Newhall II, © 2016 Garrett Bjerkhoel. The copied fixtures keep those licences.

## snmp-walk-usw-pro.constructed.json

Constructed by hand from the standard IF-MIB, IF-MIB ifXTable and LLDP-MIB `lldpRemTable` OIDs listed in `docs/integrations/unifi.md` ("SNMP fallback"), as an SNMP GET of the system group plus walks of those tables on a USW-Pro-24-PoE. Not a capture. It includes one VLAN interface that Insight should ignore, and an LLDP neighbour (a Ruckus AP) on port 12.
