# Spec Delta

## Purpose

Maintains the list of equipment Insight monitors, how it is configured, where each device is on the yacht, and which crew-facing services (Internet, Guest Wi-Fi, Crew Wi-Fi) each device contributes to.

## ADDED Requirements

### Requirement: Guided setup of integration sources
Insight SHALL provide a guided setup in which an engineer adds each integration source (Peplink router, UniFi Network controller, Ruckus Unleashed, Starlink dish) by entering its address and read-only credentials. Insight SHALL test the connection before saving it.

#### Scenario: Valid source
- **WHEN** an engineer enters a reachable Peplink router address and valid credentials
- **THEN** Insight confirms the connection succeeded and saves the source

#### Scenario: Invalid credentials
- **WHEN** an engineer enters credentials the source rejects
- **THEN** Insight reports that authentication failed, in words that identify the source, and does not save it as working

### Requirement: Populates devices from sources
Insight SHALL populate the inventory automatically from each configured source's device list. It SHALL NOT scan the network to discover devices.

#### Scenario: UniFi controller added
- **GIVEN** an engineer has added a working UniFi Network controller source
- **WHEN** Insight next collects from it
- **THEN** every switch the controller manages appears in the inventory without being entered by hand

#### Scenario: New device appears later
- **WHEN** a source reports a device that is not yet in the inventory
- **THEN** Insight adds it to the inventory and records the addition in the event timeline

### Requirement: Records device details
Each inventory entry SHALL record, where the source provides it: name, manufacturer, model, device category, IP address, MAC address, firmware version, serial number, the source it came from, and its monitoring status.

#### Scenario: Engineer views a device
- **WHEN** an engineer opens a device in the inventory
- **THEN** every available detail is shown, and any detail the source does not provide is shown as not available rather than blank or invented

### Requirement: Supports manual devices
Insight SHALL allow an engineer to add a device by hand, by name, address and category, for equipment that no integration source covers. The device is then monitored by connectivity probes only.

#### Scenario: Manual device
- **WHEN** an engineer adds a device by hand with an IP address
- **THEN** it appears in the inventory and is checked for reachability

### Requirement: Tags device location
Insight SHALL allow an engineer to assign each device a location (for example deck and area) that is used in plain-English explanations.

#### Scenario: Location used in an explanation
- **GIVEN** an access point tagged with location "Main deck, saloon"
- **WHEN** a finding concerns that access point
- **THEN** the crew explanation refers to the saloon rather than to the device name or address

### Requirement: Defines services
Insight SHALL define the services Internet, Guest Wi-Fi and Crew Wi-Fi. An engineer SHALL be able to map devices, WAN links and Wi-Fi networks (SSIDs) to each service so that service health reflects them.

#### Scenario: Wi-Fi network mapped to a service
- **WHEN** an engineer maps the SSID used by guests to the Guest Wi-Fi service
- **THEN** access points broadcasting that SSID contribute to Guest Wi-Fi health

#### Scenario: Unmapped Wi-Fi network
- **GIVEN** a Wi-Fi network has not been mapped to any service
- **WHEN** the engineer views the setup
- **THEN** Insight shows the network as unmapped, so the gap is visible

### Requirement: Keeps manual tags across refreshes
Manual information (location, service mapping, display name) SHALL be kept when a source refreshes a device's details, matching devices by a stable identifier such as MAC address or serial number.

#### Scenario: Device firmware changes
- **GIVEN** a tagged access point
- **WHEN** its firmware is upgraded and the source reports new details
- **THEN** the device's details update and its manual tags remain

### Requirement: Marks devices no longer reported
When a source stops reporting a device it previously reported, Insight SHALL keep the device and mark it as no longer reported. It SHALL NOT delete it automatically.

#### Scenario: Device removed from controller
- **WHEN** a switch disappears from the UniFi controller's device list
- **THEN** the inventory keeps the switch, marked as no longer reported by its source, until an engineer removes it
