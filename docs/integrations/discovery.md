# Discovery signatures

This page brings together the identification signatures collected for the four integration sources, from the per-vendor research in this folder. Insight's discovery (design D10) uses them to suggest equipment with a confidence level.

**Matching rule (D10):** one *strong* signature, or two *medium* ones, gives **likely**. One medium signature gives **possible**. Anything else is **unidentified**.

**Status:** nothing here has been verified on board yet. Items marked *U* are unverified and must be captured during commissioning (task 21.3). The authoritative detail, with sources, is in each vendor's page.

## Peplink router (`peplink.md`)

| # | Signature | Type | Strength |
|---|---|---|---|
| P1 | MAC OUI `00:11:6E`, `10:56:CA`, `6C:A3:D3`, `D4:13:F8`, `00:1A:DD`, `A8:C0:EA` | passive (source and ARP lists) | strong (routers, though Peplink APs and switches share these OUIs) |
| P2 | TLS certificate subject CN `captive-portal.peplink.com` (default certificate) | active (TLS handshake on 443) | strong |
| P3 | `GET /cgi-bin/MANGA/index.cgi`: page title `Web Admin \| Welcome…`, with `init_company_name = "Peplink"` | active (public page) | strong |
| P4 | `GET /api/info.firmware` answers without sign-in with `{"stat":"ok",…}` | active (public endpoint, no credentials) | strong (proof) |
| P5 | TCP 8822 open (Peplink SSH) | active (port) | medium (only if enabled) |

There are four independent strong signatures. Peplink makes no mDNS or SSDP announcements.

## UniFi Network controller (`unifi.md`)

| # | Signature | Type | Strength |
|---|---|---|---|
| U1 | Ubiquiti MAC OUI (e.g. `F0:9F:C2`, `74:AC:B9`, `24:5A:4C`; full list in `unifi.md`). Hardware consoles only | passive | strong (hardware consoles) |
| U2 | TCP 8080 (device inform) plus 443 (UniFi OS) or 8443 (self-hosted) | active (ports) | medium |
| U3 | Default TLS certificate subject `CN=UniFi, OU=UniFi, O=Ubiquiti Inc.` (self-hosted; UniFi OS subject *U*) | active (TLS) | strong where present |
| U4 | `GET /status` → `{"meta":{"rc":"ok","server_version":…}}` (self-hosted, unauthenticated) | active (public endpoint) | strong |
| U5 | Page title "UniFi OS" / "UniFi Network" (*U*) | active (public page) | medium until verified |
| U6 | UBNT discovery packets on UDP 10001 (unadopted devices; adopted *U*) | passive (needs listening on UDP 10001) | strong for switches |

There are at least two independent signatures (U1 + U2 for a Cloud Key; U2 + U3 or U4 for self-hosted). A self-hosted controller on a generic PC has no Ubiquiti OUI.

## Ruckus Unleashed master AP (`ruckus-unleashed.md`)

| # | Signature | Type | Strength |
|---|---|---|---|
| R1 | Ruckus MAC OUI (100 blocks, e.g. `24:79:2A`, `C0:8A:DE`, `D4:68:4D`; full list in `ruckus-unleashed.md`) | passive | strong for "a Ruckus AP", not specifically the master |
| R2 | `GET /` redirects with 302 to its own `/admin/login.jsp`. Members redirect to the master's address first | active (public page) | strong for the **master** |
| R3 | Default TLS certificate CN `unleashed.ruckuswireless.com` (very likely) | active (TLS) | medium |
| R4 | TCP 443 + 80 + 22 open | active (ports) | weak alone |

There are two independent strong signatures (R1 + R2). The master role can move between APs, so Insight should use the Unleashed management IP rather than one particular AP's address.

## Starlink dish (`starlink.md`)

The dish is behind the Peplink's WAN, so it never appears in LAN lists or a LAN sweep, and its MAC address is not visible to Insight.

| # | Signature | Type | Strength |
|---|---|---|---|
| S1 | Fixed address `192.168.100.1` (probed explicitly, not part of the subnet sweep) | active (known address) | strong in context |
| S2 | TCP 9200 open, with gRPC reflection listing `SpaceX.API.Device.Device` | active (port + read-only listing) | strong |
| S3 | `get_device_info` answers with an `id` like `ut…` / `dish_get_status` present | active (read-only request on the allow-list) | strong |
| S4 | Peplink LAN address answering the same gRPC service on TCP 9201–9205 (Peplink dish proxy) | active | strong (proxy enabled) |

There are two or more independent signatures (S1 + S2, or S4 + S3).

## Signatures discovery must not use

- **SNMP `sysObjectID` / `sysDescr`.** Querying them is a credential guess, even with `public` (D10).
- **Signing in, or any authenticated endpoint.**
- **The Starlink dish MAC address.** It is not visible across the routed WAN boundary.

## Passive listeners this implies

- **mDNS (UDP 5353) and SSDP (UDP 1900):** as designed. Useful later for Sonos and other AV equipment; none of the four sources announces itself.
- **UBNT discovery (UDP 10001):** optional, for UniFi switches. Listening only, never probing.
