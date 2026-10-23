# TA-o11y-sim-streams

Curated **Splunk Infrastructure Monitoring (SIM)** data streams for Splunk.

This TA ships **disabled** `sim_modular_input` stanzas with the SignalFlow **baked in** and
key dimensions promoted (`host.name`, instance/database name) for clean identity. It is the
**data-collection layer** that pulls O11y Cloud metrics into a Splunk index — decoupled from
any ITSI content pack.

- **Not ITSI-specific.** The metrics land in `sim_metrics` and are usable from Splunk core
  (search, dashboards, alerts) as much as from ITSI.
- **Domain-agnostic.** OS hosts, databases (Oracle, PostgreSQL, MSSQL) and AI workloads (GPUs,
  model serving, vector databases, provider tokens) are included today; more domains
  drop in as new `signalflow_programs/<domain>/*.signalflow` files.

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
| ai | `AI_Infrastructure` | `DCGM_FI_DEV_*` (NVIDIA DCGM exporter), `vllm:*`, `milvus_*` | 24 |
| ai | `AI_Providers` | `AWS/Bedrock` CloudWatch metrics, Azure OpenAI metrics | 10 |

The `OS_Hosts` stream is meant for a separate OS hosts content pack that is not published in this repository yet.

Cumulative counters (for example `oracledb.executions`, `postgresql.commits`, the vLLM `*_total` counters) are requested with `rollup='rate'`, so the index receives per-second values. The SQL Server `*.rate` metrics are raw perf counters despite their gauge type; the database monitoring content pack derives their rates in its base search.

### AI streams

Every AI stream publishes a unique label: `aiinf_*` for `AI_Infrastructure`, `aitok_*` for `AI_Providers`. The SIM add-on keeps the source metric name as `metric_name` and stores the label in the `sf_streamLabel` dimension. Two computations on the same metric (for example Milvus total and failed requests) therefore differ only by `sf_streamLabel`, and searches should filter on it:

```spl
| mstats latest(_value) where index=sim_metrics metric_name=* sf_streamLabel=aiinf_gpu_* by sf_streamLabel UUID span=5m
```

- Histograms (`milvus_proxy_sq_latency`) are read with `histogram(...).sum()` and `.count()`, so each 5-minute point is the interval total.
- Bedrock reports each model both per inference profile and per account; the stream keeps the maximum per `ModelId` to avoid double counting.
- Cloud integration metrics (Bedrock, Azure OpenAI) reach Observability Cloud several minutes late, so `AI_Providers` points trail the other streams.
- No stream collects agent instrumentation metrics (`gen_ai.*`), evaluations or guardrail results. They are out of scope for this add-on.

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
│   ├── database/{oracle,postgres,mssql}.signalflow
│   └── ai/{ai_infrastructure,ai_providers}.signalflow
├── scripts/build_inputs_conf.py
└── README.md
```

## Relationship to ITSI content packs

ITSI packs (e.g. `DA-ITSI-CP-database-monitoring`) consume the metrics this TA collects. The
pack's KPI base searches read `index=sim_metrics` (via the pack-owned macro
`dbm_sim_metrics_indexes`). Install this TA alongside the pack and enable the matching streams.

| Content pack | Streams |
|---|---|
| Database Monitoring | `Oracle_DB`, `MSSQL_DB`, `Postgres_DB` |
| AI Infrastructure Monitoring | `AI_Infrastructure`, `AI_Providers` |

See [CHANGELOG.md](CHANGELOG.md) for release notes.
