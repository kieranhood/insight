# Tasks

## 1. Interface verification

- [ ] 1.1 Verify the Peplink local router API against Peplink's documentation and, where possible, the on-board router's firmware. Cover: how to enable it, authentication, WAN status, health checks, link in use, cellular signal, usage, client/DHCP/ARP lists (for discovery) and rate limits. Record findings and sample responses in `docs/integrations/peplink.md`. Verify the doc lists each spec item as available or not available.
- [ ] 1.2 Verify the UniFi Network controller's local API: the official Network API, with the classic API checked for port PoE, LLDP neighbours and uplinks. Also verify switch SNMP (IF-MIB, LLDP-MIB, POWER-ETHERNET-MIB), plus the controller's client list (for discovery). Record the controller's location on board, findings and samples in `docs/integrations/unifi.md`. Verify the doc states which fields come from a reliable source and which from an optional one.
- [ ] 1.3 Verify Ruckus Unleashed SNMP OIDs on the master AP, the syslog message formats for AP join, leave and reboot (including whether the port is configurable), and `aioruckus` data for APs, WLANs and clients. Record findings and samples in `docs/integrations/ruckus-unleashed.md`. Verify the doc includes sample syslog lines for each event type.
- [ ] 1.4 Verify the Starlink dish's local gRPC status interface: fields for obstruction, outages, alerts and stowed state, plus reachability from the LAN, including any Peplink static route needed. Record findings and samples in `docs/integrations/starlink.md`. Verify the doc includes a captured status response.
- [ ] 1.5 Capture identification signatures for discovery: MAC vendor prefixes, open management ports, HTTP page titles, TLS certificate subjects and mDNS/SSDP service types for the Peplink router, UniFi Network controller, Ruckus Unleashed master and Starlink dish. Record them in `docs/integrations/discovery.md`. Verify each of the four has at least two independent signatures.

## 2. Project scaffold and container

- [x] 2.1 Create the Python 3.12 project: `pyproject.toml`, the `insight/` package layout, linting (ruff), type checking (mypy) and pytest. Verify `pytest` and `ruff check` run cleanly on the empty project.
- [x] 2.2 Add a FastAPI app with a `/healthz` endpoint that reports the version and the time of the last collection cycle, with no yacht data. Verify with a test that `/healthz` returns the version and no inventory or finding data.
- [x] 2.3 Write a Dockerfile (`python:3.12-slim`, non-root user, `HEALTHCHECK` calling `/healthz`) and `compose.yaml`: host networking, `restart: unless-stopped`, the `insight-data:/data` volume, and the `NET_RAW` and `NET_BIND_SERVICE` capabilities. Verify `docker compose up` starts the container and it reports healthy.
- [ ] 2.4 Add a CI workflow that runs lint, type checks and tests, then builds the image. Verify the workflow passes on the branch.

## 3. Storage and common model

- [x] 3.1 Define the common model types (Source, Device, Port, WanLink, WifiNetwork, AccessPoint, Client, Metric, Event), each with `observed_at` and a reliability class. Verify unit tests construct each type and reject missing timestamps.
- [x] 3.2 Implement the SQLite schema (WAL mode) with versioned, forward-only migrations applied at startup, plus an automatic backup taken before any migration. Verify a test that migrating an empty database succeeds and creates a backup file.
- [x] 3.3 Implement the single-writer persistence task with batched inserts for metrics and events. Verify a test that inserts 10,000 metrics in a batch and reads them back.
- [x] 3.4 Implement the current-state store. It holds the latest snapshot per source with its freshness, compares snapshots to emit events, and merges devices across sources by MAC address, then serial number. Verify unit tests covering port-down and failover event emission, and the merge of a device seen by two sources.
- [x] 3.5 Implement the topology graph, built from uplink and neighbour data with manual overrides. Verify a test that resolves "APs downstream of switch X" from a fixture.
- [x] 3.6 Store times in UTC and add a ship's-time zone setting used for display. Verify a test that formats a stored timestamp in two different ship's-time zones.

## 4. Access control

