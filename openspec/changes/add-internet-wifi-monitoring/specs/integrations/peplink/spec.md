# Spec Delta

## Purpose

Defines what Insight reads from the yacht's Peplink router, which carries all internet links, so it can tell which links are working, which one is in use, and when failover happens.

## ADDED Requirements

### Requirement: Connects to the router locally
Insight SHALL read from the Peplink router through its local management interface on the yacht's network, using a read-only API client. It SHALL NOT depend on Peplink's cloud service (InControl). Because the router locks access after repeated failures, Insight SHALL NOT retry rejected credentials automatically.

#### Scenario: Internet down
- **GIVEN** all internet links are down
- **WHEN** Insight collects from the Peplink router
- **THEN** collection succeeds over the local network

#### Scenario: Credentials rejected
- **WHEN** the router rejects Insight's credentials
- **THEN** Insight records an authentication failure and does not try those credentials again until an engineer updates them

### Requirement: Classifies router data by interface
Data from the router's documented local API SHALL be classed as reliable. Data available only from undocumented endpoints (router model, serial number, uptime and WAN latency) SHALL be classed as optional.

#### Scenario: Undocumented endpoint changes
- **WHEN** an undocumented endpoint returns data Insight cannot interpret
- **THEN** WAN status, health check results and cellular data from the documented API continue to be collected

### Requirement: Does not store SIM or access secrets
Insight SHALL discard SIM identifiers (such as ICCID and IMSI), APN passwords and other secrets the router returns, before storing or displaying anything.

#### Scenario: Cellular details returned
- **WHEN** the router's cellular status includes a SIM identifier and an APN password
- **THEN** neither appears in Insight's stored data, events or interface

### Requirement: Reports router details
The Peplink integration SHALL report the router's model, firmware version, serial number and uptime, where the router provides them.

#### Scenario: Router in inventory
- **WHEN** the Peplink source is first collected
- **THEN** the router appears in the inventory with its model and firmware version

### Requirement: Reports each WAN link
The Peplink integration SHALL report every WAN link the router has configured (for example Starlink, cellular, VSAT), with its name, type, connection state (connected, standby, disconnected or disabled) and priority.

#### Scenario: Starlink and cellular links
- **GIVEN** a router with a Starlink link at priority 1 and a cellular link at priority 2
- **WHEN** Insight collects from it
- **THEN** both links appear with their states and priorities

### Requirement: Reports link health checks
The Peplink integration SHALL report the pass or fail result of the router's own health check for each WAN link, as Insight's primary evidence for each link's health. Latency SHALL be reported where an optional source provides it. Packet loss is measured by Insight's own probes, on the link in use.

#### Scenario: Link failing health check
- **WHEN** the router reports the Starlink link failing its health check
- **THEN** Insight records that link as unhealthy, with the router's health check result as evidence

### Requirement: Identifies the link in use
The Peplink integration SHALL identify which WAN link or links are currently carrying traffic. Where the router does not report this directly, Insight SHALL derive it from each link's status and priority.

#### Scenario: Traffic on cellular
- **WHEN** the router is sending traffic over the cellular link only
- **THEN** Insight records cellular as the link in use

#### Scenario: Derived from priority
- **GIVEN** the Starlink link (priority 1) is disconnected and the cellular link (priority 2) is connected
- **WHEN** the router does not report which link is in use
- **THEN** Insight records cellular as the link in use

### Requirement: Records failover events
The Peplink integration SHALL record an event whenever the link in use changes, including the previous link, the new link and the time.

#### Scenario: Failover to cellular
- **WHEN** traffic moves from the Starlink link to the cellular link
- **THEN** a failover event is recorded with both link names and the time it was observed

### Requirement: Reports cellular signal
For cellular WAN links, the Peplink integration SHALL report signal quality and carrier or network type, where the router provides them.

#### Scenario: Weak cellular signal
- **WHEN** the router reports weak signal on the cellular link
- **THEN** the signal value is recorded as a metric for that link

### Requirement: Reports data usage
The Peplink integration SHALL report data usage for each WAN link, where the router provides it, so that use of metered links can be seen.

#### Scenario: Cellular data usage
- **WHEN** the router reports data used on the cellular link
- **THEN** Insight records that usage against the link
