#!/usr/bin/env python3
"""Deploy the Database Monitoring ITSI objects to an ITSI search head via REST (authoring tool).

Environment: ITSI_URL (https://host:8089), ITSI_TOKEN (Splunk bearer token),
ITSI_INSECURE=1 to skip TLS verification for self-signed management certificates.
"""
from __future__ import annotations

import copy
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

ITSI_URL = os.environ["ITSI_URL"].rstrip("/")
TOKEN = os.environ["ITSI_TOKEN"]
CTX = ssl.create_default_context()
if os.environ.get("ITSI_INSECURE") == "1":
    # self-signed management certs (labs); keep verification on everywhere else
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE
HDR = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# Packaged in default/macros.conf — single override point for SIM metric indexes.
METRICS_MACRO = "dbm_sim_metrics_indexes"


def http(method: str, path: str, data=None):
    url = f"{ITSI_URL}{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=HDR, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {err[:800]}") from e


def patch(path: str, payload: dict):
    return http("POST", f"{path}?is_partial_data=1", payload)


def get(path: str) -> dict | None:
    try:
        status, data = http("GET", path)
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    if status != 200 or not data:
        return None
    return data


def post(path: str, payload: dict):
    return http("POST", path, payload)


def delete(path: str):
    url = f"{ITSI_URL}{path}"
    req = urllib.request.Request(url, headers=HDR, method="DELETE")
    try:
        with urllib.request.urlopen(req, context=CTX) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return e.code
        err = e.read().decode()
        raise RuntimeError(f"DELETE {path} -> HTTP {e.code}: {err[:800]}") from e


def entity_rule_for(etype_title: str) -> list:
    return [{
        "rule_condition": "AND",
        "rule_items": [
            {"field": "ITSIUniqueId", "field_type": "alias", "rule_type": "matches", "value": "*"},
            {"field": "etype", "field_type": "info", "rule_type": "matches", "value": etype_title.lower()},
        ],
    }]


def mstats_by(engine_key: str) -> str:
    if engine_key == "oracle":
        return "host.name oracledb.instance.name"
    if engine_key == "mssql":
        return "host.name sqlserver.instance.name"
    return "host.name postgresql.database.name"


def entity_id_eval_spl(engine_key: str) -> str:
    if engine_key == "oracle":
        return (
            "| eval host=lower('host.name') "
            "| eval instance=if(isnotnull('oracledb.instance.name') AND 'oracledb.instance.name'!=\"\", "
            "'oracledb.instance.name', \"default\") "
            '| eval ITSIUniqueId=host."::".instance '
        )
    if engine_key == "mssql":
        return (
            "| eval host=lower('host.name') "
            f"{MSSQL_INSTANCE_EVAL}"
            '| eval ITSIUniqueId=host."::".instance '
        )
    return (
        "| eval host=lower('host.name') "
        "| eval instance='postgresql.database.name' "
        '| eval ITSIUniqueId=host."::".instance '
    )


def mstats_where(engine_key: str) -> str:
    return f"`{METRICS_MACRO}`"


def data_drilldowns_for(engine_key: str) -> list:
    """ITSI metrics explorer drilldown — complements UDF entity health dashboard."""
    if engine_key == "oracle":
        metric_values = ["oracledb.*"]
    elif engine_key == "mssql":
        metric_values = ["sqlserver.*"]
    else:
        metric_values = ["postgresql.*"]
    return [{
        "title": "O11y SIM metrics (Splunk)",
        "type": "metrics",
        "static_filter": {"type": "include", "field": "metric_name", "values": metric_values},
        "entity_field_filter": {"type": "entity", "data_field": "host", "entity_field": "host"},
    }]


def build_vital_metric_search(engine_key: str, mstats_part: str, val_expr: str) -> str:
    return (
        f"| mstats {mstats_part} where {mstats_where(engine_key)} by {mstats_by(engine_key)} span=5m "
        f"{entity_id_eval_spl(engine_key)}"
        f"| eval val={val_expr} "
        f"| table _time val ITSIUniqueId"
    )


# sqlserver.*.rate metrics are raw cumulative perf counters despite the GAUGE type,
# so the MSSQL base search derives per-second rates from consecutive 5m points.
MSSQL_INSTANCE_EVAL = (
    '| eval instance=if(isnotnull(\'sqlserver.instance.name\') AND \'sqlserver.instance.name\'!="", '
    '\'sqlserver.instance.name\', "default") '
)

