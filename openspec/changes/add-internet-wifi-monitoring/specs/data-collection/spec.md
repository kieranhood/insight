# Spec Delta

## Purpose

Defines how Insight gathers data from on-board systems through vendor-specific adapters into one vendor-neutral model, while never changing device configuration and always knowing whether the data it holds is current.

## ADDED Requirements

### Requirement: One adapter per integration
Insight SHALL collect data from each vendor through its own adapter. Each adapter SHALL deliver data in a common, vendor-neutral model of devices, interfaces, WAN links, Wi-Fi networks, access points, clients, metrics and events. Diagnostics, health status and the views SHALL use only that common model.

#### Scenario: Diagnosis is vendor-neutral
- **GIVEN** an access point offline rule
- **WHEN** an access point reported by any Wi-Fi adapter goes offline
- **THEN** the same rule applies regardless of which vendor reported it

### Requirement: Integrations are read-only
Adapters SHALL only read information. They SHALL NOT change configuration, reboot devices, or invoke any operation that alters the state of a monitored system.

#### Scenario: Adapter capabilities
- **WHEN** any adapter communicates with a monitored system
- **THEN** it uses only read operations, and the configured credentials need only read-only permission where the system supports it

### Requirement: Polls on a schedule
Insight SHALL poll each source on a configurable interval with a sensible default for each source. It SHALL respect any rate limits the source documents.

#### Scenario: Default polling
- **WHEN** a source is configured without a custom interval
- **THEN** Insight polls it at that adapter's default interval

### Requirement: Records collection timestamps
Every collected value SHALL carry the time it was observed. Every source SHALL record when it was last collected successfully.

#### Scenario: Stale data shown
- **WHEN** a value is displayed
- **THEN** the time it was last updated is available alongside it

### Requirement: Detects monitoring failures
Insight SHALL treat a source it cannot reach, cannot authenticate to, or receives unparseable data from as a monitoring failure. It SHALL NOT treat that as a fault in the devices that source reports.

#### Scenario: Controller unreachable
- **GIVEN** the UniFi Network controller stops responding
- **WHEN** a collection cycle fails
- **THEN** Insight records a monitoring failure for that source, marks the data it reports as stale, and does not report the switches as offline on that basis alone

#### Scenario: Source recovers
- **WHEN** a source with a monitoring failure is collected successfully again
- **THEN** the monitoring failure is resolved and recorded in the event timeline

### Requirement: Distinguishes reliable from optional sources
Each data source SHALL be classified as reliable (an official or standard interface) or optional (an unofficial interface that may change without notice). Optional sources SHALL only add information. Insight SHALL continue to work correctly when an optional source fails.

#### Scenario: Optional source breaks after firmware update
- **GIVEN** an optional source that returns unrecognised data after a firmware update
- **WHEN** collection from it fails
- **THEN** Insight keeps collecting from reliable sources, records the optional source as unavailable, and findings that needed only that source become "insufficient information"

#### Scenario: Engineer can see source type
- **WHEN** an engineer views a configured source
- **THEN** Insight shows whether it is reliable or optional

### Requirement: Only collects what an integration supports
Insight SHALL collect only metrics that an integration actually provides. Where a metric is not available from any source, Insight SHALL show it as not available. It SHALL NOT estimate or invent it.

#### Scenario: Metric not provided
- **GIVEN** a source that does not report per-client signal strength
- **WHEN** an engineer views client details
- **THEN** signal strength is shown as not available

### Requirement: Isolates adapter failures
A failure, timeout or error in one adapter SHALL NOT stop or delay collection from other adapters.

#### Scenario: One source times out
- **WHEN** the Ruckus source times out
- **THEN** Peplink, UniFi and Starlink collection continues on schedule
