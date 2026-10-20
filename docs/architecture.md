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
- **State on disk first.** Today incidents are JSON files with a file lock and the ledger is a JSONL file. Postgres for state and DuckDB for analytics come with multi-client support; a Helm chart comes later.
- **Web console in Python, server-rendered, no JavaScript.** Sprint 2's approval console uses the standard library only (decision 0008); it can move to FastAPI when dashboards arrive.

## Folder layout

```
src/wheelhouse/
  config.py          settings from environment and .env                      (built)
  safety/            Lockkeeper: tiers, catalog, guard, SQL check, Ed25519 approvals (built)
  ledger/            Purser: ProvenKit AIDR records, hash chain, verify       (built)
  runtime/           inventory, SSH transport, runner, replay of recordings  (built)
  providers/         Anthropic, OpenRouter, Ollama with usage and cost        (built)
  crew/              incidents, Lookout, Diver, Assayer, Navigator, Helmsman, watch loop (built)
  console.py         approval console (local web page)                        (built)
  mcp_server.py      MCP server: look actions and change requests             (built)
  cli.py             doctor, catalog, check, hosts, run, request, approve, keys,
                     watch, incidents, console, ledger, mcp
  move/              Surveyor, Cartographer, Shipwright                       (Sprint 8+)
  keel/              Quartermaster, Master-at-Arms, trace ingest              (Sprint 6+)
lab/                 Docker lab (five systemd hosts), drill recorder and recordings
docs/                vision, crew, safety model, roadmap, decisions
```

One MCP server covers all connected hosts today; per-system connectors (Windows, Airflow, Databricks, Fabric) are added as catalog entries and connectors in later sprints.