ORACLE_SPL = (
    '| mstats avg("oracledb.cpu_time") as ora_cpu_time, latest("oracledb.sessions.usage") as ora_sessions_used, '
    'latest("oracledb.sessions.limit") as ora_sessions_max, latest("oracledb.pga_memory") as ora_pga_memory, '
    'latest("oracledb.processes.usage") as ora_processes_used, latest("oracledb.processes.limit") as ora_processes_max, '
    'latest("oracledb.transactions.usage") as ora_txns_active, latest("oracledb.enqueue_locks.usage") as ora_enqueue_locks_used, '
    'latest("oracledb.enqueue_locks.limit") as ora_enqueue_locks_max, latest("oracledb.dml_locks.usage") as ora_dml_locks_used, '
    'latest("oracledb.dml_locks.limit") as ora_dml_locks_max, avg("oracledb.executions") as ora_executions_rate, '
    'avg("oracledb.hard_parses") as ora_hard_parses_rate, avg("oracledb.logical_reads") as ora_logical_reads_rate, '
    'avg("oracledb.physical_reads") as ora_physical_reads_rate, avg("oracledb.user_commits") as ora_user_commits_rate, '
    'avg("oracledb.user_rollbacks") as ora_user_rollbacks_rate, avg("oracledb.enqueue_deadlocks") as ora_enqueue_deadlocks_rate '
    f'WHERE `{METRICS_MACRO}` by host.name oracledb.instance.name span=5m '
    '| eval host=lower(\'host.name\') '
    '| eval instance=if(isnotnull(\'oracledb.instance.name\') AND \'oracledb.instance.name\'!="", \'oracledb.instance.name\', "default") '
    '| eval ITSIUniqueId=host."::".instance '
    '| eval ora_sessions_pct=round(100*ora_sessions_used/ora_sessions_max,1) '
    '| eval ora_processes_pct=round(100*ora_processes_used/ora_processes_max,1) '
    '| eval ora_enqueue_locks_pct=round(100*ora_enqueue_locks_used/ora_enqueue_locks_max,1) '
    '| eval ora_dml_locks_pct=round(100*ora_dml_locks_used/ora_dml_locks_max,1) '
    '| eval ora_cache_hit_ratio_pct=round(100*(ora_logical_reads_rate-ora_physical_reads_rate)/ora_logical_reads_rate,2) '
    '| eval ora_hard_parse_ratio_pct=round(100*ora_hard_parses_rate/ora_executions_rate,2) '
    '| eval ora_pga_memory_mb=round(ora_pga_memory/1048576,2) '
    '| dedup _time ITSIUniqueId'
)

MSSQL_SPL = (
    '| mstats latest("sqlserver.page.buffer_cache.hit_ratio") as sa_bch, latest("sqlserver.page.life_expectancy") as sa_ple, '
    'latest("sqlserver.user.connection.count") as sa_conn, latest("sqlserver.processes.blocked") as sa_blocked, '
    'max("sqlserver.batch.request.rate") as c_batch, max("sqlserver.lock.wait.rate") as c_lock, '
    'max("sqlserver.batch.sql_compilation.rate") as c_sqlcomp '
    f'where `{METRICS_MACRO}` by host.name sqlserver.instance.name span=5m '
    '| eval host=lower(\'host.name\') '
    f'{MSSQL_INSTANCE_EVAL}'
    '| eval ITSIUniqueId=host."::".instance '
    '| sort 0 ITSIUniqueId _time '
    '| streamstats current=f window=1 last(_time) as p_time last(c_batch) as p_batch last(c_lock) as p_lock '
    'last(c_sqlcomp) as p_sqlcomp by ITSIUniqueId '
    '| eval dt=_time-p_time '
    '| eval sa_batch=if(dt>0 AND c_batch>=p_batch, round((c_batch-p_batch)/dt,2), null()) '
    '| eval sa_lock=if(dt>0 AND c_lock>=p_lock, round((c_lock-p_lock)/dt,2), null()) '
    '| eval sa_sqlcomp=if(dt>0 AND c_sqlcomp>=p_sqlcomp, round((c_sqlcomp-p_sqlcomp)/dt,2), null()) '
    '| fields - c_* p_* dt '
    '| dedup _time ITSIUniqueId'
)

POSTGRES_SPL = (
    '| mstats latest("postgresql.backends") as pg_backends, '
    'avg("postgresql.commits") as pg_commits_rate, avg("postgresql.rollbacks") as pg_rollbacks_rate, '
    'avg("postgresql.deadlocks") as pg_deadlocks_rate, avg("postgresql.blocks_read") as pg_blocks_read, '
    'latest("postgresql.db_size") as pg_db_size_bytes, '
    'latest("postgresql.replication.data_delay") as pg_repl_delay_s '
    f'where `{METRICS_MACRO}` by host.name postgresql.database.name span=5m '
    '| eval host=lower(\'host.name\') '
    '| eval instance=\'postgresql.database.name\' '
    '| eval ITSIUniqueId=host."::".instance '
    '| dedup _time ITSIUniqueId'
)

