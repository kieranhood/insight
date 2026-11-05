# Ruckus Unleashed integration (task 1.3)

Status: desk research, 2026-11-05. **Nothing here has been checked against the on-board Unleashed network yet.**
Everything marked *Unverified* must be confirmed on board (see "Open items").

Spec: `openspec/changes/add-internet-wifi-monitoring/specs/integrations/ruckus-unleashed/spec.md`.
Design: D9 (Ruckus SNMP reliable 60 s, Ruckus syslog reliable push, Ruckus web via `aioruckus` optional 120 s), D10 (discovery), Risks.

## Summary

- **SNMP (official, reliable).** The Unleashed agent runs on the **master AP** and implements
  `RUCKUS-UNLEASHED-SYSTEM-MIB` under `1.3.6.1.4.1.25053.1.15.1.1.1`. It gives AP count
  (`…15.1.0`), registered AP count (`…15.15.0`), authorised clients (`…15.2.0`), all clients
  (`…15.30.0`), and the master's name, IP, MAC, model, serial, firmware, uptime, CPU and memory.
  Two real captures (R650 and R770 masters on 200.19) confirm these OIDs answer.
  v2c and v3 are both supported.
- **Correction to the brief:** a **per-AP SNMP table does exist in the MIB**:
  `ruckusUnleashedWLANAPEthStatusTable` (`1.3.6.1.4.1.25053.1.15.2.1.1.2.8`). It is indexed by
  AP MAC and Ethernet port, and holds the port's phy status, speed and duplex. Whether it is
  populated on 200.x is **Unverified**: no public walk we found contains it. If it is populated,
  it is a reliable per-AP presence signal. Per-AP radio, channel and client data has no SNMP
  table in the Unleashed MIBs.
- **SNMP traps exist** (`RUCKUS-UNLEASHED-EVENT-MIB`): AP join, AP lost, AP cold start,
  AP warm start, radio on/off, and master AP switch. Insight's design does not use traps today.
- **Syslog (official, reliable).** Set under *Admin & Services > System > System Info > Log
  Settings*, or with the CLI `config > system > syslog`. **The destination port cannot be
  changed. It is fixed at UDP 514** (community reports; the CLI shows 514 but offers no port
  command; Ruckus logged a feature request). **Insight must listen on UDP 514**, or the Peplink must
  redirect it with a destination NAT. Events come from `eventd_to_syslog()` in the form
  `AP[<name>@<mac>] …`. We have **verbatim** Unleashed lines for AP join and AP warm boot.
  **No verbatim line was found for AP disconnect/lost contact.** Its wording comes from the Ruckus
  message reference template (`Lost contact with {ap}`), and its exact form is *Unverified*.
- **Web/AJAX via `aioruckus` (unofficial, optional).** v0.49 (PyPI, 2026-09-15), 0BSD licence,
  Python ≥ 3.9, actively maintained. It is also used by Home Assistant's `ruckus_unleashed`
  integration. It covers everything the optional requirement asks for: per-AP name, model, MAC, IP,
  firmware, state, channels, per-radio airtime/busy (channel utilisation), WLANs/SSIDs, and
  clients with their AP, SSID, radio type/channel (band) and RSSI.
  **Cautions:** it contains write methods (`do_restart_ap`, `do_block_client`,
  `do_delete_wlan`, …). By default it **returns WLAN passphrases in clear**
  (`redact_secrets=False`). It sends the login password in the URL query string. Its default
  HTTP session disables TLS verification.
- **Master moves.** Any AP can become master (there is a "master AP switch" trap). Insight should
  target the Unleashed **management interface IP**, if one is configured, rather than one AP's
  address. If none is configured, Insight should re-find the master.

## Interfaces

