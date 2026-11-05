# Design

## Context

The repository is empty apart from OpenSpec, so this is a greenfield build. See proposal.md (Why, What Changes) for motivation and scope, and `specs/` for the behaviour contract.

Constraints that shape the approach:

- **Runs on board, offline-first.** The host is a dedicated fanless x86 mini-PC (Intel N100 class: 4 cores, 8–16 GB RAM, SSD) running Linux and Docker, powered from the UPS. The internet may be absent for hours.
- **One yacht, small scale.** Roughly a Peplink router, 2–6 UniFi switches, 10–30 Ruckus Unleashed access points, one Starlink dish and up to a few hundred Wi-Fi clients.
- **On-board network:** Peplink router → UniFi switches → Ruckus Unleashed APs (all Wi-Fi). No UniFi APs or UniFi gateway. The UniFi Network controller therefore runs on a Cloud Key or as self-hosted software; which one is still to be confirmed on board.
- **Read-only access.** The engineer view may be used over Starlink or metered cellular.
- **Some valuable data comes only from unofficial interfaces:** the Starlink dish's local status interface and the Unleashed web interface. These must be optional and fail safely (see `data-collection`).

## Goals / Non-Goals

**Goals:**
- A single container that the 50N team can install, update and support with minimal effort.
- A clean boundary between vendor adapters and everything else, so that adding Synology, UPS, Sonos and Crestron later means adding adapters and rules, with no changes to the core.
- Diagnostic rules and their plain-English wording that are easy to review, test and extend.
- The ability to develop and test without being on the yacht.

**Non-Goals:**
- High availability or clustering. One host is accepted, and its failure is a known gap.
- A general-purpose metrics platform (Prometheus or Grafana style). History serves diagnosis and the views, not arbitrary querying.
- Multi-yacht or tenant concepts in the data model, beyond not hard-coding anything that would block them later.
- Internationalisation. Text is English in this change, though explanation templates are kept separate from code so translation remains possible.

## Decisions

### D1. Python 3.12, a single async process
The backend is a single asyncio Python application. It contains the collection scheduler, adapters, probe runner, syslog receiver, rule engine and web server (FastAPI with Uvicorn).

- **Why:** the best existing Ruckus Unleashed client (`aioruckus`) is async Python. Mature async SNMP (`pysnmp`), HTTP (`httpx`) and gRPC (`grpcio`) libraries exist. The workload is I/O-bound and small. A single process removes coordination between services.
- **Alternatives:** Go would give a single static binary and a Go Unleashed client exists, but it is less mature and slower to iterate on for rules and UI. Node/TypeScript has a weaker SNMP and Ruckus ecosystem. Several services in Compose would bring operational overhead with no benefit at this scale.

### D2. A common model held in a current-state store
Adapters never talk to rules or views. Each adapter returns a *snapshot* in the common model: Source, Device, Port, WanLink, WifiNetwork, AccessPoint, Client, Metric observations and raw Events. Every item carries `observed_at` and its source's reliability class (`reliable` or `optional`).

A central **state store** holds the latest snapshot per source with its freshness. It compares each new snapshot with the previous one to emit events (port down, failover, AP gone), merges devices across sources using stable keys (MAC address, then serial number), and records the topology.

- **Why:** this is what makes rules vendor-neutral and lets "monitoring failure" be a first-class state. If a source's snapshot is stale, everything derived from it is stale.
- **Alternatives:** rules querying adapters directly would couple rules to vendors. A pure event stream would make "current status" hard to answer.

### D3. Topology graph from LLDP and uplinks
The state store keeps a small graph: router ← switch uplinks ← switch ports ← neighbours (APs). It is built from UniFi LLDP neighbour and uplink data, with manual overrides in the inventory. Rules use it to attach symptoms to causes, for example "these 3 APs are all on SW-LD-01, which is offline".

- **Alternative:** manual topology only. Rejected as too much setup and liable to drift. Manual overrides remain available for gaps.

### D4. Rules as small Python classes; wording in templates
Each diagnostic rule is a Python class with declarative metadata:

| Field | Purpose |
|---|---|
| `id`, `title`, `severity` | identity and default severity |
| `requires` | the observations the rule needs, and from which reliability class |
| `min_duration`, `clear_duration` | how long a condition must hold to open, and stay clear to resolve |
| `explains` | the symptom rules this rule absorbs when it fires (used for grouping) |
| `evaluate(state)` | returns zero or more candidate findings, each with confidence and evidence references |

Crew and engineer wording lives in separate Jinja2 template files, one per rule, filled from the finding's facts (location names, link names, durations). After each collection cycle the engine:

