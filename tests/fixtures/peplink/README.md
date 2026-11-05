# Peplink router fixtures

**None of these files is a capture from a real router.** Two are copied word for word from Peplink's
official API documentation. The rest were built by hand from documented field lists, or, for
endpoints Peplink does not document, from field lists published by open-source projects that
captured real routers. Replace them, or add captured versions next to them, once the on-board router
has been polled (see `docs/integrations/peplink.md`, "Open items").

## Scenario

All the constructed files describe the same router at the same moment, `2026-11-05T10:00:00Z`
(`1793872800`, 11:00 CET on the router's clock):

- Pepwave MAX BR1 Pro 5G on firmware `8.5.4 build 5808`. It booted on Nov 1 at 06:26 CET
  (`uptime.second` = 361989).
- WAN 1, **Starlink**: ethernet, priority 1, connected, carrying traffic. It failed its DNS
  health check at 10:41 CET, and it recovered at 10:58 CET (see `status_log.json`).
- WAN 2, **Cellular**: Vodafone ES, LTE-A, priority 2, hot standby. It carried traffic only between
  10:41 and 10:58 CET.
- WAN 3, **Wi-Fi WAN**: present on the hardware but disabled. It covers the "disabled" state.
- LAN: untagged 192.168.50.0/24, VLAN 20 "AV" and VLAN 30 "Crew". There are four active clients and one
  inactive one.

`status_wan_connection_failover.json` is the same router during the outage (about 10:45 CET), with
Starlink failing its health check and cellular carrying traffic.

Placeholders: serial `1111-2222-3333`, `productCode` `EXAMPLE-PRODUCT-CODE`, modem firmware
`EXAMPLE-MODEM-FW`, all-zero IMSI, ICCID and IMEI. Firmware build numbers are realistic in form but
not verified. Router MACs use the real Pepwave OUI `A8:C0:EA` with made-up suffixes. Client MACs use
real vendor OUIs (Dell, Ubiquiti, Sonos, Apple) with made-up suffixes, plus one locally administered
MAC (`02:…`) of the kind a phone with MAC randomisation would use.

## Provenance, per file

Sources:

- [API-8.6.0] Peplink Router API Documentation for Firmware 8.6.0 (official):
  <https://download.peplink.com/resources/Peplink-Router-API-Documentation-for-Firmware-8.6.0.pdf>
- [HA-LOCAL] `weirded/ha-peplink-local`, `API.md` (Apache-2.0), examples captured from a Balance on 8.5.1:
  <https://github.com/weirded/ha-peplink-local/blob/main/API.md>
- [SUPERVISION] `maximvs101/peplink-supervision-public` (MIT). It holds anonymised captures from a
  MAX HD2, a MAX HD4 MBX and a Dome Pro Duo, all on 8.5.4, in `backend/tests/fixtures/*.json`:
  <https://github.com/maximvs101/peplink-supervision-public/tree/main/backend/tests/fixtures>

| File | Endpoint | Provenance |
|---|---|---|
| `login.json` | `POST /api/login` | **Copied from official documentation** [API-8.6.0], `/api/login` cURL example. This is the admin response. A read-only user should get `"POST": 0` (documented, not captured). |
| `auth_token_grant.json` | `POST /api/auth.token.grant` | **Copied from official documentation** [API-8.6.0], `/api/auth.token.grant` cURL example. The example requested `scope: api`. Insight will request `api.read-only`, and the response should then say `"scope": "api.read-only"`. |
| `error_unauthorized.json` | any, when the token or session is missing or refused | Constructed from the documented fail format [API-8.6.0], "Response". The code and message match what [SUPERVISION] reports seeing (`backend/app/peplink/router_api.py`). |
| `info_firmware.json` | `GET /api/info.firmware` | Constructed from documented field list [API-8.6.0], `info.firmware`. The versions were changed from the doc's 7.x example. The doc says an unauthenticated call returns only the in-use firmware; the shape of that reply is **unverified**. |
| `status_system_info.json` | `GET /api/status.system.info` (**undocumented**) | Constructed from field lists in open-source projects: [HA-LOCAL] (`device` block) and [SUPERVISION] `max_hd2_8.5.4.json` (`cpuLoad`, `uptime`, `systemTime`, `macInfo`, `subscription`). Peplink does not document this endpoint. Some blocks seen in the capture were left out (`openvpn`, `speedfusionConnect*`). |
| `status_wan_connection.json` | `GET /api/status.wan.connection` | Constructed from documented field list [API-8.6.0], `status.wan.connection` (`WAN_Status_Obj`, `Gobi_Obj`, `RAT_Obj`, `Band_Obj`, `Signal_Obj`). Undocumented keys that real 8.5.x routers return (`portId`, `managementOnly`, `virtual`, `modulePowerOn`, `simCardDetected`, `pci`, `channelWidth`, `dataTechnology`, `manufacturer`, `model`, `firmware`) follow the shape in [SUPERVISION] `dome_pro_duo_8.5.4.json`. **The `"message": "Standby"` and `"statusLed": "yellow"` of the hot-standby cellular WAN are not verified.** No source shows what a hot-standby WAN reports. |
| `status_wan_connection_failover.json` | `GET /api/status.wan.connection` | Constructed, same basis as above. **The `"message": "WAN failed DNS test"` of the failing Starlink WAN is not verified.** It mirrors the event-log wording reported in [SUPERVISION] (`docs/REVUE-2026-09-24.md`, `max_hd4_mbx_8.5.4.json` → `status.log`). Whether `uptime` resets to 0 is also not verified. |
| `status_wan_connection_allowance.json` | `GET /api/status.wan.connection.allowance` | Constructed from documented field list [API-8.6.0], `status.wan.connection.allowance` (`SIM_Allowance_Obj` for cellular, `Allowance_Obj` otherwise). What a WAN with the monitor **disabled** returns (here `{"enable": false}`) is **unverified**. |
| `config_wan_connection_healthcheck.json` | `GET /api/config.wan.connection?infoType=healthcheck` | Constructed from documented field list and example [API-8.6.0], `config.wan.connection`. The doc's example uses a `nslookup` key, while its field table says `dns`; this file follows the example. [SUPERVISION] reports that an `api.read-only` client is **refused** `config.wan*`, so Insight may not be able to read this. |
| `status_client.json` | `GET /api/status.client?outputWeight=full` | Constructed from documented field list [API-8.6.0], `status.client` (`Client_Obj`, `Lease_Obj`, `Signal_Detail_Obj`, `Bandwidth_Obj`). As documented, an inactive client has no `connectionType`, and an untagged-LAN client has no `vlanId`. |
| `status_lan_profile.json` | `GET /api/status.lan.profile` | Constructed from documented field list [API-8.6.0], `status.lan.profile`. |
| `status_traffic.json` | `GET /api/status.traffic` (**undocumented**) | Constructed from field lists in open-source projects: [HA-LOCAL] (`status.traffic` example) and [SUPERVISION] `max_hd2_8.5.4.json` (`portType: "gobi"` for cellular, the `virtual` flag). The period that `traffic` counters cover (since boot? since install?) is **unverified**. |
| `status_wan_latency.json` | `GET /api/status.wan.latency` (**undocumented**) | Constructed from the field list in open-source project [SUPERVISION] `max_hd2_8.5.4.json`, `max_hd4_mbx_8.5.4.json`: 360 points, 10 s apart, covering the last hour, in ms. A WAN with no measurement has no `data` key. The values are synthetic. Whether a hot-standby WAN has latency data is **unverified**. |
| `status_log.json` | `GET /api/status.log` (**undocumented**) | Constructed from the line format in open-source project [SUPERVISION] `max_hd2_8.5.4.json`, `max_hd4_mbx_8.5.4.json` → `status.log` (newest first, no year, router local time). The lines are made up to match the scenario. |
