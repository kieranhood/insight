# Peplink router integration (Balance / MAX, firmware 8.x)

Task 1.1 of `openspec/changes/add-internet-wifi-monitoring`. It checks the requirements in
`specs/integrations/peplink/spec.md`, plus the Peplink part of "Discovers equipment passively"
(`specs/device-inventory/spec.md`) and D10 in `design.md`.

**Status: desk research only.** Nothing here has been tested against the on-board router yet.
Findings are labelled by how strong their source is:

- **Official**: Peplink's own API documentation, user manual or MIB files.
- **Open-source capture**: field names and behaviour reported by open-source projects that ran
  against real routers.
- **Unverified**: inferred, or reported by a single forum user.

The items to confirm on board are listed at the end.

## Summary

- **Use the local Router API.** It is HTTPS JSON on the router's web-admin port (`https://<router>/api/<function>`).
  It works with no internet and needs no InControl. Peplink documents it for firmware 7.0+ and publishes a PDF
  for each 8.x release, up to 8.6.0. It is free; only one documented command (`cmd.starlink`) needs a
  Care plan.
- **Authentication:** create an **API client with scope `api.read-only`** (client ID and secret). Exchange it for an
  access token valid **48 h** (`expiresIn: 172800`), and send the token as the `accessToken` query parameter.
  Creating the client needs **one admin login**, done once by the engineer. There is no web UI page for it
  in the 8.6.0 manual. The fallback is the web-admin **read-only user**, which gives a cookie session limited
  to GET.
- **Documented and directly usable:**
  - WAN list with name, type, enable flag, status message, LED colour, priority and uptime (`status.wan.connection`)
  - full cellular radio data: RSRP, RSRQ, SINR and RSSI per carrier, carrier name, network type, signal level and cell ID
  - per-WAN and per-SIM bandwidth-allowance usage (`status.wan.connection.allowance`)
  - firmware version (`info.firmware`, which also answers without auth)
  - the DHCP/client list with MAC, IP, name, VLAN and lease (`status.client`)
  - LAN subnets (`status.lan.profile`)
- **Not in the documented API:**
  - **router model, serial and uptime.** These are only in the undocumented `status.system.info`, or in SNMP.
  - **health-check latency and packet loss.** The documented API exposes health checks only as their effect
    on the WAN's state. Latency comes only from the undocumented `status.wan.latency` (WAN Quality, 10 s points).
    Packet loss is not available for plain WAN links at all; it appears only inside SpeedFusion tunnel stats.
  - **an explicit "carrying traffic" flag.** Insight must derive the link in use from priority, state and
    per-WAN throughput (the undocumented `status.traffic`).
  - **an ARP table.**
- **SNMP fallback (v1/v2c/v3, off by default)** has an explicit WAN state, including
  `standby(8)` and `health-check-fail(6)`, plus a pass/fail health-check flag. It also has device model, serial and
  uptime, cellular signal, and daily, monthly and since-boot usage per WAN. It has no priority, latency or client list.
- **Discovery:** Peplink makes **no mDNS or SSDP announcements** as far as anyone reports. Passive discovery for
  Peplink therefore comes only from its client list. Active signatures are strong: six Peplink/Pepwave OUIs, the
  page title `Web Admin | Welcome`, a TLS certificate for `captive-portal.peplink.com`, and an unauthenticated
  `GET /api/info.firmware`.

See "Findings that affect Insight's design or specs" at the end.

## Interfaces

