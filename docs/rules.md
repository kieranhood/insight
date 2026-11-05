# Diagnostic rules

Generated from the rule catalogue by `scripts/gen_rules_doc.py`; do not edit by hand.

Every finding has a confidence: **confirmed** (evidence directly shows it), **probable** (evidence points to it, other causes possible), **insufficient information** (something is wrong, cause unknown) or **monitoring failure** (Insight cannot see the system). Crew wording is checked automatically: no addresses, port numbers or technical terms, and hedged wording unless confirmed. Thresholds are settings an engineer can change.

## `internet_unavailable`: Internet unavailable

Every internet path is down, according to the router and/or Insight's own checks.

- **Severity:** critical
- **Needs:** none. **Optional:** none
- **Opens after:** 60 s; **resolves after clear for:** 120 s
- **Absorbs:** `failover_to_backup`, `primary_link_degraded`, `all_paths_degraded`, `dns_failure`, `weak_cellular_signal`
- **Thresholds:** `probe_failure_threshold` = 3
- **Confidence:** **Confirmed** when the router reports every enabled WAN link down or failing its health check. **Probable** when only Insight's checks fail while the router still shows a link up (the cause may be beyond the router).

**Example (confirmed)**: *Internet unavailable*

> Crew: There is no internet connection on board at the moment. All of the yacht's connections (Starlink and Cellular) are down. Guests and crew will not be able to get online. Please let the ETO or 50N support know.
>
> Engineer: All WAN links are down or failing health checks, and Insight's internet checks fail.

**Example (probable)**: *Internet unavailable*

> Crew: The internet appears to be unavailable: Insight's own checks can't reach the internet, although the router still shows a connection. Guests and crew may not be able to get online. Please let the ETO or 50N support know.
>
> Engineer: Insight's internet checks fail on every target, but the router reports at least one link connected. The cause may be upstream of the router.

## `failover_to_backup`: Running on the backup internet connection

The main (highest-priority) WAN link is not usable and another link carries the traffic.

- **Severity:** warning
- **Needs:** wan. **Optional:** none
- **Opens after:** 30 s; **resolves after clear for:** 120 s
- **Absorbs:** `primary_link_degraded`
- **Confidence:** **Confirmed**: the router reports the highest-priority link unusable and a lower-priority link in use.

**Example (confirmed)**: *Running on the backup internet connection*

> Crew: The main internet connection (Starlink) is unavailable, so the yacht has switched to its backup mobile data connection. The internet still works, but it may be slower and uses mobile data, which can be expensive. Nothing needs to be done on board: the yacht will switch back automatically when Starlink recovers.
>
> Engineer: Starlink is disconnected; traffic has failed over to Cellular.

## `primary_link_degraded`: Internet slow or dropping out

The link in use loses packets or responds slowly, measured by Insight's own checks.

- **Severity:** warning
- **Needs:** wan, probes. **Optional:** dish
- **Opens after:** 120 s; **resolves after clear for:** 300 s
- **Thresholds:** `threshold_degraded_loss_pct` = 5.0, `threshold_degraded_latency_ms` = 600.0
- **Confidence:** **Insufficient information**: degradation is measured on the link in use, but no source evidences why. If the dish reports obstruction, the obstruction finding replaces this one.

**Example (insufficient information)**: *Internet slow or dropping out*

> Crew: The internet is working but is slow or dropping out at times on the Starlink connection. Pages may take a long time to load and calls may break up. Insight can't yet tell why, because detailed information from the Starlink dish isn't available. Nothing needs to be done on board unless it continues; the ETO may want to look into it.
>
> Engineer: Starlink is degraded: 12.0% loss, 950.0 ms round trip, web checks slower than normal. Cause could not be determined because detailed dish data is unavailable.

**Example (insufficient information)**: *Internet slow or dropping out*

> Crew: The internet is working but is slow or dropping out at times on the Starlink connection. Pages may take a long time to load and calls may break up. Insight can't yet tell why. Nothing needs to be done on board unless it continues; the ETO may want to look into it.
>
> Engineer: Starlink is degraded: 7.0% loss, 700.0 ms round trip. Cause could not be determined.

## `all_paths_degraded`: Every internet connection is struggling

Two or more connected WAN links all show high latency or loss at the same time.

- **Severity:** warning
- **Needs:** wan. **Optional:** none
- **Opens after:** 120 s; **resolves after clear for:** 300 s
- **Absorbs:** `primary_link_degraded`
- **Thresholds:** `threshold_degraded_loss_pct` = 5.0, `threshold_degraded_latency_ms` = 600.0
- **Confidence:** **Probable**: every connected link shows high latency or loss; several explanations remain possible.

**Example (probable)**: *Every internet connection is struggling*

> Crew: All of the yacht's internet connections (Starlink and Cellular) appear to be slow or dropping out at the same time. The internet may be unreliable for guests and crew. This could have several causes, so please let the ETO or 50N support know.
>
> Engineer: All connected links (Starlink and Cellular) show high latency or loss simultaneously. Several explanations are possible.

## `dns_failure`: Websites can't be found, though the internet connection works