1. checks each rule's `requires` against data freshness;
2. turns rules that need stale data from a failed source into monitoring-failure findings;
3. downgrades rules whose optional inputs are missing to "insufficient information", or skips them when the optional data is essential (Starlink obstruction, Wi-Fi congestion);
4. evaluates the rules;
5. suppresses symptom findings explained by a firing cause rule;
6. applies durations and flapping detection, where three or more open/clear cycles within an hour mark the finding as intermittent;
7. stores finding changes.

- **Why:** this is deterministic, testable with plain unit tests, and works offline. Wording can be reviewed by non-developers in the template files. Code-based rules handle cross-system logic far more easily than a DSL.
- **Alternatives:** a YAML or DSL rule language would be too limiting for correlation and premature with about 13 rules. LLM-generated explanations were rejected for this change because they are unavailable offline and non-deterministic; they could be revisited later as an online-only extra.

### D5. Storage: SQLite in WAL mode on the volume
Data is stored in a single SQLite database on the `/data` volume, with these tables:
- `sources`, `devices` (plus manual tags) and `services`/mappings;
- `metrics` (series id, timestamp, value);
- `metric_daily` (rollups);
- `events`;
- `findings` and `finding_evidence`;
- `users` and `sessions`;
- `settings`.

Gauges such as latency, PoE watts and client counts are stored at their polling interval. State-like values such as port up/down and WAN state are stored as change events rather than repeated samples.

**Volume estimate:** about 800 numeric series × 1 sample/min ≈ 1.2 M rows/day, or about 35 M rows over 30 days. That is roughly 2–4 GB with indexes, comfortably within a mini-PC SSD. A nightly job builds daily rollups, enforces retention and runs `VACUUM`/`ANALYZE` incrementally. Free-space checks drive the low-disk behaviour in `history`.

- **Why:** there's no extra container to run, and backup is a single file. Performance is sufficient at this scale.
- **Alternatives:** PostgreSQL or TimescaleDB adds a second container and more operational effort. InfluxDB or Prometheus would add a separate store and query language just for metrics.

### D6. Web UI: server-rendered HTML with htmx, all assets local
Pages are rendered on the server with Jinja2. htmx handles partial updates, and live updates use Server-Sent Events, falling back to polling. CSS is hand-written with tokens for light and dark themes. Charts use a small vendored library (uPlot, about 50 KB). Every asset ships inside the image.

- **Why:** pages stay small for engineers on satellite or cellular links. There's no JavaScript build toolchain or framework churn, and it works fully offline (`deployment`: assets are local). Both views share templates and components.
- **Alternatives:** a React or Vue SPA would mean a heavier first load, a build pipeline, and a separate API to secure. That's worth reconsidering only if the UI becomes highly interactive.

### D7. Security mechanics
- Passwords are hashed with Argon2id.
- Sessions use server-side records with `HttpOnly`, `Secure` and `SameSite=Strict` cookies, plus a CSRF token on forms. The idle timeout defaults to 12 hours for crew and 2 hours for engineers.
- The role check is enforced on the server for every engineer route and API.
- Sign-in throttling: five failures in ten minutes locks that account for fifteen minutes.
- Device credentials are encrypted with Fernet. The key is generated on first run and stored in `/data/secret.key` (mode 0600) inside the container user's volume. This protects credentials in exported or backed-up databases. It does **not** protect against someone with root on the host, and that is documented.
- TLS: a self-signed certificate is generated on first run and served directly by Uvicorn. An engineer can upload a replacement certificate.
- The container runs as a non-root user.

### D8. Container and networking
- The base image is `python:3.12-slim`, built for `linux/amd64`, with `linux/arm64` as a stretch goal.
- The image is published to a container registry (e.g. GHCR) and also attached to each release as a `docker save` tarball for offline upgrades.
- Compose service settings:
  - `network_mode: host`;
  - `restart: unless-stopped`;
  - the named volume `insight-data:/data`;
  - a `HEALTHCHECK` that calls `/healthz`. This reports the web process and the time of the last completed collection cycle, with no yacht data.
- Capabilities: `NET_RAW` for ICMP probes, and `NET_BIND_SERVICE` so the container can listen on UDP 514 for Ruckus syslog and on 443 for HTTPS. The ports are configurable, defaulting to 443 for HTTPS and 514 for syslog.
- **Why host networking:** it makes ICMP, syslog and future multicast discovery (Sonos) work without NAT surprises. The box is single-purpose.
- Times are stored in UTC and displayed in "ship's time", a time zone an engineer sets. Yachts cross time zones, so the displayed zone has to be changeable.

### D9. Adapter specifics and defaults