| Interface | Official? | Insight class | Auth | Notes |
|---|---|---|---|---|
| SNMP agent on master (`RUCKUS-UNLEASHED-SYSTEM-MIB`, `-WLAN-MIB`) | Yes. MIBs published by Ruckus, mirrored in LibreNMS | **reliable** | v2c read-only community, or v3 user (MD5/SHA auth, DES/AES privacy) | Scalars only, except the per-AP Ethernet table (population *Unverified*). The config has separate RO and RW communities/users; Insight uses only RO. |
| Syslog (UDP) | Yes. Documented in the Unleashed admin guide and the Syslog Event Message Reference Guide (one per release) | **reliable** (push) | None (UDP; source address only) | Fixed port 514. Facility "Keep Original" or local0 to 7. Priority filter. "Inherit remote syslog server for APs" makes member APs send their own logs too. |
| SNMP traps (`RUCKUS-UNLEASHED-EVENT-MIB`) | Yes | not in design (possible future reliable source) | v2c community or v3 trap user | Would need a UDP 162 listener. Per-event switches exist in the config (`MSG_AP_joined`, `MSG_AP_lost`, `MSG_AP_cold_reboot`, `MSG_AP_warm_reboot`). |
| Web UI AJAX (`/admin/_cmdstat.jsp`, `/admin/_conf.jsp`) via `aioruckus` | **No.** Undocumented; reverse-engineered | **optional** | Web admin username/password (session cookie + CSRF token) | XML over HTTPS on 443. Mixes reads and writes. Insight must allow-list read methods (below). |
| ICMP to each AP | n/a | **reliable** (probes) | None | Needs AP IPs: from `aioruckus`, from UniFi neighbours (*Unverified* whether LLDP carries the IP), or from manual entry. |
| SSH CLI | Yes (CLI reference guide) | not used | Admin account | Mentioned only for setup. `scrapli_community` has a driver, but there are no parsers. |

### Read-only `aioruckus` allow-list

Only these `RuckusAjaxApi` methods should ever be called. Everything named `do_*` writes, and so
does `get_backup()` in effect (it makes a full configuration export that includes secrets). These
are excluded.

| Method | Request sent | Use |
|---|---|---|
| `get_system_info()` | `getconf comp='system'` (identity, sysinfo, port, unleashed-network) | master name, model, serial, version, uptime |
| `get_ap_stats(StatsLevel.L1)` | `getstat comp='stamgr' <ap LEVEL='1'/>` | per-AP status, radios, channels, airtime |
| `get_aps()` | `getconf comp='ap-list'` | configured AP list (includes offline APs), approved flag, version |
| `get_active_clients(StatsLevel.L1)` | `getstat comp='stamgr' <client LEVEL='1'/>` | clients |
| `get_vap_stats()` | `getstat comp='stamgr' <vap LEVEL='1'/>` | per-AP, per-radio SSID/BSSID, channel, client count (1 request) |
| `get_wlans()` | `getconf comp='wlansvc-list'` **plus 7 policy lookups** | SSIDs. Poll rarely. Always use `redact_secrets=True`. |
| `get_ap_events()` / `get_events(limit=…)` | `getstat comp='eventd' <xevent …/>` | optional pull of the same AP join/lost events as syslog (gap-fill after an Insight restart) |

## Setup steps for an engineer

All of this is on the **master AP web UI** (`https://<master or management IP>/`). Menu names are
from the 200.x documentation and community posts, and should be checked on board.

1. **Management interface (recommended).** *Admin & Services > System > IP Settings > Management
   Interface*: give the Unleashed network a fixed management IP, so Insight always reaches the
   current master. Record this IP in Insight as the Ruckus host. *Unverified:* whether SNMP answers
   on the management IP, or only on the master's own IP.
2. **SNMP (read-only).** *Admin & Services > Administer > Network Management*.
   - Preferred: the **SNMPv3 Agent** tab. Tick *Enable SNMPv3 Agent*. Under **Read Only**, set a
     user name, Authentication **SHA** with an 8 to 32 character passphrase, and Privacy **AES**
     with a passphrase. Leave the Read-Write user empty/unused, if the UI allows it (*Unverified*).
   - Or: the **SNMPv2 Agent** tab. Tick *Enable SNMP Agent* and set a strong
     **RO community**. The page also has an RW community field (the stored config always has
     `ro-community` and `rw-community`). Set the RW community to a long random value that is
     never written down for Insight. *Unverified* whether it can be blanked.
   - Do **not** enable traps unless Insight later adds a trap receiver.
   - Optionally restrict management access by ACL to Insight's IP (*Admin & Services >
     Administer > Management ACL*, if present on the build).
