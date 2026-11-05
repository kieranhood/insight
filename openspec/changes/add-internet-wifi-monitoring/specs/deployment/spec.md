# Spec Delta

## Purpose

Defines how Insight is packaged, installed, run, updated and kept running on a dedicated on-board host, so that it operates reliably without an internet connection.

## ADDED Requirements

### Requirement: Runs as a Docker container
Insight SHALL be distributed as a Docker image and SHALL be startable on a Linux host with Docker and Docker Compose using a single provided Compose file. No other software needs to be installed on the host.

#### Scenario: Fresh installation
- **GIVEN** a Linux host with Docker and Docker Compose installed
- **WHEN** an installer places the provided Compose file on the host and starts it
- **THEN** Insight starts and its web interface becomes reachable on the host's configured address and port

### Requirement: Operates without internet access
Insight SHALL perform all monitoring, diagnosis, storage and presentation on board. It SHALL NOT depend on any external internet service in order to run, start or serve its interface.

#### Scenario: Yacht has no internet connection
- **GIVEN** every internet link on the yacht is down
- **WHEN** a crew member opens Insight on the yacht's network
- **THEN** the interface loads, shows current findings, and continues to collect data from on-board systems

#### Scenario: Interface assets are local
- **WHEN** the web interface loads
- **THEN** every script, stylesheet, font and image it uses is served by Insight itself rather than fetched from an external host

### Requirement: Data persists across restarts and upgrades
Insight SHALL store its configuration, history, inventory, accounts and credentials in a persistent volume that survives container restarts, image upgrades and host reboots.

#### Scenario: Image upgrade keeps data
- **GIVEN** Insight has been running with configured sources and recorded history
- **WHEN** the container is replaced with a newer Insight image using the same volume
- **THEN** configuration, accounts, inventory and history are all still present

### Requirement: Restarts automatically
Insight SHALL be configured to restart automatically after a crash, a Docker restart or a host power cycle, without manual intervention.

#### Scenario: Host loses power
- **GIVEN** Insight is running
- **WHEN** the host loses power and then boots again
- **THEN** Insight starts automatically and resumes monitoring

### Requirement: Exposes a container health check
Insight SHALL provide a container health check that reports unhealthy when its web interface or its collection scheduler has stopped working.

#### Scenario: Collection stalls
- **GIVEN** Insight's web process is running
- **WHEN** no collection cycle has completed within three times the configured polling interval
- **THEN** the container health check reports unhealthy

### Requirement: Supports offline upgrades
Insight SHALL be upgradeable both by pulling an image from a registry when internet access is available and by loading an image from a file when it is not.

#### Scenario: Upgrade from a file
- **GIVEN** the yacht has no internet connection
- **WHEN** an engineer loads a new Insight image from a file onto the host and restarts the Compose service
- **THEN** the new version runs with existing data intact

### Requirement: Reports its own version
Insight SHALL display its version in the engineer console and expose it through its health endpoint.

#### Scenario: Engineer checks version
- **WHEN** an engineer views the engineer console
- **THEN** the running Insight version is shown