- [x] 4.1 Implement accounts with crew and engineer roles, Argon2id password hashing, and a first-run flow that requires an engineer account to be created. Verify tests: no default credentials exist, the first-run page blocks every other page, and stored hashes are not plain text.
- [x] 4.2 Implement sessions: secure cookies, CSRF tokens, idle timeouts and sign-out. Verify tests that an expired session redirects to sign-in and that a form post without a CSRF token is rejected.
- [x] 4.3 Enforce the engineer role on the server for every engineer and configuration route. Verify a test that requests every engineer route as a crew user and expects refusal.
- [x] 4.4 Implement sign-in throttling: five failures in ten minutes locks the account for a period. Verify a test that the sixth attempt is refused even with the correct password.
- [x] 4.5 Implement device-credential encryption at rest. The key is generated on first run and stored in `/data/secret.key` with mode 0600. Credentials are masked in the UI and never returned by any API. Verify tests that the database contains no plain-text credential and that the API response masks it.
- [x] 4.6 Implement HTTPS with a self-signed certificate generated on first run, an HTTP-to-HTTPS redirect, and upload of a replacement certificate. Verify a test that plain HTTP redirects, and manually check that an uploaded certificate is served.

## 5. Collection framework and simulator

- [ ] 5.1 Implement the adapter interface and scheduler: one task per source, per-source intervals with jitter, timeouts, and isolation so one adapter's failure doesn't affect others. Verify a test in which a hanging adapter does not delay a second adapter's cycles.
- [ ] 5.2 Implement monitoring-failure detection for unreachable sources, authentication failures and unparseable data, including staleness marking and recovery events. Verify tests for each failure type and for recovery.
- [ ] 5.3 Implement the reliable/optional classification: an optional adapter failing never blocks reliable collection. Verify a test in which an optional adapter raises errors while reliable data keeps updating.
- [ ] 5.4 Implement the simulator source, which replays scripted scenarios (failover, AP PoE loss, dish obstruction, controller outage, DNS failure) through the full pipeline. Verify that the simulator runs each scenario and emits the expected events.
- [ ] 5.5 Wire the collection-cycle timestamp into `/healthz` so the container reports unhealthy after three missed intervals. Verify a test that stalls the scheduler and expects an unhealthy response.

## 6. Device inventory and setup

- [ ] 6.1 Implement the guided source setup: enter address and credentials, test the connection, report errors in plain words naming the source, and save the source. Verify tests for success, bad credentials and an unreachable address, using a fake adapter.
- [ ] 6.2 Implement inventory population from sources: add new devices with a timeline event, update details, and mark devices no longer reported. Verify tests for each case.
- [ ] 6.3 Implement manual devices that are monitored by probes only. Verify a test that a manual device appears in the inventory and is scheduled for reachability checks.
- [ ] 6.4 Implement location tags, display names and service definitions (Internet, Guest Wi-Fi, Crew Wi-Fi). Services map to devices, WAN links and SSIDs, and unmapped SSIDs are flagged. Manual tags persist across refreshes. Verify tests that tags survive a firmware-change refresh and that unmapped SSIDs are listed.

## 7. Peplink adapter

- [ ] 7.1 Implement the Peplink adapter for router details, WAN links (state, type, priority), health checks, the link in use, cellular signal and usage, mapped into the common model. Verify parser tests against the samples recorded in task 1.1.
- [ ] 7.2 Emit failover events when the link in use changes. Verify a fixture-pair test that produces one failover event with both link names.

## 8. UniFi adapter

- [ ] 8.1 Implement the UniFi controller adapter for switch details, port state and counters, PoE per port and budget, LLDP neighbours and uplinks, mapped into the common model, using the reliable/optional split decided in task 1.2. Verify parser tests against the task 1.2 samples.
- [ ] 8.2 Implement the SNMP fallback for UniFi switches (availability, port state, traffic; PoE and LLDP where available). Verify parser tests against the recorded SNMP walks.
- [ ] 8.3 Feed neighbour and uplink data into the topology graph. Verify a test that links a Ruckus AP to its UniFi switch port from a fixture.

## 9. Ruckus Unleashed adapter

