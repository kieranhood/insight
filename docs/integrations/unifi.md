# UniFi switches (UniFi Network controller)

Task 1.2 of `openspec/changes/add-internet-wifi-monitoring`. Research done 2026-11-05 from published sources only: no on-board controller or switch was available. Anything not confirmed by a source below is marked **Unverified**. It must be checked at commissioning before task 8 depends on it.

Insight's source classes (design.md):

- **Reliable**: official or standard interfaces. Here that means the official UniFi Network API (Integration API) and standard SNMP MIBs.
- **Optional**: unofficial interfaces. Here that means the classic controller API (`/api/s/<site>/...`).

## Summary

- **The official local UniFi Network API (Integration API, `/integration/v1`, API key) is not enough for Insight on its own.** It does give switch identity, online state, uptime, per-port link state and negotiated speed, per-port "PoE enabled" and "PoE delivering" flags, the parent device's ID, and a client list. It does **not** give PoE watts, PoE budget, LLDP neighbours, per-port error or traffic counters, the uplink port number, or the switch port a client is on. This was checked against Ubiquiti's published OpenAPI spec, which has the same port and PoE schema in every version from 9.1.120 to 11.0.97.
- **The classic controller API has everything the spec asks for.** It is unofficial, so per design.md it is **optional**. Its `stat/device` call returns `port_table[]` with `up`, `speed`, error and byte counters, `poe_mode`, `poe_enable`, `poe_power` and `lldp_table`. It also returns `total_max_power`, `uplink{port_idx, uplink_mac, uplink_remote_port}` and `downlink_table`. Its `stat/sta` call returns clients with `sw_mac` and `sw_port`. Mature open-source clients (aiounifi, unpoller, Art-of-WiFi) all depend on it, and it still works on Network 11.x for devices and clients.
- **SNMP from the switches (reliable, standard MIBs) is the reliable base for port counters.** IF-MIB is expected to work. LLDP-MIB depends on the model: community reports show it working on USW-Pro models and missing on Gen1 USW-24/48-POE. POWER-ETHERNET-MIB has no evidence either way (**Unverified**). SNMP is turned on site-wide from the controller. USW Flex and Ultra switches do not support SNMP at all.
- **Things that affect the design and specs:**
  1. No read-only API key exists. Anecdotal reports say only a Super Admin can create one.
  2. Network 8.x, and the legacy self-hosted Network Server, have no API keys and no official API.
  3. The spec scenario "Ruckus AP on port 12" can only be met from an optional source, unless the switch model serves LLDP-MIB.

  See [Open items](#open-items).

## Interfaces

| Interface | Official? | Auth | Notes |
|---|---|---|---|
| **UniFi Network API** (Integration API) `https://<console>/proxy/network/integration/v1/...` | **Yes**. Documented at developer.ui.com, with an OpenAPI spec and a Postman collection. | `X-API-KEY: <key>` header, stateless. The key is created in the Network app under *Integrations*. | Insight would class this as **reliable**. Only on UniFi OS (Cloud Key Gen2/Gen2+, UniFi OS Server, UniFi OS consoles). Published docs start at v9.1.120; unpoller says "available since Network 9.3.43". There is nothing for 8.x. The API has write endpoints too (port and device actions, configuration), which Insight must never call. The spec is also served by the controller at `/proxy/network/api-docs/integration.json` (per unpoller; **Unverified**). |
| **Classic controller API** `https://<host>[:8443]/[proxy/network/]api/s/<site>/stat/device`, `/stat/sta`, `/api/self/sites` | **No**. Undocumented by Ubiquiti. Field names come from open-source clients. | UniFi OS: `X-API-KEY` (used by unpoller and Art-of-WiFi), or `POST /api/auth/login` plus the `TOKEN` cookie (and `X-CSRF-Token`, needed only on non-GET calls). Legacy self-hosted: `POST /api/login` plus a session cookie. No API key there. | Insight would class this as **optional**. Ubiquiti has said nothing about stability, but `stat/device` and `stat/sta` have stayed stable from 5.x to 11.x (Art-of-WiFi supports 5.x–11.x and says devices and clients were "unaffected" by the 11.0 changes). Use `GET`. Art-of-WiFi's `list_devices()` uses `POST` with a `macs` filter, which is not needed. |
| **SNMP on each switch** (v1/v2c/v3, UDP 161) | Standard MIBs, plus Ubiquiti's private UI-MIB | Community string (read-only), or v3 user. Auvik reports that v3 is fixed at SHA/AES-128. | Insight would class this as **reliable**. Turned on site-wide from the controller, with no per-switch setting. Not supported on USW Flex or Ultra. What each MIB returns depends on the model (see [SNMP fallback](#snmp-fallback)). |
| **Site Manager API** `https://api.ui.com/...` (cloud) | Yes | Cloud API key | **Not usable.** It needs internet, and the spec says Insight "SHALL NOT depend on Ubiquiti's cloud services". Listed only to rule it out. |

### URL forms

| Controller type | Base URL | Official API | Classic API |
|---|---|---|---|
| UniFi OS console, Cloud Key Gen2/Gen2+ (UniFi OS 2.x+) | `https://<ip>` (443) | `/proxy/network/integration/v1/...` | `/proxy/network/api/s/<site>/...`; log in at `/api/auth/login` (no prefix) |
| UniFi OS Server (new self-hosted) | `https://<ip>:11443` | same as above (**Unverified** on UniFi OS Server specifically) | same as above |
| Legacy self-hosted UniFi Network Server (Windows, Linux, Docker); Cloud Key Gen1 | `https://<ip>:8443` | **Not available.** The API key method is not supported (Art-of-WiFi). | `/api/s/<site>/...`; log in at `/api/login` |

Site identifiers differ between the two APIs:

- The classic API uses the site's short name (usually `default`).
- The official API uses a UUID `siteId` from `GET /v1/sites`. Its `internalReference` field holds the classic short name, so the two APIs can be mapped to each other.

## Authentication & setup steps for an engineer

1. **Identify the controller.** Browse to it. If the login page is a UniFi OS page on port 443, it is a UniFi OS console or Cloud Key Gen2. If it is a UniFi Network page on port 8443, it is the legacy self-hosted server or a Cloud Key Gen1. Record the Network application version (Settings → System or the About panel; `GET /v1/info` returns `applicationVersion`).
2. **UniFi OS and Network 9.3 or later: preferred route (official API, plus the classic API with the same key):**
   1. Create a local-only admin, for example `insight`, with Remote/cloud access disabled. Art-of-WiFi says local accounts are not subject to MFA.
   2. While signed in as that user, open the Network app → **Integrations**. Older builds use Settings → Control Plane → Integrations; sources disagree on the path. Choose **Create New API Key** and copy the key, which is shown once. Store it in Insight's source secret.
   3. **Role caveat.** The key "inherits the permissions from the admin user that created it" (Art-of-WiFi). A Home Assistant issue from July/August 2025 reports two things: only a **Super Admin** could create a key, and View Only and Full Management users could not. It also reports that the key kept working after the user was demoted to read-only. This is anecdotal and has not been checked against Ubiquiti (**Unverified**). Insight must therefore enforce read-only itself: it may only send `GET` to an allowlist of paths.
3. **Strictly read-only alternative, or the legacy self-hosted controller (classic API only, optional class):**
   1. Create a local admin with the Network role **View Only**. Art-of-WiFi recommends View Only for read-only use cases.
   2. Insight then logs in with username and password.
   3. Insight must keep the session cookie and log in again only on `401`. It must not log in on every poll.
4. **TLS.** The controller's certificate is self-signed by default. Record its SHA-256 fingerprint and pin it in Insight. Don't turn verification off globally (unpoller has fingerprint pinning).
5. **Smoke test** from the Insight host:
   - `curl -sk -H "X-API-KEY: $KEY" https://<ip>/proxy/network/integration/v1/info`
   - then `.../v1/sites`
   - then `.../proxy/network/api/s/default/stat/device`
6. **SNMP** (only if you want the SNMP base or fallback):
   1. In the Network app, enable SNMP. The current official article gives *Settings → CyberSecure → Traffic Logging → SNMP*. Auvik and older versions give *Settings → System → SNMP*.
   2. Set a non-default v2c community, or v3 credentials. This changes the controller's configuration, so the engineer does it, not Insight.
   3. Run `snmpwalk` against each switch to confirm what it serves (see [SNMP fallback](#snmp-fallback)).
7. **LLDP on the neighbours.** Confirm that the Ruckus APs and the Peplink router send LLDP (**Unverified** for both). If they don't, port linking falls back to the client list (`stat/sta` `sw_mac`/`sw_port`).

## Data availability

Legend:

- **A** = Available
- **P** = Partially
- **N** = Not available
- **U** = Unverified

Classic paths are relative to `/api/s/<site>/`, with a `/proxy/network` prefix on UniFi OS. Official paths are relative to `/proxy/network/integration`.

| Spec item | Official Network API (**reliable**) | Classic API (**optional**) | SNMP on switch (**reliable**) |
|---|---|---|---|
| **Read via the on-board controller, no cloud** | **A**. Local console URL with an API key. | **A**. Local URL. | n/a (direct to the switch) |
| Switch **name** | **A**. `GET /v1/sites/{siteId}/devices` → `name` | **A**. `GET stat/device` → `name` | **A**. SNMPv2-MIB `sysName` |
| Switch **model** | **A**. `model`, a display name such as `"USW Enterprise 8 PoE"` per aiounifi's capture. | **A**. `model`, a code such as `US24P250` or `USL24P` | **P/U**. ENTITY-MIB `entPhysicalDescr.1`/`entPhysicalModelName`. Missing on Gen1 USW-48-POE (LibreNMS); `sysDescr` there is generic Linux. |
| Switch **IP address** | **A**. `ipAddress` (may be missing on some device types) | **A**. `ip` (also `config_network.ip`) | **A**. The address Insight polls. |
| Switch **MAC address** | **A**. `macAddress` | **A**. `mac` | **P**. IF-MIB `ifPhysAddress` of the CPU or VLAN interface (**U**: which ifIndex) |
| Switch **firmware version** | **A**. `firmwareVersion` | **A**. `version` (for example `4.0.66.10832`); also `upgradable`, `upgrade_to_firmware` | **U**. Possibly in `sysDescr` or `entPhysicalSoftwareRev`. |
| Switch **uptime** | **A**, one call per switch. `GET /v1/sites/{siteId}/devices/{id}/statistics/latest` → `uptimeSec` | **A**. `uptime` (s), `_uptime` | **A**. `sysUpTime` (agent uptime) |
| Switch **online state** | **A**. `state`: `ONLINE`, `OFFLINE`, `PENDING_ADOPTION`, `UPDATING`, `GETTING_READY`, `ADOPTING`, `DELETING`, `CONNECTION_INTERRUPTED`, `ISOLATED`, … | **A**. `state` int: 0 disconnected, 1 connected, 2 pending, 4 upgrading, 5 provisioning, 6 heartbeat missed, … (aiounifi `DeviceState`). Also `last_seen`. | **P**. Inferred from whether SNMP replies. |
| Port **link up/down** | **A**. `GET /v1/sites/{siteId}/devices/{id}` → `interfaces.ports[].state` (`UP`, `DOWN`, `UNKNOWN`), keyed by `idx` | **A**. `port_table[].up` (also `enable`, `port_idx`, `name`, `media`) | **A**. IF-MIB `ifOperStatus` (`ifAdminStatus`) |
| Port **negotiated speed** | **A**. `ports[].speedMbps` (missing when down), `maxSpeedMbps`, `connector` | **A**. `port_table[].speed` (Mb/s, 0 when down), `full_duplex`, `speed_caps` | **A**. IF-MIB `ifHighSpeed` |
| Port **error counters** | **N** | **A**. `port_table[].rx_errors`, `tx_errors`, `rx_dropped`, `tx_dropped` | **A** (**U** per model). IF-MIB `ifInErrors`, `ifOutErrors`, `ifInDiscards`, `ifOutDiscards`. LibreNMS shows port statistics on Gen1 and Pro. |
| Port **traffic counters** | **N** per port. Only device-level `statistics/latest` → `uplink.txRateBps`/`rxRateBps`. | **A**. `port_table[].rx_bytes`, `tx_bytes`, `rx_packets`, `tx_packets`, `rx_broadcast`/`multicast`, `rx_bytes-r`/`tx_bytes-r` (rates) | **A**. IF-MIB `ifHCInOctets`, `ifHCOutOctets` and the packet counters |
| **PoE enabled** per port | **A**. `ports[].poe.enabled` ("Whether the PoE feature is enabled on the port"), plus `poe.standard` and `poe.type` | **A**. Configured: `port_table[].poe_mode` (`auto`, `off`, `pasv24`, `passthrough`). Capable: `port_poe`, `poe_caps`. | **U**. POWER-ETHERNET-MIB `pethPsePortAdminEnable` has no evidence on UniFi. |
| **PoE power delivered** per port | **P**. `ports[].poe.state` = `UP`, `DOWN`, `LIMITED` or `UNKNOWN` ("Whether the port currently supplies power"). No watts. | **A**. `port_table[].poe_power` (W, **string**, for example `"7.12"`), `poe_voltage`, `poe_current` (mA), `poe_class`. `poe_enable` and `poe_good` are true while the port is powering, as seen in the fixtures. | **U**. POWER-ETHERNET-MIB `pethPsePortDetectionStatus` has no evidence. Per-port watts are not in the standard MIB. |
| Switch **PoE budget** | **N** | **P/U**. `total_max_power` (W). Its meaning is **Unverified**: samples show 135 on a 150 W model and 222 on a 250 W model. | **U**. POWER-ETHERNET-MIB `pethMainPsePower` |
| Switch **PoE usage** | **N** | **P**. Add up `port_table[].poe_power`. No total field has been confirmed. | **U**. `pethMainPseConsumptionPower` |
| **Neighbour on each port** (name and MAC) | **N**. No LLDP. **P**: a wired client's `uplinkDeviceId` (`GET /v1/sites/{siteId}/clients`) names the **switch but not the port**. | **A** (two shapes, depending on firmware):<br>(a) per port: `port_table[].lldp_table[]` = `{lldp_chassis_id, lldp_port_id, lldp_system_name}`<br>(b) per device: `lldp_table[]` = `{chassis_id, chassis_id_subtype, port_id, local_port_idx, local_port_name, is_wired}`. A system name is **not** confirmed in shape (b).<br>MAC-table fallback: `stat/sta` → `sw_mac` + `sw_port`. | **P/U**. LLDP-MIB `lldpRemTable` (`lldpRemChassisId`, `lldpRemSysName`, `lldpRemPortId`). Shown on USW-Pro-24/48-POE; **absent** on Gen1 USW-24/48-POE (LibreNMS). BRIDGE-MIB FDB (MAC per port) is populated on Gen1. |
| **Uplink port** and the device it connects to | **P**. `GET .../devices/{id}` → `uplink.deviceId` (the parent UniFi device only). No local or remote port number. When the parent is not a UniFi device (the Peplink router here) the field is probably absent (**U**). | **A**. `port_table[].is_uplink`. `uplink` = `{port_idx, uplink_mac, uplink_remote_port, uplink_device_name, up, speed, type}`. Also `last_uplink`, `uplink_depth`, and `downlink_table[] {mac, port_idx}` for UniFi devices downstream. **U**: whether `uplink_remote_port` is filled in when the parent is the Peplink. | **P**. No "uplink" concept. Insight would have to infer it from the LLDP neighbour or from configuration. |
| **Client list** (discovery) | **A**. `GET /v1/sites/{siteId}/clients` (paged, `limit` ≤ 200): `type` (`WIRED`, `WIRELESS`, `VPN`, `TELEPORT`), `macAddress`, `ipAddress`, `name`, `connectedAt`, `uplinkDeviceId`, `access.type`. No switch port. | **A**. `GET stat/sta`: `mac`, `ip`, `hostname`, `name`, `oui`, `is_wired`, `sw_mac`, `sw_port`, `sw_depth`, `uptime`, `first_seen`, `last_seen`, `network`, `vlan` | **P/U**. BRIDGE/Q-BRIDGE FDB gives MAC per port only. |

**Reliable or optional, field by field (how the adapter should split it):**

- **Reliable**, from the official API:
  - switch name, model, IP, MAC, firmware, online state, uptime
  - port up/down, port speed
  - PoE enabled
  - PoE delivering, as a yes/no only
  - parent device ID
  - clients: MAC, IP, name, parent switch
- **Reliable**, from SNMP IF-MIB: port error and traffic counters, which the official API does not have.
- **Optional**, from the classic API:
  - PoE watts
  - PoE budget and usage
  - LLDP neighbours (name and MAC)
  - uplink port and remote port
  - client switch port
  - classic error and byte counters, when SNMP is not configured
- **Not available from any reliable source, as far as the evidence goes:** PoE watts, budget and usage; uplink port number; the attached device per port. The exception is LLDP-MIB on models that serve it (**U**).
- **Legacy self-hosted controller or Network 8.x:** the official API does not exist, so **everything** from the controller is optional and only SNMP is reliable.

## Polling & limits

- **Official API requests per cycle.** With N switches, one cycle at the default 60 s is about `1 + 2N + ⌈clients/200⌉` requests:
  - `/v1/sites`, cached
  - `/devices` (paged, `limit` default 25, maximum 200)
  - `/devices/{id}` per switch, for ports
  - `/devices/{id}/statistics/latest` per switch, for uptime
  - `/clients`

  For about 4 switches that is about 10 requests per minute.
- **Classic API:** 2 requests per cycle (`stat/device`, `stat/sta`). The response can be large: the open-source sample for a single 24-port switch is about 45 KB of JSON. Use `GET /stat/device`; `stat/device-basic` is lighter but has no ports. Optionally filter by MAC with `stat/device/<mac>`.
- **Rate limits.** None are documented for the local APIs. The cloud Site Manager API documents 10,000 requests/min (v1) with `Retry-After`, which does not apply here. unpoller handles `429 Too Many Requests` with `Retry-After` from controllers, so Insight should honour `Retry-After` and back off. Logging in again and again is the main risk. UniFi OS throttles failed logins, but the details are **Unverified**. Keep one session and log in again only on `401` (`api.err.LoginRequired`). An MFA-enabled account returns HTTP 499 (`api.err.Ubic2faTokenRequired`) and must not be used.
- **Read-only enforcement.** Both APIs have write endpoints. Classic: `cmd/devmgr`, `rest/*` with PUT/POST. Official: `POST .../devices/{id}/actions`, `.../ports/{portIdx}/actions` and others. The adapter should hard-code a `GET` allowlist.

## Compatibility & licensing

- **Official API versions.** developer.ui.com serves OpenAPI specs for 9.1.120, 9.2.87, 9.3.45, 9.4.19, 9.5.21, 10.1.84 and 11.0.97 (checked by download). The `Port overview` and `Port PoE overview` schemas, `uplink {deviceId}` and the wired-client `uplinkDeviceId` are the same in all of them. Docs for 8.x, 9.0.x and other 10.0.x builds returned 404. unpoller says integration/v1 needs **9.3.43+**. So Network **8.x has no official API**, and 9.0–9.2 support is **Unverified**.
- **Network 11.x** runs only on UniFi OS 6.0+ and "no longer available for the self-hosted Network Server" (Art-of-WiFi). Ubiquiti calls UniFi OS Server the replacement for the legacy server. In 11.x, the classic time-series and events endpoints changed. Devices, clients and health endpoints were "unaffected".
- **Cloud Key.** Gen2/Gen2+ run UniFi OS (firmware 2.0.24+ per Art-of-WiFi), so they use port 443 and the `/proxy/network` prefix. Cloud Key Gen1 runs the legacy controller on 8443. Its maximum supported Network version is **Unverified**; it is likely below 9.3, which would mean classic API only.
- **Switch firmware.** The classic LLDP structure changed between firmware generations: per-port `lldp_table` in 4.x samples, device-level `lldp_table` in newer samples. The adapter must accept both. The official API hides firmware differences.
- **Licensing.** The local Network API needs no paid licence. The terms of use for developer.ui.com were not reviewed (**Unverified**). Libraries consulted: aiounifi (MIT), unpoller/unifi (MIT), Art-of-WiFi UniFi-API-client (MIT). The fixtures copied from aiounifi and unpoller are MIT-licensed; see `tests/fixtures/unifi/README.md`.

## SNMP fallback

- **Enabling.** SNMP is a site-wide controller setting with no per-switch toggle.
  - Location: *Settings → CyberSecure → Traffic Logging → SNMP* (current Ubiquiti help article), or *Settings → System → SNMP* (Auvik, older versions).
  - Versions: v1/v2c (the community string is read-only, default `public`, and should be changed) and v3 (Auvik: SHA/AES-128, with one password field).
  - Traps: "not currently available".
  - Unsupported: **USW Flex and Ultra switches do not support SNMP.**
  - If snmpd isn't answering after enabling, force-provision the switch (Auvik).
- **What to expect** (community evidence only, so all **Unverified** for the on-board models):

| MIB | Insight use | Evidence |
|---|---|---|
| SNMPv2-MIB (`sysName`, `sysDescr`, `sysUpTime`) | name, uptime, reachability | Works on USW. On Gen1 `sysDescr` is generic Linux or "EdgeSwitch". |
| IF-MIB (`ifOperStatus`, `ifHighSpeed`, `ifHC*Octets`, `ifIn/OutErrors`) | port state, speed, traffic, errors (**reliable base**) | LibreNMS shows port statistics on Gen1 USW-24/48-POE and on USW-Pro. |
| ENTITY-MIB | model | Present on USW-16-150W and USW-Pro; "No Such Object" on Gen1 USW-48-POE |
| BRIDGE-MIB / Q-BRIDGE-MIB | MAC per port (attachment fallback) | `dot1dTpFdbPort` present on Gen1 USW-48-POE |
| LLDP-MIB (`1.0.8802.1.1.2`) | neighbours | Shown on USW-Pro-24/48-POE; **not** on Gen1 USW-24/48-POE |
| POWER-ETHERNET-MIB (`1.3.6.1.2.1.105`) | PoE | **No evidence found.** No poster reports PoE data over SNMP for any USW model. Assume **not available** until a walk shows otherwise. |
| UI-MIB / UBNT-UniFi-MIB (private) | possibly PoE and temperature | Ubiquiti warns its MIBs "are not comprehensive". Contents for switches **Unverified**. |

- **Fit with the spec.** "Falls back to SNMP" promises availability, port state and port traffic over SNMP. IF-MIB should cover these. PoE and LLDP must be shown as "not available" unless the commissioning walk proves otherwise.
- **Commissioning walk.** Capture `snmpwalk -v2c -c <community> <switch> 1.3.6.1.2.1` plus `1.0.8802.1.1.2` from each switch model on board. Store the walks as fixtures for task 8.2; none exist yet.

## Discovery signatures

Separate signatures are needed for the controller and for the switches. They are collected for task 1.5 and `docs/integrations/discovery.md`.

| Signature | UniFi OS controller (Cloud Key Gen2/Gen2+) | Legacy self-hosted controller | UniFi switch | Strength / status |
|---|---|---|---|---|
| **MAC OUI** (Ubiquiti, from the Wireshark `manuf` database) | Ubiquiti OUI | **None.** It runs on a generic PC or VM. | Ubiquiti OUI | strong for hardware |
| **Open TCP ports** | 443 (UniFi OS web and API), 8080 (device inform). 8443: **U** on UniFi OS. | 8443 (GUI/API), 8080 (inform), 8880/8843 (guest portal), 6789 (speed test). UniFi OS Server: 11443. | 22 (SSH, if enabled); no web UI (**U**) | medium |
| **UDP ports** | 3478 (STUN), 10001 (discovery) | 3478, 10001, 1900 (only when "Make application discoverable on L2 network" is enabled) | 10001 | medium |
| **HTTP page title** | "UniFi OS" (**U**) | "UniFi Network" (older "UniFi Controller") (**U**) | n/a | weak until verified |
| **TLS certificate subject** (default self-signed) | **U**. The UniFi OS cert lives at `/data/unifi-core/config/unifi-core.crt`; its subject was not found. | `C=US, ST=New York, L=New York, O=Ubiquiti Inc., OU=UniFi, CN=UniFi` (user-posted `openssl s_client` output). An older variant is `CN=UniFi, OU=UniFi, O=ubnt.com, L=San Jose, ST=CA, C=US`. | n/a | strong where present |
| **Unauthenticated HTTP** | **U** | `GET /status` → `{"meta":{"rc":"ok","server_version":...}}`. unpoller uses `/status` as a version and auth probe; it would be an extra request in the active sweep. **U** for the exact body. | n/a | strong (active only) |
| **UBNT discovery, UDP 10001** | **U** whether the console announces itself | n/a | Unadopted devices broadcast to `255.255.255.255` and multicast `233.89.188.1`, UDP 10001. The payload is TLV: 0x01 MAC, 0x02 IP, 0x03 firmware, 0x0B hostname, 0x0C platform, 0x14 model. Whether adopted devices also announce is **U**. A `01 00 00 00` probe gets a reply, but that is active and UDP. | strong; passive listening needs Insight to bind UDP 10001 on the host |
| **mDNS / SSDP** | **U**. No source found. | UDP 1900 L2 discovery (format **U**) | **U** | unknown |

Ubiquiti OUIs: `00:15:6D 00:27:22 04:18:D6 0C:EA:14 18:E8:29 1C:0B:8B 1C:6A:1B 24:5A:4C 24:A4:3C 28:70:4E 2C:E5:BD 44:D9:E7 58:D6:1F 60:22:32 68:2E:3C 68:72:51 68:D7:9A 6C:63:F8 70:A7:41 74:83:C2 74:AC:B9 74:F9:2C 74:FA:29 78:45:58 78:8A:20 80:2A:A8 84:78:48 8C:30:66 8C:ED:E1 90:41:B2 94:2A:6F 9C:05:D6 A4:F8:FF A8:9C:6C AC:8B:A9 B4:FB:E4 CC:35:D9 D0:21:F9 D4:89:C1 D8:B3:70 D8:C2:62 DC:9F:DB E0:63:DA E4:38:83 F0:9F:C2 F4:92:BF F4:E2:C6 FC:EC:DA`. The list includes the MA-S block `00:50:C2:B0:40/36`.

Source-derived discovery (D10) is available two ways:

- **Official API:** clients with `macAddress`, `ipAddress`, `name` and the switch.
- **Classic API (optional):** the same, plus the switch port, plus LLDP neighbours.

**U:** without a UniFi gateway, client `ip` and `hostname` may be sparse. The controller then learns clients from the switches' MAC tables, not from DHCP or ARP on a gateway.

## Controller location on board

**To be confirmed at commissioning.** Check and record:

- **Hardware.** Is it a Cloud Key (Gen1 UC-CK, Gen2 UCK-G2, Gen2+ UCK-G2-PLUS), UniFi OS Server, a legacy self-hosted Network Server (which host and OS), or none at all?
- **Location.** Where it is installed (rack and space), its IP and VLAN, and whether Insight's host can reach it on 443 or 8443.
- **Versions.** UniFi OS version and Network application version. These decide whether the official API exists: 9.3.43+ is the safe assumption.
- **Accounts.** Whether a local-only admin can be created. Which role can create an API key on that build: try View Only first, and record what happens.
- **TLS.** The certificate fingerprint, and whether the cert is the default self-signed one.
- **Switches.** Models and firmware for each switch. Gen1, Gen2 or Pro matters for SNMP LLDP. Note any Flex or Ultra switches, which have no SNMP.
- **Neighbours.** Whether the Ruckus APs and the Peplink router show up as LLDP neighbours in the UniFi UI (Port Manager or the device's Ports tab).
- **Uplinks.** Which switch port goes to the Peplink, and whether the controller shows `uplink_remote_port` for it.
- **Availability.** Whether the controller is always powered and running. If it is only run occasionally, SNMP becomes the primary source rather than the fallback.

## Open items

1. **Spec wording, "read-only API key or account".** No read-only API key scope seems to exist. Proposal: keep "read-only account" (a View Only local admin, classic API only), and allow an API key with read-only enforced by Insight (GET allowlist). Record the trade-off in design D9.
2. **SNMP alongside the controller, not only instead of it.** The official API has no per-port error or traffic counters, so a reliable source for them needs SNMP *in addition to* the controller. Today the spec only says SNMP is a fallback "where no controller is reachable or configured". Consider adding "SNMP MAY be configured alongside the controller for port counters".
3. **The "Ruckus AP on port 12" scenario.** From reliable sources Insight can learn that the AP sits on *that switch* (official `uplinkDeviceId`), but not on *that port*. The port comes from the optional classic API (LLDP, or `sw_port`), or from SNMP LLDP-MIB on Pro-class switches. The topology link should carry the source class of its evidence.
4. **"PoE power drops to zero".** On the reliable path this can only be detected as `poe.state` changing from `UP` to `DOWN`, not as watts. Watts, budget and usage are optional-only.
5. **Uplinks.** The uplink port number is optional-only. The official API gives only the parent device's ID, and probably nothing when the parent is the Peplink (**U**).
6. **Version gate.** If the on-board controller is Network 8.x, the legacy self-hosted server or a Cloud Key Gen1, the whole controller adapter is optional, and only SNMP is reliable. D9's "reliable" class for UniFi then doesn't hold. Upgrading or migrating to UniFi OS is the remedy.
7. **Discovery listener.** Passive UBNT discovery needs Insight to bind UDP 10001. That is not covered by D8's capabilities list (no privilege is needed for ports above 1024). Decide whether to include it. An active UDP 10001 probe would be a new active technique, outside D10's TCP-only sweep.
8. **Still to verify at commissioning:**
   - the meaning of `total_max_power`
   - the LLDP shape and whether `system_name` is present on current USW firmware
   - SNMP MIB coverage, including POWER-ETHERNET-MIB, on the on-board models
   - the UniFi OS page title, cert subject and mDNS
   - local rate limits and login throttling
   - client IP coverage without a UniFi gateway
9. **Fixtures.** No samples were captured on board. Replace or supplement the constructed fixtures with real captures (sanitised) at commissioning, and add SNMP walks.

## Sources

Official (Ubiquiti):
- UniFi Network API docs, Getting Started (v11.0.97): https://developer.ui.com/network/v11.0.97/gettingstarted
- OpenAPI spec (downloaded and analysed): https://developer.ui.com/network/v11.0.97/openapi.json. Earlier versions were compared: `.../v9.1.120/openapi.json`, `.../v9.2.87/...`, `.../v9.3.45/...`, `.../v9.4.19/...`, `.../v9.5.21/...`, `.../v10.1.84/...`
- Postman collection (example responses): https://developer.ui.com/network/v11.0.97/postman-collection.json
- Getting Started with the Official UniFi API (help centre; blocked by Cloudflare, read through search snippets only): https://help.ui.com/hc/en-us/articles/30076656117655-Getting-Started-with-the-Official-UniFi-API
- SNMP Monitoring in UniFi Network (help centre; read through search snippets only): https://help.ui.com/hc/en-us/articles/33502980942615-SNMP-Monitoring-in-UniFi-Network
- Site Manager API (cloud; rate limits): https://developer.ui.com/site-manager/v1.0.0/gettingstarted

Open source and community:
- aiounifi (Home Assistant's UniFi library), commit `82d69b8d`: https://github.com/Kane610/aiounifi. See `aiounifi/models/device.py`, `models/client.py`, `network/v1/`, `tests/fixtures.py`, `tests/network/v1/test_devices.py` and `test_clients.py`.
- unpoller/unifi, commit `dbabcae0`: https://github.com/unpoller/unifi. See `unifi.go` (X-API-Key on classic paths, 429 handling), `types.go` (paths), `usw.go`, `examples/usw.json` and `POTENTIAL_FEATURES.md` (integration/v1 since 9.3.43, `/proxy/network/api-docs/integration.json`).
- Art-of-WiFi UniFi-API-client, commit `e1f7f63b`: https://github.com/Art-of-WiFi/UniFi-API-client. See README (versions, ports 443/8443/11443, API key only on UniFi OS, Network 11 notes) and `src/Client.php`.
- Art of WiFi, "UniFi API Authentication: Local Admin vs. API Key vs. Site Manager": https://artofwifi.net/blog/unifi-api-authentication-local-admin-vs-api-key-vs-site-manager
- UniFi best-practices reference (classic login paths, CSRF, 499 MFA): https://github.com/uchkunr/unifi-best-practices
- Home Assistant issue #149762 (API key roles; no read-only keys): https://github.com/home-assistant/core/issues/149762
- Scanopy UniFi types (stat/device sub-tables undocumented; unpoller as the de-facto reference): https://github.com/scanopy/scanopy/blob/main/backend/src/daemon/discovery/integration/unifi/types.rs
- LibreNMS, USW-48-POE SNMP thread (Gen1 vs Pro MIB coverage): https://community.librenms.org/t/ubiquiti-usw-48-poe-detected-as-generic-mips/26072
- Auvik, troubleshooting SNMP for UniFi USW (read through search snippets): https://support.auvik.com/hc/en-us/articles/38543112712084-How-to-troubleshoot-SNMP-for-UniFi-USW-series-switches
- awto-unifi-us48 issue #36 (stock MIB list "expected", unverified): https://github.com/awto-au/awto-unifi-us48/issues/36
- UniFi inform and discovery protocol notes (UDP 10001 TLV): https://github.com/jk-5/unifi-inform-protocol
- Python UBNT discovery (probe `01 00 00 00`): https://github.com/nitefood/python-ubnt-discovery
- Required ports (community summary): https://mkcontroller.com/blog/tutorials/unifi/unifi_required_ports
- Default certificate subject (user-posted `openssl` output): https://community.letsencrypt.org/t/link-letsencrypt-and-my-fqdn-again-unifi/187111 and https://binaryfury.wann.net/?p=1535
- UniFi OS cert path (acme.sh deploy script): https://code.nicolabs.net/nicolabs/acme.sh/src/commit/a94ac63e74d541662df242abf3f41bff3085397d/deploy/unifi.sh
- Network 11 and UniFi OS Server: https://www.virtualizationhowto.com/2026/10/unifi-network-11-is-here-i-migrated-my-home-lab-to-the-new-unifi-os-server/
- Wireshark OUI database: https://www.wireshark.org/download/automated/data/manuf