ENGINES = {
    "oracle": {
        "etype_key": "dbm_o11y_oracle_database",
        "etype_title": "O11y Oracle Database",
        "dashboard_id": "dbm_oracle_entity_health",
        "import_name": "DBM Import Entities - Oracle Database",
        "import_spl": (
            f'| mstats latest("oracledb.sessions.usage") as probe where `{METRICS_MACRO}` '
            'by host.name oracledb.instance.name '
            '| eval host=lower(\'host.name\') '
            '| eval instance=if(isnotnull(\'oracledb.instance.name\') AND \'oracledb.instance.name\'!="", \'oracledb.instance.name\', "default") '
            '| eval ITSIUniqueId=host."::".instance '
            '| eval etype="O11y Oracle Database" '
            '| stats max(_time) as last_seen by ITSIUniqueId host instance etype '
            '| table ITSIUniqueId etype host instance last_seen'
        ),
        "bs_key": "DBM_Oracle_BaseSearch",
        "bs_spl": ORACLE_SPL,
        "svc_key": "dbm_database_oracle",
        "svc_title": "Database Oracle",
        "template_key": "dbm_template_oracle",
        "template_title": "Database Oracle (O11y)",
        "kpis": [
            ("Oracle CPU Time", "ora_cpu_time", "dbm_oracle_cpu_time"),
            ("Active Sessions", "ora_sessions_used", "dbm_oracle_sessions_active"),
            ("Sessions Used %", "ora_sessions_pct", "dbm_oracle_sessions_pct"),
            ("PGA Memory", "ora_pga_memory", "dbm_oracle_pga_memory"),
            ("Executions /s", "ora_executions_rate", "dbm_oracle_executions_rate"),
            ("Hard Parses /s", "ora_hard_parses_rate", "dbm_oracle_hard_parses_rate"),
            ("Hard Parse Ratio", "ora_hard_parse_ratio_pct", "dbm_oracle_hard_parse_ratio"),
            ("Logical Reads /s", "ora_logical_reads_rate", "dbm_oracle_logical_reads"),
            ("Physical Reads /s", "ora_physical_reads_rate", "dbm_oracle_physical_reads"),
            ("Buffer Cache Hit Ratio", "ora_cache_hit_ratio_pct", "dbm_oracle_cache_hit_ratio"),
            ("User Commits /s", "ora_user_commits_rate", "dbm_oracle_user_commits"),
            ("Enqueue Locks Used %", "ora_enqueue_locks_pct", "dbm_oracle_enqueue_locks_pct"),
            ("Enqueue Deadlocks /s", "ora_enqueue_deadlocks_rate", "dbm_oracle_enqueue_deadlocks"),
        ],
        "vital_metrics": [
            ("Sessions Used %", 'latest("oracledb.sessions.usage") as u, latest("oracledb.sessions.limit") as l', "round(100*u/l,1)"),
            ("Buffer Cache Hit Ratio", 'avg("oracledb.logical_reads") as lr, avg("oracledb.physical_reads") as pr', "round(100*(lr-pr)/lr,2)"),
        ],
        "dash_metrics": [
            ("Sessions Used %", 'latest("oracledb.sessions.usage") as u, latest("oracledb.sessions.limit") as l', "round(100*u/l,1)"),
            ("Executions /s", 'avg("oracledb.executions") as v', "v"),
            ("Buffer Cache Hit %", 'avg("oracledb.logical_reads") as lr, avg("oracledb.physical_reads") as pr', "round(100*(lr-pr)/lr,2)"),
            ("Active Transactions", 'latest("oracledb.transactions.usage") as v', "v"),
        ],
    },
    "mssql": {
        "etype_key": "dbm_o11y_mssql_database",
        "etype_title": "O11y MSSQL Database",
        "dashboard_id": "dbm_mssql_entity_health",
        "import_name": "DBM Import Entities - MSSQL Database",
        "import_spl": (
            f'| mstats latest("sqlserver.user.connection.count") as probe where `{METRICS_MACRO}` '
            'by host.name sqlserver.instance.name '
            '| eval host=lower(\'host.name\') '
            f'{MSSQL_INSTANCE_EVAL}'
            '| eval ITSIUniqueId=host."::".instance '
            '| eval etype="O11y MSSQL Database" '
            '| stats max(_time) as last_seen by ITSIUniqueId host instance etype '
            '| table ITSIUniqueId etype host instance last_seen'
        ),
        "bs_key": "DBM_MSSQL_BaseSearch",
        "bs_spl": MSSQL_SPL,
        "svc_key": "dbm_database_mssql",
        "svc_title": "Database MSSQL",
        "template_key": "dbm_template_mssql",
        "template_title": "Database MSSQL (O11y)",
        "kpis": [
            ("Buffer Cache Hit Ratio", "m_bch", "dbm_mssql_bch", "sa_bch"),
            ("Page Life Expectancy", "m_ple", "dbm_mssql_ple", "sa_ple"),
            ("User Connections", "m_conn", "dbm_mssql_conn", "sa_conn"),
            ("Batch Request Rate", "m_batch", "dbm_mssql_batch", "sa_batch"),
            ("Lock Wait Rate", "m_lock", "dbm_mssql_lock", "sa_lock"),
            ("SQL Compilation Rate", "m_sqlcomp", "dbm_mssql_sqlcomp", "sa_sqlcomp"),
            ("Blocked Processes", "m_blocked", "dbm_mssql_blocked", "sa_blocked"),
        ],
        "vital_metrics": [
            ("Buffer Cache Hit Ratio", 'avg("sqlserver.page.buffer_cache.hit_ratio") as v', "v"),
            ("User Connections", 'avg("sqlserver.user.connection.count") as v', "v"),
        ],
        "dash_metrics": [
            ("Buffer Cache Hit Ratio", 'avg("sqlserver.page.buffer_cache.hit_ratio") as v', "v"),
            ("Page Life Expectancy", 'avg("sqlserver.page.life_expectancy") as v', "v"),
            ("User Connections", 'avg("sqlserver.user.connection.count") as v', "v"),
            ("Blocked Processes", 'latest("sqlserver.processes.blocked") as v', "v"),
        ],
    },
    "postgres": {
        "etype_key": "dbm_o11y_postgres_database",
        "etype_title": "O11y PostgreSQL Database",
        "dashboard_id": "dbm_postgres_entity_health",
        "import_name": "DBM Import Entities - PostgreSQL Database",
        "import_spl": (
            f'| mstats latest("postgresql.backends") as probe where `{METRICS_MACRO}` '
            'by host.name postgresql.database.name '
            '| eval host=lower(\'host.name\') '
            '| eval instance=\'postgresql.database.name\' '
            '| eval ITSIUniqueId=host."::".instance '
            '| eval etype="O11y PostgreSQL Database" '
            '| stats max(_time) as last_seen by ITSIUniqueId host instance etype '
            '| table ITSIUniqueId etype host instance last_seen'
        ),
        "bs_key": "DBM_Postgres_BaseSearch",
        "bs_spl": POSTGRES_SPL,
        "svc_key": "dbm_database_postgres",
        "svc_title": "Database Postgres",
        "template_key": "dbm_template_postgres",
        "template_title": "Database Postgres (O11y)",
        "kpis": [
            ("Postgres Backends", "pg_backends", "dbm_postgres_backends"),
            ("Postgres Commits Rate", "pg_commits_rate", "dbm_postgres_commits"),
            ("Postgres Rollbacks Rate", "pg_rollbacks_rate", "dbm_postgres_rollbacks"),
            ("Postgres Deadlocks Rate", "pg_deadlocks_rate", "dbm_postgres_deadlocks"),
            ("Postgres Blocks Read", "pg_blocks_read", "dbm_postgres_blocks_read"),
            ("Postgres Database Size", "pg_db_size_bytes", "dbm_postgres_db_size"),
            ("Postgres Replication Delay", "pg_repl_delay_s", "dbm_postgres_repl_delay"),
        ],
        "vital_metrics": [
            ("Backends", 'latest("postgresql.backends") as v', "v"),
            ("Database Size", 'latest("postgresql.db_size") as v', "v"),
        ],
        "dash_metrics": [
            ("Backends", 'latest("postgresql.backends") as v', "v"),
            ("Commits Rate", 'latest("postgresql.commits") as c', "c"),
            ("Deadlocks", 'latest("postgresql.deadlocks") as v', "v"),
            ("Database Size", 'latest("postgresql.db_size") as v', "v"),
        ],
    },
}