3. **Syslog.** *Admin & Services > System > System Info > Log Settings*:
   - Tick **Enable reporting to remote syslog server at** and enter Insight's IP. **The port is
     always UDP 514.**
   - **Event Log Level / Priority:** "Show More"/"All" or at least **Warning**. AP join is
     logged at *Warning*, lost contact at *Critical*, and heartbeats lost at *Warning*. Info-level
     messages are dropped if the priority is set above them.
   - **Facility:** "Keep Original" is fine. If you choose `local0` to `local7`, note which one.
   - Optional: **Inherit remote syslog server for APs**. This makes each member AP send its own
     syslog to Insight. It is useful for reboots that the master cannot see, but it means messages
     arrive from many source IPs.
   - CLI equivalent: `config` → `system` → `syslog` → `server <insight-ip>`, plus `facility`,
     `priority`, `ap-facility` and `ap-priority`. There is no `port` command.
4. **Web account for the optional source.** Create a dedicated account. Do not reuse the
   super-admin account.
   - *Admin & Services > System > Roles*: create role "Insight-Monitor". Tick **Allow Unleashed
     Administration** and choose **Monitoring Admin** (stored as `admin-priv="ro"`).
   - *Admin & Services > System > Users*: create user `insight` with that role.
   - *Unverified:* that `aioruckus` reads AP stats, clients and `getconf` lists with a
     Monitoring-Admin user. Home Assistant only says the user "can log in to the web dashboard and
     view AP, WLAN, and Client information". It may be that only the single local super-admin can log in to
     `/admin/login.jsp`, and role users need an AAA server. Test this on board first.

## Data availability

Legend: **A** = Available, **P** = Partially, **N** = Not available, **U** = Unverified (documented
or in the source code, but not seen on a real device). OIDs are relative to
`1.3.6.1.4.1.25053.1.15.1.1.1` (`SYS`) unless they are written in full.