- [ ] 9.1 Implement the Ruckus SNMP adapter on the master AP: AP counts, registered count, client totals and master details. Verify parser tests against the task 1.3 samples.
- [ ] 9.2 Implement the syslog UDP receiver and Ruckus message patterns for AP join, leave and reboot. Unrecognised lines are stored as raw events. Verify tests against the sample lines from task 1.3, including an unrecognised line.
- [ ] 9.3 Implement the optional `aioruckus` adapter for per-AP details, channels and utilisation, WLANs, and clients with AP, SSID, band and signal. Verify parser tests, plus a test that a parse failure leaves the SNMP and syslog data intact.
- [ ] 9.4 Populate Ruckus APs from the optional source, or from UniFi neighbours and manual entry when it is disabled. Verify tests for both modes.

## 10. Starlink adapter

- [ ] 10.1 Implement Starlink link attribution, so an engineer can mark the Peplink WAN that is Starlink, and dish reachability checks. Verify a test that the marked link's health check results are attributed to Starlink.
- [ ] 10.2 Implement the optional dish gRPC adapter for online state, obstruction, outages, latency, throughput, alerts, stowed state, versions and uptime. Verify parser tests against the task 1.4 sample, plus a test that a malformed response marks only the optional source as failed.

## 11. Connectivity probes

- [ ] 11.1 Implement device reachability probes for all inventory devices with an IP address, with a consecutive-failure threshold. Verify tests that one lost check does not mark a device unreachable but consecutive failures do.
- [ ] 11.2 Implement internet reachability probes against several configurable targets, reporting loss only when all targets fail. Verify a test with one target failing and a test with all failing.
- [ ] 11.3 Implement DNS probes via the system resolver and an independent public resolver. Verify a test that the local-fail/public-succeed case produces the "DNS failing while IP works" evidence.
- [ ] 11.4 Implement HTTP probes with response-time baselines, label every probe result with the WAN link in use, and provide default targets and editable settings. Verify tests for the slowdown evidence and for link labelling.

## 12. Discovery

- [ ] 12.1 Implement source-derived passive discovery from the Peplink and UniFi client and address lists (where task 1 confirms they exist), matched to the inventory by MAC address then IP address. Verify tests that a client absent from the inventory is listed as discovered and an inventory device is not.
- [ ] 12.2 Implement the mDNS and SSDP listeners, recording announced names and service types. Verify tests that feed recorded announcement packets and check the discovered entries.
- [ ] 12.3 Implement the active sweep: engineer-started runs on selected subnets only; no subnets selected by default; exclusions override selections; a /22 cap; rate limiting; connect-only checks on the fixed port list; HTTP title and TLS subject reads; cancellation; and a timeline entry naming who started the run. Verify tests that excluded and unselected addresses are never contacted, that the rate limit holds, and that no request carries credentials.
- [ ] 12.4 Implement the fingerprint signature table and matching (likely, possible, unidentified, with the evidence used), loaded from data, using the task 1.5 signatures. Verify tests that recorded observations of each of the four source types give "likely", and that an unmatched device gives "unidentified".
- [ ] 12.5 Implement the engineer review flow. Discovered devices can be accepted as probe-only inventory devices or dismissed, and dismissals persist by MAC address. Recognised sources offer guided setup with the address pre-filled. Verify view tests for accept, dismiss, rediscovery of a dismissed device and the pre-filled setup.
- [ ] 12.6 Implement passive new-device notices: a timeline event and an entry in the review list, with no automatic adoption or active probing. Verify a simulator scenario that adds a client and checks for the event and review entry, and that no probe traffic is sent to it.
- [ ] 12.7 Write `docs/discovery.md`: what each discovery layer does and sends, which subnets to select or exclude, and telling the yacht's IT contact before an active run. Verify the doc's limits match the implemented defaults (no subnets selected, /22 cap, rate limit).

## 13. History and retention

