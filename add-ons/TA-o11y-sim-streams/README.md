# TA-o11y-sim-streams

Curated **Splunk Infrastructure Monitoring (SIM)** data streams for Splunk.

This TA ships **disabled** `sim_modular_input` stanzas with the SignalFlow **baked in** and
key dimensions promoted (`host.name`, instance/database name) for clean identity. It is the
**data-collection layer** that pulls O11y Cloud metrics into a Splunk index — decoupled from
any ITSI content pack.

- **Not ITSI-specific.** The metrics land in `sim_metrics` and are usable from Splunk core
  (search, dashboards, alerts) as much as from ITSI.
- **Domain-agnostic.** OS hosts and databases (Oracle, PostgreSQL, MSSQL) are included today;
  more domains (cloud, k8s…) drop in as new `signalflow_programs/<domain>/*.signalflow` files.

## Requirements

- `splunk_ta_sim` installed and licensed (provides the `sim_modular_input` handler).
- An O11y realm/account configured in the SIM add-on
  (Settings → Data Inputs → Splunk Infrastructure Monitoring → account).

## Enable a stream (operator)

1. **Org:** leave `org_id` blank to use the SIM add-on's **default account** (zero config), or
   set `org_id` on the stream to target another org.
2. **Enable:** Settings → Data Inputs → **Splunk Infrastructure Monitoring Data Streams** →
   e.g. `Oracle_DB` / `Postgres_DB` / `MSSQL_DB` → **Enable**.

Streams ship `disabled = 1`, so nothing runs until you enable it.

## Streams shipped

| Domain | Input | Metric prefix | # metrics |
|---|---|---|---|
| os | `OS_Hosts` | `cpu.* memory.* df_complex.* disk_ops.* if_octets.* if_errors.* vmpage_io.*` | 20 |
| database | `Oracle_DB` | `oracledb.*` | 25 |
| database | `Postgres_DB` | `postgresql.*` | 8 |
| database | `MSSQL_DB` | `sqlserver.*` | 18 |

The `OS_Hosts` stream is meant for a separate OS hosts content pack that is not published in this repository yet.

Cumulative counters (for example `oracledb.executions`, `postgresql.commits`) are requested with `rollup='rate'`, so the index receives per-second values. The SQL Server `*.rate` metrics are raw perf counters despite their gauge type; the database monitoring content pack derives their rates in its base search.

## Verify (~5 min after enable)

```spl
| mstats latest("oracledb.sessions.usage") as oracle,
         latest("postgresql.backends") as postgres,
         latest("sqlserver.user.connection.count") as mssql
  where index=sim_metrics earliest=-15m by host.name
```

## Adding / editing streams

1. Add or edit `signalflow_programs/<domain>/<name>.signalflow`. Optional leading directives:
   - `# input: <StanzaName>` (default: filename stem, title-cased)
   - `# index: <index>` (default: `sim_metrics`)
   - `# interval: <seconds>` (default: `300`)
2. Regenerate: `python3 scripts/build_inputs_conf.py`.
3. Never hand-edit `default/inputs.conf` — it is generated.

## Layout

```
TA-o11y-sim-streams/
├── default/
│   ├── app.conf
│   └── inputs.conf                     # GENERATED (disabled stanzas)
├── signalflow_programs/
│   ├── os/os_hosts.signalflow
│   └── database/{oracle,postgres,mssql}.signalflow
├── scripts/build_inputs_conf.py
└── README.md
```

## Relationship to ITSI content packs

ITSI packs (e.g. `DA-ITSI-CP-database-monitoring`) consume the metrics this TA collects. The
pack's KPI base searches read `index=sim_metrics` (via the pack-owned macro
`dbm_sim_metrics_indexes`). Install this TA alongside the pack and enable the matching streams.