| Spec requirement / item | SNMP (master) | Syslog | `aioruckus` (optional) | Other |
|---|---|---|---|---|
| **R1** Number of APs known | **A** `SYS.15.1.0` ruckusUnleashedSystemStatsNumAP "Number of AP" (captured) | – | **A** `len(get_aps())` | – |
| **R1** Number of APs registered | **A/U** `SYS.15.15.0` NumRegisteredAP "Number of registered AP". It answers in captures, but **its meaning compared with NumAP is unverified.** In every capture the two counts are equal. Possibly NumAP = connected and Registered = approved, or the other way round. | – | **A** `get_aps()` `approved`, and `get_ap_stats()` `state`/`registered` | – |
| **R1** Total connected clients | **A** `SYS.15.2.0` NumSta "authorized client devices"; `SYS.15.30.0` AllNumSta "All client devices" (both captured) | – | **A** `len(get_active_clients())` | – |
| **R1** Master name | **A** `SYS.1.1.0` (also sysName `1.3.6.1.2.1.1.5.0`) | hostname in syslog header (*U*) | **A** `get_system_info()["identity"]["name"]` | – |
| **R1** Master model | **A** `SYS.1.9.0` (e.g. `R650`); sysDescr `Ruckus Wireless R650` | – | **A** `sysinfo.model` | – |
| **R1** Master MAC / IP | **A** `SYS.1.3.0` (6-octet string), `SYS.1.2.0` (IpAddress) | – | **A** `port.mac`, `port.ip` | – |
| **R1** Master firmware | **A** `SYS.1.18.0` e.g. `200.19.7.11 build 283` | – | **A** `sysinfo.version` | – |
| **R1** Master serial | **A** `SYS.1.15.0` (shows `000000000000` in the anonymised captures) | – | **A** `sysinfo.serial` | – |
| **R1** Master uptime | **A** `SYS.1.8.0` TimeTicks; sysUpTime `1.3.6.1.2.1.1.3.0` | – | **A** `sysinfo.uptime` | – |
| (extra) Master CPU / memory % | **A** `SYS.15.13.0`, `SYS.15.14.0` | – | **A** `sysinfo.cpu_busy`, `mem_free` | – |
| (extra) Licensed APs / max clients / country | **A** `SYS.1.12.0`, `SYS.1.13.0`, `SYS.1.20.0` | – | – | – |
| (extra) Per-AP Ethernet link status | **U** `1.3.6.1.4.1.25053.1.15.2.1.1.2.8.1.{1 mac, 2 port, 5 ifname, 8 phy up(1)/down(2), 9 speed Mb/s, 10 duplex, 11 label}.<mac 6 octets>.<port>` | – | **A** `get_ap_stats()` `lan-port`, `port` | UniFi port state |
| **R1 scenario** 8 known, 7 registered → "1 AP not registered" | **A/U** the computation is trivial, but see the meaning caveat above | – | – | – |
| **R2** Receive Unleashed syslog | – | **A** UDP **514 fixed** | – | – |
| **R2** AP join | – | **A** verbatim: `AP[name@mac] joins with uptime [n] s and last disconnected reason [r]` | **A** `get_ap_events()` | SNMP trap `…2.15.1.1` (not used) |
| **R2** AP leave / disconnect | – | **U** template `Lost contact with {ap}` (Critical); precursor `{ap} heartbeats lost` (Warning). No verbatim line found. | **A/U** `get_ap_events()`; message text *U* | trap `…2.15.1.5` APLost |
| **R2** AP reboot | – | **A** (warm) verbatim: `AP[name@mac] warm boot successfully,last reboot reason [r].`; **U** (cold). A reboot can also be inferred from a join with a small uptime and an `AP Restart : …` reason. | **A** `get_ap_stats()` `last-reboot-reason`, reboot counters | traps `…2.15.1.31` / `.32` |
| **R2** Unrecognised → raw event | – | **A** (receiver-side behaviour). Plenty of other lines exist (radio on/off, client join, `rfmd` noise). | – | – |
| **R3** Per-AP reachability | **N** (except via the *U* per-AP Ethernet table) | – | – | **A** ICMP. IPs from `aioruckus`/manual. That APs answer ping is *U* but normal. |
| **R4** AP name | – | – | **A** `devname` | UniFi LLDP sysName (*U*) |
| **R4** AP model | **N** (master only) | – | **A** `model` | – |
| **R4** AP MAC | **U** (per-AP Ethernet table index) | **A** in `AP[name@mac]` | **A** `mac` | UniFi LLDP chassis/port MAC (*U*) |
| **R4** AP IP | – | – | **A** `ip` | – |
| **R4** AP firmware | – | – | **A** `firmware-version` (stats); `version` (config) | – |
| **R4** AP status | – | join/lost events | **A/U** `state` (values *U*); compare `get_aps()` with `get_ap_stats()` | – |
| **R4** AP channels | – | – | **A** `radio[].channel`, `radio[].channelization`, `channel-11ng`, `channel-11na` | – |
| **R4** Channel utilisation | – | – | **P/U** `radio[].airtime-busy`, `airtime-total`, `airtime-rx`, `airtime-tx`. Units and the fetch level are *U* (we assume percent at L1). `noisefloor` and `phyerr` are also present. | – |
| **R4** Wi-Fi networks (SSID) | **N** | – | **A** `get_wlans()` `name`, `ssid`, `encryption`, `vlan-id`; `get_vap_stats()` per-AP `ssid`/`bssid` | – |
| **R4** Client's AP | – | (client join lines exist, not required) | **A** `ap` (MAC), `ap-name` | – |
| **R4** Client's SSID | – | – | **A** `ssid`, `wlan`, `wlan-id` | – |
| **R4** Client band | – | – | **A/U** derive from `radio-type` (`11ng` → 2.4 GHz) and `channel` (≤14 → 2.4 GHz, 36 to 177 → 5 GHz; 6 GHz numbering overlaps, so 6 GHz needs `radio-type`, *U*) | – |
| **R4** Client signal | – | – | **A** `rssi` (string), `received-signal-strength` (dBm float), `noise-floor`, `rssi-level`; `avg-rssi` only at L2 | – |
| **R4 failure** Bad data → only optional marked unavailable | n/a | n/a | aioruckus raises `AuthenticationError`, `ConnectionError`, `ConnectionRefusedError` (master rebuilding/wizard), `RuntimeError` (empty reply), or XML parse errors. Insight must catch them all. | – |
| **R5** Populate APs from optional source | – | – | **A** `get_aps()` (all configured APs, including offline) | – |
| **R5** Otherwise from UniFi neighbours and manual entry | – | – | – | **U** (task 1.2): Ruckus APs advertising LLDP (name and MAC) on UniFi ports. Ruckus AP LLDP is believed to be on by default; unconfirmed for Unleashed 200.x. |

## Syslog message patterns

Messages are produced by the master's event daemon and prefixed with `eventd_to_syslog():`.
The program/tag is `syslog`. An AP is rendered `AP[<name>@<mac>]`, with values in square
brackets. Lines as stored by a receiving syslog daemon (verbatim, from an Unleashed network):

