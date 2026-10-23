#!/usr/bin/env python3
"""Deploy the AI Infrastructure Monitoring ITSI objects over REST (authoring tool).

Needs the AI_Infrastructure stream of TA-o11y-sim-streams 1.1.0 or later.
Environment: ITSI_URL, ITSI_TOKEN, ITSI_INSECURE=1 for self-signed management certificates.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import itsi_pack  # noqa: E402

GPU = {
    "key": "aiinf_gpu",
    "column_prefix": "aiinf_gpu_",
    "sources": [{"labels": "aiinf_gpu_*", "dims": ["UUID"], "eval": "| eval ITSIUniqueId=UUID"}],
    "info_sources": [
        {"labels": "aiinf_gpu_util", "dims": ["UUID", "host.name", "gpu", "modelName"],
         "eval": "| eval ITSIUniqueId=UUID, host=lower('host.name'), gpu_index=gpu, gpu_model=modelName"},
        {"labels": "aiinf_gpu_util", "dims": ["UUID", "k8s.cluster.name"],
         "eval": "| eval ITSIUniqueId=UUID, cluster='k8s.cluster.name'"},
    ],
    "info_fields": ["host", "gpu_index", "gpu_model", "cluster"],
    "title_eval": ('| eval entity_title=coalesce(host,"unknown-host").":gpu".coalesce(gpu_index,"?")'
                   '." (".coalesce(gpu_model,"GPU").") ".substr(ITSIUniqueId,5,8)'),
    "derive": (
        "| eval gpu_util=round(aiinf_gpu_util,1), "
        "gpu_fb_used_pct=if(aiinf_gpu_fb_used+aiinf_gpu_fb_free>0, "
        "round(100*aiinf_gpu_fb_used/(aiinf_gpu_fb_used+aiinf_gpu_fb_free),1), null()), "
        "gpu_power_w=round(aiinf_gpu_power,1), gpu_temp_c=aiinf_gpu_temp, gpu_mem_temp_c=aiinf_gpu_mem_temp, "
        "gpu_tensor_pct=round(100*aiinf_gpu_tensor,1), gpu_xid=aiinf_gpu_xid "
        "| fields _time ITSIUniqueId gpu_*"
    ),
    "kpis": [
        {"title": "GPU Utilization %", "field": "gpu_util", "unit": "%"},
        {"title": "Framebuffer Used %", "field": "gpu_fb_used_pct", "unit": "%"},
        {"title": "GPU Power", "field": "gpu_power_w", "unit": "W", "aggregate": "sum"},
        {"title": "GPU Temperature", "field": "gpu_temp_c", "unit": "°C", "aggregate": "max"},
        {"title": "Memory Temperature", "field": "gpu_mem_temp_c", "unit": "°C", "aggregate": "max"},
        {"title": "Tensor Core Active %", "field": "gpu_tensor_pct", "unit": "%"},
        {"title": "Last XID Error", "field": "gpu_xid", "entity": "max", "aggregate": "max",
         "description": "Most recent NVIDIA XID error code reported by DCGM; 0 means none. Reported by a subset of drivers only."},
    ],
    "vitals": [("GPU Utilization %", "gpu_util", "%"), ("Framebuffer Used %", "gpu_fb_used_pct", "%")],
    "dashboard": [("GPU Utilization %", "gpu_util"), ("Framebuffer Used %", "gpu_fb_used_pct"),
                  ("Power (W)", "gpu_power_w"), ("GPU Temperature (°C)", "gpu_temp_c")],
    "drilldown": ("UUID", "ITSIUniqueId"),
    "etype_key": "aiinf_o11y_nvidia_gpu",
    "etype_title": "O11y NVIDIA GPU",
    "etype_description": "NVIDIA GPU reported by the DCGM exporter to Splunk Observability Cloud (ITSIUniqueId = GPU UUID).",
    "dashboard_id": "aiinf_gpu_entity_health",
    "import_name": "AIINF Import Entities - NVIDIA GPU",
    "bs_key": "AIINF_GPU_BaseSearch",
    "svc_key": "aiinf_gpus",
    "svc_title": "AI GPUs",
    "svc_description": "NVIDIA GPUs (DCGM) from Splunk Observability Cloud. KPIs are managed on the AI GPUs (O11y) template.",
    "template_key": "aiinf_template_gpus",
    "template_title": "AI GPUs (O11y)",
}

VLLM = {
    "key": "aiinf_vllm",
    "column_prefix": "aiinf_vllm_",
    "sources": [{"labels": "aiinf_vllm_*", "dims": ["service.instance.id", "model_name"],
                 "eval": "| eval ITSIUniqueId='service.instance.id'.\"::\".model_name"}],
    "info_sources": [
        {"labels": "aiinf_vllm_running", "dims": ["service.instance.id", "model_name"],
         "eval": "| eval ITSIUniqueId='service.instance.id'.\"::\".model_name, instance='service.instance.id', model=model_name"},
        {"labels": "aiinf_vllm_running", "dims": ["service.instance.id", "model_name", "host.name"],
         "eval": "| eval ITSIUniqueId='service.instance.id'.\"::\".model_name, host=lower('host.name')"},
        {"labels": "aiinf_vllm_running", "dims": ["service.instance.id", "model_name", "k8s.cluster.name"],
         "eval": "| eval ITSIUniqueId='service.instance.id'.\"::\".model_name, cluster='k8s.cluster.name'"},
    ],
    "info_fields": ["instance", "model", "host", "cluster"],
    "title_eval": '| eval entity_title=coalesce(model,"model")." @ ".coalesce(instance,"instance")',
    "derive": (
        "| eval vllm_running=aiinf_vllm_running, vllm_waiting=aiinf_vllm_waiting, "
        "vllm_kv_pct=round(100*coalesce(aiinf_vllm_kv,aiinf_vllm_kv_legacy),1), "
        "vllm_latency_s=if(aiinf_vllm_e2e_count>0, round(aiinf_vllm_e2e_sum/aiinf_vllm_e2e_count,3), null()), "
        "vllm_prompt_tps=round(aiinf_vllm_prompt_tps,2), vllm_gen_tps=round(aiinf_vllm_gen_tps,2), "
        "vllm_preempt=round(aiinf_vllm_preempt,4) "
        "| fields _time ITSIUniqueId vllm_*"
    ),
    "kpis": [
        {"title": "Requests Running", "field": "vllm_running", "aggregate": "sum"},
        {"title": "Requests Waiting", "field": "vllm_waiting", "aggregate": "sum"},
        {"title": "KV Cache Usage %", "field": "vllm_kv_pct", "unit": "%", "aggregate": "max"},
        {"title": "Request Latency", "field": "vllm_latency_s", "unit": "s",
         "description": "Average end-to-end request latency. Needs the vLLM latency histogram, which not every exporter scrapes."},
        {"title": "Prompt Tokens /s", "field": "vllm_prompt_tps", "unit": "tokens/s", "aggregate": "sum"},
        {"title": "Generation Tokens /s", "field": "vllm_gen_tps", "unit": "tokens/s", "aggregate": "sum"},
        {"title": "Preemptions /s", "field": "vllm_preempt", "unit": "/s", "aggregate": "sum"},
    ],
    "vitals": [("Generation Tokens /s", "vllm_gen_tps", "tokens/s"), ("KV Cache Usage %", "vllm_kv_pct", "%")],
    "dashboard": [("Generation Tokens /s", "vllm_gen_tps"), ("Prompt Tokens /s", "vllm_prompt_tps"),
                  ("Requests Running", "vllm_running"), ("KV Cache Usage %", "vllm_kv_pct")],
    "drilldown": ("service.instance.id", "instance"),
    "etype_key": "aiinf_o11y_vllm_instance",
    "etype_title": "O11y vLLM Instance",
    "etype_description": "vLLM model server (one entity per serving endpoint and model; ITSIUniqueId = instance::model).",
    "dashboard_id": "aiinf_vllm_entity_health",
    "import_name": "AIINF Import Entities - vLLM Instance",
    "bs_key": "AIINF_vLLM_BaseSearch",
    "svc_key": "aiinf_model_serving",
    "svc_title": "AI Model Serving",
    "svc_description": "vLLM model serving (including NVIDIA Dynamo and llm-d workers). KPIs are managed on the AI Model Serving (O11y) template.",
    "template_key": "aiinf_template_model_serving",
    "template_title": "AI Model Serving (O11y)",
}

MILVUS = {
    "key": "aiinf_milvus",
    "column_prefix": "aiinf_milvus_",
    "sources": [{"labels": "aiinf_milvus_*", "dims": ["service.instance.id"],
                 "eval": "| eval ITSIUniqueId='service.instance.id'"}],
    "info_sources": [
        {"labels": "aiinf_milvus_req", "dims": ["service.instance.id"],
         "eval": "| eval ITSIUniqueId='service.instance.id', instance='service.instance.id'"},
        {"labels": "aiinf_milvus_req", "dims": ["service.instance.id", "k8s.cluster.name"],
         "eval": "| eval ITSIUniqueId='service.instance.id', cluster='k8s.cluster.name'"},
    ],
    "info_fields": ["instance", "cluster"],
    "title_eval": '| eval entity_title=if(isnotnull(cluster), cluster."/".instance, instance)',
    "derive": (
        "| eval milvus_req_s=round(aiinf_milvus_req,3), "
        "milvus_fail_pct=if(aiinf_milvus_req>0, round(100*coalesce(aiinf_milvus_fail,0)/aiinf_milvus_req,2), 0), "
        "milvus_search_latency_ms=if(aiinf_milvus_sq_count>0, round(aiinf_milvus_sq_sum/aiinf_milvus_sq_count,2), null()), "
        "milvus_search_vps=round(aiinf_milvus_search_vps,2), milvus_entities=aiinf_milvus_entities, "
        "milvus_nodes=aiinf_milvus_nodes "
        "| fields _time ITSIUniqueId milvus_*"
    ),
    "kpis": [
        {"title": "Requests /s", "field": "milvus_req_s", "unit": "/s", "aggregate": "sum"},
        {"title": "Failed Requests %", "field": "milvus_fail_pct", "unit": "%", "aggregate": "max"},
        {"title": "Search Latency", "field": "milvus_search_latency_ms", "unit": "ms"},
        {"title": "Search Vectors /s", "field": "milvus_search_vps", "unit": "/s", "aggregate": "sum"},
        {"title": "Loaded Entities", "field": "milvus_entities", "aggregate": "sum"},
        {"title": "Milvus Nodes", "field": "milvus_nodes", "aggregate": "sum"},
    ],
    "vitals": [("Requests /s", "milvus_req_s", "/s"), ("Search Latency", "milvus_search_latency_ms", "ms")],
    "dashboard": [("Requests /s", "milvus_req_s"), ("Failed Requests %", "milvus_fail_pct"),
                  ("Search Latency (ms)", "milvus_search_latency_ms"), ("Loaded Entities", "milvus_entities")],
    "drilldown": ("service.instance.id", "ITSIUniqueId"),
    "etype_key": "aiinf_o11y_milvus_instance",
    "etype_title": "O11y Milvus Instance",
    "etype_description": "Milvus vector database instance (ITSIUniqueId = metrics endpoint).",
    "dashboard_id": "aiinf_milvus_entity_health",
    "import_name": "AIINF Import Entities - Milvus Instance",
    "bs_key": "AIINF_Milvus_BaseSearch",
    "svc_key": "aiinf_vector_databases",
    "svc_title": "AI Vector Databases",
    "svc_description": "Milvus vector databases. KPIs are managed on the AI Vector Databases (O11y) template.",
    "template_key": "aiinf_template_vector_databases",
    "template_title": "AI Vector Databases (O11y)",
}

PACK = {
    "app": "DA-ITSI-CP-ai-infrastructure-monitoring",
    "app_label": "ITSI CP - AI Infrastructure Monitoring (O11y)",
    "macro": "aiinf_sim_metrics_indexes",
    "rollup": {
        "key": "aiinf_rollup",
        "title": "AI Infrastructure Monitoring",
        "description": "AI infrastructure from Splunk Observability Cloud: GPUs, model serving and vector databases.",
    },
    "components": [GPU, VLLM, MILVUS],
}

if __name__ == "__main__":
    itsi_pack.deploy(PACK)