def kpi_specs(eng: dict) -> list[tuple]:
    """Normalize ENGINES kpi tuples to (title, base_metric_key, kpi_key, threshold_field)."""
    specs = []
    for item in eng["kpis"]:
        if len(item) == 4:
            specs.append(item)
        else:
            title, metric_key, kpi_key = item
            specs.append((title, metric_key, kpi_key, metric_key))
    return specs


KPI_DESCRIPTIONS = {
    "Postgres Replication Delay": (
        "Optional. Reports only on PostgreSQL replicas (postgresql.replication.data_delay); "
        "shows N/A at info severity, which does not affect the health score, on primaries and standalone instances."
    ),
}


def build_kpis(eng: dict, service_entity_filter: bool = True) -> list:
    return [
        make_kpi(title, base_key, kpi_key, eng["bs_key"], eng["bs_spl"], threshold_field=tf,
                 service_entity_filter=service_entity_filter, description=KPI_DESCRIPTIONS.get(title, ""))
        for title, base_key, kpi_key, tf in kpi_specs(eng)
    ]


def default_thresholds(metric_field: str) -> dict:
    """Baseline 'normal' severity when data is present; enables health score calculation."""
    return {
        "baseSeverityColor": "#5fbf7fff",
        "baseSeverityColorLight": "#5fbf7f33",
        "baseSeverityLabel": "normal",
        "baseSeverityValue": 2,
        "gaugeMax": 100,
        "gaugeMin": 0,
        "isMaxStatic": False,
        "isMinStatic": True,
        "metricField": metric_field,
        "renderBoundaryMax": 100,
        "renderBoundaryMin": 0,
        "thresholdLevels": [],
    }


def make_kpi(title, base_metric_key, kpi_key, bs_key, bs_spl, threshold_field=None, service_entity_filter=True,
             description=""):
    tf = threshold_field or base_metric_key
    return {
        "_key": kpi_key,
        "title": title,
        "description": description,
        "search_type": "shared_base",
        "base_search_id": bs_key,
        "base_search_metric": base_metric_key,
        "base_search": bs_spl,
        "search": bs_spl,
        "search_alert": bs_spl,
        "is_entity_breakdown": True,
        "is_split_by_entity": True,
        "is_service_entity_filter": service_entity_filter,
        "is_filter_entities_to_service": service_entity_filter,
        "entity_breakdown_id_fields": "ITSIUniqueId",
        "entity_id_fields": "ITSIUniqueId",
        "entity_alias_filtering_fields": "ITSIUniqueId",
        "entity_filter_field": "ITSIUniqueId",
        "entity_split_field": "ITSIUniqueId",
        "threshold_field": tf,
        "aggregate_thresholds": default_thresholds(tf),
        "entity_thresholds": default_thresholds(tf),
        "aggregate_statop": "avg",
        "entity_statop": "avg",
        "fill_gaps": "null_value",
        "gap_severity": "info",
        "gap_severity_value": "1",
        "gap_severity_color": "#AED3E5",
        "gap_severity_color_light": "#E3F0F6",
        "enabled": True,
        "alert_period": "5",
        "alert_lag": "30",
        "alert_on": "both",
        "urgency": 5.0,
        "type": "kpis_primary",
        "sec_grp": "default_itsi_security_group",
        "kpi_threshold_template_id": "",
        "anomaly_detection_alerting_enabled": False,
        "search_buckets": "",
        "search_occurrences": 1.0,
        "search_alert_earliest": "15",
    }


