# Spec Delta

## Purpose

Defines what Insight reads from the yacht's Peplink router, which carries all internet links, so it can tell which links are working, which one is in use, and when failover happens.

## ADDED Requirements

### Requirement: Connects to the router locally
Insight SHALL read from the Peplink router through its local management interface on the yacht's network, using read-only credentials. It SHALL NOT depend on Peplink's cloud service (InControl).

#### Scenario: Internet down
- **GIVEN** all internet links are down
- **WHEN** Insight collects from the Peplink router
- **THEN** collection succeeds over the local network

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
The Peplink integration SHALL report the result of the router's own health checks for each WAN link, including latency and packet loss where the router provides them. These are Insight's primary evidence for each link's health.

#### Scenario: Link failing health check
- **WHEN** the router reports the Starlink link failing its health check
- **THEN** Insight records that link as unhealthy, with the router's health check result as evidence

### Requirement: Identifies the link in use
The Peplink integration SHALL identify which WAN link or links are currently carrying traffic.

#### Scenario: Traffic on cellular
- **WHEN** the router is sending traffic over the cellular link only
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
