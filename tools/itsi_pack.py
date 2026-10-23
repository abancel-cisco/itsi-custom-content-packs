"""Shared REST deployer for the label-pivot content packs (authoring tool, not needed to install a pack).

A pack is a dict (see content-packs/*/tools/deploy_*.py) with a rollup service and components. Each
component is one leaf service linked to its own service template, one KPI base search, one entity
type with vitals and an entity health dashboard, and one entity import search.

Data comes from TA-o11y-sim-streams: every SignalFlow stream carries a unique label, stored by the SIM
add-on as the sf_streamLabel dimension. Base searches pivot those labels into columns, so a pack only
ever reads its own streams.

Environment: ITSI_URL (https://host:8089), ITSI_TOKEN (Splunk bearer token),
ITSI_INSECURE=1 to skip TLS verification for self-signed management certificates.
"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

ITSI_URL = os.environ["ITSI_URL"].rstrip("/")
TOKEN = os.environ["ITSI_TOKEN"]
CTX = ssl.create_default_context()
if os.environ.get("ITSI_INSECURE") == "1":
    CTX.check_hostname = False
    CTX.verify_mode = ssl.CERT_NONE

ITOA = "/servicesNS/nobody/SA-ITOA/itoa_interface"
TEAM = "default_itsi_security_group"


# ---------------------------------------------------------------- REST

def _request(method: str, path: str, body: bytes | None = None, content_type: str | None = None):
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(f"{ITSI_URL}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=CTX) as resp:
            raw = resp.read()
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:800]}") from e


def http(method: str, path: str, data=None):
    body = json.dumps(data).encode() if data is not None else None
    status, raw = _request(method, path, body, "application/json")
    return status, (json.loads(raw) if raw else None)


def get(path: str):
    try:
        status, data = http("GET", path)
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return None
        raise
    return data if status == 200 and data else None


def post(path: str, payload: dict):
    return http("POST", path, payload)


def patch(path: str, payload: dict):
    return http("POST", f"{path}?is_partial_data=1", payload)


def delete(path: str):
    try:
        return _request("DELETE", path)[0]
    except RuntimeError as exc:
        if "HTTP 404" in str(exc):
            return 404
        raise


def form(method: str, path: str, fields: dict, ok_codes=(200, 201)):
    body = urllib.parse.urlencode(fields).encode()
    try:
        status, raw = _request(method, path, body, "application/x-www-form-urlencoded")
    except RuntimeError as exc:
        code = int(str(exc).split("HTTP ")[1][:3])
        if code in ok_codes:
            return code, None
        raise
    return status, raw


def exists(path: str) -> bool:
    try:
        _request("GET", path)
        return True
    except RuntimeError:
        return False


def q(name: str) -> str:
    return urllib.parse.quote(name, safe="")


# ---------------------------------------------------------------- SPL builders

def _mstats(pack: dict, src: dict, with_label: bool) -> str:
    # mstats drops series that lack any by-field, so a source only groups by dimensions its streams always carry
    # unless the source sets fillnull, which keeps those series with the placeholder value instead
    by = ("sf_streamLabel " if with_label else "") + " ".join(src["dims"])
    fill = f'fillnull_value="{src["fillnull"]}" ' if src.get("fillnull") else ""
    return (f'| mstats {fill}latest(_value) as v where `{pack["macro"]}` metric_name=* sf_streamLabel={src["labels"]} '
            f'by {by} span=5m {src["eval"]}')


def _union(pack: dict, sources: list, with_label: bool) -> str:
    first, rest = sources[0], sources[1:]
    spl = _mstats(pack, first, with_label)
    for src in rest:
        spl += f" | append [ {_mstats(pack, src, with_label)} ]"
    return spl


def base_search_spl(pack: dict, comp: dict) -> str:
    """Component sources pivoted to one row per entity and 5-minute bucket, then KPI columns derived."""
    col = comp["column_prefix"]
    return (
        _union(pack, comp["sources"], with_label=True)
        + f' | eval lbl={comp.get("label_expr", "sf_streamLabel")} | eval {{lbl}}=v '
        + f"| stats first({col}*) as {col}* by _time ITSIUniqueId "
        + comp["derive"]
    )


def import_spl(pack: dict, comp: dict) -> str:
    info_aggs = " ".join(f"first({f}) as {f}" for f in comp["info_fields"])
    sources = comp["sources"] + comp.get("info_sources", [])
    return (
        _union(pack, sources, with_label=False)
        + f" | stats max(_time) as last_seen {info_aggs} by ITSIUniqueId "
        + f'{comp["title_eval"]} '
        + f'| eval etype="{comp["etype_title"]}" '
        + f"| table ITSIUniqueId entity_title etype {' '.join(comp['info_fields'])} last_seen"
    )


def entity_metric_spl(pack: dict, comp: dict, val_expr: str) -> str:
    """Per-entity series for vitals and dashboards, built on the base search columns."""
    return base_search_spl(pack, comp) + f" | eval val={val_expr} | table _time val ITSIUniqueId"


# ---------------------------------------------------------------- KPIs

def thresholds(field: str) -> dict:
    return {
        "baseSeverityColor": "#5fbf7fff", "baseSeverityColorLight": "#5fbf7f33",
        "baseSeverityLabel": "normal", "baseSeverityValue": 2,
        "gaugeMax": 100, "gaugeMin": 0, "isMaxStatic": False, "isMinStatic": True,
        "metricField": field, "renderBoundaryMax": 100, "renderBoundaryMin": 0, "thresholdLevels": [],
    }


def kpi_key(comp: dict, field: str) -> str:
    return f"{comp['key']}_{field}"


def make_kpi(pack: dict, comp: dict, spec: dict, service_entity_filter: bool) -> dict:
    spl = base_search_spl(pack, comp)
    return {
        "_key": kpi_key(comp, spec["field"]),
        "title": spec["title"],
        "description": spec.get("description", ""),
        "unit": spec.get("unit", ""),
        "search_type": "shared_base",
        "base_search_id": comp["bs_key"],
        "base_search_metric": spec["field"],
        "base_search": spl, "search": spl, "search_alert": spl,
        "is_entity_breakdown": True, "is_split_by_entity": True,
        "is_service_entity_filter": service_entity_filter,
        "is_filter_entities_to_service": service_entity_filter,
        "entity_breakdown_id_fields": "ITSIUniqueId", "entity_id_fields": "ITSIUniqueId",
        "entity_alias_filtering_fields": "ITSIUniqueId", "entity_filter_field": "ITSIUniqueId",
        "entity_split_field": "ITSIUniqueId",
        "threshold_field": spec["field"],
        "aggregate_thresholds": thresholds(spec["field"]),
        "entity_thresholds": thresholds(spec["field"]),
        "aggregate_statop": spec.get("aggregate", "avg"),
        "entity_statop": spec.get("entity", "avg"),
        "fill_gaps": "null_value", "gap_severity": "info", "gap_severity_value": "1",
        "gap_severity_color": "#AED3E5", "gap_severity_color_light": "#E3F0F6",
        "enabled": True, "alert_period": "5", "alert_lag": "30", "alert_on": "both", "urgency": 5.0,
        "type": "kpis_primary", "sec_grp": TEAM, "kpi_threshold_template_id": "",
        "anomaly_detection_alerting_enabled": False, "search_buckets": "", "search_occurrences": 1.0,
        "search_alert_earliest": "15",
    }


def base_search_payload(pack: dict, comp: dict) -> dict:
    metrics = [{
        "_key": spec["field"], "title": spec["title"], "threshold_field": spec["field"],
        "unit": spec.get("unit", ""),
        "aggregate_statop": spec.get("aggregate", "avg"), "entity_statop": spec.get("entity", "avg"),
        "fill_gaps": "null_value", "gap_severity": "info", "gap_severity_value": "1",
        "gap_severity_color": "#AED3E5", "gap_severity_color_light": "#E3F0F6",
    } for spec in comp["kpis"]]
    return {
        "_key": comp["bs_key"], "title": comp["bs_key"].replace("_", " "),
        "description": f"Consolidated KPI base search for {comp['svc_title']} (O11y SIM streams {comp['column_prefix']}*).",
        "base_search": base_search_spl(pack, comp),
        "search_alert_earliest": "15", "alert_period": "5", "alert_lag": "30",
        "is_metric": False, "metric_qualifier": "", "source_itsi_da": "", "sec_grp": TEAM,
        "is_entity_breakdown": True, "is_service_entity_filter": True,
        "is_split_by_entity": True, "is_filter_entities_to_service": True,
        "entity_breakdown_id_fields": "ITSIUniqueId", "entity_alias_filtering_fields": "ITSIUniqueId",
        "entity_id_fields": "ITSIUniqueId", "entity_filter_field": "ITSIUniqueId",
        "entity_split_field": "ITSIUniqueId",
        "metrics": metrics,
    }


# ---------------------------------------------------------------- deploy steps

def ensure_app(pack: dict):
    app = pack["app"]
    if not exists(f"/services/apps/local/{app}"):
        form("POST", "/services/apps/local", {"name": app, "template": "barebones", "visible": "false",
                                              "label": pack["app_label"]})
        print(f"  created app shell {app}")
    base = f"/servicesNS/nobody/{app}/configs/conf-macros"
    if not exists(f"{base}/{pack['macro']}"):
        form("POST", base, {"name": pack["macro"], "definition": "index=sim_metrics"})
        print(f"  created macro {pack['macro']}")
    form("POST", f"{base}/{pack['macro']}/acl", {"owner": "nobody", "sharing": "global", "perms.read": "*"})


def upsert_base_search(pack: dict, comp: dict):
    path = f"{ITOA}/kpi_base_search/{comp['bs_key']}"
    existing = get(path)
    payload = base_search_payload(pack, comp)
    if existing:
        post(path, {**existing, **payload})
        print(f"  updated base search {comp['bs_key']}")
    else:
        post(f"{ITOA}/kpi_base_search", payload)
        print(f"  created base search {comp['bs_key']}")


def dashboard_definition(pack: dict, comp: dict) -> dict:
    viz, ds, layout = {}, {}, []
    for i, (title, expr) in enumerate(comp["dashboard"]):
        viz[f"viz_{i}"] = {"dataSources": {"primary": f"ds_{i}"}, "title": title, "type": "splunk.line",
                           "options": {"nullValueDisplay": "gap", "legendDisplay": "off"}}
        ds[f"ds_{i}"] = {"name": f"ds_{i}", "type": "ds.search", "options": {"query": (
            base_search_spl(pack, comp) + f' | search ITSIUniqueId="$entity_id$" | eval val={expr} '
            f'| timechart span=5m avg(val) as "{title}"')}}
        layout.append({"item": f"viz_{i}", "type": "block",
                       "position": {"x": (i % 2) * 600, "y": (i // 2) * 260, "w": 580, "h": 250}})
    return {
        "title": f"{comp['etype_title']} Entity Health",
        "description": f"Splunk Observability metrics for {comp['etype_title']} entities.",
        "inputs": {},
        "defaults": {"dataSources": {"ds.search": {"options": {"queryParameters": {
            "earliest": "$global_time.earliest$", "latest": "$global_time.latest$"}}}}},
        "visualizations": viz, "dataSources": ds,
        "layout": {"type": "grid", "options": {"height": 560, "width": 1200}, "structure": layout, "globalInputs": []},
    }


def upsert_dashboard(pack: dict, comp: dict):
    app, view = pack["app"], comp["dashboard_id"]
    label = f"{comp['etype_title']} Entity Health"
    xml = (f'<dashboard version="2" theme="light">\n    <label>{label}</label>\n'
           f'    <description>ITSI entity health for {comp["etype_title"]}</description>\n'
           f'    <definition><![CDATA[\n{json.dumps(dashboard_definition(pack, comp), indent=4)}\n]]></definition>\n'
           f'</dashboard>\n')
    base = f"/servicesNS/nobody/{app}/data/ui/views"
    if exists(f"{base}/{view}"):
        form("POST", f"{base}/{view}", {"eai:data": xml})
    else:
        form("POST", base, {"name": view, "eai:data": xml})
    form("POST", f"{base}/{view}/acl", {"owner": "nobody", "sharing": "global", "perms.read": "*",
                                         "perms.write": "admin,power"})
    print(f"  dashboard {view}")


def upsert_entity_type(pack: dict, comp: dict):
    vitals = [{
        "is_key": 1 if i == 0 else 0, "metric_name": title,
        "matching_entity_fields": ["ITSIUniqueId"], "split_by_fields": ["ITSIUniqueId"],
        "unit": unit, "search": entity_metric_spl(pack, comp, expr),
    } for i, (title, expr, unit) in enumerate(comp["vitals"])]
    payload = {
        "_key": comp["etype_key"], "title": comp["etype_title"],
        "identifying_name": comp["etype_title"].lower(),
        "description": comp["etype_description"],
        "show_dashboards_in_service_analyzer": True, "show_navigation_in_service_analyzer": True,
        "data_drilldowns": [{
            "title": "O11y SIM metrics (Splunk)", "type": "metrics",
            "static_filter": {"type": "include", "field": "sf_streamLabel", "values": [f"{comp['column_prefix']}*"]},
            "entity_field_filter": {"type": "entity", "data_field": comp["drilldown"][0],
                                    "entity_field": comp["drilldown"][1]},
        }],
        "dashboard_drilldowns": [{
            "title": f"{comp['etype_title']} Entity Health", "id": comp["dashboard_id"], "base_url": "",
            "dashboard_type": "udf_dashboard",
            "params": {"static_params": {}, "alias_param_map": [
                {"alias": "ITSIUniqueId", "param": "entity_id"},
                {"alias": "time_range_token-2", "param": "global_time"},
            ]},
        }],
        "vital_metrics": vitals,
    }
    path = f"{ITOA}/entity_type/{comp['etype_key']}"
    if get(path):
        post(path, {**get(path), **payload})
        print(f"  updated entity type {comp['etype_title']}")
    else:
        post(f"{ITOA}/entity_type", payload)
        print(f"  created entity type {comp['etype_title']}")


def upsert_import_search(pack: dict, comp: dict):
    fields = {
        "search": import_spl(pack, comp),
        "dispatch.earliest_time": "-24h", "dispatch.latest_time": "now",
        "cron_schedule": "*/15 * * * *", "is_scheduled": "1", "disabled": "0",
        "actions": "itsi_import_objects", "action.itsi_import_objects": "1",
        "action.itsi_import_objects.param.backfill_enabled": "0",
        "action.itsi_import_objects.param.entity_identifier_fields": "ITSIUniqueId",
        "action.itsi_import_objects.param.entity_informational_fields": ",".join(comp["info_fields"] + ["etype", "last_seen"]),
        "action.itsi_import_objects.param.entity_merge_field": "ITSIUniqueId",
        "action.itsi_import_objects.param.entity_title_field": "entity_title",
        "action.itsi_import_objects.param.entity_type_field": "etype",
        "action.itsi_import_objects.param.service_enabled": "1",
        "action.itsi_import_objects.param.service_team": TEAM,
        "action.itsi_import_objects.param.service_templates_config": "{}",
        "action.itsi_import_objects.param.update_type": "upsert",
        "alert.track": "0",
    }
    base = f"/servicesNS/nobody/{pack['app']}/saved/searches"
    if exists(f"{base}/{q(comp['import_name'])}"):
        form("POST", f"{base}/{q(comp['import_name'])}", fields)
        print(f"  updated import search {comp['import_name']}")
    else:
        form("POST", base, {"name": comp["import_name"], **fields})
        print(f"  created import search {comp['import_name']}")
    form("POST", f"{base}/{q(comp['import_name'])}/acl", {"owner": "nobody", "sharing": "global", "perms.read": "*"})


def upsert_template(pack: dict, comp: dict):
    payload = {
        "_key": comp["template_key"], "title": comp["template_title"],
        "identifying_name": comp["template_title"].lower(),
        "description": f"KPIs for {comp['svc_title']}. Linked services receive changes made here.",
        "service_id": comp["svc_key"], "entity_rules": [],
        "kpis": [make_kpi(pack, comp, spec, service_entity_filter=False) for spec in comp["kpis"]],
        "team_id": TEAM, "is_healthscore_calculate_by_entity_enabled": 1,
    }
    path = f"{ITOA}/base_service_template/{comp['template_key']}"
    existing = get(path)
    if existing:
        post(path, {**existing, **{k: v for k, v in payload.items() if k != "entity_rules"}})
        print(f"  updated template {comp['template_title']}")
    else:
        post(f"{ITOA}/base_service_template", payload)
        # Creation copies KPIs from the source service and ignores the payload's KPI list.
        created = get(path)
        post(path, {**created, **{k: v for k, v in payload.items() if k != "entity_rules"}})
        print(f"  created template {comp['template_title']}")


def entity_rules(comp: dict) -> list:
    return [{"rule_condition": "AND", "rule_items": [
        {"field": "ITSIUniqueId", "field_type": "alias", "rule_type": "matches", "value": "*"},
        {"field": "etype", "field_type": "info", "rule_type": "matches", "value": comp["etype_title"].lower()},
    ]}]


def ensure_service_shell(comp: dict):
    """A template can only be created from an existing service, so new leaves start as empty services."""
    if not get(f"{ITOA}/service/{comp['svc_key']}"):
        post(f"{ITOA}/service", {"_key": comp["svc_key"], "title": comp["svc_title"],
                                 "identifying_name": comp["svc_title"].lower(), "enabled": False,
                                 "entity_rules": [], "kpis": [], "team_id": TEAM})
        print(f"  created empty service {comp['svc_title']}")


def upsert_leaf_service(pack: dict, comp: dict):
    payload = {
        "_key": comp["svc_key"], "title": comp["svc_title"], "identifying_name": comp["svc_title"].lower(),
        "description": comp["svc_description"], "enabled": True,
        "entity_rules": entity_rules(comp), "team_id": TEAM,
        "is_healthscore_calculate_by_entity_enabled": 1,
    }
    path = f"{ITOA}/service/{comp['svc_key']}"
    existing = get(path)
    if existing and existing.get("base_service_template_id") == comp["template_key"]:
        patch(path, payload)
        print(f"  patched service {comp['svc_title']} (linked; KPIs come from the template)")
        return
    if existing and existing.get("base_service_template_id"):
        raise RuntimeError(f"{comp['svc_key']} is linked to another template: {existing['base_service_template_id']}")
    template_titles = {spec["title"] for spec in comp["kpis"]}
    payload["kpis"] = [k for k in (existing or {}).get("kpis") or []
                       if str(k.get("_key", "")).startswith("SHKPI-") or k.get("title") not in template_titles]
    if existing:
        post(path, {**existing, **payload})
    else:
        post(f"{ITOA}/service", payload)
    post(f"{path}/base_service_template", {"_key": comp["template_key"], "overwrite_entity_rules": "ignore"})
    print(f"  {'updated' if existing else 'created'} service {comp['svc_title']} and linked it to {comp['template_title']}")


def upsert_rollup(pack: dict):
    r = pack["rollup"]
    deps = [{"serviceid": c["svc_key"], "kpis_depending_on": [f"SHKPI-{c['svc_key']}"], "overloaded_urgencies": {}}
            for c in pack["components"]]
    payload = {"_key": r["key"], "title": r["title"], "identifying_name": r["title"].lower(),
               "description": r["description"], "enabled": True, "entity_rules": [], "team_id": TEAM}
    path = f"{ITOA}/service/{r['key']}"
    if get(path):
        patch(path, payload)
    else:
        post(f"{ITOA}/service", {**payload, "kpis": []})
    patch(path, {"services_depends_on": []})
    patch(path, {"services_depends_on": deps})
    print(f"  rollup {r['title']} -> {len(deps)} services")


def run_imports(pack: dict, comp: dict):
    name = comp["import_name"]
    for coll in ("itsi_import_objects_cache", "itsi_bulk_import_entities_status_cache"):
        delete(f"/servicesNS/nobody/SA-ITOA/storage/collections/data/{coll}/{q(name)}")
    _, raw = form("POST", f"/servicesNS/nobody/{pack['app']}/saved/searches/{q(name)}/dispatch",
                  {"output_mode": "json", "trigger_actions": "1"})
    sid = json.loads(raw)["sid"]
    for _ in range(60):
        time.sleep(2)
        job = get(f"/servicesNS/nobody/{pack['app']}/search/jobs/{sid}?output_mode=json")
        if job and job["entry"][0]["content"].get("isDone"):
            print(f"  import {name}: {job['entry'][0]['content'].get('resultCount')} rows")
            return
    print(f"  import {name}: still running (sid={sid})")


def bind_entities(comp: dict):
    flt = q(json.dumps({"entity_type_ids": comp["etype_key"]}))
    items = get(f"{ITOA}/entity?filter={flt}&fields=_key&count=2000") or []
    keys = [i["_key"] for i in items if i.get("_key")]
    if keys:
        patch(f"{ITOA}/service/{comp['svc_key']}", {"entity_keys": keys})
    print(f"  {comp['svc_title']}: {len(keys)} entities")


def deploy(pack: dict, extra_steps=None):
    print(f"=== {pack['rollup']['title']} ===")
    print("--- app shell and index macro")
    ensure_app(pack)
    if extra_steps:
        print("--- pack-specific objects")
        extra_steps(pack)
    print("--- base searches")
    for comp in pack["components"]:
        upsert_base_search(pack, comp)
    print("--- entity types, dashboards, import searches")
    for comp in pack["components"]:
        upsert_dashboard(pack, comp)
        upsert_entity_type(pack, comp)
        upsert_import_search(pack, comp)
    print("--- service templates")
    for comp in pack["components"]:
        ensure_service_shell(comp)
        upsert_template(pack, comp)
    print("--- leaf services (linked to templates)")
    for comp in pack["components"]:
        upsert_leaf_service(pack, comp)
    print("--- rollup")
    upsert_rollup(pack)
    print("--- entity imports")
    for comp in pack["components"]:
        run_imports(pack, comp)
    time.sleep(20)
    for comp in pack["components"]:
        bind_entities(comp)
    print("=== done ===")
