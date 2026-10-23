# AI Infrastructure Monitoring content pack

ITSI service trees for AI infrastructure monitored by Splunk Observability Cloud:

- **AI Infrastructure Monitoring**: NVIDIA GPUs, vLLM model serving and Milvus vector databases.
- **AI Tokens and Costs**: token usage, requests and estimated cost of managed AI providers (AWS Bedrock, Azure OpenAI).

Metrics reach Splunk through the Splunk Infrastructure Monitoring Add-on and the companion [`TA-o11y-sim-streams`](../../add-ons/TA-o11y-sim-streams) (1.1.0 or later).

## Requirements

- Splunk ITSI (tested on 5.0.x).
- Splunk Infrastructure Monitoring Add-on (`splunk_ta_sim`), connected to your Observability Cloud org.
- `TA-o11y-sim-streams` 1.1.0 with the `AI_Infrastructure` and `AI_Providers` streams enabled, writing to the `sim_metrics` metrics index.
- In Observability Cloud, any of: the NVIDIA DCGM exporter (`DCGM_FI_DEV_*`), vLLM metrics (`vllm:*`), Milvus metrics (`milvus_*`), the AWS integration (CloudWatch `AWS/Bedrock`), the Azure integration (Cognitive Services, for Azure OpenAI). Services without data stay empty.

## Install

1. Install `TA-o11y-sim-streams` on the search head and enable the `AI_Infrastructure` and `AI_Providers` streams. Leave `org_id` blank to use the add-on's default account.
2. Check that metrics arrive. Cloud provider metrics reach Observability Cloud several minutes late, so allow about fifteen minutes:

   ```spl
   | mstats count(_value) where index=sim_metrics metric_name=* (sf_streamLabel=aiinf_* OR sf_streamLabel=aitok_*) by sf_streamLabel
   ```

3. Install the content pack app `DA-ITSI-CP-CUST-6adb6edda4d5254f2e07f4c9_1_0_0.tar.gz` from the GitHub release (Apps → Install app from file), then install the pack from ITSI → Configuration → Data integrations → Content library.
4. Run the four `AIINF Import Entities - *` and `AITOK Import Entities - *` searches once to create the entities.
5. Align the `ai_model_prices` lookup with the token rates configured in Observability Cloud (see Model prices).

## What is included

| Object | Names |
|---|---|
| Services | AI (top level), depending on two rollups. AI Infrastructure Monitoring (rollup): AI GPUs, AI Model Serving, AI Vector Databases. AI Tokens and Costs (rollup): AI Provider Tokens and Costs |
| Service templates | One per leaf service, named after it with an `(O11y)` suffix; each leaf service is linked to its template |
| KPI base searches | `AIINF_GPU_BaseSearch`, `AIINF_vLLM_BaseSearch`, `AIINF_Milvus_BaseSearch`, `AITOK_Provider_BaseSearch`: 15-minute window, 5-minute frequency |
| Entity types | O11y NVIDIA GPU, O11y vLLM Instance, O11y Milvus Instance, O11y AI Provider Model, each with vital metrics and an entity health dashboard |
| Entity import searches | `AIINF Import Entities - NVIDIA GPU`, `- vLLM Instance`, `- Milvus Instance`, `AITOK Import Entities - AI Provider Model` |
| Lookup | `ai_model_prices` (file `ai_model_prices.csv`), USD per million tokens per model |
| Macros | `aiinf_sim_metrics_indexes`, `aitok_sim_metrics_indexes` (default `index=sim_metrics`) |

| Entity type | ITSIUniqueId | Informational fields |
|---|---|---|
| O11y NVIDIA GPU | GPU UUID | host, gpu_index, gpu_model, cluster |
| O11y vLLM Instance | `service.instance.id::model_name` | instance, model, host, cluster |
| O11y Milvus Instance | `service.instance.id` | instance, cluster |
| O11y AI Provider Model | `aws-bedrock::ModelId` or `azure-openai::account::deployment` | provider, model, account |

## KPIs

| Service | KPIs |
|---|---|
| AI GPUs (7) | GPU Utilization %, Framebuffer Used %, GPU Power (sum across GPUs), GPU Temperature (max), Memory Temperature (max), Tensor Core Active %, Last XID Error |
| AI Model Serving (7) | Requests Running, Requests Waiting, KV Cache Usage % (max), Request Latency, Prompt Tokens /s, Generation Tokens /s, Preemptions /s |
| AI Vector Databases (6) | Requests /s, Failed Requests %, Search Latency, Search Vectors /s, Loaded Entities, Milvus Nodes |
| AI Provider Tokens and Costs (7) | Estimated Cost (USD), Input Tokens, Output Tokens, Requests, Throttled Requests, Response Latency (ms), Unpriced Models |

