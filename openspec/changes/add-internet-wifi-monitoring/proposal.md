# Proposal

## Why

Crew on board a superyacht have no single place to answer "is the internet working, is the Wi-Fi working, and if not, why?" The information exists, but it is spread across Peplink, UniFi, Ruckus and Starlink tools that need networking knowledge to read. Every problem therefore becomes a call to 50N Systems' remote support, and the engineer starts without any evidence of what happened.

Insight, by 50N Systems, closes that gap. It brings data from those systems together on board, identifies likely problems, and explains them in plain English for crew. Behind each explanation it keeps the technical evidence a remote support engineer needs. This first change delivers the platform foundation plus the internet and Wi-Fi slice, because connectivity is the most common complaint and those integrations are the easiest to read.

## What Changes

- Introduce Insight as a self-contained application that runs on board in a Docker container on a dedicated mini-PC. It works fully without an internet connection.
- Add a vendor-neutral data collection framework. Each vendor has its own read-only adapter feeding a common internal model, and Insight distinguishes "the system is faulty" from "Insight cannot currently see the system".
- Add read-only integrations for:
  - **Peplink** routers: WAN links, link health checks, failover and usage.
  - **UniFi** switches: ports, link state, PoE and LLDP neighbours. Wi-Fi on this yacht is not UniFi.
  - **Ruckus Unleashed** Wi-Fi: official SNMP as the reliable base, with the unofficial web interface as an optional extra.
  - **Starlink**: Peplink's view of the link plus Insight's own tests as the reliable base, with the dish's unofficial local status interface as an optional extra.
- Add Insight's own connectivity probes: device reachability, internet reachability, DNS resolution and HTTP checks.
- Add an equipment inventory, populated from the controllers after a guided setup. Each device carries a location and the services it belongs to: Internet, Guest Wi-Fi and Crew Wi-Fi.
- Add a diagnostic engine built from hand-written rules. Each finding has a severity, a confidence level (confirmed, probable, insufficient information, or monitoring failure), supporting evidence, likely causes, next steps and a lifecycle from first detected to resolved.
- Add health status for each service and system: HEALTHY, DEGRADED, CRITICAL or UNKNOWN. Missing data is never shown as an equipment fault.
- Add on-board history: stored readings, an event timeline, and defined retention.
- Add two web views of one application:
  - a **crew dashboard** in plain English that works on a phone or tablet;
  - an **engineer console** with evidence, raw readings, inventory detail and the timeline, usable over a slow satellite or 4G link.
- Add local accounts with two roles (crew and engineer). Remote engineers reach Insight through 50N's existing remote-access route; Insight is never exposed directly to the internet.
- Out of scope for this change: Synology, UPS, Sonos and Crestron integrations; the shareable support snapshot; push or messaging notifications; AI-generated explanations; shore and fleet services; any capability that changes device configuration.

## Capabilities

### New Capabilities
- `deployment`: packaging and running Insight as a Docker container on a dedicated on-board host, including persistent data, automatic restart, health checks and offline-capable updates.
- `access-control`: local user accounts, crew and engineer roles, authentication and protection of stored device credentials.
- `device-inventory`: guided setup of integration sources, a device inventory populated from those sources, manual location and service tagging, and the services (Internet, Guest Wi-Fi, Crew Wi-Fi) that devices make up.
- `data-collection`: the adapter framework, the common vendor-neutral data model, read-only polling, separating reliable from optional (unofficial) data sources, and detecting monitoring failures.
- `integrations/peplink`: what Insight reads from Peplink routers and how it maps into the common model.
- `integrations/unifi`: what Insight reads from UniFi switches via the UniFi Network controller, with SNMP fallback.
- `integrations/ruckus-unleashed`: what Insight reads from Ruckus Unleashed via SNMP and, optionally, its web interface.
- `integrations/starlink`: what Insight reads about the Starlink link and, optionally, from the dish's local status interface.
- `connectivity-probes`: active tests Insight runs itself (reachability, DNS, HTTP) and how their results become evidence.
- `diagnostics`: the rule-based diagnostic engine, confidence levels, evidence, plain-English explanations, the initial problem catalogue and the issue lifecycle.
- `health-status`: rolling findings and observations up into HEALTHY, DEGRADED, CRITICAL or UNKNOWN status for each system, each service and the yacht overall.
- `history`: storing readings and events, the event timeline, and data retention.
- `crew-dashboard`: the plain-English, mobile-friendly view for the captain and crew.
- `engineer-console`: the technical view for the ETO and remote support engineers, with evidence, raw readings, inventory and the timeline.

### Modified Capabilities
- None. This is the first change in the project.

## Impact

- **Code:** a new application in an empty repository: backend service, adapters, diagnostic rules, web UI, and Docker packaging.
- **Dependencies:** a Python runtime (proposed in design.md), a Ruckus Unleashed client library, an SNMP library, an embedded SQLite database, and Docker and Docker Compose on the host.
- **On-board systems:** read-only API or SNMP credentials are needed for the Peplink router, the UniFi Network controller and Ruckus Unleashed. Ruckus may also need syslog forwarding to Insight. Insight needs network access to the management addresses of those devices and of the Starlink dish.
- **Hardware:** one fanless mini-PC in the comms rack, powered from the UPS, running Linux with Docker and NTP.
- **Operations:** 50N maintains the mini-PC's OS and Insight's updates. Remote engineers use 50N's existing remote-access route.
- **Risks:** the Starlink and Ruckus enrichment uses unofficial interfaces that can change after firmware updates. The UniFi integration depends on a reachable UniFi Network controller.
