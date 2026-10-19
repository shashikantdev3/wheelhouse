# Roadmap

Part-time pace, one sprint is about one to two weeks. Every sprint ends with tests passing in CI and an exit check. Nothing is called done until it is measured.

## Milestone 1: Watch works on a real lab (v0.1)

| Sprint | Scope | Exit check |
|---|---|---|
| **0. Foundations** (done 19 Oct 2026) | Plan and docs; Python project; settings; Lockkeeper core (tiers, typed catalog, destructive guard, read-only SQL check, approvals bound to a step hash); `wheelhouse doctor`; CI on Linux and Windows | Safety tests pass; doctor reports which model keys are present |
| **1. Lab, ledger, providers** (done 19 Oct 2026) | Docker Compose lab (web, app, MySQL, RabbitMQ, Memcached, an ETL job, all reachable over SSH); Purser ledger in ProvenKit format; model providers (Anthropic, OpenRouter, Ollama); Linux and MySQL connectors as MCP servers | `docker compose up` starts the lab; Look actions run against it and are recorded in the ledger |
| **2. Reactive crew** | Lookout (decision model first, via twosystems ladder), Diver, Navigator, Assayer claim check, Helmsman, approval screen in the console | One incident goes end to end: detected, investigated with cited evidence, planned, approved, executed, verified |
| **3. Drills and scorecard** | 20 to 30 injected faults with known root causes (failed load, schema drift, late data, disk full, queue backlog, stuck job, bad config); evaluation harness in CI | README shows a measured scorecard: diagnosis accuracy, time to diagnosis, unsafe action rate (target zero) |

**Release v0.1 here.** This is the point where Wheelhouse is resume-ready and demo-ready.

## Milestone 2: Proactive and provable (v0.2)

| Sprint | Scope | Exit check |
|---|---|---|
| **4. Barometer and Bosun** | Forecasts (disk fill time, CPU and memory pressure, queue growth, late data) with error bands; warning emails; shift handover report | Forecast error measured on lab history; a warning email arrives before an injected disk-fill fault |
| **5. Proof pack** | Monthly client report: watched, predicted, prevented, approved by whom; silent holdout so "prevented" is measured | Proof pack generated from a month of lab runs, every figure traceable to ledger records |

## Milestone 3: Keel, AI control built in (v0.3)

| Sprint | Scope | Exit check |
|---|---|---|
| **6. Observability and FinOps** | Trace view for Wheelhouse's own agents; OTLP ingest of `gen_ai.*` spans from client AI apps; Quartermaster dashboard (tokens and cost by agent, incident, client, model); budgets; Barometer forecasts budget overrun | A sample app instrumented with OpenTelemetry appears in the dashboard with correct token counts |
| **7. Guardrails, security, evals** | Master-at-Arms: prompt-injection and secret scans on untrusted text, tool-misuse rules, red-team drills; Assayer evaluations as CI gates; optimisation advice with measured saving | Red-team drill pack passes; a planted injection in a log line is caught and the action is refused |

## Milestone 4: Move (v0.4)

| Sprint | Scope | Exit check |
|---|---|---|
| **8. Survey and lineage** | Legacy estate in the lab (MySQL procedures, cron SQL and shell ETL); Surveyor inventory; Cartographer column lineage | Lineage graph matches a hand-labelled answer key |
| **9. Convert and prove** | Shipwright to dbt and Delta (DuckDB locally); Assayer parity (counts, checksums, sample diffs); migration waves gated by Lockkeeper; the lineage map handed to Watch | Parity report per table; share converted deterministically vs by LLM vs by hand, measured |

## Milestone 5: Ready to deploy for clients (v1.0)

| Sprint | Scope | Exit check |
|---|---|---|
| **10. Deploy anywhere** | Installer, Helm chart, Windows (WinRM) and cloud connectors (Azure, Fabric, Databricks), SSO | Fresh install on a clean VM in under one hour, timed |
| **11. Multi-client and launch** | Multi-client console, per-client policies, docs site, demo video, FDE deployment playbook | Two design partners running it |

## Out of scope until a client asks

Endpoint management, password resets, a ticketing system of our own, autonomous changes without approval.
