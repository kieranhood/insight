# Spec Delta

## Purpose

Controls who can use Insight and what they can see, with a plain-English crew role and a technical engineer role, and protects the device credentials Insight holds.

## ADDED Requirements

### Requirement: Requires sign-in
Insight SHALL require users to sign in with a local account before showing any yacht information. The only exception is the container health endpoint, which reveals no yacht data.

#### Scenario: Unauthenticated access
- **WHEN** someone who is not signed in opens any Insight page
- **THEN** they are shown the sign-in page and no yacht information

### Requirement: Provides crew and engineer roles
Every account SHALL have exactly one role: crew or engineer. The crew role SHALL grant access to the crew dashboard. The engineer role SHALL grant access to the crew dashboard and the engineer console.

#### Scenario: Crew user opens the engineer console
- **GIVEN** a user signed in with the crew role
- **WHEN** they request an engineer console page
- **THEN** access is refused and no technical detail is returned

#### Scenario: Engineer user
- **GIVEN** a user signed in with the engineer role
- **WHEN** they navigate Insight
- **THEN** both the crew dashboard and the engineer console are available

### Requirement: Restricts administration to engineers
Only engineer accounts SHALL be able to create, change or remove accounts, integration sources, credentials, device tags and settings.

#### Scenario: Crew user tries to change a setting
- **GIVEN** a user signed in with the crew role
- **WHEN** they attempt to change any configuration
- **THEN** the change is refused

### Requirement: Creates the first engineer account on first run
On first start, with no accounts present, Insight SHALL require an initial engineer account to be created before it can be used. It SHALL NOT ship with a default password.

#### Scenario: First start
- **GIVEN** a new installation with no accounts
- **WHEN** the web interface is opened
- **THEN** the user is asked to create an engineer account, and no other page is available until they do

### Requirement: Stores passwords securely
Insight SHALL store account passwords only as salted hashes produced by a password-hashing algorithm designed for that purpose. It SHALL NOT store or display them in plain text.

#### Scenario: Stored passwords are not readable
- **WHEN** the persistent data is inspected directly
- **THEN** no account password is present in readable form

### Requirement: Protects device credentials
Insight SHALL encrypt stored device credentials (API keys, passwords, SNMP community strings) at rest. Once entered, a credential SHALL NOT be displayed again in the interface or returned by any API.

#### Scenario: Engineer views a configured source
- **GIVEN** a configured Peplink source with stored credentials
- **WHEN** an engineer opens that source's settings
- **THEN** the credential is shown masked and can only be replaced, not revealed

### Requirement: Limits sign-in attempts
Insight SHALL slow down or temporarily block repeated failed sign-in attempts for an account.

#### Scenario: Repeated wrong password
- **WHEN** an account has five consecutive failed sign-in attempts within ten minutes
- **THEN** further attempts for that account are refused for a period of time

### Requirement: Expires sessions
Signed-in sessions SHALL expire after a period of inactivity, and users SHALL be able to sign out explicitly.

#### Scenario: Idle session
- **GIVEN** a signed-in user
- **WHEN** their session has been inactive for longer than the configured timeout
- **THEN** their next request requires them to sign in again

### Requirement: Serves the interface over HTTPS
Insight SHALL serve its web interface over HTTPS. It SHALL use a self-generated certificate unless an engineer installs one.

#### Scenario: Plain HTTP request
- **WHEN** a browser requests Insight over plain HTTP
- **THEN** it is redirected to HTTPS

### Requirement: Opens no inbound route from the internet
Insight SHALL NOT create, request or require any inbound access from the internet. Remote engineers reach it only through a remote-access route provided separately on the yacht's network.

#### Scenario: Remote engineer access
- **GIVEN** a 50N engineer connected to the yacht's network through 50N's remote-access route
- **WHEN** they open Insight's address
- **THEN** they sign in with an engineer account exactly as they would on board
