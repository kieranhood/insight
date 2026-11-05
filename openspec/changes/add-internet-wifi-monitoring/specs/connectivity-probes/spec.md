# Spec Delta

## Purpose

Defines the active tests Insight runs itself from the yacht's network: device reachability, internet reachability, DNS and HTTP. They provide vendor-independent evidence of what the crew actually experiences.

## ADDED Requirements

### Requirement: Checks device reachability
Insight SHALL periodically check that every inventory device with an IP address is reachable. It SHALL record round-trip time and loss for each check.

#### Scenario: Device stops responding
- **WHEN** a device fails consecutive reachability checks
- **THEN** Insight records it as unreachable, with the check results as evidence

#### Scenario: Single lost check
- **WHEN** a device misses one check but answers the next
- **THEN** Insight does not record the device as unreachable

### Requirement: Checks internet reachability
Insight SHALL periodically test reachability of several independent internet targets, configurable by an engineer, and record latency and loss. Internet reachability SHALL only be considered lost when every target fails.

#### Scenario: One target down
- **WHEN** one internet target fails but the others respond
- **THEN** Insight does not report the internet as unreachable

#### Scenario: All targets down
- **WHEN** every internet target fails consecutive checks
- **THEN** Insight records internet reachability as lost from the yacht's network

### Requirement: Checks DNS resolution
Insight SHALL periodically resolve configured test names, both through the DNS server the yacht's network provides and through at least one independent public resolver. It SHALL record success, failure and response time for each.

#### Scenario: Local DNS failing
- **WHEN** resolution through the yacht's DNS server fails, a public resolver succeeds, and internet reachability by IP address succeeds
- **THEN** Insight records evidence that DNS resolution on the yacht's network is failing while IP connectivity works

### Requirement: Checks HTTP access
Insight SHALL periodically fetch one or more configured web addresses and record success, status and response time. This shows whether ordinary web access works from the yacht's network.

#### Scenario: Web access slow
- **WHEN** HTTP checks succeed but take far longer than their recent normal
- **THEN** Insight records the slowdown as evidence of degraded internet performance

### Requirement: Labels probe results by vantage point
Probe results SHALL be labelled as measured from Insight's position on the yacht's network, through whichever WAN link is in use at the time. They SHALL NOT be presented as a test of any particular WAN link.

#### Scenario: Probe evidence shown
- **WHEN** an engineer views internet probe evidence
- **THEN** it states which WAN link was in use when each result was measured, where known

### Requirement: Probe settings are configurable
An engineer SHALL be able to change probe targets and intervals. Insight SHALL provide sensible defaults so that probes work without configuration.

#### Scenario: Default probes
- **GIVEN** a new installation with no probe settings changed
- **WHEN** Insight runs
- **THEN** internet, DNS and HTTP probes run with default targets