| Adapter | Interface | Class | Default poll |
|---|---|---|---|
| Peplink | Local router API (documented); SNMP fallback | reliable | 30 s |
| UniFi | UniFi Network controller local API (API key); SNMP to switches as fallback | reliable (see Open Questions) | 60 s |
| Ruckus SNMP | SNMP on the Unleashed master AP | reliable | 60 s |
| Ruckus syslog | UDP receiver; regex patterns for join/leave/reboot | reliable | push |
| Ruckus web | `aioruckus` against the Unleashed web interface | optional | 120 s |
| Starlink dish | gRPC status interface at `192.168.100.1:9200` | optional | 30 s |
| Probes | ICMP to each device; ICMP and HTTPS to internet targets; DNS via system and public resolvers | reliable | 30 s device and internet, 60 s DNS, 120 s HTTP |

Every adapter call has a timeout and runs in its own task, so one slow source cannot delay the others (`data-collection`). Polling intervals get a small random jitter so that all the sources aren't polled at the same moment.

### D10. Verification before building on an interface
Task 1 verifies each interface against the real firmware versions on board, or vendor documentation where the kit isn't available. It records what each interface exposes, its authentication, licensing, polling limits and response samples in `docs/integrations/<vendor>.md`. Those samples become the adapters' test fixtures. Where an interface does not provide something the specs mark "where available", the adapter reports it as not available; the specs do not change.

### D11. Developing without the yacht
Recorded fixtures drive adapter tests. A **simulator source**, enabled by a setting, replays scripted scenarios such as failover, AP PoE loss, dish obstruction and controller outage through the full pipeline. This drives rule tests and lets the UI be developed and demonstrated on shore.

## Risks / Trade-offs

- **[Unofficial interfaces change after firmware updates]** → They are classed as optional, versions are pinned in fixtures, and failures surface as monitoring failures plus "insufficient information". Each optional adapter has a parser test suite that is updated when firmware changes.
- **[The Starlink dish address may not be reachable from the LAN]** → The Peplink router may need a static route to `192.168.100.0/24` via the Starlink WAN. This is included in the install checklist. Without it, Starlink falls back to the Peplink and probe data only.
- **[The UniFi Network controller is off or absent]** → SNMP fallback to the switches. LLDP neighbour data over SNMP may be weaker, which reduces topology accuracy. Manual overrides mitigate this.
- **[The Unleashed SNMP gives master-level totals only]** → Per-AP identification comes from probes, syslog and UniFi port neighbours. Wi-Fi congestion findings are only possible with the optional source.
- **[Probes see only the WAN link currently in use]** → Per-link health comes from the Peplink health checks, and probe results are labelled with the link in use (`connectivity-probes`).
- **[A single host is a single point of failure, and Insight cannot report its own death]** → Accepted for this change. A heartbeat checked by the Peplink or by 50N is a future change.
- **[The encryption key sits on the same disk as the data]** → It protects database exports and backups only, and this is documented. Hardware-backed keys are out of scope.
- **[SQLite write contention]** → A single writer task with batched inserts and WAL mode. The scale is far below SQLite's limits.
- **[Self-signed certificate warnings]** → Expected on first use. The install guide covers trusting the certificate or uploading one.
- **[Rules tuned on assumptions, not real data]** → Thresholds are settings, not constants. The first weeks on board serve as a tuning period, with the timeline used to review false positives.

## Migration Plan

This is a greenfield build, so there is no existing data to migrate.

**Install:**
1. Prepare the mini-PC with Linux, Docker and NTP pointing at the Peplink, and connect it to the UPS.
2. Place the Compose file and run `docker compose up -d`.
3. Create the engineer account.
4. Add the sources.
5. Tag locations and map services.
6. Add the Peplink static route for the dish if needed.
7. Point Unleashed syslog at Insight.

**Upgrade:**
1. Insight backs up the SQLite file before running any schema migration. Migrations are forward-only, versioned, and applied at startup.
2. The new image is pulled from the registry, or loaded from a tarball with `docker load` when offline.

**Rollback:** stop the container, restore the pre-migration backup file, and start the previous image tag.

## Open Questions

- **UniFi controller:** where it runs on board (Cloud Key or self-hosted), and whether the official local Network API exposes port PoE and LLDP neighbours. If it does not, the adapter uses the controller's long-standing classic API for those fields. That data would be classed as optional, with SNMP as the reliable base for port state. Task 1 resolves this; the specs are unaffected.
- **Unleashed syslog:** whether Unleashed can send syslog to a non-standard port. If it can, Insight could avoid binding port 514.
- **Registry:** which registry 50N uses to publish images (GHCR assumed).
- **Default thresholds:** latency, loss, obstruction fraction and channel utilisation. Initial values come from vendor guidance and are tuned on board.
