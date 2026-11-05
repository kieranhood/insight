# Spec Delta

## Purpose

Defines how Insight assesses the Starlink connection. A reliable base comes from the Peplink router and Insight's own probes, with optional detail from the dish's local status interface explaining why the link is degraded.

## ADDED Requirements

### Requirement: Identifies the Starlink link
An engineer SHALL be able to mark which Peplink WAN link is the Starlink connection. That link's state, health checks, latency, packet loss and failover events SHALL then be attributed to Starlink.

#### Scenario: Starlink link marked
- **GIVEN** an engineer has marked the Peplink WAN link "Starlink" as the Starlink connection
- **WHEN** the router reports that link failing its health check
- **THEN** Insight records the Starlink connection as unhealthy, with the router's health check as evidence

### Requirement: Checks the dish is reachable
Insight SHALL check whether the Starlink dish's local management address is reachable from the yacht's network. The address SHALL be configurable, defaulting to `192.168.100.1` port 9200, so that a router-provided proxy address can be used instead.

#### Scenario: Dish unreachable
- **WHEN** the dish's local address stops responding while the Starlink WAN link is also down
- **THEN** Insight records both observations as evidence for a Starlink outage

### Requirement: Optional detail from the dish's local status interface
When an engineer enables it, Insight SHALL read the dish's local status interface as an optional source. It SHALL report, where available: online state, obstruction fraction, recent outages and their causes, latency, throughput, active alerts (for example overheating, motor or power faults), stowed state, hardware and software versions, and uptime.

#### Scenario: Dish reports obstruction
- **GIVEN** the optional dish source is enabled
- **WHEN** the dish reports a significant obstruction fraction and recent outages caused by obstruction
- **THEN** Insight records both as evidence attributed to the dish

#### Scenario: Dish reports an alert
- **WHEN** the dish reports an active alert such as thermal throttling
- **THEN** Insight records the alert as an event with its time

#### Scenario: Dish reached through the router's proxy
- **GIVEN** an engineer has set the dish address to the Peplink's LAN address and dish proxy port
- **WHEN** Insight collects dish status
- **THEN** it reads the dish through that address

### Requirement: Sends only read-only requests to the dish
Insight SHALL send the dish only requests from a fixed list of read-only requests. It SHALL never send requests that change the dish's state, such as stow, reboot or configuration changes.

#### Scenario: Adapter limited to the allow-list
- **WHEN** any request is about to be sent to the dish
- **THEN** it is refused unless it is on the read-only list

### Requirement: Starlink assessment survives loss of the optional source
When the optional dish source is unavailable, disabled or returns data Insight cannot interpret, Insight SHALL still assess the Starlink connection from the Peplink link and probe data. Findings that need dish detail SHALL become "insufficient information".

#### Scenario: Dish firmware changes its interface
- **GIVEN** the dish's local status interface stops returning data Insight can interpret
- **WHEN** the Starlink link is degraded according to the Peplink router
- **THEN** Insight still reports degraded Starlink connectivity, and states that the cause cannot be determined because detailed dish data is unavailable

### Requirement: Does not use cloud-only Starlink services
The Starlink integration SHALL NOT require Starlink's cloud API or account access.

#### Scenario: Internet down
- **WHEN** the Starlink link is down and the yacht has no other internet connection
- **THEN** all Starlink information that does not depend on the internet is still collected
