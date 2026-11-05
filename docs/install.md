# Installing Insight on board

This guide takes a provisioned Insight appliance (see `docs/appliance.md`) to a working installation on the yacht. Allow about an hour.

## 1. Before you go on board

- [ ] The appliance has been provisioned with `appliance/provision.yml`. It has full-disk encryption, Secure Boot and the firmware password set, and its recovery key is stored in 50N's password manager.
- [ ] You can reach it over SSH with your 50N key as `50n-admin`.
- [ ] You have the Insight image: either the registry tag, or the release tarball (`insight-<version>.tar`) on a USB stick if the yacht may be offline.

## 2. Install it on board

1. Mount the appliance in the comms rack and **power it from the UPS**.
2. Connect it to the **management network**, where it can reach the Peplink router, the UniFi controller, the Ruckus Unleashed management address and the Starlink dish address. Crew and engineers reach Insight's web page through an allowed route; do not put the appliance on the guest network.
3. Give it a fixed address (a DHCP reservation on the Peplink is easiest).
4. Check the clock: `timedatectl` should show *System clock synchronized: yes*. The Peplink's NTP server is **off by default**; turn it on (*System → Time*) or point `ntp_servers` at another on-board source and re-run the playbook.

## 3. Start Insight

```bash
cd /opt/insight
```

If the yacht has internet, pull the image:

```bash
docker compose pull
```

If it does not, load the release tarball instead:

```bash
docker load -i /media/usb/insight-<version>.tar
```

Then start it:

```bash
docker compose up -d
```

Check it is running and healthy:

```bash
docker compose ps
```

The **STATUS** column should read `healthy` within a minute or two.

Insight listens on HTTPS port 443 and redirects plain HTTP on port 80. It also listens on UDP 514 for Ruckus syslog. To use other ports, set `INSIGHT_HTTPS_PORT`, `INSIGHT_HTTP_PORT` or `INSIGHT_SYSLOG_PORT` in `/opt/insight/.env`. Unleashed can only send syslog to port 514.

## 4. First run

1. Browse to `https://<appliance address>/`. The first time, the browser warns about the **self-signed certificate**: check that the address is the appliance, then proceed. To avoid the warning, upload a certificate under **Engineer → Settings → HTTPS certificate**, or trust the self-signed one on the devices crew use.
2. Insight asks you to **create the first engineer account**. There is no default password.
3. Under **Settings → Users**, add crew accounts.
4. Under **Settings → Ship's time and history**, set the ship's time zone.

## 5. Add the sources

Under **Engineer → Sources → Add a source**, add each of the following. Insight tests each connection before saving it and explains any failure. Each vendor's research notes in `docs/integrations/` have the details.

| Source | What you need on the device | Address example |
|---|---|---|
| **Peplink router** | Create a read-only API client: an admin login, then `api.read-only` scope. See `docs/integrations/peplink.md`. **Don't retry wrong credentials**: the router locks out after five failures. | `https://192.168.50.1` |
| **UniFi Network controller** | UniFi OS: an API key (Network app → Integrations). Legacy controller: a View Only admin. | `https://192.168.50.20` or `https://192.168.50.20:8443` |
| **UniFi switch (SNMP)**, optional | Turn on SNMP for the site in the Network app. Add one per switch if you want port counters, or if there is no controller. | `10.10.0.11` |
| **Ruckus Unleashed (SNMP)** | Turn on read-only SNMP (Admin & Services → System → Network Management). Use the **Unleashed management address**: the master role moves between access points. | `10.10.20.10` |
| **Ruckus Unleashed (web interface)**, optional | An Unleashed admin login. Unofficial; Insight carries on without it. | `10.10.20.10` |
| **Starlink dish**, optional | See "Dish access" below. | `192.168.100.1:9200` |

Insight's own checks (reachability, internet, DNS, web) run automatically.

### Ruckus syslog

In Unleashed, set **Admin & Services → System → Log Settings → Remote syslog** to the appliance's address. Insight then records access points joining, leaving and rebooting as they happen.

### Dish access through the Peplink

A static route **does not** work on Peplink WAN ports. Use one of these:

- **Starlink WAN pairing plus an enforced outbound policy (recommended).** Mark the WAN as Starlink on the Peplink (or set its *Management IP Address* on older firmware). Then add an **outbound policy rule** sending `192.168.100.1` to the Starlink WAN, with **Enforced** selected. Without "Enforced", the Peplink stops routing to the dish exactly when Starlink fails its health check, which is when Insight needs dish data most.
- **The Peplink's dish proxy** (firmware 8.5+): use the Peplink's LAN address and port 9200 plus the WAN number as the dish address, for example `192.168.50.1:9201`.

Set the same address under **Settings → Insight's own checks → Starlink dish address**.

## 6. Tell Insight about the yacht

1. **Services:** under **Settings → Services**, assign the guest and crew Wi-Fi networks. The Internet service covers all WAN links automatically.
2. **Starlink:** under **Settings → Starlink**, choose which router link is Starlink.
3. **Locations:** under **Engineer → Inventory**, open each access point and switch and set its **location**, for example "Main deck, saloon". Crew explanations use these names.
4. **Attachments:** where the controller can't report which access point is on which switch port, record it on the access point's inventory page.

## 7. Discovery (optional)

Read `docs/discovery.md` **before the first discovery run**. In short: tell the yacht's IT contact first, select only management subnets, and exclude guest, AV and bridge networks.

## 8. Check it works

- **Engineer → Sources:** every source shows **OK**.
- **Status:** shows HEALTHY, or explains why not.
- Unplug a non-critical access point for two minutes. A finding should appear naming its location, then resolve when you plug it back in.
