# Spec Delta

## Purpose

Defines how Insight summarises the state of each system, each crew-facing service and the yacht overall into a simple status. Anyone can then see at a glance whether something needs attention, without missing monitoring data being mistaken for a fault.

## ADDED Requirements

### Requirement: Uses four status values
Insight SHALL express health using exactly four statuses:
- **HEALTHY**: working normally, based on current data;
- **DEGRADED**: working with reduced performance or partial loss;
- **CRITICAL**: not working, or severely impaired;
- **UNKNOWN**: Insight does not have current data to judge.

#### Scenario: Status values
- **WHEN** any status is displayed
- **THEN** it is one of HEALTHY, DEGRADED, CRITICAL or UNKNOWN

### Requirement: Status for each system
Insight SHALL show a status for each monitored system: Peplink router, Starlink, UniFi switching and Ruckus Wi-Fi. Each status SHALL be derived from that system's current observations and open findings.

#### Scenario: Peplink healthy
- **GIVEN** the Peplink router is reachable and reports no faults
- **WHEN** its status is calculated
- **THEN** the Peplink router is HEALTHY

### Requirement: Status for each service
Insight SHALL show a status for the Internet, Guest Wi-Fi and Crew Wi-Fi services. Each status SHALL be derived from the devices, links and networks mapped to it and their open findings.

#### Scenario: Internet degraded on backup link
- **WHEN** the yacht has failed over from Starlink to cellular
- **THEN** the Internet service is DEGRADED, not HEALTHY

#### Scenario: Guest Wi-Fi partially down
- **WHEN** one of several access points serving Guest Wi-Fi is offline
- **THEN** Guest Wi-Fi is DEGRADED

#### Scenario: Unmapped service
- **GIVEN** no devices or networks are mapped to Crew Wi-Fi
- **WHEN** its status is calculated
- **THEN** Crew Wi-Fi is UNKNOWN and shows that it has not been set up

### Requirement: Overall yacht status
Insight SHALL show an overall status that is the worst status across all services. It SHALL be UNKNOWN only when every service is UNKNOWN.

#### Scenario: One service critical
- **WHEN** the Internet is CRITICAL and both Wi-Fi services are HEALTHY
- **THEN** the overall status is CRITICAL

### Requirement: Missing data is UNKNOWN, not a fault
A system or service whose required data is stale or unavailable because of a monitoring failure SHALL be UNKNOWN. It SHALL NOT be DEGRADED or CRITICAL on that basis alone.

#### Scenario: Wi-Fi monitoring lost
- **WHEN** Insight loses contact with the Ruckus master access point while probes still reach the access points
- **THEN** Ruckus Wi-Fi is UNKNOWN, not CRITICAL

### Requirement: Status shows freshness and reason
Each status SHALL show when it was last updated, and the open findings or observations responsible for any status other than HEALTHY.

#### Scenario: Degraded status explained
- **WHEN** a user views a DEGRADED service
- **THEN** they can see which finding or findings make it DEGRADED and when the status was last updated

### Requirement: Status changes are recorded
Every change in system, service or overall status SHALL be recorded in the event timeline with the previous status, the new status and the time.

#### Scenario: Internet recovers
- **WHEN** the Internet service changes from DEGRADED to HEALTHY
- **THEN** the change is recorded in the event timeline
