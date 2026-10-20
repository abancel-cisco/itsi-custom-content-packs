# Database Monitoring content pack

ITSI service tree for Oracle, Microsoft SQL Server and PostgreSQL instances monitored by Splunk Observability Cloud. Metrics reach Splunk through the Splunk Infrastructure Monitoring Add-on and the companion [`TA-o11y-sim-streams`](../../add-ons/TA-o11y-sim-streams).

Package: `DA-ITSI-CP-CUST-6a4e4181bb0ab5578803e6fd_1_2_0.tar.gz`, attached to the `database-monitoring-v1.2.0` release.

## Requirements

- Splunk ITSI (tested on 5.0.x).
- Splunk Infrastructure Monitoring Add-on (`splunk_ta_sim`), connected to your Observability Cloud org.
- `TA-o11y-sim-streams` with the `Oracle_DB`, `MSSQL_DB` and `Postgres_DB` streams enabled, writing to the `sim_metrics` metrics index.
- OpenTelemetry collector receivers publishing to Observability Cloud: `oracledb`, `sqlserver`, `postgresql`.

## Install

1. Install `TA-o11y-sim-streams` on the search head, then enable the three database streams (Settings → Data inputs → Splunk Infrastructure Monitoring Data Streams). Leave `org_id` blank to use the add-on's default account.
2. Check that metrics arrive after about five minutes:

   ```spl
   | mstats count where index=sim_metrics (metric_name=oracledb.* OR metric_name=sqlserver.* OR metric_name=postgresql.*) by metric_name
   ```

3. Install the content pack app (Apps → Install app from file), then install the pack from ITSI → Configuration → Data integrations → Content library.
4. Enable and run the three `DBM Import Entities - *` searches once to create the database entities.

## What is included

| Object | Names |
|---|---|
| Services | Database (rollup), Database Oracle, Database MSSQL, Database Postgres |
| Service templates | Database Oracle (O11y), Database MSSQL (O11y), Database Postgres (O11y); each leaf service is linked to its template |
| KPI base searches | `DBM_Oracle_BaseSearch`, `DBM_MSSQL_BaseSearch`, `DBM_Postgres_BaseSearch`: one consolidated `mstats` search per engine, 15-minute window, 5-minute frequency |
| Entity types | O11y Oracle Database, O11y MSSQL Database, O11y PostgreSQL Database, each with vital metrics and an entity health dashboard |
| Entity import searches | `DBM Import Entities - Oracle Database`, `- MSSQL Database`, `- PostgreSQL Database` |
| Macro | `dbm_sim_metrics_indexes` (default `index=sim_metrics`) |

Entity identity is `ITSIUniqueId = host::instance`, where the instance is the Oracle instance, the SQL Server instance name, or the PostgreSQL database.

## KPIs

| Engine | KPIs |
|---|---|
| Oracle (13) | Oracle CPU Time (CPU seconds per second), Active Sessions, Sessions Used %, PGA Memory, Executions /s, Hard Parses /s, Hard Parse Ratio, Logical Reads /s, Physical Reads /s, Buffer Cache Hit Ratio, User Commits /s, Enqueue Locks Used %, Enqueue Deadlocks /s |
| SQL Server (7) | Buffer Cache Hit Ratio, Page Life Expectancy, User Connections, Batch Request Rate, Lock Wait Rate, SQL Compilation Rate, Blocked Processes |
| PostgreSQL (7) | Backends, Commits Rate, Rollbacks Rate, Deadlocks Rate, Blocks Read, Database Size, Replication Delay (optional) |

Rates are per second. Oracle and PostgreSQL counters arrive as per-second rates from the streams. SQL Server `*.rate` metrics are raw perf counters, so the base search derives the rate from consecutive five-minute points.

## After install

- If the SIM metrics land in another index, edit the `dbm_sim_metrics_indexes` macro.
- Narrow the entity rules on the leaf services (`ITSIUniqueId matches *`) if other database entities share the same types.
- KPIs ship without severity thresholds, so every KPI reports normal. Add static or adaptive thresholds per environment.
- Postgres Replication Delay reports only on replicas. Elsewhere it shows N/A at info severity, which does not affect the health score.
- Edit KPIs on the service templates, not on the services: linked services receive template changes.

## Authoring tool

[`tools/deploy_dbm_itsi.py`](tools/deploy_dbm_itsi.py) creates or updates every object of the pack on an ITSI instance over REST. It is how the pack is developed before being built with ITSI's content pack authoring. It is not needed to install the pack.

```sh
ITSI_URL=https://your-search-head:8089 ITSI_TOKEN=<bearer token> python3 tools/deploy_dbm_itsi.py
```

Set `ITSI_INSECURE=1` only for management ports with self-signed certificates. Read the token from a secret store or environment; do not put it in files.

See [CHANGELOG.md](CHANGELOG.md) for release notes.
