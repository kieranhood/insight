# Spec Delta

## Purpose

Defines what Insight reads from the yacht's Ruckus Unleashed Wi-Fi system: a reliable base from SNMP, syslog and probes, plus optional per-access-point and per-client detail from the Unleashed web interface.

## ADDED Requirements

### Requirement: Reads totals over SNMP as the reliable source
The Ruckus integration SHALL read the Unleashed master access point over SNMP, using read-only credentials, as its reliable source. This SHALL report the number of access points known and registered, the total number of connected clients, and the master's own details, where available.

#### Scenario: One access point missing
- **WHEN** SNMP reports 8 known access points but only 7 registered
- **THEN** Insight records that one access point is not registered, with the counts as evidence

### Requirement: Receives Unleashed syslog events
Insight SHALL be able to receive syslog messages from Ruckus Unleashed. It SHALL record access point join, leave and reboot events it can recognise. Unrecognised messages SHALL be kept as raw events for engineers.

#### Scenario: Access point leaves
- **GIVEN** Unleashed is configured to send syslog to Insight
- **WHEN** Unleashed logs that an access point has disconnected
- **THEN** Insight records an access point disconnected event naming that access point

#### Scenario: Unrecognised message
- **WHEN** a syslog message from Unleashed does not match any known pattern
- **THEN** it is stored as a raw event visible in the engineer console and does not create a finding

### Requirement: Checks each access point's reachability
Insight SHALL check that each Ruckus access point in the inventory is reachable over the network, so that a specific missing access point can be identified without the optional source.

#### Scenario: Specific access point unreachable
- **GIVEN** the access points are in the inventory with their IP addresses
- **WHEN** one access point stops responding to reachability checks
- **THEN** Insight identifies that specific access point as unreachable

### Requirement: Optional detail from the web interface
When an engineer enables it, the Ruckus integration SHALL read the Unleashed web interface as an optional source. It SHALL report, where available: each access point's name, model, MAC, IP, firmware, status, channels and channel utilisation; each Wi-Fi network (SSID); and each client's access point, SSID, band and signal strength.

#### Scenario: Optional source enabled
- **GIVEN** the optional Unleashed web interface source is enabled with valid credentials
- **WHEN** Insight collects from it
- **THEN** each access point appears in the inventory with its details, and clients are associated with their access points and Wi-Fi networks

#### Scenario: Optional source fails
- **WHEN** the Unleashed web interface returns data Insight cannot interpret
- **THEN** SNMP, syslog and reachability collection continue, and per-access-point and per-client detail is shown as not available

### Requirement: Populates access points from available sources
Insight SHALL populate Ruckus access points in the inventory from the optional source when it is enabled. Otherwise it SHALL populate them from the UniFi switch neighbour information and from manual entry.

#### Scenario: Optional source disabled
- **GIVEN** the optional source is disabled
- **WHEN** UniFi switches report Ruckus access points as port neighbours
- **THEN** those access points appear in the inventory with the name and MAC address the switch reported
