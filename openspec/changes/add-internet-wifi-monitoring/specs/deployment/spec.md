# Spec Delta

## Purpose

Defines how Insight is packaged, installed, run, updated and kept running on a dedicated on-board host, so that it operates reliably without an internet connection. The host is a 50N-managed appliance that protects Insight's software and data from being copied.

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

### Requirement: Supplied as a managed appliance
Insight SHALL be supplied as an appliance that 50N Systems owns and administers. The client's crew and IT staff SHALL have access only to Insight's web interface. They SHALL NOT be given operating-system, shell or Docker access to the host.

#### Scenario: Client user on the host
- **WHEN** anyone other than a 50N administrator tries to sign in to the host's operating system, locally or over the network
- **THEN** no account is available to them, and only Insight's web interface is offered

#### Scenario: Docker access
- **WHEN** the host's accounts are inspected
- **THEN** only 50N administrator accounts can run Docker commands

### Requirement: Remote shell access is key-only and 50N-only
Remote shell access to the host SHALL accept only key-based authentication with keys held by 50N Systems. Password authentication and direct root sign-in SHALL be disabled.

#### Scenario: Password sign-in attempt
- **WHEN** someone attempts to open a remote shell to the host with a password
- **THEN** the attempt is refused

### Requirement: Storage is encrypted at rest
The host's disk SHALL be fully encrypted. It SHALL unlock automatically at boot using the host's built-in security chip (TPM), so that Insight starts unattended after a power cut. A recovery key SHALL be held only by 50N Systems.

#### Scenario: Unattended boot
- **WHEN** the host powers on after a power cut
- **THEN** the disk unlocks without anyone entering a passphrase and Insight starts

#### Scenario: Disk removed
- **WHEN** the disk is removed and connected to another computer
- **THEN** its contents, including Insight's software and data, cannot be read without 50N's recovery key

### Requirement: Boot is locked to the internal disk
The host SHALL boot only from its internal disk with Secure Boot enabled. Its firmware settings SHALL be protected by a password held by 50N Systems, and booting from USB or other external media SHALL be disabled.

#### Scenario: USB boot attempt
- **WHEN** someone connects a USB drive and tries to boot the host from it
- **THEN** the host does not boot from the USB drive, and firmware settings cannot be changed without the 50N password

### Requirement: Shows ownership and licence notice
Insight SHALL show a notice stating that it is proprietary software of 50N Systems, licensed for use on that yacht only, with copying and reverse engineering prohibited. The notice SHALL appear on the sign-in page and on an about page available to all users.

#### Scenario: Sign-in page
- **WHEN** anyone opens Insight's sign-in page
- **THEN** the 50N Systems copyright and licence notice is visible