| Interface | Official? | Auth | Notes |
|---|---|---|---|
| Router API, `https://<ip>[:port]/api/<func>` | **Yes**. Per-release PDF: 8.0.0–8.6.0 | API client ID/secret → token (`?accessToken=`), or `POST /api/login` → `bauth` cookie | Same port as web admin (HTTPS 443 by default). Peplink says to use it only over HTTPS. JSON envelope `{"stat":"ok"\|"fail","response"\|"code"+"message"}`. Endpoints marked `beta`/`alpha` carry a `notice`. |
| Undocumented `/api/` functions: `status.system.info`, `status.traffic`, `status.wan.latency`, `status.wan.quality`, `status.log`, `status.port`, `info.capability`, `info.time` | No. Used by the web UI, and named but not documented by a forum poster ([forum 45532](https://forum.peplink.com/t/peplink-api-device-status/45532)) | Same as above | Seen working on 8.5.x by open-source projects. They can change without notice. `info.capability` is **refused** to `api.read-only` clients. |
| Web UI CGI, `/cgi-bin/MANGA/api.cgi?func=<func>` | No | `bauth` cookie | Same functions as `/api/`. Used by [ha-peplink-local](https://github.com/weirded/ha-peplink-local). Insight does not need it. |
| SNMP v1/v2c/v3, UDP 161 | **Yes**. MIBs at `download.peplink.com/resources/balance_max_snmp_mib-<ver>.zip` | Community plus allowed source subnet, or v3 user (auth MD5/SHA, privacy **DES only**) | **Disabled by default.** The MIBs (WAN 2016, DEVICE 2017, CELLULAR 2020) are older than the API. |
| Remote syslog (System > Event Log) | Yes (manual §16.1.6) | n/a. The router pushes to a host | Off by default. It could send WAN up/down events to Insight's existing syslog receiver. Message format on the wire is **unverified**. |
| InControl 2 (cloud) | Yes | OAuth | **Not acceptable** (needs internet). Ignored. |

## Authentication and setup steps for an engineer

From the official 8.6.0 API documentation (pp. 1–9) and manual §16.1.1:

- Permission levels: **Read-Only** ("can only read the status and the config"), Read-Write, and Admin.
- An API client has scope `api` (read-write) or `api.read-only`.
- Only an admin *login* can create clients. API clients cannot create other clients.
- `POST /api/auth.token.grant` returns `accessToken`, `authorizationType: 3`, `scope` and `expiresIn` (172800 s = 48 h in
  the doc's example). An open-source project measured 48 h on a MAX HD4 MBX 8.5.4.
- A cookie session from `/api/login` follows the web-admin idle timeout (default **4 h**).
- The web-admin read-only user (default name `user`) is enabled once a password is set. Its login gets `GET: 1, POST: 0`.

### Recommended: read-only API client

This is a one-off step, done by the engineer from a laptop on the LAN. It is a configuration change on the
router, so Insight should guide the engineer through it rather than perform it.

```bash
R=https://192.168.50.1            # router LAN IP (Pepwave default 192.168.50.1, Balance 192.168.1.1)
# 1. admin login (cookie)
curl -k -c pep.txt -H 'Content-Type: application/json' \
     -d '{"username":"admin","password":"…"}' $R/api/login
# 2. create the read-only client; note clientId and clientSecret
curl -k -b pep.txt -H 'Content-Type: application/json' \
     -d '{"action":"add","name":"insight","scope":"api.read-only"}' $R/api/auth.client
# 3. log out
curl -k -b pep.txt -X POST $R/api/logout
```

Enter the `clientId` and `clientSecret` in Insight's Peplink source settings. Insight then:

1. Calls `POST /api/auth.token.grant` with `clientId` and `clientSecret` (optionally `scope=api.read-only`), and keeps
   the token until about 1 h before `expiresIn` runs out, or until a 401. It must **not** grant a token per poll.
   - **Request encoding is not settled.** The doc and `peplinkctl` use JSON (`Content-Type: application/json`, with
     `scope`). [peplink-supervision] measured on 8.5.4 that JSON without `scope` gave `401 "Internal Error"` and
     form-urlencoded worked. Field names must be camelCase. Implement JSON first, fall back to
     form-urlencoded, and confirm on board.
2. Sends `?accessToken=<token>` on every GET. [peplink-supervision] measured that `Authorization: Bearer` and
   `access_token` are rejected.
3. On `{"stat":"fail","code":401}` (or HTTP 401/403), requests one new token. If that also fails, it marks the source
   "credentials refused" and **stops retrying** until the engineer acts. See the lockout note below.

To revoke later, an admin uses `POST /api/auth.client` with `{"action":"remove","clientId":…}`, or `auth.token.revoke`.

### Fallback: web-admin read-only user

1. Web admin → System > Admin Security: set a Read-only User name and password.
2. Insight calls `POST /api/login` (JSON `username`/`password`) and keeps the `bauth` cookie. It logs in again when the
   cookie expires (4 h idle by default).

Drawbacks of this route:

- Every login writes `Admin: … login successful` to the router's event log.
- The account is shared with anyone else who has the read-only password.
- Coverage of the undocumented endpoints for this account is **unverified**.
- If web-admin RADIUS is enabled, local accounts are disabled (manual §16.1.1).

### TLS and access

- HTTPS is the default (manual §16.1.1, "Default will be HTTPS"). The certificate is self-signed, issued for
  `captive-portal.peplink.com` ([forum 29100](https://forum.peplink.com/t/issue-with-certificate-from-www-captive-portal-peplink-com/29100),
  confirmed by [peplink-supervision]). Insight should **pin the certificate fingerprint on first use**, and show it
  to the engineer to confirm. Hostname verification cannot pass against an IP address.
- Web Admin Access defaults to **LAN only**. "Allowed LAN Networks" can restrict which VLANs reach the UI and API.
  Insight's VLAN must be allowed.
- **Lockout:** [peplink-supervision] measured that **5 failed logins suspend admin access from that IP for 5 minutes**.
  Unauthenticated 401s on other endpoints did not count (12 in a row, then a successful login). Never retry
  credentials automatically.

## Data availability

Field paths are relative to `response`. `<id>` is the WAN connection ID, which is stable per port; `order` lists them.
Unless stated otherwise, endpoints are `GET /api/<name>` and documented in API 8.6.0.

| Spec requirement | Availability | Endpoint and fields | Notes |
|---|---|---|---|
| **Connects locally, read-only credentials, no InControl** | **Available** | Router API over LAN HTTPS. Client scope `api.read-only`. | Read-only scope covers GETs. **Caveat:** some GET endpoints are *commands* (`cmd.wifi.scan`, `cmd.carrier.scan`, `cmd.config.download`, `cmd.ap`, `cmd.sms.get`). Insight must call only an allowlist (see "Polling and limits"). Authentication itself is a POST (`auth.token.grant` or `login`), and so is one read (`status.cellularModule.temperature`). |
| Router details: **firmware** | **Available** | `info.firmware` → `<n>.version` where `<n>.inUse == true` (also `bootable`, `order`) | Answers before login, but then only the in-use firmware. Also in `status.system.info` → `device.firmwareVersion`. |
| Router details: **model** | **Partially** (undocumented) | `status.system.info` → `device.model` (e.g. `"Pepwave MAX HD2"`), `device.productCode`, `device.hardwareRevision`, `device.company` | Not in the official API ([forum 45494](https://forum.peplink.com/t/peplink-api-to-include-model-field/45494)). [peplink-supervision] reports that `api.read-only` can read it. SNMP: `deviceModel` (DEVICE MIB). |
| Router details: **serial number** | **Partially** (undocumented) | `status.system.info` → `device.serialNumber` (`XXXX-XXXX-XXXX`) | SNMP: `deviceSerialNumber`. On a Balance, the default device name `Balance_XXXX` ends with the last 4 serial digits (manual §16.1.1). The MAX equivalent is unverified. |
| Router details: **uptime** | **Partially** (undocumented) | `status.system.info` → `uptime.second` (also `uptime.string`, `systemTime.timestamp`, `cpuLoad.percentage`) | SNMP: `deviceSystemUpTime` (an OCTET STRING, so it must be parsed). Can also be inferred from the event log line `System: Started up`. |
| WAN links: **name** | **Available** | `status.wan.connection` → `<id>.name` | Operators often put phone numbers or ICCIDs in WAN names ([peplink-supervision]). Treat names as sensitive. |
| WAN links: **type** | **Available** | `<id>.type` / `<id>.virtualType`: `ethernet`, `cellular` (8.0.1+; `gobi` before), `wifi`, `modem`, `ipsec`, `adsl`, also seen `wovlan` | **Starlink is not a type.** It is an `ethernet` WAN, so the engineer marks it (task 10.1). 8.6.0 adds "Starlink status in WAN Details"; whether that is in the API, and under what fields, is **unverified**. |
| WAN links: **state** (connected / standby / disconnected / disabled) | **Partially** | `<id>.enable` (false → disabled), `<id>.statusLed` (`empty, gray, red, yellow, green, flash`), `<id>.message` (free text), `<id>.uptime`, `<id>.scheduledOff`, `<id>.asLan` | No documented state enum. Messages seen on real routers: `Connected`, `Connected to <carrier>`, `Disabled`, `No Cable Detected`, `No Device Detected`. The message and LED for **standby** and **health-check failure** are **unverified**. Proposed mapping: `enable:false` or `gray` → disabled; `green` → connected; message containing "standby" (case-insensitive) → standby; `red` → disconnected; `yellow`/`flash` → connecting, as an extra state. Keep the raw message as evidence. SNMP has an explicit enum (see "SNMP fallback"). |
| WAN links: **priority** | **Available** | `<id>.priority` (integer, 1 = highest; absent when the WAN is disabled) | Documented example shows `0`; real 8.5.x routers show 1, 2. On Balance, `config.wan.connection` says priority means "connection type" (always-on vs backup group). Mapping on a Balance is **unverified**. |
| **Health check result** | **Partially** | Pass/fail only, shown in `status.wan.connection` `message`/`statusLed`. Config (method, interval, retries) is in `config.wan.connection?infoType=healthcheck` → `<id>.healthcheck.{enable,method,timeout,interval,retry,recovery}` | There is no documented health-check result field. Event log lines name the failed test, e.g. `WAN: <name> (Priority 1) disconnected (WAN failed DNS test)` (undocumented `status.log`). SNMP `wanHealthCheckState` = `fail(0)`/`success(1)` is the cleanest source. `config.wan.connection` is reportedly **refused** to `api.read-only` clients. Defaults (manual §13.2.7): DNS lookup, every 5 s, 3 retries, 3 recovery. Cellular may use `smartcheck`. A WAN with health check **disabled** is always considered up. |
| Health check **latency** | **Partially** (undocumented) | `status.wan.latency` → `<id>.latency.data[]` (ms, 360 points, `pointInterval` 10 s, `pointStart`/`pointEnd` epoch s). No `data` key means no measurement. | From "WAN Quality monitoring", not from the health check. Whether `api.read-only` can read it is **unverified**. Also: `status.pepvpn?infoType=tunnel&tunnelOption=<peerId>` → per-WAN `rtt`, which needs a SpeedFusion peer. |
| Health check **packet loss** | **Not available** (for plain WAN links) | `status.pepvpn` tunnel stats only: `tunnel.<peer>.wan.<id>.receive.packet.loss` (cumulative counters) | Only exists when SpeedFusion/PepVPN is in use. SNMP has no loss either. Insight's own probes (tasks 11.x) must supply loss. |
| **Link in use** | **Partially** (derived) | Derived: the enabled, connected WANs at the lowest `priority` value are active; higher-priority-number WANs are standby. Confirm with the undocumented `status.traffic` → `bandwidth.<id>.overall.{download,upload}` (kbps, near-real-time). | No "in use" flag in the API. Outbound policy rules, SpeedFusion bonding and Balance load-balancing can put traffic on several WANs at once, or on a lower-priority WAN. So the spec's "link or links" wording is right, and the derivation is a best effort. SNMP `wanState` distinguishes `connected(3)` from `standby(8)`. |
| **Failover events** | **Partially** (derived) | Insight compares the derived link-in-use between polls. For exact time and cause, the undocumented `status.log` → `log[]` text lines (newest first, local time, no year). | Poll-based events are only as precise as the poll interval. Remote syslog to Insight would give pushed, timestamped events, but needs a router config change; wire format **unverified**. |
| **Cellular signal** | **Available** | `<id>.cellular.signalLevel` (0–5). Per carrier `<id>.cellular.rat[].band[]` → `name`, `channel`, `signal.{rsrp,rsrq,sinr,rssi}` (8.1.2+; before that, `cellular.band[]` with no `rat`). | Values are per carrier, and carrier-aggregation secondaries may show `sinr` 0.0 or omit it. Use the primary (first listed) band. Seen on real routers: `pci`, `channelWidth`. `pci: 0` on all bands means "not measured". SNMP: `cellularSignalRssi/Sinr/Rsrp/Rsrq` and `wanSignal` (dBm, `-9999` = n/a). History: undocumented `status.wan.quality` (last hour, 10 s). |
| Cellular **carrier / network type** | **Available** | `<id>.cellular.carrier.{name,country}`, `<id>.cellular.mobileType` (8.0.1+; `network` before), `dataTechnology` (undocumented; can be `"5G NSA"` or `"FDD / CA Downlink"`), `roamingStatus.{code,message}`, `mcc`, `mnc`, `cellTower.{cellId,tac}`, `carrierAggregation` | Also `sim.<n>.{active,…}` per SIM. **Contains IMSI, ICCID, IMEI and APN username/password.** Drop them at ingest; `lite=yes` hides them but "has no effect on MAX devices". |
| **Data usage per WAN** | **Partially** | `status.wan.connection.allowance` → `<id>.{enable,usage,limit,percent,start,unit:"MB"}`. For cellular: `<id>.<simId>.{…}`. Only meaningful where the **Bandwidth Allowance Monitor** is enabled on that WAN. Undocumented `status.traffic` → `traffic.<id>.overall.{download,upload}` (MB). | 8.0.0 supported cellular only; 8.0.1+ supports all types. Without the monitor, usage is **unverified** (probably absent). The period `status.traffic` covers is unverified. SNMP `wanDataUsageTx/RxByte` (MB, by `daily(0)`, `monthly(1)`, `sinceLastReboot(3)`) is the most complete. |
| **Client / DHCP list** (discovery) | **Available** | `status.client` (8.0.1+) → `list[].{ip,mac,name,connectionType,vlanId,active,lease.{type,expiresIn},bssid,essid,signal.{strength,level},speed}`. Parameters: `activeOnly`, `vlanId`, `connectionType`, `size` (default 1000), `outputWeight=full\|normal\|lite`, `infoType`. | Includes inactive clients (`active:false`, no `connectionType`). Before 8.1.0, `connectionType` was sometimes wrongly `ethernet`. `name` is the DHCP hostname or a name set by the admin. |
| **ARP list** (discovery) | **Not available** | None documented or reported | `status.client` covers DHCP and active hosts with static IPs (`lease.type`). Hosts that never talk through the router may be missing (**unverified**). |
| LAN subnets (helps discovery scope) | **Available** | `status.lan.profile` → `<n>.{name,vlanId,ip,mask}` | Could pre-fill the subnet list in discovery, still unselected (D10). |

## Polling and limits

- **No rate limits are documented**, and none were found on the forum. Field reports:
  - [peplink-supervision] polls `status.wan.connection` every **3 s** on a MAX HD4 MBX without trouble, and reads
    `status.log` and `status.wan.latency` once a minute.
  - It saw `status.traffic` take up to **15 s**, and `status.wan.latency` 6 s, when the router was loaded. Use
    per-endpoint timeouts, so one slow endpoint does not fail the whole cycle.
- Proposed cadence for Insight:

  | Endpoint | Interval | Why |
  |---|---|---|
  | `status.wan.connection` | 10–15 s | Failover detection. The router's own detection takes about 15 s with defaults (5 s × 3 retries). |
  | `status.traffic` | 30 s | Link-in-use confirmation and throughput. |
  | `status.wan.latency` | 60 s | One call returns an hour of 10 s points. Use it to backfill gaps. |
  | `status.wan.connection.allowance` | 5 min | |
  | `status.log` | 60 s | Only if the read-only scope allows it. |
  | `status.client`, `status.lan.profile` | 5 min | |
  | `status.system.info`, `info.firmware` | 1 h, and on (re)connect | |

- **Endpoint allowlist:** `info.firmware`, `status.system.info`, `status.wan.connection`, `status.wan.connection.allowance`,
  `status.traffic`, `status.wan.latency`, `status.wan.quality`, `status.log`, `status.client`, `status.lan.profile`,
  `status.pepvpn` (optional), and `config.wan.connection?infoType=healthcheck` (optional, may be refused).
  - Never call any `cmd.*` endpoint.
  - Never call `config.pepvpn.profile`, which returns the PSK in clear text, or `cmd.config.download`.
- Tokens:
  - Reuse one 48 h token.
  - Whether the router caps the number of outstanding tokens per client is **unverified**. Re-granting only on
    expiry or 401 keeps this moot.
  - The token travels in the URL. Insight must keep URLs with `accessToken` out of logs and error messages.
    [peplink-supervision] hit exactly this leak.
- Lockout and back-off:
  - 5 failed logins cause a 5-minute lockout (see above).
  - On "unreachable", back off: 3 → 6 → 12 → 24 → 30 s cap. That works in the field for [peplink-supervision].

## Compatibility and licensing

- **API availability by version** (official PDFs 8.0.0–8.6.0):
  - `login`/`logout` 7.0.0+; `auth.client`/`auth.token.grant` 7.1.1+; `info.firmware` 7.1.1+
  - `status.wan.connection` and `status.wan.connection.allowance` 8.0.0+
  - `status.client` and `info.location` 8.0.1+
  - `config.wan.connection` (GET) 8.1.1+
  - `status.cellularModule.temperature` 8.4.1+
- **Breaking field changes inside 8.x** (all official):
  - Cellular WAN `type` changed from `gobi` to `cellular`, and the object from `gobi` to `cellular`, in 8.0.1.
  - `network` became `mobileType` in 8.0.1.
  - Per-band data moved under `rat[]` in 8.1.2.
  - Client `signalStrength` became `signal` in 8.1.0.
  - `mode` became `routingMode` in 8.0.1.
  - `cellTower.cellUtranId` was deprecated in 8.5.3.
  - The parser must accept both forms. Undocumented endpoints still use `portType: "gobi"` on 8.5.4.
- **Firmware support:**
  - 8.6.0 (Aug 2026) **drops older Balance, MAX, MediaFast and SFE CAM HW1 models**, which stay on 8.5.x maintenance
    releases ([5Gstore 8.6.0 notes](https://5gstore.com/blog/2026/08/03/peplink-firmware-8-6-0-release/)).
  - 8.6.1 (Sep 2026) is current. Its fixes are security hardening of the API (RCE via API requests, ref 37690),
    and 8.5.4 fixed an earlier API RCE (ref 35920) ([5Gstore 8.6.1](https://5gstore.com/blog/2026/09/30/peplink-firmware-8-6-1-release-whats-new-fixed/)).
  - **Baseline Insight on 8.5.x.** Recommend at least 8.5.4.
- **Undocumented endpoints:** seen on Balance 710 (8.5.1), MAX HD2, MAX HD4 MBX and Dome Pro Duo (8.5.4). On the
  Dome, `status.traffic`, `status.wan.latency`, `status.port` and `info.capability` were **absent**.
  Every undocumented read must be optional.
- **Licensing:**
  - The local API and SNMP need no licence.
  - Documented Care-plan dependencies are unrelated to reading: `cmd.starlink`, and Site Survey / `cmd.channelPci.*`.
  - Care plan or PrimeCare status shows in `status.system.info` → `subscription.carePlan`.
  - InControl is not required.

## SNMP fallback

These come from the official MIB archive `balance_max_snmp_mib-8.3.0.zip`, downloaded from `download.peplink.com`. The
8.5.x archives returned 403. The modules are the same for each brand, but the enterprise number differs: **Peplink `23695`,
Pepwave `27662`, Pepxim `52467`**. LibreNMS detects Pepwave by `sysObjectID .1.3.6.1.4.1.27662`. Settings: System > SNMP.
v1, v2c and v3 are each switched on separately. Communities carry an allowed source subnet. v3 offers auth NONE/MD5/SHA and
privacy NONE/DES only. The port defaults to 161. SNMP is **off by default** (manual Appendix, port table).

| Need | OID (under `1.3.6.1.4.1.<ent>`) | Notes |
|---|---|---|
| Model, serial, firmware | `.200.1.1.1.1.1`, `.200.1.1.1.1.2`, `.200.1.1.1.1.3` (DEVICE `deviceModel`, `deviceSerialNumber`, `deviceFirmwareVersion`) | Read by LibreNMS `os` module. |
| Uptime | `.200.1.1.1.2.2` DEVICE `deviceSystemUpTime` (OCTET STRING) | Also CPU, memory, temperature, fan, PSU and power source. |
| WAN name / state | `.2.1.2.1.2` `wanName`; `.2.1.2.1.3` `wanState`: unknown 0, disabled 1, disconnected 2, connected 3, connecting 4, activating 5, **health-check-fail 6**, disconnected-manually 7, **standby 8** | Gives the state enum the API lacks. No WAN type or priority. |
| Health check | `.2.1.2.1.4` `wanHealthCheckState`: fail 0, success 1 | Pass/fail only, with no latency or loss. |
| Signal | `.2.1.2.1.5` `wanSignal` (dBm; −9999 = n/a). CELLULAR `.200.1.12.1.1.1.{3..8}`: RSSI, SNR, SINR, Ec/Io, RSRP, RSRQ per WAN. `.9` network type, `.10` band, `cellularCarrier` | |
| Data usage | `.2.1.4.1.{2,3}` `wanDataUsageTx/RxByte` (Counter64, **MB**) by `dataTypeID` daily 0, monthly 1, sinceLastReboot 3. Overall: `.2.2.1.1.*` | Most complete usage source. |
| Clients | none | The LAN MIB has only LAN IP, mask, speed and status. |

SNMP is a valid fallback for state, health and usage. It is still weaker than the API: no priority, latency or clients,
weak v3 crypto, and off by default. Per D10, SNMP is never used in discovery.

## Discovery signatures

| Signature | Value | Strength | Source |
|---|---|---|---|
| MAC OUI | `00:11:6E`, `10:56:CA`, `6C:A3:D3`, `D4:13:F8` (Peplink International), `00:1A:DD` (PePWave Ltd), `A8:C0:EA` (Pepwave Limited) | Strong for the router's own LAN MAC. Peplink APs and switches share them. | Wireshark `manuf` / IEEE registry. `a8:c0:ea` and `00:1a:dd` seen on real routers ([peplink-supervision]). |
| Default LAN IP | Balance `192.168.1.1`; Pepwave MAX `192.168.50.1` | Weak (usually changed) | Manual §11.1, §13 |
| Open ports | TCP 443 (web admin/API, default HTTPS), TCP 80 (default enabled; redirect to HTTPS **unverified**). Off by default: SSH TCP 8822, SNMP UDP 161, NMEA GPS TCP 60660. SpeedFusion TCP 32015 / UDP 4500 only if a PepVPN server is configured. | Weak to medium. The 8822 SSH port is distinctive when enabled. | Manual Appendix (port table) |
| HTTP page title | `GET /cgi-bin/MANGA/index.cgi` → `<title>Web Admin \| Welcome…` and body `init_company_name = "Peplink"` (probably `"Pepwave"` on Pepwave units, **unverified**) | Strong | nuclei-templates [`peplink-panel.yaml`](https://github.com/projectdiscovery/nuclei-templates/blob/main/http/exposed-panels/peplink-panel.yaml) |
| TLS certificate subject | CN `captive-portal.peplink.com` (default self-signed web-admin cert, unless the engineer uploaded one) | Strong | [forum 29100](https://forum.peplink.com/t/issue-with-certificate-from-www-captive-portal-peplink-com/29100), [peplink-supervision] |
| Unauthenticated API probe | `GET /api/info.firmware` → `{"stat":"ok","response":{…"version":"8.x.x build N"…}}` | Proof | Official doc ("can also be done before login"). Measured to not count toward lockout ([peplink-supervision]). It sends no credentials, so it fits D10's "publicly served banner" rule. |
| mDNS / SSDP | **None known.** [peplink-supervision] reports mDNS, SSDP, LLDP and broadcast probes all silent on a MAX HD4 MBX. UPnP IGD exists but is off by default, and whether it advertises is unverified. Bonjour Forwarding relays others' mDNS between VLANs, and does not announce the router. | n/a | [peplink-supervision] `docs/REFERENCE.md` ("Trouver un équipement sur le réseau") |
| SNMP sysObjectID | `.1.3.6.1.4.1.27662` (Pepwave) / `.23695` (Peplink) | Strong, but not used (D10: no SNMP in discovery) | LibreNMS `os_detection/pepwave.yaml`; MIB files |

This gives at least two independent strong signatures (OUI + TLS subject, or OUI + page title), so task 1.5 can be met
for Peplink without mDNS/SSDP.

## Open items needing on-board verification

1. Model and firmware of the on-board router. Note whether it is a Balance or a MAX, since priority semantics and `lite`
   behaviour differ.
2. Token grant encoding (JSON vs form-urlencoded) and the real `expiresIn`.
3. Which endpoints an `api.read-only` token can read: `status.system.info`, `status.traffic`, `status.wan.latency`,
   `status.wan.quality`, `status.log`, `status.client`, `config.wan.connection`. Repeat with the web read-only user.
4. Exact `message`/`statusLed` for a **hot-standby** WAN, a **cold-standby** WAN, a WAN **failing its health check**, and a
   connecting WAN. Induce each by disabling Starlink or blocking its DNS. Capture both `status.wan.connection` and `status.log`.
5. Whether `status.wan.latency` has data for a standby WAN, and what exactly it measures. Is the target the health-check
   host?
6. `status.wan.connection.allowance` and `status.traffic` output with the Bandwidth Allowance Monitor off, and the period
   `traffic` covers.
7. Whether 8.5.x/8.6.x exposes Starlink fields in `status.wan.connection` (8.6.0 "Starlink status in WAN Details").
8. Whether `status.client` lists static-IP hosts (Starlink router, UniFi gear) and how far back inactive clients go.
9. Default TLS certificate subject and SANs on this unit (`openssl s_client -connect <ip>:443 | openssl x509 -noout -subject`),
   the page title, and port 80's behaviour.
10. Remote syslog: the message format for WAN events, and whether the target port is configurable (it could share
    Insight's syslog receiver).
11. Whether the Peplink NTP server is enabled (Advanced > Misc. Settings > NTP Server). The manual's port table lists
    inbound UDP 123 as disabled by default, and D11 provisioning assumes "NTP from the Peplink".
12. Capture real responses for every endpoint in `tests/fixtures/peplink/`, anonymise IMSI, ICCID, IMEI, serial, MAC and
    GPS, and replace the constructed fixtures.

## Findings that affect Insight's design or specs

1. **Health-check evidence is binary.** The router does not publish health-check latency or loss for WAN links. Latency
   exists only through an undocumented WAN Quality endpoint, and loss only for SpeedFusion tunnels. The spec's "where the
   router provides them" holds, but Insight's own probes (11.x) must be the source of loss. The design should not expect
   router-side loss for Starlink or cellular.
2. **"Link in use" and "standby" are derived, not reported**, in the documented API. Classifying a hot-standby WAN as
   standby rests on unverified message text. SNMP `wanState` is the only explicit source. Consider making SNMP an optional
   second Peplink source for state and usage. It needs SNMPv3 setup on the router and has weak (DES) privacy.
3. **Router model, serial and uptime need an undocumented endpoint** (`status.system.info`) or SNMP. Without either, the
   inventory gets firmware only. The "Router in inventory" scenario (model + firmware) depends on an undocumented call.
4. **Setup needs one admin action on the router.** Creating the API client, or setting the read-only user's password, is
   a configuration change. Insight's guided setup should give the engineer the steps or commands, not perform them,
   to stay read-only. Insight should never store the admin password.
5. **Read-only scope is not harmless.**
   - Some `cmd.*` endpoints are GETs, and `config.*` reads can include secrets.
   - `status.wan.connection` carries IMSI, ICCID, IMEI and APN credentials, even when `lite=yes` is sent on MAX devices.
   - The adapter needs a fixed endpoint allowlist and field-level scrubbing before storage.
6. **No mDNS/SSDP from Peplink**, so the "announcements" discovery layer adds nothing for the router. Passive discovery
   relies on `status.client`. There is **no ARP list**, so the D10 phrase "Peplink client/DHCP/ARP lists" should read
   "client/DHCP list".
7. **Credential-failure handling must not retry**, because of the 5-failure lockout. The token goes in the query string,
   so it must be scrubbed from logs.
8. **Firmware baseline 8.5.x.** Many Balance/MAX models will never get 8.6, and field names change within 8.x.
9. **Remote syslog from the Peplink** to Insight's existing syslog receiver would give pushed, timestamped failover
   events with causes. It is optional, needs a router config change, and its format is unverified.

## Sources

Official (Peplink):

- Peplink Router API Documentation, firmware 8.6.0 (primary reference, printed Jun 2026): <https://download.peplink.com/resources/Peplink-Router-API-Documentation-for-Firmware-8.6.0.pdf>
- Same, for 8.5.2, 8.5.0, 8.3.0, 8.2.0 and 8.1.0 (used for version history): `https://download.peplink.com/resources/Peplink-Router-API-Documentation-for-Firmware-<ver>.pdf`
- Peplink Balance and MediaFast Firmware Manual 8.6.0 (§11.1, §13.2.7 Health Check, §16.1.1 Admin Security, §16.1.6 Event Log, §16.1.7 SNMP, Appendix port table): <https://download.peplink.com/manual/peplink-balance-and-mediafast-firmware-manual-8.6.0.pdf>
- SNMP MIB archive 8.3.0: <https://download.peplink.com/resources/balance_max_snmp_mib-8.3.0.zip>
- Forum, model field via `status.system.info`: <https://forum.peplink.com/t/peplink-api-to-include-model-field/45494>
- Forum, undocumented `status.system.info` (8.0.1): <https://forum.peplink.com/t/undocumented-rest-api-endpoint/44255>
- Forum, uptime/CPU only via undocumented call or InControl: <https://forum.peplink.com/t/peplink-api-device-status/45532>
- Forum, default cert `captive-portal.peplink.com`: <https://forum.peplink.com/t/issue-with-certificate-from-www-captive-portal-peplink-com/29100>
- Forum, hot vs cold standby: <https://forum.peplink.com/t/quicker-connection-to-backup-wan-wan-standby-state/2582>

Open source and third party:

- [peplink-supervision] `maximvs101/peplink-supervision-public` (MIT), commit `241f8ee`, captures from 8.5.4 hardware: <https://github.com/maximvs101/peplink-supervision-public>
- `weirded/ha-peplink-local` (Apache-2.0), commit `acf996b`, `API.md`: <https://github.com/weirded/ha-peplink-local/blob/main/API.md>
- `WHOIGit/peplinkctl`, commit `c79047e`, JSON token grant: <https://github.com/WHOIGit/peplinkctl>
- LibreNMS Pepwave OS definitions and Peplink MIBs: <https://github.com/librenms/librenms/tree/master/resources/definitions/os_discovery/pepwave.yaml>, <https://github.com/librenms/librenms/tree/master/mibs/peplink>
- Observium MIB browser, PEPLINK-WAN / PEPLINK-CELLULAR: <https://mibs.observium.org/mib/PEPLINK-WAN/>, <https://mibs.observium.org/mib/PEPLINK-CELLULAR/>
- nuclei-templates, Peplink panel detection: <https://github.com/projectdiscovery/nuclei-templates/blob/main/http/exposed-panels/peplink-panel.yaml>
- Wireshark OUI database: <https://www.wireshark.org/download/automated/data/manuf>
- 5Gstore release-note summaries for 8.6.0 and 8.6.1 (secondary): <https://5gstore.com/blog/2026/08/03/peplink-firmware-8-6-0-release/>, <https://5gstore.com/blog/2026/09/30/peplink-firmware-8-6-1-release-whats-new-fixed/>
- Unofficial mirror of the 8.5.2 docs (not used as a source of truth): <https://apollon-docs-staging.pages.dev/peplink/overview>
