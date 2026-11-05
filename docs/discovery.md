# Discovery guide (engineers)

Discovery helps you set Insight up faster and spot equipment that nothing else covers. It **suggests**; you **confirm**. Nothing enters the inventory until you accept it. Insight never signs in to anything it finds and never guesses credentials.

The screen is **Engineer → Discovery**.

## What each layer does and sends

| Layer | When it runs | What it does | Traffic it sends |
|---|---|---|---|
| **Source lists** (passive) | Every collection cycle | Looks at the client and address lists that Peplink and UniFi already return, and lists wired equipment that isn't in the inventory. Wi-Fi clients and randomised (private) MAC addresses are ignored, so guest phones don't appear. | None beyond normal collection |
| **Announcements** (passive) | Always | Listens for mDNS (UDP 5353) and SSDP (UDP 1900) announcements, which is how AV gear such as Sonos announces itself | None; listening only |
| **Scan** (active) | **Only when you press Start scan** | For each address in the subnets you selected: TCP connections to a fixed list of management ports (22, 80, 443, 8080, 8443, 8822, 9200, 11443). Where a web port answers, it reads the public page title, the redirect target and the TLS certificate subject. | Connection attempts and one plain `GET /` per web device, with no credentials, cookies or query string. No SNMP, no sign-in, no vulnerability tests, nothing that changes a device. |

When a new device shows up in the passive layers, Insight records a **"new device seen on the network"** event in the timeline and lists it for review. It is never added or scanned automatically.

## Limits (the defaults)

- **No subnets are selected** on a new installation, so no scan can run until you choose.
- **Never-scan subnets always win.** An address inside an excluded subnet is never contacted, even if a selected subnet overlaps it.
- **At most 1,024 addresses per run** (a /22). Insight refuses larger selections.
- **Rate limited:** about 20 new addresses per second, and at most 4 ports checked at once per device.
- **Never continuous or scheduled.** Each run is started by an engineer, can be cancelled, and is recorded in the timeline with the name of whoever started it.

## Before your first scan

1. **Tell the yacht's IT contact (or the captain) before an active scan.** Some router intrusion-detection features flag connection sweeps, and it is good practice that nobody is surprised.
2. **Select only management networks**, for example the switch and router management subnet. Use the router's LAN subnet list on the Discovery screen as a starting point; it is shown, not selected.
3. **Add these to "Never scan":**
   - the **guest** network (guests' devices are not yacht equipment);
   - **AV / entertainment** networks: some AV control equipment misbehaves when port-scanned;
   - **bridge, navigation and engineering** networks: Insight is hotel IT only and must never touch them;
   - any network you are unsure about.
4. Prefer the passive layers first. On most yachts the router and controller lists already show the equipment, so a scan is often unnecessary.

## Reviewing what was found

Each entry shows how it was found, its address, and what Insight thinks it is:

- **Likely a …:** one strong signature (such as a vendor's default certificate) or two medium ones matched.
- **Possibly a …:** a single medium signature matched (for example only the MAC address vendor).
- **Unidentified:** nothing matched. Insight does not guess.

The evidence column says what matched. Then:

- **Set up as source:** for a recognised Peplink router, UniFi controller, Ruckus Unleashed master or Starlink dish. Guided setup opens with the address filled in; you still enter credentials, and Insight still tests the connection.
- **Accept:** adds the device to the inventory, monitored by Insight's own reachability checks. Give it a name and category; set its location afterwards on its inventory page.
- **Dismiss:** hides it. It stays hidden in later runs (matched by MAC address) until you restore it.

Signature details for each vendor are in `docs/integrations/discovery.md`.
