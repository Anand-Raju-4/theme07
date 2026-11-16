# Theme 07 · Schema Drift Impact Analyzer · Starter kit

**Intent:** As a data platform lead, I want to know immediately what a source schema change will break, all the way to the reports, so that we fix it before users notice.

## What's in this kit

```
schemas/
  sources_before.json        Current schemas of 4 source tables (CRM JSON files, ERP SQL tables)
  sources_after.json         Schemas after all 10 changes
  seeded_changes.json        The 10 changes to analyse, one at a time
project/                     The "Contoso Sales" lakehouse project
  config/ingest_config.json  How each source is ingested (reader, query, write mode, schema options)
  config/schemas/            Explicit JSON schema used for CRM files
  notebooks/                 nb01 bronze ingest → nb02-04 silver → nb05-06 gold (Databricks source format)
  pipelines/pl_daily_sales_load.json   Orchestration and dependencies
  powerbi/sales_analytics_model.json   Semantic model tables, measures, reports, visuals and owners
templates/impact_report_template.csv
```

## What you build

1. Schema diff detection: added, dropped, renamed and type-changed columns.
2. A lineage graph from the config, notebooks, pipeline and Power BI metadata, down to report visuals.
3. Impact per change: **breaks**, **degrades** or **no impact**, with severity.
4. Proposed fixes for notebooks, configs and the semantic model.
5. A verdict for each change: **safe to load** or **hold the load**.

Read the ingestion config carefully: how a source is read decides whether a change fails loudly or quietly.

## Output contract

`impact_report.csv`: change_id, change_type, object, object_type, impact, severity, proposed_fix
(one row per affected object; add a verdict per change in your summary)

## How you'll be judged on proof

Correct impact prediction for all 10 seeded changes.

## Ground rules

- All data in this kit is synthetic. Names, emails and identifiers are invented.
- Do not upload any customer data, and do not put credentials or secrets in prompts or code.
- Use only the approved AI tools on the provided sandbox.
- Anything that changes data or systems needs a human approval step.
- If you can't explain it in Q&A, it doesn't count.