- [ ] 13.1 Implement metric history queries by series and time range, returning only the requested range. Verify a test that a 24-hour query returns only that range.
- [ ] 13.2 Implement the event timeline with filters for time, system, device, service and event type. Verify filter tests for each dimension.
- [ ] 13.3 Implement the nightly job that builds daily rollups, enforces the 30-day detail and 365-day summary retention (both configurable) and runs incremental vacuuming. Verify a test that ages out data and keeps its rollups.
- [ ] 13.4 Implement free-space monitoring with a low-disk finding and oldest-first pruning. Verify a test that simulates low space and checks that pruning happens and the finding is raised.
- [ ] 13.5 Represent gaps in history, both while Insight was stopped and during monitoring failures. Verify a test that a two-hour stop appears as a gap in a chart query.

## 14. Diagnostic engine

- [ ] 14.1 Implement the rule base class and metadata (`requires`, durations, severity, `explains`), plus Jinja2 crew and engineer templates for each rule. Verify a test rule that renders both templates from finding facts.
- [ ] 14.2 Implement the evaluation pipeline: freshness checks; monitoring-failure findings; insufficient-information downgrade and skipping of rules whose optional data is essential; evaluation; grouping of symptoms under causes; durations and flapping detection; persistence of finding changes. Verify unit tests for each stage.
- [ ] 14.3 Implement the finding lifecycle (open, last observed, resolved, intermittent) with timeline events. Verify tests for a brief blip, resolution after the clearing duration, and intermittent marking.
- [ ] 14.4 Add a wording lint test: crew templates must not contain IP or MAC address patterns, port numbers or protocol names, and non-confirmed templates must use hedged wording. Verify the test fails on a deliberately bad template.

## 15. Initial rule catalogue

- [ ] 15.1 Implement the internet rules: internet unavailable, primary link degraded, failover to backup (with a data-cost note), and all paths degraded. Verify simulator scenario tests for each.
- [ ] 15.2 Implement the DNS failure rule. Verify the simulator's DNS scenario produces the finding with the correct confidence and evidence.
- [ ] 15.3 Implement the Starlink rules: obstructed and dish alert, which need the optional source, and the degraded-with-unknown-cause fallback. Verify tests with the dish source both available and unavailable.
- [ ] 15.4 Implement the weak-cellular-signal-on-active-link rule. Verify a scenario test.
- [ ] 15.5 Implement the Wi-Fi infrastructure rules: AP offline, AP lost PoE (confirmed, cross-vendor), and switch offline or uplink down, grouping the affected APs. Verify the PoE-loss scenario produces one confirmed finding naming the location for crew and the switch and port for engineers, and that a switch outage produces one grouped finding.
- [ ] 15.6 Implement the Wi-Fi congestion rule, which needs optional Ruckus data. Verify it fires on high channel utilisation and does not fire when the optional source is unavailable.
- [ ] 15.7 Implement the monitoring-source-unavailable rule. Verify the controller outage scenario produces a monitoring-failure finding and no switch-offline findings.
- [ ] 15.8 Document each rule (purpose, inputs, thresholds, confidence logic, wording) in `docs/rules.md`. Verify the doc covers every rule in the catalogue.

## 16. Health status

- [ ] 16.1 Implement system, service and overall status calculation with HEALTHY, DEGRADED, CRITICAL and UNKNOWN, including UNKNOWN for stale data and unmapped services. Verify tests for each spec scenario (failover gives DEGRADED, Wi-Fi monitoring lost gives UNKNOWN, worst-of for overall).
- [ ] 16.2 Attach the responsible findings and last-updated time to each status, and record status changes in the timeline. Verify a test that a DEGRADED service lists its findings and that a status change creates an event.

## 17. Crew dashboard

- [ ] 17.1 Build the shared UI foundation: layout, design tokens for light and dark themes, a professional marine visual style, local assets only (vendored htmx and uPlot), and SSE live updates with a polling fallback. Verify a test that a page load makes no external requests, and manually check both themes.
- [ ] 17.2 Build the crew dashboard: overall and service status first, active issues sorted by severity with crew explanations and an action-needed statement, a recently resolved section covering 24 hours, last-updated time and a stale-data notice. Verify view tests against simulator scenarios.
- [ ] 17.3 Verify mobile usability with Playwright screenshots at phone, tablet and desktop widths: no horizontal scrolling, and status and issues readable.

## 18. Engineer console