vLLM counters arrive as per-second rates. KV Cache Usage reads `vllm:kv_cache_usage_perc` and falls back to the older `vllm:gpu_cache_usage_perc`. vLLM workers behind NVIDIA Dynamo or llm-d report the same metrics and land in AI Model Serving. Provider token, request and cost KPIs are totals per 5-minute interval, summed across models.

## Model prices

Provider metrics carry no cost. The pack multiplies input and output tokens by the `ai_model_prices` lookup. Observability Cloud does the same on Infrastructure → AI infrastructure provider tokens and costs, using the org's token rates. Both are estimates from published prices, not billing data.

`ai_model_prices.csv` has the columns `provider`, `model_pattern`, `input_usd_per_mtok`, `output_usd_per_mtok`, `effective_date` and `notes`. The provider model is matched against `model_pattern` with wildcards, case-insensitively, and the first matching row wins, so keep specific patterns (`gpt-4.1-mini*`) above generic ones (`gpt-4.1*`).

- Keep the lookup aligned with the token rates of the Observability Cloud provider dashboard (actions menu → Edit token rates), so ITSI and Observability Cloud show the same cost. Update both together.
- The shipped rows are public list prices at authoring time, marked `list price - verify`.
- For Azure OpenAI the deployment name is matched, so add a row per deployment if your deployment names differ from the model names.
- Models without a row count 0 in Estimated Cost and 1 in Unpriced Models.

Edit the file with the Lookup Editor app, or replace it with `| inputlookup ai_model_prices.csv | ... | outputlookup ai_model_prices.csv`.

## After install

- If the SIM metrics land in another index, edit both `*_sim_metrics_indexes` macros.
- Narrow the entity rules on the leaf services (`ITSIUniqueId matches *` and the entity type) if needed.
- KPIs ship without severity thresholds, so every KPI reports normal. Add static or adaptive thresholds, and cost budgets, per environment.
- Request Latency and Search Latency need the vLLM end-to-end latency histogram and the Milvus search latency histogram. When an exporter does not send them, the KPIs show N/A at info severity, which does not affect the health score. The same applies to provider models between calls.
- Last XID Error is reported by a subset of GPU drivers only.
- Edit KPIs on the service templates, not on the services: linked services receive template changes.

## Out of scope

Agent-level tokens and costs are not included. They depend on agent instrumentation metrics whose Observability Cloud experience is changing; the AI Tokens and Costs rollup leaves room for an agent subtree in a later version.

## Troubleshooting

| Symptom | Fix |
|---|---|
| No `aiinf_*` or `aitok_*` series in `sim_metrics` | Check that the add-on's default SIM account points at the right Observability org, or set `org_id` on the inputs. Provider metrics arrive late; wait fifteen minutes |
| Estimated Cost stays at 0 | Check Unpriced Models, then add a matching row to `ai_model_prices.csv` |
| Import searches succeed but create no entities after a reinstall | Delete the searches' records from the KV collections `itsi_import_objects_cache` and `itsi_bulk_import_entities_status_cache`, then run them again |

## Authoring tools

[`tools/deploy_ai_infrastructure.py`](tools/deploy_ai_infrastructure.py) and [`tools/deploy_ai_tokens_and_costs.py`](tools/deploy_ai_tokens_and_costs.py) create or update every object of the pack over REST, using the shared deployer in [`tools/itsi_pack.py`](../../tools/itsi_pack.py). `deploy_ai_tokens_and_costs.py --print-spl` prints the searches without deploying.

```sh
export ITSI_URL=https://your-search-head:8089 ITSI_TOKEN=<bearer token>
python3 tools/deploy_ai_infrastructure.py
python3 tools/deploy_ai_tokens_and_costs.py
```

Set `ITSI_INSECURE=1` only for management ports with self-signed certificates. Read the token from a secret store or environment; do not put it in files.

The ITSI authoring page packages the lookup file but not its lookup definition. [`tools/postbuild.py`](tools/postbuild.py) adds `default/transforms.conf` to the authored package and can drop screenshots:

```sh
python3 tools/postbuild.py authored.tar.gz DA-ITSI-CP-CUST-<id>_1_0_0.tar.gz --drop-screenshot "<file name>"
```

See [CHANGELOG.md](CHANGELOG.md) for release notes.
