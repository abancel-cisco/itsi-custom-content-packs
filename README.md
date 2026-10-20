# ITSI custom content packs

Custom content packs for Splunk IT Service Intelligence (ITSI), with the add-ons that feed them.

| Folder | What it is | Latest |
|---|---|---|
| [`content-packs/database-monitoring`](content-packs/database-monitoring) | Oracle, Microsoft SQL Server and PostgreSQL service tree on Splunk Observability Cloud metrics | 1.2.0 |
| [`add-ons/TA-o11y-sim-streams`](add-ons/TA-o11y-sim-streams) | Curated Splunk Infrastructure Monitoring data streams (SignalFlow) that pull Observability Cloud metrics into a Splunk metrics index | 1.0.0 |

Installable packages are attached to the [GitHub releases](../../releases). The folders hold the sources and the authoring tooling.

## How the pieces fit

1. OpenTelemetry collector receivers send database metrics to Splunk Observability Cloud.
2. The Splunk Infrastructure Monitoring Add-on (`splunk_ta_sim`) runs the SignalFlow streams shipped in `TA-o11y-sim-streams` and writes the results to the `sim_metrics` metrics index.
3. The content pack builds ITSI entities, services and KPIs on top of that index.

## Status

These packs are community content, not supported Splunk products. They are tested on Splunk Enterprise 10.x with ITSI 5.0.x. Test in a non-production environment first.

## License

[Apache License 2.0](LICENSE).
