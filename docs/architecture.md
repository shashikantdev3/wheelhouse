# Architecture

## Shape

```
                 +-------------------------- Wheelhouse (self-hosted) --------------------------+
 client systems  |                                                                               |
 hosts, DBs,  -->|  Connectors (MCP servers)  -->  Signals store  -->  Watch / Move / Keel crews  |--> Bosun: email, chat
 queues, ETL,    |  SSH, WinRM, SQL, RabbitMQ,      (Postgres)          |                         |
 Fabric,         |  Airflow, Databricks, Fabric,                        v                         |
 Databricks,     |  OpenTelemetry (GenAI traces)               Lockkeeper (code gate)             |
 AI apps         |                                                      |                         |
                 |                                      Helmsman runs approved actions only       |
                 |                                                      |                         |
                 |   Purser ledger (ProvenKit AIDR, hash-chained)  <----+   Web console (approve,  |
                 |   Quartermaster costs   Assayer evals                     dashboards, proof pack)|
                 +-------------------------------------------------------------------------------+
```

## Decisions that shape the code

- **Python 3.12, typed, Pydantic models.** One language for agents, connectors and maths, so every part is readable and defensible.
- **A deterministic workflow with LLM steps, not a free agent loop.** Each incident moves through fixed states (detected, triaged, investigated, planned, approved, executed, verified, closed). Each state is persisted. The model fills in content inside a state; it does not choose which state comes next. This makes runs replayable and auditable.
- **Typed actions, never shell strings.** See [safety-model.md](safety-model.md).
- **Connectors as MCP servers.** A new environment type means a new connector, not new agents. The same connectors can be used from Claude Code or GitHub Copilot.
- **Model providers behind one interface.** Anthropic, OpenRouter (including decision models such as Microsoft-Decision-1), Azure AI Foundry and Ollama. The client chooses; nothing is hard-wired.
- **Statistics for forecasting.** Barometer uses trend and seasonal baselines. LLMs explain; they do not forecast.
- **OpenTelemetry GenAI conventions for Keel.** Wheelhouse emits `gen_ai.*` spans for its own agents and accepts them from client AI apps over OTLP. These conventions were still marked "Development" in mid-2026, so Keel maps attributes through one adapter that can change in one place.
- **Postgres for state, DuckDB for analytics, JSONL ledger on disk.** Runs on one VM with Docker Compose; a Helm chart comes later.
- **Web console in Python (FastAPI, Jinja, HTMX).** No separate JavaScript application to maintain.

## Folder layout (target)

```
src/wheelhouse/
  config.py          settings from environment and .env
  safety/            Lockkeeper: tiers, catalog, guards, approvals   (Sprint 0)
  ledger/            Purser: ProvenKit AIDR records, hash chain      (Sprint 1)
  providers/         model providers and decision models             (Sprint 1)
  connectors/        MCP servers: linux, mysql, rabbitmq, ...        (Sprint 1+)
  watch/             Lookout, Barometer, Diver, Navigator, Helmsman, Bosun
  move/              Surveyor, Cartographer, Shipwright
  keel/              Quartermaster, Master-at-Arms, trace ingest
  assay/             Assayer: claim checks, parity, evaluations
  console/           web console
lab/                 Docker Compose lab and drills (faults with known root causes)
docs/                vision, crew, safety model, roadmap, decisions
```