Name lookups through the yacht's DNS server fail while a public resolver or IP connectivity works.

- **Severity:** warning
- **Needs:** probes. **Optional:** none
- **Opens after:** 90 s; **resolves after clear for:** 120 s
- **Confidence:** **Probable** ("suspected"): lookups through the yacht's resolver fail while a public resolver or IP connectivity works.

**Example (probable)**: *Websites can't be found, though the connection works*

> Crew: Websites and apps may fail to load even though the internet connection itself appears to be working. The service on board that turns website names into addresses is probably not responding. Please let the ETO or 50N support know.
>
> Engineer: A DNS problem is suspected: lookups through the yacht's resolver fail while a public resolver succeeds, and IP connectivity works.

## `starlink_obstructed`: Starlink dish's view of the sky is blocked

The dish reports obstruction (currently obstructed or a significant obstructed fraction) with obstruction outages.

- **Severity:** warning
- **Needs:** wan. **Optional:** dish (essential: the rule does not fire without it)
- **Opens after:** 60 s; **resolves after clear for:** 300 s
- **Absorbs:** `primary_link_degraded`
- **Thresholds:** `threshold_obstruction_fraction` = 0.05
- **Confidence:** **Confirmed** when the dish reports it is obstructed now and has recent outages caused by obstruction; otherwise **probable**. Does not fire without dish data.

**Example (confirmed)**: *Starlink dish's view of the sky is blocked*

> Crew: The internet is dropping out because the Starlink dish's view of the sky is partly blocked, probably by part of the yacht such as the mast or a radar dome at the current heading. It should recover as the yacht's heading changes. Nothing needs to be fixed on board.
>
> Engineer: Dish reports 18.0% obstructed and is obstructed now; 2 recent outages caused by obstruction.

**Example (probable)**: *Starlink dish's view of the sky is blocked*

> Crew: The internet may drop out at times because the Starlink dish's view of the sky appears to be partly blocked. It should improve as the yacht's heading changes. Nothing needs to be fixed on board.
>
> Engineer: Dish reports 6.0% obstructed; 0 recent outages caused by obstruction.

## `starlink_dish_alert`: Starlink dish alert

The dish reports an active alert (for example overheating, motors, mounting or water).

- **Severity:** warning
- **Needs:** none. **Optional:** dish (essential: the rule does not fire without it)
- **Opens after:** 30 s; **resolves after clear for:** 300 s
- **Confidence:** **Confirmed**: the dish reports the alert. Severity depends on the alert (thermal shutdown and water are critical). Does not fire without dish data.

**Example (confirmed)**: *The Starlink dish is too hot and has slowed itself down*

> Crew: The Starlink dish is too hot and has slowed itself down. The internet may be slower until it cools down. If it carries on, please let the ETO know.
>
> Engineer: Dish alert active: thermal_throttle.

**Example (confirmed)**: *The Starlink dish reports a problem*

> Crew: The Starlink dish reports a problem. Please let the ETO or 50N support know.
>
> Engineer: Dish alert active: novel_alert.

## `weak_cellular_signal`: Weak mobile signal on the connection in use

A cellular WAN link carrying traffic reports weak signal (RSRP or SINR below thresholds).

- **Severity:** warning
- **Needs:** wan. **Optional:** none
- **Opens after:** 120 s; **resolves after clear for:** 300 s
- **Thresholds:** `threshold_weak_rsrp_dbm` = -110.0, `threshold_weak_sinr_db` = 0.0
- **Confidence:** **Confirmed**: the router reports the signal of the cellular link in use.

**Example (confirmed)**: *Weak mobile signal on the connection in use*

> Crew: The yacht is using its mobile data connection (Cellular) and the signal is weak, so the internet will be slow and may drop out. This usually improves as the yacht moves closer to shore. Nothing needs to be done on board.
>
> Engineer: Cellular in use with RSRP -118.0 dBm and SINR -2.0 dB.

## `ap_offline`: Wi-Fi access point offline

An access point is reported disconnected by the Wi-Fi system, or stops answering Insight's checks.

- **Severity:** warning
- **Needs:** none. **Optional:** none
- **Opens after:** 90 s; **resolves after clear for:** 180 s
- **Thresholds:** `probe_failure_threshold` = 3
- **Confidence:** **Confirmed** when the Wi-Fi system reports the access point disconnected (web interface, or an Unleashed lost-contact message). **Probable** when only Insight's reachability checks fail.

**Example (confirmed)**: *Wi-Fi access point offline*

> Crew: Wi-Fi is not working in Main deck, saloon (guest Wi-Fi), because the Wi-Fi unit there has disconnected. People there may have no Wi-Fi or a weak signal from nearby areas. The ETO should check it.
>
> Engineer: AP-SALOON is reported disconnected.

**Example (probable)**: *Wi-Fi access point offline*

