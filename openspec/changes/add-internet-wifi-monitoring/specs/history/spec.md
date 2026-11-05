# Spec Delta

## Purpose

Defines how Insight keeps a record on board of past readings, events and findings. Engineers and crew can then see what happened while nobody was watching, or while the yacht was offline.

## ADDED Requirements

### Requirement: Stores readings over time
Insight SHALL store collected metrics with their observation times so that past values can be viewed. Examples include latency, packet loss, WAN state, client counts, PoE power and dish obstruction.

#### Scenario: Latency history
- **WHEN** an engineer views the Starlink link's latency for the past 24 hours
- **THEN** stored readings for that period are shown

### Requirement: Keeps an event timeline
Insight SHALL record a time-ordered timeline of significant events, each with its time, source, affected devices or services, and description. Events include:
- failovers;
- device and port state changes;
- access point disconnections;
- dish alerts;
- status changes;
- findings opened and resolved;
- monitoring failures and recoveries;
- inventory changes.

#### Scenario: Outage reconstructed
- **GIVEN** an internet outage happened overnight
- **WHEN** an engineer views the timeline for that night
- **THEN** they see the sequence of events in order, such as the Starlink link failing, failover to cellular, the finding opening, recovery and the finding resolving

### Requirement: Timeline can be filtered
The event timeline SHALL be filterable by time range, system, device, service and event type.

#### Scenario: Filter to one access point
- **WHEN** an engineer filters the timeline to a single access point over the last week
- **THEN** only events concerning that access point in that period are shown

### Requirement: Keeps resolved findings
Resolved findings SHALL remain viewable, with their full evidence and explanation, for the retention period.

#### Scenario: Yesterday's problem
- **WHEN** a crew member reports a problem that has since cleared
- **THEN** an engineer can open the resolved finding and see its evidence

### Requirement: Applies defined retention
Insight SHALL keep detailed readings for at least 30 days, and daily summaries of readings, events and findings for at least 365 days. Older data SHALL be removed automatically. An engineer SHALL be able to change these periods.

#### Scenario: Detailed data ages out
- **WHEN** detailed readings become older than the detailed retention period
- **THEN** they are removed, and their daily summaries remain

### Requirement: Protects available disk space
Insight SHALL monitor the free space available to its data store. It SHALL warn engineers before space runs out and SHALL continue to record the newest data rather than stopping when space is low.

#### Scenario: Disk nearly full
- **WHEN** free space falls below a safe threshold
- **THEN** a finding warns engineers, and Insight removes the oldest detailed readings first to keep recording

### Requirement: Records gaps in monitoring
Periods when Insight itself was not running, or a source was in monitoring failure, SHALL be visible in history as gaps. They SHALL NOT appear as periods of normal or faulty operation.

#### Scenario: Insight restarted
- **GIVEN** Insight was stopped for two hours
- **WHEN** an engineer views readings covering that period
- **THEN** the two hours are shown as having no data
