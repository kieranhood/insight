# Spec Delta

## Purpose

Defines what Insight reads from the yacht's UniFi switches (switching only; this yacht's Wi-Fi is not UniFi), so it can see port, PoE and uplink problems and which equipment is attached to each port.

## ADDED Requirements

### Requirement: Reads switches through the UniFi Network controller
The UniFi integration SHALL read switch information from the UniFi Network controller on board, using a read-only API key or account. It SHALL NOT depend on Ubiquiti's cloud services.

#### Scenario: Controller configured
- **WHEN** an engineer adds a working UniFi Network controller source
- **THEN** Insight collects the switches it manages over the local network

### Requirement: Falls back to SNMP
Where no UniFi Network controller is reachable or configured, Insight SHALL support reading the switches directly over SNMP. Data the controller provides but SNMP does not SHALL be shown as not available.

#### Scenario: Controller not running
- **GIVEN** the switches are configured as SNMP sources and no controller source exists
- **WHEN** Insight collects from them
- **THEN** switch availability, port state and port traffic are collected over SNMP

### Requirement: Reports switch details
The UniFi integration SHALL report each switch's name, model, IP address, MAC address, firmware version, uptime and online state as reported by its source.

#### Scenario: Switch goes offline
- **WHEN** the controller reports a switch as disconnected
- **THEN** Insight records the switch as offline, with the controller's report as evidence

### Requirement: Reports port state
The UniFi integration SHALL report, for each switch port: link up or down, negotiated speed, error counters and traffic counters, where available.

#### Scenario: Port goes down
- **WHEN** a switch port that was up reports link down
- **THEN** Insight records the change as an event against that switch and port

### Requirement: Reports PoE
The UniFi integration SHALL report, for each PoE-capable port, whether PoE is enabled and the power being delivered. It SHALL also report each switch's total PoE budget and usage, where available.

#### Scenario: PoE power drops to zero
- **WHEN** a port that was supplying PoE power reports zero power
- **THEN** Insight records the change as evidence, with the switch, port and time

### Requirement: Reports what is attached to each port
The UniFi integration SHALL report the neighbouring device on each port when the source identifies one (for example by LLDP), including its name and MAC address. Insight SHALL use this to link switch ports to inventory devices from other vendors.

#### Scenario: Ruckus access point on a UniFi port
- **GIVEN** a Ruckus access point is plugged into port 12 of a UniFi switch
- **WHEN** the switch reports the access point as the neighbour on port 12
- **THEN** Insight links that access point in the inventory to that switch and port

### Requirement: Reports uplinks
The UniFi integration SHALL identify each switch's uplink port and the device it connects to, where available, so that the path from an access point to the router can be traced.

#### Scenario: Switch uplink fails
- **WHEN** a switch's uplink port goes down
- **THEN** Insight records which devices are downstream of that switch