```
Apr 15 10:24:13 Ruckus1 syslog: eventd_to_syslog():AP[Ruckus2@2c:c5:d3:00:9a:70] joins with uptime [110] s and last disconnected reason [AP Restart : target fail detect]
Apr 15 10:24:16 Ruckus1 syslog: eventd_to_syslog():AP[Ruckus3@d4:68:4d:22:35:00] joins with uptime [2736005] s and last disconnected reason [Heartbeat Loss]
Apr 15 10:24:18 Ruckus1 syslog: eventd_to_syslog():AP[Ruckus2@2c:c5:d3:00:9a:70] warm boot successfully,last reboot reason [target fail detect].
Apr 15 10:25:21 Ruckus1 syslog: eventd_to_syslog():Radio [5G] of AP[Ruckus2@2c:c5:d3:00:9a:70] is ON
Apr 15 10:24:20 Ruckus1 rfmd[461]: Netlink - RTM_DELLINK
```

**Constructed, not captured** (from the Ruckus reference-guide templates `{ap} heartbeats lost`
and `Lost contact with {ap}`, rendered like the lines above):

```
Nov  5 09:58:02 Unleashed-Yacht syslog: eventd_to_syslog():AP[Bridge-Deck@2c:c5:d3:aa:bb:08] heartbeats lost
Nov  5 09:59:12 Unleashed-Yacht syslog: eventd_to_syslog():Lost contact with AP[Bridge-Deck@2c:c5:d3:aa:bb:08]
Nov  5 10:03:44 Unleashed-Yacht syslog: eventd_to_syslog():AP[Bridge-Deck@2c:c5:d3:aa:bb:08] cold boot successfully,last reboot reason [power cycle].
```

On the wire, a `<PRI>` header comes first (a ZoneDirector example shows `<134>`, i.e.
local0.info). Whether Unleashed sends an RFC 3164 hostname is *Unverified*, so the patterns use
`search`, not anchored `match`.

Proposed Python regexes (tested against `tests/fixtures/ruckus/syslog_samples.txt`):

```python
MAC = r"(?P<ap_mac>(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2})"
AP = r"AP\[(?P<ap_name>[^\]]*?)@" + MAC + r"\]"   # lazy name: tolerates '@' in AP names

AP_JOINED = re.compile(
    r"eventd_to_syslog\(\):" + AP +
    r" joins with uptime \[(?P<uptime_s>\d*)\] s"
    r"(?: and last disconnected reason \[(?P<reason>[^\]]*)\])?")
AP_DISCONNECTED = re.compile(r"eventd_to_syslog\(\):Lost contact with " + AP)          # Unverified wording
AP_REBOOTED = re.compile(
    r"eventd_to_syslog\(\):" + AP +
    r" (?P<boot>warm|cold) boot successfully,\s*last reboot reason \[(?P<reason>[^\]]*)\]")  # 'cold' Unverified
```

- `heartbeats lost` is deliberately **not** treated as a leave event. It often clears without a
  disconnect. It stays a raw event. If "Lost contact" proves to be worded differently on board,
  the heartbeat line is a fallback leave signal.
- A join whose reason starts with `AP Restart` (or whose uptime is under about 300 s) can also
  be recorded as "AP rebooted". Rule authors should de-duplicate this against the boot line.
- Name the AP by MAC (a stable key) and keep `ap_name` as a label.
- Other known reasons: `Heartbeat Loss`, `AP Restart : power cycle`, `AP Restart : application, reboot`,
  `AP Restart : target fail detect`, watchdog. Treat `reason` as free text.
- Line 4 (radio on) and line 5 (`rfmd`) must be stored raw with no finding (spec scenario).

## Polling & limits

- **SNMP, 60 s:** about 20 scalars in one GET (or 2 to 3 small GETs). This is negligible load.
  Use a 2 s timeout with 1 retry. Counters `SYS.15.5` to `.21` are Counter64, so use v2c or v3.
- **Syslog:** push. Volume is low unless AP inheritance and Info level are on, when client
  join/leave lines can arrive at several per minute on a busy charter. The receiver must
  rate-limit raw-event storage.
- **`aioruckus`, 120 s:** keep one logged-in session and reuse it. aioruckus logs in again by
  itself when it gets a 302. Login costs 3 to 4 requests (redirect discovery, login, CSRF,
  cluster check), each with a 3 s timeout. A cycle of `get_ap_stats` + `get_active_clients` +
  `get_vap_stats` is 3 requests. `get_wlans()` costs 8 requests, so poll it about every 15 min,
  or derive SSIDs from `get_vap_stats()`. `get_aps()` and `get_system_info()` are about 1 request
  each, so poll them every 5 to 15 min.
