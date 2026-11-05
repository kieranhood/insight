# Spec Delta

## Purpose

Maintains the list of equipment Insight monitors: how it is found and configured, where each device is on the yacht, and which crew-facing services (Internet, Guest Wi-Fi, Crew Wi-Fi) each device contributes to. Discovery suggests equipment, and an engineer confirms it.

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
Insight SHALL populate the inventory automatically from each configured source's device list. Devices found only by discovery SHALL NOT be added to the inventory unless an engineer accepts them.

#### Scenario: UniFi controller added
- **GIVEN** an engineer has added a working UniFi Network controller source
- **WHEN** Insight next collects from it
- **THEN** every switch the controller manages appears in the inventory without being entered by hand

#### Scenario: New device appears later
- **WHEN** a source reports a device that is not yet in the inventory
- **THEN** Insight adds it to the inventory and records the addition in the event timeline

### Requirement: Discovers equipment passively
Insight SHALL discover equipment passively: from device, client and address lists that configured sources already provide, and from announcements devices make on the network (for example mDNS and SSDP). Passive discovery SHALL NOT send any traffic beyond what Insight already sends to its configured sources.

#### Scenario: Device seen by the router
- **GIVEN** a configured Peplink source that reports the devices it has seen on the network
- **WHEN** an engineer opens discovery
- **THEN** devices from that list that are not in the inventory are shown as discovered

#### Scenario: Device announces itself
- **WHEN** a device on the network announces a service over mDNS or SSDP
- **THEN** Insight records it as discovered, with the announced name and service type

### Requirement: Active discovery is engineer-started and limited
Insight SHALL actively probe the network for equipment only when an engineer starts a discovery run, and only on subnets that engineer has selected. Insight SHALL ship with no subnets selected. Active discovery SHALL be rate-limited and SHALL NOT run continuously or on a schedule.

#### Scenario: Engineer starts a discovery run
- **WHEN** an engineer selects the management subnet and starts a discovery run
- **THEN** Insight probes only addresses in that subnet and reports progress until the run finishes

#### Scenario: No subnet selected
- **GIVEN** no subnet has been selected
- **WHEN** Insight is running
- **THEN** no active discovery takes place

#### Scenario: Excluded subnet
- **GIVEN** an engineer has marked a subnet as excluded, such as the guest network or a bridge network
- **WHEN** a discovery run includes a range overlapping it
- **THEN** no address in the excluded subnet is probed

### Requirement: Active discovery is non-intrusive
Active discovery SHALL use only lightweight checks: reachability, connection attempts to a defined set of known management ports, and reading publicly served banners or page titles. It SHALL NOT attempt to sign in, guess credentials (including default SNMP communities), test for vulnerabilities or change anything on a device.

#### Scenario: Device with a login page
- **WHEN** discovery finds a device serving a web login page
- **THEN** Insight reads only the publicly served page title and does not submit any credentials

### Requirement: Discovered equipment is identified with confidence
For each discovered device, Insight SHALL show its address, MAC address and name where known, how it was found, and its likely type and manufacturer with a confidence level (likely or possible). A device that cannot be identified SHALL be shown as unidentified. Insight SHALL NOT guess its type.

#### Scenario: Recognised router
- **WHEN** discovery finds a device whose banner and ports match a Peplink router
- **THEN** it is shown as "likely a Peplink router", with the evidence used to identify it

#### Scenario: Unrecognised device
- **WHEN** a discovered device matches no known signature
- **THEN** it is shown as unidentified, with what was observed

### Requirement: Discovery pre-fills guided setup
When discovery identifies a likely integration source (a Peplink router, a UniFi Network controller, a Ruckus Unleashed master access point or a Starlink dish), Insight SHALL offer to start guided setup for it with its address pre-filled. The engineer SHALL still enter credentials and Insight SHALL still test the connection.

#### Scenario: Adding a discovered controller
- **GIVEN** discovery has found a likely UniFi Network controller
- **WHEN** the engineer chooses to add it
- **THEN** guided setup opens with the controller's address filled in, and asks for credentials

### Requirement: Engineer reviews discovered equipment
An engineer SHALL be able to accept a discovered device into the inventory, monitored by probes only unless a source covers it, or dismiss it. Dismissed devices SHALL stay dismissed in later discovery results unless the engineer restores them.

#### Scenario: Accepting an unknown device
- **WHEN** an engineer accepts a discovered device and gives it a name and category
- **THEN** it appears in the inventory and is checked for reachability

#### Scenario: Dismissed device seen again
- **GIVEN** an engineer has dismissed a discovered device
- **WHEN** a later discovery run finds it again
- **THEN** it is not shown as new

### Requirement: Notices new devices passively
While running, Insight SHALL notice through passive discovery when a device that is neither in the inventory nor dismissed appears on the network. It SHALL record an event and show the device to engineers as newly discovered. It SHALL NOT add the device automatically or probe it actively.

#### Scenario: New device plugged in
- **WHEN** a new device appears in a configured source's client list
- **THEN** a "new device discovered" event is recorded and the device is listed for engineer review

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
