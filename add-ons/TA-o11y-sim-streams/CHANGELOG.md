# Changelog

## 1.1.0

- AI streams: `AI_Infrastructure` (NVIDIA DCGM GPUs, vLLM model serving, Milvus vector database) and `AI_Providers` (AWS Bedrock and Azure OpenAI tokens, requests, throttling and latency).
- AI streams publish unique labels, stored as the `sf_streamLabel` dimension, so packs read only their own streams.
- `build_inputs_conf.py` counts `histogram(...)` calls as metrics.

## 1.0.0

- First release: `OS_Hosts`, `Oracle_DB`, `Postgres_DB` and `MSSQL_DB` streams, shipped disabled.
