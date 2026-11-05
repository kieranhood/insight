# Spec Delta

## Purpose

Defines Insight's central feature. It combines observations from multiple systems into findings that say what is wrong, how sure Insight is, why it is likely happening and what to check next. Each finding is written in plain English for crew and backed by evidence for engineers.

## ADDED Requirements

### Requirement: Findings come from defined rules
Insight SHALL produce findings only from defined diagnostic rules. Each rule SHALL state the observations it needs, the condition it detects, its severity, its confidence and its explanation text. Explanations SHALL be produced on board without any external service.

#### Scenario: No matching rule
- **WHEN** observations do not satisfy any rule
- **THEN** Insight produces no finding and does not speculate about a problem

#### Scenario: Diagnosis while offline
- **GIVEN** the yacht has no internet connection
- **WHEN** a rule's condition is met
- **THEN** the finding and its full explanation are produced

### Requirement: Every finding states its confidence
Each finding SHALL carry exactly one confidence level:
- **confirmed**: the evidence directly shows the problem;
- **probable**: the evidence points to the problem but other explanations remain possible;
- **insufficient information**: something is wrong but the cause cannot be determined;
- **monitoring failure**: Insight cannot currently observe the system.

#### Scenario: Directly reported fault
- **WHEN** a switch reports that the port feeding an access point has lost link
- **THEN** the finding that the access point is disconnected is marked confirmed

#### Scenario: Cause cannot be determined
- **WHEN** the Starlink link is degraded and no source shows why
- **THEN** the finding is marked insufficient information and says the cause could not be determined

### Requirement: Findings never overstate certainty
Explanations SHALL match their confidence level. A finding that is not confirmed SHALL use wording such as "likely" or "may be" and SHALL NOT state a single definite root cause when several explanations are possible.

#### Scenario: Several possible causes
- **WHEN** all internet paths show packet loss and no single cause is evidenced
- **THEN** the finding lists the possible causes without naming any one as definite

### Requirement: Findings have a crew explanation and engineer detail
Each finding SHALL include:
- a crew explanation in plain English, without networking jargon, saying what is affected, whether guests or crew are affected, and whether anything should be done on board;
- engineer detail with the technical summary, likely causes, supporting evidence and suggested checks.

#### Scenario: Same finding, two audiences
- **WHEN** an access point in the saloon goes offline
- **THEN** the crew explanation says Wi-Fi may be unavailable in the saloon, and the engineer detail names the access point, its switch port and the evidence observed

### Requirement: Findings carry standard fields
Each finding SHALL include: title, severity (information, warning or critical), confidence, affected systems and services, summary, likely causes, supporting evidence, suggested next steps, time first detected, time last observed and current status.

#### Scenario: Finding detail
- **WHEN** a user opens a finding
- **THEN** every standard field appropriate to their role is shown

### Requirement: Every finding shows its evidence
Each finding SHALL reference the specific observations that triggered it, with their sources and observation times. A finding without evidence SHALL NOT be produced.

#### Scenario: Engineer checks evidence
- **WHEN** an engineer views a failover finding
- **THEN** they see the Peplink link states and health check results that triggered it, each with its source and time

### Requirement: Monitoring failures are not equipment faults
When the data a rule needs comes from a source in monitoring failure, Insight SHALL produce a monitoring failure finding for that source. It SHALL NOT produce a fault finding for the equipment.

#### Scenario: Ruckus source unreachable
- **WHEN** Insight cannot reach the Ruckus master access point over SNMP
- **THEN** it reports that Wi-Fi monitoring is unavailable, not that the Wi-Fi is down

### Requirement: Related symptoms are grouped under a likely cause
When one observed condition explains several symptoms, Insight SHALL report a single finding for the likely cause that lists the affected devices and services. It SHALL NOT report a separate finding for each symptom.

#### Scenario: Switch failure takes access points down
- **WHEN** a switch goes offline and the access points connected to it become unreachable
- **THEN** Insight reports one finding for the switch that lists the affected access points and areas, rather than one finding per access point

### Requirement: Findings have a lifecycle
A finding SHALL open when its condition has persisted for the rule's minimum duration. It SHALL resolve when the condition has been clear for the rule's clearing duration. Opening and resolution SHALL be recorded in the event timeline.

#### Scenario: Brief blip
- **WHEN** a condition is met for less than the rule's minimum duration
- **THEN** no finding is opened

#### Scenario: Problem clears
- **GIVEN** an open finding
- **WHEN** its condition has been clear for the clearing duration
- **THEN** the finding is marked resolved with the resolution time, and remains viewable in history

#### Scenario: Recurring problem
- **WHEN** a condition repeatedly opens and clears within a short period
- **THEN** Insight indicates that the problem is intermittent instead of creating a separate finding each time

### Requirement: Initial problem catalogue
Insight SHALL include rules for at least these problems:
- internet unavailable;
- primary link degraded;
- failover to a backup link;
- all internet paths degraded;
- DNS failure with IP connectivity working;
- Starlink obstructed;
- Starlink dish alert;
- weak cellular signal on the link in use;
- access point offline;
- access point lost PoE power;
- switch offline or uplink down;
- Wi-Fi congestion in an area;
- monitoring source unavailable.

#### Scenario: Failover to cellular
- **WHEN** the Peplink router moves traffic from the Starlink link to a cellular link
- **THEN** Insight reports that the main internet connection is unavailable and the yacht is using its backup cellular connection, which may be slower and may incur data costs

#### Scenario: DNS failure
- **WHEN** DNS resolution through the yacht's network fails while internet reachability by IP address succeeds
- **THEN** Insight reports that a DNS problem is suspected while basic connectivity remains available

#### Scenario: Internet working but an access point is offline
- **WHEN** WAN links and internet probes are healthy but one access point is offline
- **THEN** Insight reports that the internet is working but Wi-Fi may be unavailable in the affected area

#### Scenario: Access point lost PoE power
- **GIVEN** current PoE power data for the switch port linked to a Ruckus access point
- **WHEN** that port reports zero PoE power or link down, and the access point becomes unreachable
- **THEN** Insight reports, as confirmed, that the access point has lost power or connection from its switch, naming its location for crew and the switch and port for engineers

#### Scenario: Access point lost connection without PoE data
- **GIVEN** PoE power data is not available, and the access point's port is known from LLDP or an engineer's record
- **WHEN** that port reports link down and the access point becomes unreachable
- **THEN** Insight reports, as probable, that the access point has lost power or connection from its switch

#### Scenario: Starlink obstruction without dish data
- **GIVEN** the optional dish source is unavailable
- **WHEN** the Starlink link is degraded
- **THEN** the obstruction rule does not fire, and the degradation is reported with insufficient information about its cause

#### Scenario: Wi-Fi congestion needs optional data
- **GIVEN** the optional Ruckus web interface source is unavailable
- **WHEN** Insight evaluates Wi-Fi congestion
- **THEN** no congestion finding is produced, because channel utilisation and client data are not available