def build_dashboard_definition(engine_key: str, eng: dict) -> dict:
    viz = {}
    ds = {}
    layout = []
    for i, (title, mstats_part, val_expr) in enumerate(eng["dash_metrics"]):
        vid = f"viz_{i}"
        did = f"ds_{i}"
        viz[vid] = {
            "dataSources": {"primary": did},
            "title": title,
            "type": "splunk.line",
            "options": {"nullValueDisplay": "gap", "legendDisplay": "off"},
        }
        ds[did] = {
            "name": did,
            "type": "ds.search",
            "options": {
                "query": (
                    f"| mstats {mstats_part} where {mstats_where(engine_key)} earliest=-24h@h "
                    f"by {mstats_by(engine_key)} span=5m "
                    f"{entity_id_eval_spl(engine_key)}"
                    f'| search ITSIUniqueId="$db_entity_id$" '
                    f"| eval val={val_expr} "
                    f'| timechart span=5m avg(val) as "{title}"'
                )
            },
        }
        layout.append({
            "item": vid,
            "type": "block",
            "position": {"x": (i % 2) * 600, "y": (i // 2) * 260, "w": 580, "h": 250},
        })
    return {
        "title": f"{eng['etype_title']} Entity Health",
        "description": f"O11y SIM database metrics for {eng['etype_title']} entities.",
        "inputs": {},
        "defaults": {
            "dataSources": {
                "ds.search": {
                    "options": {
                        "queryParameters": {
                            "earliest": "$global_time.earliest$",
                            "latest": "$global_time.latest$",
                        }
                    }
                }
            }
        },
        "visualizations": viz,
        "dataSources": ds,
        "layout": {"type": "grid", "options": {"height": 560, "width": 1200}, "structure": layout, "globalInputs": []},
    }


def dashboard_xml(dashboard_id: str, label: str, definition: dict) -> str:
    def_json = json.dumps(definition, indent=4)
    return (
        f'<dashboard version="2" theme="light">\n'
        f'    <label>{label}</label>\n'
        f'    <description>ITSI entity health for {label}</description>\n'
        f'    <definition><![CDATA[\n{def_json}\n]]></definition>\n'
        f'</dashboard>\n'
    )


def upsert_dashboard(dashboard_id: str, label: str, definition: dict):
    xml = dashboard_xml(dashboard_id, label, definition)
    base = f"/servicesNS/nobody/search/data/ui/views"
    # Try delete existing
    try:
        req_del = urllib.request.Request(
            f"{ITSI_URL}{base}/{dashboard_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            method="DELETE",
        )
        with urllib.request.urlopen(req_del, context=CTX) as resp:
            resp.read()
    except urllib.error.HTTPError:
        pass
    body = urllib.parse.urlencode({"name": dashboard_id, "eai:data": xml}).encode()
    for url in (f"{ITSI_URL}{base}/{dashboard_id}", f"{ITSI_URL}{base}"):
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, context=CTX) as resp:
                resp.read()
            break
        except urllib.error.HTTPError as e:
            if url.endswith(base) and e.code in (404, 405):
                continue
            err = e.read().decode()
            raise RuntimeError(f"dashboard {dashboard_id}: HTTP {e.code}: {err[:400]}") from e
    acl_url = f"{ITSI_URL}/servicesNS/nobody/search/data/ui/views/{dashboard_id}/acl"
    acl_body = "owner=nobody&sharing=global&perms.read=*&perms.write=admin,power"
    req2 = urllib.request.Request(
        acl_url,
        data=acl_body.encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req2, context=CTX) as resp:
        resp.read()
    print(f"  dashboard {dashboard_id}")


IMPORT_APP = "SA-ITOA"
DASHBOARD_APP = "search"


def delete_saved_search(app: str, name: str):
    path = f"/servicesNS/nobody/{app}/saved/searches/{urllib.parse.quote(name, safe='')}"
    try:
        delete(path)
        print(f"  removed old saved search {name} from {app}")
    except RuntimeError:
        pass


def upsert_entity_import_savedsearch(name: str, search: str):
    """Match ITSI Import Objects - Get_OS_Hosts action wiring (Observability CP)."""
    create_fields = {
        "name": name,
        "search": search,
        "dispatch.earliest_time": "-24h",
        "dispatch.latest_time": "now",
        "cron_schedule": "*/15 * * * *",
        "is_scheduled": "1",
        "disabled": "0",
        "actions": "itsi_import_objects",
        "action.itsi_import_objects": "1",
        "action.itsi_import_objects.param.backfill_enabled": "0",
        "action.itsi_import_objects.param.entity_identifier_fields": "ITSIUniqueId",
        "action.itsi_import_objects.param.entity_informational_fields": "host,instance,last_seen,etype",
        "action.itsi_import_objects.param.entity_merge_field": "ITSIUniqueId",
        "action.itsi_import_objects.param.entity_merge_fqdn": "",
        "action.itsi_import_objects.param.entity_status_tracking": "",
        "action.itsi_import_objects.param.entity_title_field": "ITSIUniqueId",
        "action.itsi_import_objects.param.entity_type_field": "etype",
        "action.itsi_import_objects.param.field_level_update_type": "",
        "action.itsi_import_objects.param.service_enabled": "1",
        "action.itsi_import_objects.param.service_team": "default_itsi_security_group",
        "action.itsi_import_objects.param.service_templates_config": "{}",
        "action.itsi_import_objects.param.update_type": "upsert",
        "alert.track": "0",
    }
    update_fields = dict(create_fields)
    update_fields.pop("name", None)
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/x-www-form-urlencoded"}
    named = f"{ITSI_URL}/servicesNS/nobody/{IMPORT_APP}/saved/searches/{urllib.parse.quote(name, safe='')}"
    check = urllib.request.Request(named, headers={"Authorization": f"Bearer {TOKEN}"}, method="GET")
    exists = False
    try:
        with urllib.request.urlopen(check, context=CTX) as resp:
            exists = resp.status == 200
    except urllib.error.HTTPError:
        exists = False
    payload = urllib.parse.urlencode(update_fields if exists else create_fields).encode()
    target = named if exists else f"{ITSI_URL}/servicesNS/nobody/{IMPORT_APP}/saved/searches"
    req = urllib.request.Request(target, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, context=CTX) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 409 and not exists:
            req2 = urllib.request.Request(named, data=urllib.parse.urlencode(update_fields).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(req2, context=CTX) as resp:
                resp.read()
            exists = True
        else:
            err = e.read().decode()
            raise RuntimeError(f"saved search {name}: HTTP {e.code}: {err[:400]}") from e
    print(f"  import search {name} in {IMPORT_APP} ({'updated' if exists else 'created'})")
    verify_import_search(name)


def verify_import_search(name: str):
    path = f"/servicesNS/nobody/{IMPORT_APP}/saved/searches/{urllib.parse.quote(name, safe='')}?output_mode=json"
    req = urllib.request.Request(f"{ITSI_URL}{path}", headers={"Authorization": f"Bearer {TOKEN}"}, method="GET")
    with urllib.request.urlopen(req, context=CTX) as resp:
        data = json.loads(resp.read())
    content = data["entry"][0]["content"]
    if content.get("actions") != "itsi_import_objects":
        raise RuntimeError(f"import search {name} missing itsi_import_objects action")
    print(f"  verified import search {name}")


def clear_import_cache(name: str):
    for obj in ("itsi_import_objects_cache", "itsi_bulk_import_entities_status_cache"):
        path = f"/servicesNS/nobody/SA-ITOA/storage/collections/data/{obj}/{urllib.parse.quote(name, safe='')}"
        try:
            delete(path)
            print(f"  cleared {obj} for {name}")
        except RuntimeError:
            pass


def dispatch_import(name: str):
    path = f"/servicesNS/nobody/{IMPORT_APP}/saved/searches/{urllib.parse.quote(name, safe='')}/dispatch"
    body = urllib.parse.urlencode({"output_mode": "json", "trigger_actions": "1"}).encode()
    req = urllib.request.Request(
        f"{ITSI_URL}{path}",
        data=body,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, context=CTX) as resp:
        sid = json.loads(resp.read())["sid"]
    for _ in range(30):
        time.sleep(2)
        job = json.loads(
            urllib.request.urlopen(
                urllib.request.Request(
                    f"{ITSI_URL}/servicesNS/nobody/{IMPORT_APP}/search/jobs/{sid}?output_mode=json",
                    headers={"Authorization": f"Bearer {TOKEN}"},
                ),
                context=CTX,
            ).read()
        )["entry"][0]["content"]
        if job.get("isDone"):
            break
    print(f"  dispatched import {name} (sid={sid})")


RETIRED_KPI_TITLES = {"Postgres Temp Files", "Transaction Rate"}


def service_own_kpis(existing: list | None, template_titles: set[str]) -> list:
    """SHKPI + KPIs the template does not provide (minus retired ones); the link call adds the template's set."""
    return [
        k for k in existing or []
        if str(k.get("_key", "")).startswith("SHKPI-")
        or (k.get("title") not in template_titles and k.get("title") not in RETIRED_KPI_TITLES)
    ]


def rollup_deps(child_keys: list[str]) -> list[dict]:
    return [
        {"serviceid": key, "kpis_depending_on": [f"SHKPI-{key}"], "overloaded_urgencies": {}}
        for key in child_keys
    ]


def upsert_leaf_service(eng: dict):
    svc_payload = {
        "_key": eng["svc_key"],
        "title": eng["svc_title"],
        "identifying_name": eng["svc_title"].lower(),
        "description": (
            f"{eng['svc_title']} — O11y SIM metrics via {eng['bs_key']}. "
            f"KPIs are managed on service template {eng['template_title']}. "
            f"Entities: {eng['etype_title']} (ITSIUniqueId = host::instance)."
        ),
        "enabled": True,
        "entity_rules": entity_rule_for(eng["etype_title"]),
        "team_id": "default_itsi_security_group",
        "is_healthscore_calculate_by_entity_enabled": 1,
    }
    path = f"/servicesNS/nobody/SA-ITOA/itoa_interface/service/{eng['svc_key']}"
    existing = get(path)
    if existing and existing.get("base_service_template_id") == eng["template_key"]:
        patch(path, svc_payload)
        print(f"  patched service {eng['svc_title']} (already linked; KPIs come from template)")
        return
    if existing and existing.get("base_service_template_id"):
        raise RuntimeError(f"{eng['svc_key']} is linked to another template: {existing['base_service_template_id']}")
    template_titles = {k["title"] for k in build_kpis(eng)}
    svc_payload["kpis"] = service_own_kpis((existing or {}).get("kpis"), template_titles)
    if existing:
        # partial updates merge KPI lists, so removing the service's own copies needs a full-object write
        post(path, {**existing, **svc_payload})
        print(f"  updated service {eng['svc_title']} (own copies of template KPIs removed)")
    else:
        post("/servicesNS/nobody/SA-ITOA/itoa_interface/service", svc_payload)
        print(f"  created service {eng['svc_title']}")
    post(f"{path}/base_service_template", {"_key": eng["template_key"], "overwrite_entity_rules": "ignore"})
    print(f"  linked {eng['svc_title']} to {eng['template_key']}")


def upsert_template(eng: dict):
    kpis = build_kpis(eng, service_entity_filter=False)
    tmpl = {
        "_key": eng["template_key"],
        "title": eng["template_title"],
        "identifying_name": eng["template_title"].lower(),
        "service_id": eng["svc_key"],
        "entity_rules": [],
        "kpis": kpis,
        "team_id": "default_itsi_security_group",
        "is_healthscore_calculate_by_entity_enabled": 1,
    }
    existing = get(f"/servicesNS/nobody/SA-ITOA/itoa_interface/base_service_template/{eng['template_key']}")
    if existing:
        post(
            f"/servicesNS/nobody/SA-ITOA/itoa_interface/base_service_template/{eng['template_key']}",
            {**existing, **{k: v for k, v in tmpl.items() if k != "entity_rules"}},
        )
        print(f"  replaced template {eng['template_title']} (KPIs synced)")
    else:
        post("/servicesNS/nobody/SA-ITOA/itoa_interface/base_service_template", tmpl)
        print(f"  created template {eng['template_title']}")


def refresh_rollup_deps(child_keys: list[str]):
    """Clear and re-set deps so ITSI rebuilds services_depending_on_me on children."""
    empty = patch("/servicesNS/nobody/SA-ITOA/itoa_interface/service/dbm_database_rollup", {"services_depends_on": []})
    patch("/servicesNS/nobody/SA-ITOA/itoa_interface/service/dbm_database_rollup", {"services_depends_on": rollup_deps(child_keys)})
    print("  refreshed rollup dependency links")


def cleanup_orphan_dbm_entities():
    """Remove stale DBM entities from early imports (host / instance titles) that block match_entities."""
    dbm_types = {eng["etype_key"] for eng in ENGINES.values()}
    items = get("/servicesNS/nobody/SA-ITOA/itoa_interface/entity?count=2000&fields=_key,title,services,entity_type_ids") or []
    deleted = 0
    for e in items:
        tids = set(e.get("entity_type_ids") or [])
        if not (tids & dbm_types):
            continue
        title = e.get("title", "")
        if " / " in title or (not e.get("services") and "::" not in title):
            try:
                delete(f"/servicesNS/nobody/SA-ITOA/itoa_interface/entity/{e['_key']}")
                print(f"  deleted orphan entity {title}")
                deleted += 1
            except RuntimeError:
                pass
    if not deleted:
        print("  no orphan DBM entities found")


def dispatch_shared_indicators():
    """Force-run shared base-search KPI indicators so health scores refresh immediately."""
    for bs_key in {eng["bs_key"] for eng in ENGINES.values()}:
        name = f"Indicator - Shared - {bs_key} - ITSI Search"
        path = f"/servicesNS/nobody/itsi/saved/searches/{urllib.parse.quote(name, safe='')}/dispatch"
        body = urllib.parse.urlencode({"output_mode": "json", "trigger_actions": "1"}).encode()
        req = urllib.request.Request(
            f"{ITSI_URL}{path}",
            data=body,
            headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, context=CTX) as resp:
                sid = json.loads(resp.read())["sid"]
            print(f"  dispatched {name} (sid={sid})")
        except Exception as exc:
            print(f"  WARN dispatch {name}: {exc}")


def bind_service_entities(eng: dict):
    """Entity rules do not always evaluate immediately after import; bind matched entities."""
    etype_value = eng["etype_title"].lower()
    filt = urllib.parse.quote(json.dumps({"_itsi_informational_lookups": {"$regex": f"etype={etype_value}"}}))
    items = get(f"/servicesNS/nobody/SA-ITOA/itoa_interface/entity?filter={filt}&fields=_key,title&count=500") or []
    keys = [i["_key"] for i in items if i.get("_key") and "::" in i.get("title", "")]
    if not keys:
        print(f"  no entities to bind for {eng['svc_title']}")
        return
    patch(f"/servicesNS/nobody/SA-ITOA/itoa_interface/service/{eng['svc_key']}", {"entity_keys": keys})
    print(f"  bound {len(keys)} entities to {eng['svc_title']}")


def upsert_rollup(child_keys: list[str]):
    deps = rollup_deps(child_keys)
    rollup = {
        "_key": "dbm_database_rollup",
        "title": "Database",
        "identifying_name": "database",
        "description": "Database monitoring rollup (Oracle, PostgreSQL, MSSQL) from Splunk Observability SIM.",
        "enabled": True,
        "entity_rules": [],
        "kpis": [],
        "team_id": "default_itsi_security_group",
        "services_depends_on": deps,
    }
    existing = get("/servicesNS/nobody/SA-ITOA/itoa_interface/service/dbm_database_rollup")
    if existing:
        existing_shkpi = [k for k in (existing.get("kpis") or []) if str(k.get("_key", "")).startswith("SHKPI-")]
        rollup["kpis"] = existing_shkpi
        patch("/servicesNS/nobody/SA-ITOA/itoa_interface/service/dbm_database_rollup", rollup)
        print("  patched rollup service Database (serviceid deps)")
    else:
        post("/servicesNS/nobody/SA-ITOA/itoa_interface/service", rollup)
        print("  created rollup service Database")


PACK_APP = "DA-ITSI-CP-database-monitoring"


def form_post(path: str, fields: dict):
    req = urllib.request.Request(
        f"{ITSI_URL}{path}",
        data=urllib.parse.urlencode(fields).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=CTX) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code


def ensure_pack_macro():
    """Create the pack app shell and its index macro when the app is not installed."""
    if form_post("/services/apps/local", {"name": PACK_APP, "template": "barebones", "visible": "false",
                                          "label": "ITSI CP - Database Monitoring (O11y)"}) in (200, 201):
        print(f"  created app shell {PACK_APP}")
    base = f"/servicesNS/nobody/{PACK_APP}/configs/conf-macros"
    if form_post(base, {"name": METRICS_MACRO, "definition": "index=sim_metrics"}) in (200, 201):
        print(f"  created macro {METRICS_MACRO}")
    form_post(f"{base}/{METRICS_MACRO}/acl", {"owner": "nobody", "sharing": "global", "perms.read": "*"})


def base_search_payload(eng: dict) -> dict:
    metrics = [{
        "_key": base_key,
        "title": title,
        "threshold_field": tf,
        "unit": "%" if "%" in title or "Ratio" in title else "",
        "aggregate_statop": "avg",
        "entity_statop": "avg",
        "fill_gaps": "null_value",
        "gap_severity": "info",
        "gap_severity_value": "1",
        "gap_severity_color": "#AED3E5",
        "gap_severity_color_light": "#E3F0F6",
    } for title, base_key, _kpi_key, tf in kpi_specs(eng)]
    return {
        "_key": eng["bs_key"],
        "title": eng["bs_key"].replace("_", " "),
        "description": f"Consolidated KPI base search for {eng['svc_title']} (O11y SIM metrics).",
        "base_search": eng["bs_spl"],
        "search_alert_earliest": "15",
        "alert_period": "5",
        "alert_lag": "30",
        "is_metric": False,
        "metric_qualifier": "",
        "source_itsi_da": "",
        "sec_grp": "default_itsi_security_group",
        "is_entity_breakdown": True,
        "is_service_entity_filter": True,
        "entity_breakdown_id_fields": "ITSIUniqueId",
        "entity_alias_filtering_fields": "ITSIUniqueId",
        "entity_id_fields": "ITSIUniqueId",
        "metrics": metrics,
    }


def main():
    print("=== 0. Pack app + index macro ===")
    ensure_pack_macro()

    print("=== 1. KPI base searches ===")
    for eng in ENGINES.values():
        existing_bs = get(f"/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_base_search/{eng['bs_key']}")
        if not existing_bs:
            post("/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_base_search", base_search_payload(eng))
            print(f"  created {eng['bs_key']}")
            continue
        try:
            # partial updates merge the metrics list, so retired metrics need a full-object write
            post(
                f"/servicesNS/nobody/SA-ITOA/itoa_interface/kpi_base_search/{eng['bs_key']}",
                {
                    **existing_bs,
                    **base_search_payload(eng),
                    "entity_filter_field": "ITSIUniqueId",
                    "entity_split_field": "ITSIUniqueId",
                    "is_split_by_entity": True,
                    "is_filter_entities_to_service": True,
                },
            )
            print(f"  updated {eng['bs_key']}")
        except RuntimeError as exc:
            print(f"  skip {eng['bs_key']}: {exc}")

    print("=== 2. Entity types + dashboards + import searches ===")
    for engine_key, eng in ENGINES.items():
        upsert_dashboard(
            eng["dashboard_id"],
            f"{eng['etype_title']} Entity Health",
            build_dashboard_definition(engine_key, eng),
        )
        vital = []
        for i, (mname, mstats_part, val_expr) in enumerate(eng["vital_metrics"]):
            vital.append({
                "is_key": 1 if i == 0 else 0,
                "metric_name": mname,
                "matching_entity_fields": ["ITSIUniqueId"],
                "split_by_fields": ["ITSIUniqueId"],
                "unit": "%" if "%" in mname else "",
                "search": build_vital_metric_search(engine_key, mstats_part, val_expr),
            })
        et_payload = {
            "_key": eng["etype_key"],
            "title": eng["etype_title"],
            "identifying_name": eng["etype_title"].lower(),
            "description": f"Splunk Observability SIM database instance for {eng['etype_title']}. Independent of OS Hosts.",
            "show_dashboards_in_service_analyzer": True,
            "show_navigation_in_service_analyzer": True,
            "data_drilldowns": data_drilldowns_for(engine_key),
            "dashboard_drilldowns": [{
                "title": f"{eng['etype_title']} Entity Health",
                "id": eng["dashboard_id"],
                "base_url": "",
                "dashboard_type": "udf_dashboard",
                "params": {
                    "static_params": {},
                    "alias_param_map": [
                        {"alias": "ITSIUniqueId", "param": "db_entity_id"},
                        {"alias": "host", "param": "db_host"},
                        {"alias": "time_range_token-2", "param": "global_time"},
                    ],
                },
            }],
            "vital_metrics": vital,
        }
        try:
            patch(f"/servicesNS/nobody/SA-ITOA/itoa_interface/entity_type/{eng['etype_key']}", et_payload)
            print(f"  updated entity type {eng['etype_title']}")
        except RuntimeError:
            post("/servicesNS/nobody/SA-ITOA/itoa_interface/entity_type", et_payload)
            print(f"  created entity type {eng['etype_title']}")
        upsert_entity_import_savedsearch(eng["import_name"], eng["import_spl"])
        delete_saved_search("search", eng["import_name"])

    print("=== 3. Service templates (source of truth for KPIs) ===")
    for eng in ENGINES.values():
        upsert_template(eng)

    print("=== 4. Leaf services (linked to templates) ===")
    for eng in ENGINES.values():
        upsert_leaf_service(eng)

    print("=== 5. Rollup service Database (serviceid deps) ===")
    upsert_rollup([eng["svc_key"] for eng in ENGINES.values()])
    refresh_rollup_deps([eng["svc_key"] for eng in ENGINES.values()])

    print("=== 6. Entity imports (upsert, clear cache, dispatch, bind) ===")
    cleanup_orphan_dbm_entities()
    for eng in ENGINES.values():
        upsert_entity_import_savedsearch(eng["import_name"], eng["import_spl"])
        clear_import_cache(eng["import_name"])
        try:
            dispatch_import(eng["import_name"])
        except Exception as exc:
            print(f"  WARN dispatch {eng['import_name']}: {exc}")
        bind_service_entities(eng)

    print("=== 7. Refresh KPI indicators + rollup deps ===")
    dispatch_shared_indicators()
    refresh_rollup_deps([eng["svc_key"] for eng in ENGINES.values()])

    print("=== Done ===")


if __name__ == "__main__":
    main()