- The master is an AP with a small CPU (master CPU 3 to 29% in captures). No published rate limit
  exists. Do not go below 60 s for AJAX. *Unverified:* whether Insight's session counts against
  a concurrent-admin limit or logs out an engineer using the same account. Use a dedicated account.
- Default aioruckus client timeout is 10 s total. Pass `timeout=` per call. Data-collection's
  per-adapter timeout still applies.
- **Fail-safe:** if the master is mid-election or rebuilding, aioruckus raises
  `ConnectionRefusedError` ("temporary"). Treat this as optional-source unavailable, not as a fault.

## Compatibility & licensing

| Item | Finding |
|---|---|
| Unleashed firmware | MIB OIDs confirmed on 200.14 (R850), 200.15 (T300) and 200.19 (R650, R770) by LibreNMS captures. `sysObjectID` varies (`…25053.3.1.5.20` > 200.14, `…3.1.5.15` ≤ 200.14, `0.0.0` on one R650, `…3.1.4.125` on an R770), so it cannot be relied on. |
| aioruckus | v0.49, released 2026-09-15 on PyPI. Last commit 2026-09-15 (tests on Python 3.15). "Compatible with all Ruckus Unleashed versions, and ZoneDirector 9.10 onwards." Auto-detects Unleashed, ZD, SmartZone and Ruckus One. |
| Python | `requires-python >=3.9`. Insight is 3.12, which is fine. |
| Dependencies | `aiohttp`, `cryptography`, `xmltodict` (plus `typing_extensions` < 3.12). **aiohttp is new to Insight** (Insight uses httpx). Pin it. |
| Licence | aioruckus: **0BSD** (no attribution needed; compatible with closed distribution). ruckus-go (reference only): MIT. LibreNMS MIB/test data: GPL-3.0; Insight only uses the OID numbers. |
| Maintenance | Single main maintainer (ms264556), very active, used by Home Assistant core. Risk: an undocumented API can break after firmware updates. Pin the version and keep fixtures per firmware. |
| Security notes | (1) Login is `GET /admin/login.jsp?username=…&password=…`, so credentials travel in the query string (inside TLS, but may be logged on the AP). (2) `create_legacy_client_session()` sets `CERT_NONE` and `DEFAULT` ciphers. Insight should pass its own `aiohttp.ClientSession` with the master's self-signed cert pinned. (3) `redact_secrets=True` is mandatory. Otherwise `get_wlans()` returns PSKs, because `getconf` is sent with `DECRYPT_X='true'`. (4) Station records may carry `wpa-passphrase` (DPSK). Drop it in the adapter. |

## Discovery signatures

