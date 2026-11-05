"""Versioned, forward-only schema migrations. Each entry moves the schema up one version."""

from __future__ import annotations

MIGRATIONS: list[str] = [
    # v1: initial schema
    """
    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('crew', 'engineer')),
        created_at TEXT NOT NULL,
        last_sign_in_at TEXT,
        failed_attempts TEXT NOT NULL DEFAULT '[]',
        locked_until TEXT
    );

    CREATE TABLE sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        csrf_token TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE sources (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        address TEXT NOT NULL,
        reliability TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        credentials BLOB,
        options TEXT NOT NULL DEFAULT '{}',
        interval_s REAL,
        created_at TEXT NOT NULL
    );

    CREATE TABLE devices (
        key TEXT PRIMARY KEY,
        name TEXT,
        display_name TEXT,
        manufacturer TEXT,
        model TEXT,
        category TEXT NOT NULL DEFAULT 'other',
        ip TEXT,
        mac TEXT,
        firmware TEXT,
        serial TEXT,
        source_ids TEXT NOT NULL DEFAULT '[]',
        location TEXT,
        manual INTEGER NOT NULL DEFAULT 0,
        reported INTEGER NOT NULL DEFAULT 1,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX devices_ip ON devices(ip);

    CREATE TABLE service_mappings (
        service TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('device', 'wan', 'ssid')),
        ref TEXT NOT NULL,
        PRIMARY KEY (service, kind, ref)
    );

    CREATE TABLE topology_overrides (
        device_key TEXT PRIMARY KEY,
        parent_key TEXT NOT NULL,
        port_id TEXT
    );

    CREATE TABLE series (
        id INTEGER PRIMARY KEY,
        subject TEXT NOT NULL,
        name TEXT NOT NULL,
        unit TEXT NOT NULL DEFAULT '',
        UNIQUE (subject, name)
    );

    CREATE TABLE metrics (
        series_id INTEGER NOT NULL REFERENCES series(id),
        ts INTEGER NOT NULL,
        value REAL NOT NULL
    );
    CREATE INDEX metrics_series_ts ON metrics(series_id, ts);
    CREATE INDEX metrics_ts ON metrics(ts);

    CREATE TABLE metric_daily (
        series_id INTEGER NOT NULL REFERENCES series(id),
        day TEXT NOT NULL,
        min REAL NOT NULL,
        max REAL NOT NULL,
        avg REAL NOT NULL,
        count INTEGER NOT NULL,
        PRIMARY KEY (series_id, day)
    );

    CREATE TABLE events (
        id INTEGER PRIMARY KEY,
        ts INTEGER NOT NULL,
        kind TEXT NOT NULL,
        source_id TEXT,
        subject TEXT NOT NULL,
        devices TEXT NOT NULL DEFAULT '[]',
        services TEXT NOT NULL DEFAULT '[]',
        systems TEXT NOT NULL DEFAULT '[]',
        message TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX events_ts ON events(ts);
    CREATE INDEX events_kind_ts ON events(kind, ts);

    CREATE TABLE event_daily (
        day TEXT NOT NULL,
        kind TEXT NOT NULL,
        count INTEGER NOT NULL,
        PRIMARY KEY (day, kind)
    );

    CREATE TABLE findings (
        id INTEGER PRIMARY KEY,
        rule_id TEXT NOT NULL,
        dedupe_key TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
        title TEXT NOT NULL,
        severity TEXT NOT NULL,
        confidence TEXT NOT NULL,
        intermittent INTEGER NOT NULL DEFAULT 0,
        first_detected_at TEXT NOT NULL,
        last_observed_at TEXT NOT NULL,
        resolved_at TEXT,
        systems TEXT NOT NULL DEFAULT '[]',
        services TEXT NOT NULL DEFAULT '[]',
        devices TEXT NOT NULL DEFAULT '[]',
        facts TEXT NOT NULL DEFAULT '{}',
        crew_text TEXT NOT NULL,
        engineer_text TEXT NOT NULL,
        summary TEXT NOT NULL,
        likely_causes TEXT NOT NULL DEFAULT '[]',
        next_steps TEXT NOT NULL DEFAULT '[]',
        action TEXT NOT NULL DEFAULT 'none',
        guests_affected INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX findings_status ON findings(status);
    CREATE INDEX findings_dedupe ON findings(dedupe_key, status);

    CREATE TABLE finding_evidence (
        id INTEGER PRIMARY KEY,
        finding_id INTEGER NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
        observed_at TEXT NOT NULL,
        source_id TEXT,
        description TEXT NOT NULL,
        data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX finding_evidence_finding ON finding_evidence(finding_id);

    CREATE TABLE finding_daily (
        day TEXT NOT NULL,
        rule_id TEXT NOT NULL,
        opened INTEGER NOT NULL,
        PRIMARY KEY (day, rule_id)
    );

    CREATE TABLE discovered (
        key TEXT PRIMARY KEY,
        mac TEXT,
        ip TEXT,
        name TEXT,
        how TEXT NOT NULL DEFAULT '[]',
        observations TEXT NOT NULL DEFAULT '{}',
        likely_type TEXT,
        confidence TEXT NOT NULL DEFAULT 'unidentified',
        evidence TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'accepted', 'dismissed')),
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    );

    CREATE TABLE gaps (
        id INTEGER PRIMARY KEY,
        scope TEXT NOT NULL,
        start_ts INTEGER NOT NULL,
        end_ts INTEGER
    );
    CREATE INDEX gaps_scope ON gaps(scope, start_ts);
    """,
]

SCHEMA_VERSION = len(MIGRATIONS)
