# Spec Delta

## Purpose

Defines the technical view for the ETO and 50N remote support engineers. It gives the evidence, raw readings, inventory, timeline and configuration needed to investigate problems without being on board.

## ADDED Requirements

### Requirement: Shows full finding detail
The engineer console SHALL show, for every open and resolved finding: all standard finding fields, the rule that produced it, its confidence, the full evidence with sources and times, and the suggested checks.

#### Scenario: Investigating a finding
- **WHEN** an engineer opens a finding about an access point losing PoE power
- **THEN** they see the switch, port, PoE readings, reachability results and related events, each with its source and time

### Requirement: Shows the inventory
The engineer console SHALL list every inventory device with its details, source, location, services, monitoring status and last update. It SHALL allow searching and filtering.

#### Scenario: Find a device by address
- **WHEN** an engineer searches the inventory for an IP address
- **THEN** the device with that address is shown

### Requirement: Shows device detail and readings
For each device, the engineer console SHALL show its current readings, its recent history as charts or tables, its related findings, its timeline events and, for switches, port-level detail including PoE and neighbours.

#### Scenario: Switch port view
- **WHEN** an engineer opens a UniFi switch
- **THEN** each port shows its link state, speed, PoE power and neighbouring device where known

### Requirement: Shows WAN link detail
The engineer console SHALL show each WAN link's state, priority, health check results, latency, loss, data usage and whether it is in use. It SHALL also show the history of these readings and failover events.

#### Scenario: Comparing links
- **WHEN** an engineer views WAN links
- **THEN** Starlink and cellular are shown side by side with their current state and recent latency and loss

### Requirement: Shows the event timeline
The engineer console SHALL provide the event timeline with filtering by time range, system, device, service and event type.

#### Scenario: Overnight investigation
- **WHEN** an engineer filters the timeline to the hours of a reported outage
- **THEN** all events in that window are shown in order

### Requirement: Shows source and monitoring health
The engineer console SHALL show each integration source with its type (reliable or optional), last successful collection, current state and most recent error.

#### Scenario: Optional source broken
- **WHEN** the Starlink dish's optional source has failed since a firmware update
- **THEN** the console shows that source as failing, with its last error and when it last worked

### Requirement: Provides configuration
The engineer console SHALL provide the guided setup of sources, credentials, device location and service tagging, probe settings, retention settings and user accounts.

#### Scenario: Adding a location
- **WHEN** an engineer sets an access point's location
- **THEN** the location is saved and used in crew explanations from then on

### Requirement: Usable over a slow link
The engineer console SHALL remain usable over a slow or high-latency connection, such as a satellite or metered cellular link. Pages SHALL load only the data they show, and history SHALL be fetched for the selected time range only.

#### Scenario: Remote engineer on cellular backup
- **GIVEN** a remote engineer connects while the yacht is on its cellular backup link
- **WHEN** they open the findings and timeline pages
- **THEN** the pages load without fetching full history or large assets