| Signature | Value | Strength |
|---|---|---|
| MAC OUI (IEEE, "Ruckus Wireless", 100 MA-L blocks as of 2026-11-05) | `00:13:92 00:1D:2E 00:1F:41 00:22:7F 00:24:82 00:25:C4 00:33:58 00:E6:3A 04:4F:AA 0C:F4:D5 10:F0:68 18:4B:0D 18:7C:0B 1C:3A:60 1C:B9:C4 20:58:69 24:79:2A 24:C9:A1 28:B3:71 2C:5D:93 2C:AB:46 2C:C5:D3 2C:E6:CC 30:87:D9 34:15:93 34:20:E3 34:8F:27 34:FA:9F 38:45:3B 38:FF:36 3C:46:A1 40:B8:2D 44:1E:98 4C:B1:CD 50:A7:33 54:3D:37 54:EC:2F 58:93:96 58:B6:33 58:FB:96 5C:83:6C 5C:DF:89 60:D0:2C 68:92:34 68:FD:E8 6C:AA:B3 70:32:0C 70:47:77 70:B2:58 70:CA:97 74:31:7E 74:3E:2B 74:91:1A 78:9F:6A 80:03:84 80:BC:37 80:F0:CF 84:18:3A 84:23:88 8C:0C:90 8C:7A:15 8C:FE:74 90:3A:72 94:B3:4F 94:BF:C4 94:F6:65 A8:0B:FB AC:67:06 AC:DE:01 B0:7C:51 B4:79:C8 B4:E5:3E BC:9C:8D C0:8A:DE C0:C5:20 C0:C7:0A C4:01:7C C4:10:8A C8:03:F5 C8:08:73 C8:84:8C C8:A6:08 CC:1B:5A CC:2D:D2 D0:4F:58 D4:68:4D D4:BD:4F D4:C1:9E D8:38:FC DC:AE:EB E0:10:7F E8:1D:A8 E8:FC:5F EC:58:EA EC:8C:A2 F0:3E:90 F0:6F:CE F0:B0:52 F8:E7:1E FC:5C:45` | strong for "Ruckus device". It does not tell master from member (every AP matches). Some newer units may use CommScope OUIs (*U*). |
| Open ports | TCP 443 (web UI/AJAX), TCP 80 (redirects to HTTPS), TCP 22 (CLI) on every AP. Members redirect the web UI to the master. UDP 161 on the master. UDP 12222/12223 (AP to master control, LWAPP-style), not probed. | weak alone |
| HTTP behaviour | `GET /` → `302` to `/admin/login.jsp` (Unleashed and ZD 9.x); on a member, a redirect first to the master's `/`. `index.html` or `wizard.jsp` in the redirect means rebuilding or the setup wizard. | strong (the master is the host that redirects to its *own* `/admin/login.jsp`) |
| HTTP page title | *Unverified.* Not in any source we read. Capture it on board. | – |
| TLS certificate subject | Default self-signed cert. The firmware's default DN file (`/etc/airespider/certs/default_dn`) contains **`unleashed.ruckuswireless.com`**, so the default cert CN is very likely that (*U*: the test backups had a replaced cert). | medium |
| SNMP sysDescr (not used in discovery, per D10) | `Ruckus Wireless <model>` (e.g. `Ruckus Wireless R650`) | – |
| mDNS / SSDP | None found for the Unleashed master itself (its Bonjour gateway relays *client* services). *Unverified.* Listen on board. | – |

## Open items needing on-board verification

1. Meaning of `NumAP` (`SYS.15.1.0`) compared with `NumRegisteredAP` (`SYS.15.15.0`): power one AP off and read both.
   This decides whether the spec's "8 known / 7 registered" scenario is what really happens. If NumAP drops
   instead, Insight must compare against the inventory count.
2. Walk `1.3.6.1.4.1.25053.1.15.2` to see whether the per-AP Ethernet table is populated. If it is, it gives a reliable
   per-AP MAC and up/down signal over SNMP. Also check whether member APs answer SNMP at all.
3. Whether SNMP and the web UI answer on the **management interface IP**, and what happens to both
   during a master switch.
4. Capture real syslog lines (with `tcpdump -A udp port 514`) for: AP power-off (lost contact /
   heartbeats lost), AP power-on (join), AP reboot from the UI (warm boot) and power-cycle (cold
   boot?). Note the `<PRI>`/header format and the source IP (master compared with member when
   inherit is on).
5. Confirm there is no port setting on the build in use (UI and CLI `syslog` context), so that UDP 514 is final.
6. Whether a **Monitoring Admin** role user can log in with aioruckus and read `get_ap_stats`,
   `get_active_clients`, `get_aps` and `get_wlans`. Also whether Insight's session disturbs engineers' sessions.
7. Real `get_ap_stats(L1)` output: `state` values; whether offline APs are listed; whether `radio[]`
   with `airtime-*` comes back at L1 or needs L2; airtime units (percent compared with raw). Replace
   `tests/fixtures/ruckus/aioruckus_*.json` with redacted captures.
8. Client `radio-type` values, including 6 GHz (`11ax`/`11be`?), for the band mapping.
9. Web page title and TLS cert subject/issuer of the master for the discovery table.
10. Whether Ruckus APs send LLDP to the UniFi switches (task 1.2) and what name/MAC they advertise
    (Ethernet MAC compared with the AP's base MAC).
11. Firmware version on board (200.x), recorded in the fixtures.

## Sources

- aioruckus source, v0.49: <https://github.com/ms264556/aioruckus> (README, `aioruckus/ajaxsession.py`,
  `unleashedsession.py`, `ruckusajaxapi.py`, `ruckusconfigurationapi.py`, `ajaxtyping.py`, `const.py`,
  `utility.py`, `unleashedtojson.py`, `tests/`, `pyproject.toml`, `LICENSE`)
- aioruckus test config backups (Unleashed 200.7/200.15/200.19: `system.xml` `<log … remote-log-server>`,
  `<snmp>`, `<snmpv3>`, `<event-switch MSG_AP_*>`, `default_dn`): <https://github.com/ms264556/aioruckus/tree/master/tests/live/backups>
