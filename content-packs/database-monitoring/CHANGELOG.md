# Changelog

## 1.2.0

- Self-contained: no dependency on the Splunk Observability Cloud content pack, the APM parent service or the OS Hosts entity type.
- Rate KPIs fixed. Oracle and PostgreSQL counters now arrive as per-second rates; SQL Server rates are derived from its raw perf counters.
- SQL Server entities identified by instance name (`host::instance`) instead of `host::default`.
- SQL Server: Transaction Rate replaced by Blocked Processes. PostgreSQL: Temp Files removed; metric names aligned with the OpenTelemetry `postgresql` receiver.
- Oracle sessions summed across session status and type.
- KPI search window widened to 15 minutes to absorb the five-minute stream resolution.
- Leaf services linked to their service templates.
- Postgres Replication Delay made optional (info severity when absent).
- Index macro `dbm_sim_metrics_indexes` shipped with the pack.

## 1.1.0

- First internal build: Database rollup, Oracle, SQL Server and PostgreSQL leaf services, entity types and entity health dashboards.
