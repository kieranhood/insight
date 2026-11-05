# Ruckus Unleashed fixtures

**Only a few lines here come from real devices.** Most files were built by hand from
documented fields. Every file and every syslog line is labelled below. Replace or add to
them once the on-board master AP has been polled (see `docs/integrations/ruckus-unleashed.md`,
"Open items needing on-board verification").

Scenario used by the constructed files: 8 APs, `Sun-Deck` (`2c:c5:d3:aa:bb:07`) offline;
master `Main-Salon` (R750, `10.10.20.11`); WLANs `Guest` and `Crew`; 23 clients in total
(SNMP and the per-AP `num-sta` agree), 6 of them listed in the client file. MAC addresses
use the Ruckus OUI `2C:C5:D3`. Serial numbers and IPs are placeholders.

## Files

| File | Provenance | Notes |
|---|---|---|
| `snmp_master.json` | **Constructed from documented fields.** OIDs and types come from `RUCKUS-UNLEASHED-SYSTEM-MIB` <https://github.com/librenms/librenms/blob/master/mibs/ruckus/RUCKUS-UNLEASHED-SYSTEM-MIB>. Value formats (version string `200.x.y.z build n`, licensed APs 128, max clients 512, 2-letter country code, sysObjectID) copy the LibreNMS captures below. | Values were chosen for the spec scenario: `NumAP` (…15.1.0) = 8, `NumRegisteredAP` (…15.15.0) = 7. **What "registered" means on a real master is unverified.** In every capture we found, the two counts are equal. |
| `snmp_master_librenms_r650.json` | **Copied from** <https://github.com/librenms/librenms/blob/master/tests/snmpsim/ruckuswireless-unleashed_r650.snmprec> (commit `b787b2e`, 2026-11-05). Only the `system` group scalars and the Ruckus enterprise OIDs are kept. The values match the source exactly; LibreNMS had already anonymised them (`192.0.2.10`, MAC `001122334455`, serial `000000000000`). | A real R650 master on Unleashed `200.19.7.11 build 283`, with 4 APs, 4 registered and 11 clients. Note that `sysObjectID` is `0.0.0` on this unit. LibreNMS is GPL-3.0-or-later; this file holds only device-reported values. |
| `syslog_samples.txt` | Mixed. See the per-line table below. | One message per line, **as written by the receiving syslog daemon** (the `<PRI>` header is already stripped). The exact on-the-wire header Unleashed sends is unverified. |
| `aioruckus_aps.json` | **Constructed from documented fields:** the `ApStats` / `ApStatsRadio` TypedDicts in <https://github.com/ms264556/aioruckus/blob/v0.49/aioruckus/ajaxtyping.py>, returned by `RuckusAjaxApi.get_ap_stats()` (<https://github.com/ms264556/aioruckus/blob/v0.49/aioruckus/ruckusajaxapi.py>). Numbers are typed the way aioruckus 0.49 coerces them (`num-sta` int, `uptime` float, radio `channel` int, `airtime-busy` float); other attributes stay strings. | **Unverified:** the `state` values (`Connected`/`Disconnected` are guesses); whether an offline AP is listed by `get_ap_stats()` at all (it is always listed by `get_aps()`); which fields come back at `StatsLevel.L1`; and the units of the `airtime-*` fields (assumed to be percent). |
| `aioruckus_wlans.json` | **Constructed from documented fields:** the `Wlan` TypedDict in <https://github.com/ms264556/aioruckus/blob/v0.49/aioruckus/ajaxtyping.py>, as returned by `get_wlans()` on a session created with `redact_secrets=True` (so `x-passphrase` and other `x-` attributes are dropped). Encryption values come from `WlanEncryption` in <https://github.com/ms264556/aioruckus/blob/v0.49/aioruckus/const.py>. | Cut down to the fields Insight needs. The real response also carries resolved policy objects. |
| `aioruckus_clients.json` | **Constructed from documented fields:** the `Client` TypedDict in <https://github.com/ms264556/aioruckus/blob/v0.49/aioruckus/ajaxtyping.py>, returned by `get_active_clients()`. Field meanings cross-checked against `Station` in <https://github.com/willglynn/ruckus-go/blob/b1b4d54/ruckusweb/stations.go>. | `rssi` is a string and `received-signal-strength` is a float (dBm), following the aioruckus type hints. Band is derived from `radio-type` / `channel`. The real values of `radio-type`, `status` and `auth-method` are unverified. |

## `syslog_samples.txt`, line by line

| Line | Event | Provenance |
|---|---|---|
| 1 | AP join (reason: restart) | **Copied from** a forum post about a 3-AP Unleashed network: <https://forums.servethehome.com/index.php?threads/one-ruckus-r600-restarts-occasionally.37263/> |
| 2 | AP join (reason: heartbeat loss) | **Copied from** the same post |
| 3 | AP reboot (warm boot) | **Copied from** the same post |
| 4 | Radio ON. Not a join, leave or reboot, so it must stay a raw event | **Copied from** the same post |
| 5 | Unrecognisable (`rfmd` netlink noise), must stay a raw event | **Copied from** the same post |
| 6 | Heartbeats lost (precursor of a disconnect) | **Constructed** from the message template `{ap} heartbeats lost` in the Unleashed 200.10/200.13 Syslog Event Message Reference Guides (<https://support.alcadis.nl/Support_files/Ruckus/Unleashed//Manuals/Ruckus%20Unleashed%20200.10/Unleashed-200.10-Syslog-Event-Message-Reference-Guide-RevA-20210526.pdf>), using the `eventd_to_syslog():AP[name@mac]` rendering seen in lines 1 to 3 |
| 7 | AP disconnected ("Lost contact") | **Constructed** from the template `Lost contact with {ap}` in the same guides, using the same rendering. **No verbatim Unleashed line was found.** |
| 8 | AP join after power cycle | **Constructed** from the line 1 format. `AP Restart : power cycle` is a reason string reported on the Ruckus forums. |
| 9 | AP reboot (cold boot) | **Constructed by analogy** with line 3. The `cold boot successfully` wording is a guess. It is implied by the MIB's separate cold-start and warm-start traps and by the `MSG_AP_cold_reboot` event name in the Unleashed config, but no cold-boot line was found. |