- aioruckus on PyPI: <https://pypi.org/project/aioruckus/> (JSON API `https://pypi.org/pypi/aioruckus/json`)
- ruckus-go (AJAX request/response structures): <https://github.com/willglynn/ruckus-go>
- Unleashed MIBs (mirrored by LibreNMS): <https://github.com/librenms/librenms/tree/master/mibs/ruckus>
  (`RUCKUS-UNLEASHED-SYSTEM-MIB`, `RUCKUS-UNLEASHED-WLAN-MIB`, `RUCKUS-UNLEASHED-EVENT-MIB`, `RUCKUS-ROOT-MIB`)
- LibreNMS SNMP captures: <https://github.com/librenms/librenms/tree/master/tests/snmpsim> (`ruckuswireless-unleashed*.snmprec`)
  and OS definitions <https://github.com/librenms/librenms/blob/master/resources/definitions/os_detection/ruckuswireless-unleashed.yaml>
- Netdata Ruckus Unleashed SNMP profile: <https://learn.netdata.cloud/docs/network-performance-monitoring/device-metrics/integrations/ruckus-unleashed>
- Unleashed Syslog Event Message Reference Guides (200.10, 200.12, 200.13, 200.15, 200.16; mirror, now behind a login page; content seen only via search excerpts):
  <https://support.alcadis.nl/Support_files/Ruckus/Unleashed//Manuals/Ruckus%20Unleashed%20200.10/Unleashed-200.10-Syslog-Event-Message-Reference-Guide-RevA-20210526.pdf>,
  <https://support.alcadis.nl/Support_files/Ruckus/Unleashed/Manuals/Ruckus%20Unleashed%20200.13/Unleashed-200.13-Syslog-Event-Message-Reference-Guide-RevA-20221031.pdf>
- Unleashed 200.8 "Enabling Log Delivery to Remote Syslog Server": <https://docs.ruckuswireless.com/unleashed/200.8/GUID-ABFF6565-73CF-4D8A-B287-1A3C3F9473A0.html> (search excerpt only; the site returned 403)
- Unleashed 200.2 SNMPv3: <https://docs.ruckuswireless.com/unleashed/200.2/t-EnableSNMPv3.html>; SNMP traps 200.5: <https://docs.ruckuswireless.com/unleashed/200.5/t-EnableSNMPTrap.html> (search excerpts only)
- Ruckus forum, "Ruckus Unleashed Syslog custom port" (port fixed at 514; feature request; DNAT workaround): <https://community.ruckuswireless.com/t5/Unleashed/Ruckus-Unleashed-Syslog-custom-port/m-p/44576> (search excerpts; login wall)
- Ruckus forum, Unleashed syslog to remote server / CLI syslog context: <https://community.ruckuswireless.com/t5/Unleashed/Does-Unleashed-AP-system-log-can-redirect-to-remote-log-server/m-p/16540> (search excerpts)
- Verbatim Unleashed syslog lines: <https://forums.servethehome.com/index.php?threads/one-ruckus-r600-restarts-occasionally.37263/>
- Ruckus forum thread on "joins with uptime … last disconnected reason": <https://community.ruckuswireless.com/t5/To-Be-Moved/Seeing-almost-constant-quot-joins-with-uptime-xxxxxx-s-and-last/td-p/9367>
- Heartbeats lost KB: <https://support.ruckuswireless.com/articles/000003945>
- Auvik, configure syslog on Unleashed (menu path, "Inherit remote syslog server for APs"): <https://support.auvik.com/hc/en-us/articles/360048571671-How-to-configure-syslog-on-a-Ruckus-Unleashed-controller> (search excerpt; 403 on fetch)
- Unleashed management interface (forum): <https://community.ruckuswireless.com/t5/Unleashed/R310-Question-about-the-management-interface/m-p/52422>
- Unleashed roles / Monitoring Admin (guide): <https://nguvu.org/wi-fi/ruckus-unleashed-setup/>
- Home Assistant `ruckus_unleashed` integration: <https://www.home-assistant.io/integrations/ruckus_unleashed/>
- Unleashed default self-signed certificate (forum): <https://community.ruckuswireless.com/t5/Unleashed/SSL-Certificates-for-R600-Unleashed-where-to-buy/m-p/18442>
- IEEE OUI registry: <https://standards-oui.ieee.org/oui/oui.csv>
