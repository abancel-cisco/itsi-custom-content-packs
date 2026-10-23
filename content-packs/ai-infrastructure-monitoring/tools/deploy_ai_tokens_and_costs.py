#!/usr/bin/env python3
"""Deploy the AI Tokens and Costs ITSI objects over REST (authoring tool).

Part of the AI Infrastructure Monitoring content pack. Needs the AI_Providers stream of
TA-o11y-sim-streams 1.1.0 or later.
Environment: ITSI_URL, ITSI_TOKEN, ITSI_INSECURE=1 for self-signed management certificates.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import itsi_pack  # noqa: E402

PRICE_LOOKUP = "ai_model_prices"
PRICE_FILE = "ai_model_prices.csv"
# List prices in USD per million tokens at authoring time. Verify against the provider price pages and
# your contracted rates; the first matching row wins, so keep specific patterns above generic ones.
PRICES = [
    ("aws-bedrock", "*claude-sonnet-4-5*", 3.00, 15.00),
    ("aws-bedrock", "*claude-haiku-4-5*", 1.00, 5.00),
    ("azure-openai", "gpt-4.1-mini*", 0.40, 1.60),
    ("azure-openai", "gpt-4.1-nano*", 0.10, 0.40),
    ("azure-openai", "gpt-4.1*", 2.00, 8.00),
    ("azure-openai", "gpt-4o-mini*", 0.15, 0.60),
    ("azure-openai", "gpt-4o*", 2.50, 10.00),
    ("azure-openai", "text-embedding-3-large*", 0.13, 0.00),
    ("azure-openai", "text-embedding-3-small*", 0.02, 0.00),
]
PRICE_DATE = "2026-10-21"

PROVIDER = {
    "key": "aitok_prov",
    "column_prefix": "aitok_prov_",
    "label_expr": 'replace(sf_streamLabel,"^aitok_(bedrock|azure)_","aitok_prov_")',
    "sources": [
        {"labels": "aitok_bedrock_*", "dims": ["ModelId"],
         "eval": '| eval ITSIUniqueId="aws-bedrock::".ModelId, provider="aws-bedrock", model=ModelId'},
        {"labels": "aitok_azure_*", "dims": ["azure_resource_id", "modeldeploymentname"],
         "eval": '| eval account=mvindex(split(azure_resource_id,"/"),-1), '
                 'ITSIUniqueId="azure-openai::".account."::".modeldeploymentname, '
                 'provider="azure-openai", model=modeldeploymentname'},
    ],
    "info_fields": ["provider", "model", "account"],
    "title_eval": '| eval entity_title=model." (".provider.if(isnotnull(account), "/".account, "").")"',
    "derive": (
        '| eval model=mvindex(split(ITSIUniqueId,"::"),-1) '
        f"| lookup {PRICE_LOOKUP} model_pattern AS model OUTPUT input_usd_per_mtok output_usd_per_mtok "
        "| eval prov_tok_in=aitok_prov_tok_in, prov_tok_out=aitok_prov_tok_out, "
        "prov_requests=aitok_prov_req, prov_throttled=coalesce(aitok_prov_throttled,0), "
        "prov_latency_ms=round(aitok_prov_latency,1), "
        "prov_unpriced=if(isnull(input_usd_per_mtok),1,0), "
        "prov_cost_usd=round((coalesce(aitok_prov_tok_in,0)*coalesce(input_usd_per_mtok,0)"
        "+coalesce(aitok_prov_tok_out,0)*coalesce(output_usd_per_mtok,0))/1000000,4) "
        "| fields _time ITSIUniqueId prov_*"
    ),
    "kpis": [
        {"title": "Estimated Cost (USD / 5 min)", "field": "prov_cost_usd", "unit": "USD", "aggregate": "sum",
         "description": f"Tokens multiplied by the {PRICE_LOOKUP} lookup (USD per million tokens). 0 when the model has no price row."},
        {"title": "Input Tokens (/ 5 min)", "field": "prov_tok_in", "unit": "tokens", "aggregate": "sum"},
        {"title": "Output Tokens (/ 5 min)", "field": "prov_tok_out", "unit": "tokens", "aggregate": "sum"},
        {"title": "Requests (/ 5 min)", "field": "prov_requests", "aggregate": "sum"},
        {"title": "Throttled Requests (/ 5 min)", "field": "prov_throttled", "aggregate": "sum",
         "description": "Bedrock InvocationThrottles or Azure OpenAI requests answered with HTTP 429."},
        {"title": "Response Latency", "field": "prov_latency_ms", "unit": "ms",
         "description": "Bedrock InvocationLatency or Azure OpenAI TimeToResponse."},
        {"title": "Unpriced Models", "field": "prov_unpriced", "entity": "max", "aggregate": "sum",
         "description": f"1 when the model matches no row of the {PRICE_LOOKUP} lookup, so its cost is not counted."},
    ],
    "vitals": [("Estimated Cost (USD / 5 min)", "prov_cost_usd", "USD"), ("Input Tokens (/ 5 min)", "prov_tok_in", "tokens")],
    "dashboard": [("Estimated Cost (USD / 5 min)", "prov_cost_usd"), ("Input Tokens", "prov_tok_in"),
                  ("Output Tokens", "prov_tok_out"), ("Requests", "prov_requests")],
    "drilldown": ("modeldeploymentname", "model"),
    "etype_key": "aitok_o11y_ai_provider_model",
    "etype_title": "O11y AI Provider Model",
    "etype_description": "Model consumed from a managed AI provider: AWS Bedrock model or Azure OpenAI deployment "
                         "(ITSIUniqueId = provider::model or azure-openai::account::deployment).",
    "dashboard_id": "aitok_provider_entity_health",
    "import_name": "AITOK Import Entities - AI Provider Model",
    "bs_key": "AITOK_Provider_BaseSearch",
    "svc_key": "aitok_provider_tokens_costs",
    "svc_title": "AI Provider Tokens and Costs",
    "svc_description": "Token consumption and estimated cost of managed AI providers (AWS Bedrock, Azure OpenAI). "
                       "KPIs are managed on the AI Provider Tokens and Costs (O11y) template.",
    "template_key": "aitok_template_provider_tokens_costs",
    "template_title": "AI Provider Tokens and Costs (O11y)",
}

PACK = {
    "app": "DA-ITSI-CP-ai-tokens-and-costs",
    "app_label": "ITSI CP - AI Tokens and Costs (O11y)",
    "macro": "aitok_sim_metrics_indexes",
    "rollup": {
        "key": "aitok_rollup",
        "title": "AI Tokens and Costs",
        "description": "Tokenomics from Splunk Observability Cloud: token usage and estimated cost of managed AI providers.",
    },
    "components": [PROVIDER],
}


def ensure_price_lookup(pack: dict):
    """Creates the price table once; later runs keep any prices edited in Splunk."""
    app = pack["app"]
    files = f"/servicesNS/nobody/{app}/data/lookup-table-files"
    # The endpoint only lists files written by outputlookup after a reload.
    itsi_pack._request("GET", f"{files}/_reload")
    if not itsi_pack.exists(f"{files}/{PRICE_FILE}"):
        rows = ["provider,model_pattern,input_usd_per_mtok,output_usd_per_mtok,effective_date,notes"]
        rows += [f"{p},{m},{i},{o},{PRICE_DATE},list price - verify" for p, m, i, o in PRICES]
        data = "\n".join(rows)
        # makeresults only splits rows on real newlines, so the CSV must not be JSON-escaped.
        spl = (f'| makeresults format=csv data="{data}" '
               "| table provider model_pattern input_usd_per_mtok output_usd_per_mtok effective_date notes "
               f"| outputlookup {PRICE_FILE}")
        itsi_pack.form("POST", f"/servicesNS/nobody/{app}/search/jobs",
                       {"search": spl, "exec_mode": "oneshot", "output_mode": "json"})
        itsi_pack._request("GET", f"{files}/_reload")
        if not itsi_pack.exists(f"{files}/{PRICE_FILE}"):
            raise RuntimeError(f"{PRICE_FILE} was not created")
        print(f"  created {PRICE_FILE} ({len(PRICES)} models)")
    else:
        print(f"  kept existing {PRICE_FILE}")
    itsi_pack.form("POST", f"{files}/{PRICE_FILE}/acl", {"owner": "nobody", "sharing": "global", "perms.read": "*",
                                                         "perms.write": "admin,power"})
    lookups = f"/servicesNS/nobody/{app}/data/transforms/lookups"
    fields = {"filename": PRICE_FILE, "match_type": "WILDCARD(model_pattern)", "max_matches": "1",
              "case_sensitive_match": "0"}
    if itsi_pack.exists(f"{lookups}/{PRICE_LOOKUP}"):
        itsi_pack.form("POST", f"{lookups}/{PRICE_LOOKUP}", fields)
    else:
        itsi_pack.form("POST", lookups, {"name": PRICE_LOOKUP, **fields})
    itsi_pack.form("POST", f"{lookups}/{PRICE_LOOKUP}/acl", {"owner": "nobody", "sharing": "global", "perms.read": "*"})
    print(f"  lookup definition {PRICE_LOOKUP}")


if __name__ == "__main__":
    if "--print-spl" in sys.argv:
        for comp in PACK["components"]:
            print(f"## {comp['bs_key']}\n{itsi_pack.base_search_spl(PACK, comp)}\n")
            print(f"## {comp['import_name']}\n{itsi_pack.import_spl(PACK, comp)}\n")
    else:
        itsi_pack.deploy(PACK, extra_steps=ensure_price_lookup)