- [ ] 18.1 Build the findings views: open and resolved findings with full detail, the rule, confidence, evidence with sources and times, and suggested checks. Verify view tests using the PoE-loss scenario.
- [ ] 18.2 Build the inventory list with search and filters, and device detail pages with readings, history charts, related findings and events, plus switch port detail with PoE and neighbours. Verify view tests, including search by IP address.
- [ ] 18.3 Build the WAN links view (side-by-side state, health, latency, loss, usage, link in use, failover history) and the timeline view with filters. Verify view tests.
- [ ] 18.4 Build the sources and monitoring health view (type, last success, state, last error) and the version display. Verify a view test with a failing optional source.
- [ ] 18.5 Build the configuration screens: source setup, credentials, locations and service mapping, Starlink link marking, probes, retention, ship's time, users and the certificate. Verify view tests that each setting saves and takes effect.
- [ ] 18.6 Check slow-link behaviour: measure page weight and confirm history is fetched by range. Verify that a scripted check keeps the findings and timeline pages under the agreed size budget, e.g. 200 KB excluding cached assets.

## 19. Managed appliance and licence notice

- [ ] 19.1 Add a proprietary `LICENSE` (all rights reserved, 50N Systems; wording to be legally reviewed), a copyright and licence notice on the sign-in page and an about page available to all users, and an OCI licence label on the image. Verify a test that the sign-in and about pages show the notice, and that `docker inspect` shows the label.
- [ ] 19.2 Write the appliance provisioning playbook (Ansible) for Debian stable. It installs Docker, sets NTP from the Peplink and unattended security upgrades, creates a single `50n-admin` account that is the only member of `docker`, and applies an SSH policy that is key-only with no root login. Verify on a clean VM that password SSH and root SSH are refused, and that only `50n-admin` can run `docker ps`.
- [ ] 19.3 Add full-disk encryption (LUKS2) with TPM 2.0 auto-unlock bound to PCR 7, and generate and record the recovery key. Verify on a test mini-PC that it boots unattended after a power cut, that the disk is unreadable when attached to another machine, and that the recovery key unlocks it.
- [ ] 19.4 Write the firmware lock checklist: Secure Boot on, firmware password set, USB and network boot disabled, boot order locked. Verify on a test mini-PC that a USB boot attempt fails and that firmware settings require the password.
- [ ] 19.5 Write `docs/appliance.md` covering provisioning, the firmware checklist, recovery key storage and rotation, who holds SSH keys and firmware passwords, the firmware-update procedure, and a summary of what the client does and does not get access to, for client agreements. Verify by provisioning a second test unit from the doc alone.

## 20. Release and install

- [ ] 20.1 Publish multi-tag images to the registry from CI, and attach a `docker save` tarball to each release. Verify a release build produces both.
- [ ] 20.2 Write `docs/install.md`. It covers on-board installation of a provisioned appliance (per `docs/appliance.md`, with UPS power), Compose setup, first run, source setup, the Peplink static route to the dish, Unleashed syslog, trusting the certificate, and a link to `docs/discovery.md` before the first discovery run. Verify by following it on a clean VM to a working install against the simulator.
- [ ] 20.3 Write `docs/upgrade.md` covering online pull, offline `docker load`, the automatic pre-migration backup and rollback. Verify by upgrading and rolling back on a test VM with data intact.

## 21. Integration checks

- [ ] 21.1 Run an end-to-end test with the simulator: on a fresh container, create the first account, add simulator sources, then play every scenario. Verify the expected findings, statuses, timeline events and crew wording all appear, and that data survives a container restart and an image upgrade.
- [ ] 21.2 Run an offline check: with outbound internet blocked on the host, the container starts, the UI fully loads, and diagnosis continues. Verify by running the end-to-end test with networking restricted.
- [ ] 21.3 Commission on board against the real Peplink, UniFi, Ruckus and Starlink kit. Verify each source collects, the inventory and topology are correct, and induced test conditions produce the expected findings. Unplugging an AP should give a PoE or AP-offline finding; disabling the Starlink WAN should give a failover finding.

## Workflow follow-up

- Tune rule thresholds after the first weeks on board using the timeline, then archive the change once it has been reviewed.
