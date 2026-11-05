# Spec Delta

## Purpose

Defines the plain-English view for the captain and crew. It answers whether the internet and Wi-Fi are working, whether guests are affected and whether anything needs doing, without requiring networking knowledge.

## ADDED Requirements

### Requirement: Shows overall and service status first
The crew dashboard SHALL show the overall yacht status and the status of the Internet, Guest Wi-Fi and Crew Wi-Fi services before anything else.

#### Scenario: Opening the dashboard
- **WHEN** a crew member opens Insight
- **THEN** the first thing they see is the overall status and each service's status, with the number of active issues

### Requirement: Lists active issues in plain English
The crew dashboard SHALL list open findings, most severe first, each with its title, severity, crew explanation, the areas or services affected, whether guests are affected, and since when.

#### Scenario: Failover in progress
- **WHEN** the yacht is running on its backup cellular link
- **THEN** the dashboard shows an issue explaining, in plain English, that the main internet connection is unavailable and the backup is in use

### Requirement: Uses no technical jargon
Crew-facing text SHALL NOT include IP addresses, MAC addresses, port numbers, protocol names or vendor error codes. It SHALL describe places by their tagged location and systems by everyday names.

#### Scenario: Access point problem described for crew
- **WHEN** an access point tagged "Lower deck, guest cabin 4" is offline
- **THEN** the crew explanation refers to "Wi-Fi in guest cabin 4 on the lower deck" and not to the access point's name or address

### Requirement: Says whether action is needed
Each crew-facing issue SHALL state clearly one of the following: nothing needs to be done on board; a specific simple check can be made on board; or the ETO or 50N support should be contacted.

#### Scenario: Nothing to do on board
- **WHEN** the Starlink dish is obstructed by the yacht's own structure
- **THEN** the crew explanation says the connection should recover as the yacht's heading changes, and that nothing needs to be fixed on board

### Requirement: Shows uncertainty honestly
Crew-facing text SHALL reflect each finding's confidence. Findings that are not confirmed SHALL say so in plain words. Unknown status SHALL be explained as "Insight can't currently check this", not as a fault.

#### Scenario: Monitoring unavailable
- **WHEN** the Wi-Fi services are UNKNOWN because Wi-Fi monitoring is unavailable
- **THEN** the dashboard says Insight cannot currently check the Wi-Fi, and does not say the Wi-Fi is down

### Requirement: Shows when information was last updated
The crew dashboard SHALL show when its information was last updated. It SHALL clearly indicate when that information is out of date.

#### Scenario: Stale page
- **WHEN** the dashboard has not received fresh data for longer than expected
- **THEN** it shows a clear notice that the information may be out of date

### Requirement: Refreshes automatically
The crew dashboard SHALL update automatically while open, without the user reloading the page.

#### Scenario: Issue resolves while viewing
- **WHEN** an open issue resolves while a crew member has the dashboard open
- **THEN** the dashboard updates to show it resolved without a manual reload

### Requirement: Works on phones and tablets
The crew dashboard SHALL be usable on phone, tablet and desktop screens in current mobile and desktop browsers, without installing an app.

#### Scenario: Phone screen
- **WHEN** a crew member opens the dashboard on a phone
- **THEN** the status and issues are readable without horizontal scrolling or zooming

### Requirement: Shows recently resolved issues
The crew dashboard SHALL show issues resolved in the last 24 hours, separately from active issues.

#### Scenario: Problem cleared this morning
- **WHEN** an internet outage resolved two hours ago
- **THEN** it appears under recently resolved, with when it started and ended

### Requirement: Looks like a professional marine product
The crew dashboard SHALL have a consistent, polished visual design suitable for use on a superyacht. It SHALL be usable in both light and dark appearance, including on a bridge at night.

#### Scenario: Dark appearance
- **WHEN** a device is set to dark appearance
- **THEN** the dashboard displays in a dark theme that stays legible
