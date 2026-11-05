# Insight

Insight by 50N Systems is an on-board monitoring and diagnostic platform for yacht hotel IT. It brings together information from the yacht's Peplink router, UniFi switches, Ruckus Unleashed Wi-Fi and Starlink connection, plus its own connectivity checks. It identifies likely problems and explains them in plain English for crew, with the technical evidence remote support engineers need.

It runs entirely on board in one Docker container, on a 50N-managed appliance, and works without an internet connection.

Proprietary software of 50N Systems. See `LICENSE`.

## Guides

| Guide | For |
|---|---|
| [`docs/install.md`](docs/install.md) | Installing on board: sources, dish access, services, locations |
| [`docs/upgrade.md`](docs/upgrade.md) | Upgrading, including offline, and rolling back |
| [`docs/appliance.md`](docs/appliance.md) | Building and looking after the 50N appliance |
| [`docs/discovery.md`](docs/discovery.md) | Using discovery safely |
| [`docs/rules.md`](docs/rules.md) | Every diagnostic rule: inputs, thresholds, confidence and wording (generated) |
| [`docs/integrations/`](docs/integrations/) | What each vendor interface provides, with sources |

Planning (proposal, specs, design, tasks) lives in `openspec/`.

## Development

```bash
uv venv --python 3.12 .venv
```

```bash
uv pip install -e '.[dev]'
```

```bash
.venv/bin/pytest -q
```

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy
```

The **simulator** plays a scripted yacht through the real pipeline, so rules and screens can be developed and demonstrated without the boat. Add sources of type *Simulator* (one per role: `peplink`, `unifi`, `ruckus-snmp`, `ruckus-web`, `starlink`, `probes`), then load scenarios under **Engineer → Simulator**.

End-to-end check against a built image (add `--offline` to run with no route to the internet):

```bash
docker build -t insight:dev .
```

```bash
.venv/bin/python scripts/e2e.py --image insight:dev
```

After changing rules or their wording, regenerate the rules reference:

```bash
.venv/bin/python scripts/gen_rules_doc.py
```

## Layout

| Path | Contents |
|---|---|
| `insight/adapters/` | Vendor adapters (Peplink, UniFi, Ruckus, Starlink) and the simulator |
| `insight/collection/` | Adapter interface and scheduler |
| `insight/diagnostics/` | Engine, rules and plain-English templates |
| `insight/discovery/` | Passive and engineer-started discovery |
| `insight/web/` | Crew dashboard and engineer console |
| `appliance/` | Appliance provisioning playbook |