> Crew: Wi-Fi may not be working in one area of the yacht (its location hasn't been set yet): the Wi-Fi unit there has stopped answering Insight's checks. People there may have no Wi-Fi or a weak signal. The ETO should check it.
>
> Engineer: AP-CAB4 is not answering reachability checks.

## `ap_lost_poe`: Wi-Fi access point lost power or connection from its switch

An access point's switch port lost link or PoE power and the access point stopped answering.

- **Severity:** warning
- **Needs:** switches, probes. **Optional:** poe
- **Opens after:** 60 s; **resolves after clear for:** 180 s
- **Absorbs:** `ap_offline`
- **Confidence:** **Confirmed** when current PoE power data for the access point's port shows 0 W or link down. **Probable** when PoE data is unavailable but the port (known from LLDP or an engineer's record) is down and the access point does not answer.

**Example (confirmed)**: *Wi-Fi access point lost power or connection from its switch*

> Crew: Wi-Fi is not working in Lower deck, guest cabin 4 (guest Wi-Fi): the Wi-Fi unit there has lost power from the network cabinet. The ETO should check the network cabinet that feeds it.
>
> Engineer: AP-CAB4 on SW-LD-01 port 1: link down, PoE 0.0 W; the access point is not answering.

**Example (probable)**: *Wi-Fi access point lost power or connection from its switch*

> Crew: Wi-Fi is probably not working in Lower deck, guest cabin 4: the Wi-Fi unit there seems to have lost its connection to the network cabinet. The ETO should check the network cabinet that feeds it.
>
> Engineer: AP-CAB4 on SW-LD-01 port 1: link down, PoE power data not available; the access point is not answering.

## `switch_offline`: Network switch offline

A switch is reported offline (or its uplink is down); everything behind it is listed as affected.

- **Severity:** critical
- **Needs:** switches. **Optional:** none
- **Opens after:** 60 s; **resolves after clear for:** 180 s
- **Absorbs:** `ap_offline`, `ap_lost_poe`
- **Confidence:** **Confirmed** when the controller reports the switch offline; **probable** when only Insight's checks fail. Lists everything behind the switch, using remembered cabling.

**Example (confirmed)**: *Network switch offline*

> Crew: A network cabinet switch in Lower deck comms cabinet has gone offline. Wi-Fi and wired equipment in Lower deck, guest cabin 4; and Lower deck, guest cabin 6 will not work.The ETO should check the cabinet's power and the switch.
>
> Engineer: SW-LD-01 is reported offline by the controller; 3 devices behind it.

**Example (probable)**: *Network switch offline*

> Crew: A network cabinet switch appears to be offline. The ETO should check the cabinet's power and the switch.
>
> Engineer: SW-LD-01 is not answering reachability checks; 0 devices behind it.

## `wifi_congestion`: Wi-Fi busy in one area

An access point reports very high channel utilisation or a very high number of clients.

- **Severity:** warning
- **Needs:** none. **Optional:** wifi_detail (essential: the rule does not fire without it)
- **Opens after:** 300 s; **resolves after clear for:** 600 s
- **Thresholds:** `threshold_channel_util_pct` = 80.0, `threshold_ap_clients` = 40
- **Confidence:** **Probable**: high channel utilisation or client count suggests local congestion. Does not fire without the optional Ruckus web data.

**Example (probable)**: *Wi-Fi busy in one area*

> Crew: Wi-Fi in Main deck, saloon is probably slow because it is very busy (48 devices connected). It should improve when fewer devices are in use there. Nothing needs to be done on board, but the ETO may want to look at it if it happens often.
>
> Engineer: AP-SALOON: 2.4GHz 92.0% busy; 48 clients. Likely local wireless congestion.

## `monitoring_source_unavailable`: Insight can't currently check part of the system

A configured source cannot be reached, rejects Insight's credentials, or returns data Insight can't interpret.

- **Severity:** warning
- **Needs:** none. **Optional:** none
- **Opens after:** 60 s; **resolves after clear for:** 60 s
- **Confidence:** **Monitoring failure**: Insight cannot collect from the source. Equipment it covers is not reported faulty on that basis. Optional sources are information severity.

**Example (monitoring failure)**: *Insight can't currently check the network switches*

> Crew: Insight can't currently check the network switches, so it can't tell whether they are working. This doesn't mean anything is wrong with them. Please let the ETO or 50N support know if it continues.
>
> Engineer: Insight cannot collect from UniFi controller (unreachable) for 5 minutes.

**Example (monitoring failure)**: *Insight can't currently check detailed Starlink dish information*

> Crew: Insight can't currently get detailed Starlink dish information. This doesn't mean anything is wrong; Insight carries on checking everything else.
>
> Engineer: Insight cannot collect from Starlink dish (unparseable) for 60 minutes.

## `low_disk_space`: Insight is running out of storage space

Free space for Insight's data has fallen below the safe threshold; the oldest readings are being removed.

- **Severity:** warning
- **Needs:** none. **Optional:** none
- **Opens after:** 0 s; **resolves after clear for:** 600 s
- **Thresholds:** `low_disk_free_mb` = 1024
- **Confidence:** **Confirmed**: measured free space is below the threshold.

**Example (confirmed)**: *Insight is running out of storage space*

> Crew: Insight is running low on storage space and has started removing its oldest records. Monitoring continues. Please let 50N support know.
>
> Engineer: 412.0 MB free (threshold 1024.0 MB). Oldest detailed readings are being removed to keep recording.

