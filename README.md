# Wheelhouse

**A self-hosted crew of AI agents that migrates a data estate, then runs it, and proves every action it took.**

> **Status: Sprint 1 of 11 (October 2026).** What exists today: the safety gate (Lockkeeper), a tamper-evident ledger in the ProvenKit format, an SSH runner with human approvals, model providers, an MCP server, and a five-host lab with real systemd. The agents and the console come next. See the [roadmap](docs/roadmap.md). This README only describes what exists or is clearly marked as planned.

## Why

IT service companies and data consultancies run "managed services" for their clients. Migration tools stop at cutover, operations tools start blind, prevented incidents earn no credit, and AI is entering production with no cost control or audit trail. Wheelhouse puts one crew on all of it, inside the client's own network. The full case, including what already exists in the market, is in [docs/vision.md](docs/vision.md).

## Three modules (planned)

| Module | What it does | Crew |
|---|---|---|
| **Watch** | Managed services agent: L1 watch, investigation, remediation plans, and forecasts that warn before things break | Lookout, Barometer, Diver, Navigator, Helmsman, Bosun |
| **Move** | Migration factory: legacy ETL and warehouse to a governed lakehouse, with lineage and parity proof | Surveyor, Cartographer, Shipwright |
| **Keel** | AI control built in: observability, evaluations, token FinOps, guardrails and AI security | Quartermaster, Master-at-Arms |
| Shared | Safety gate, verification, tamper-evident records | Lockkeeper, Assayer, Purser |

Every agent's job and limits: [docs/crew.md](docs/crew.md).

## The rules

- Read-only, allowlisted actions run on their own. Every change runs only after a named human approves that exact step.
- No agent can delete, purge, drop, truncate or format anything. This is enforced in code by two independent allowlists (the catalog and the guard); no approval can unlock it.
- Agents never write shell commands. They request typed actions; Lockkeeper decides.
- Text from logs, tickets and documents is data, never instructions.

How this is enforced, and its honest limits: [docs/safety-model.md](docs/safety-model.md).

## What works today

Requires [uv](https://docs.astral.sh/uv/). For the lab: Docker and OpenSSH.

```bash
uv sync --all-extras
uv run wheelhouse doctor --live          # which keys are configured (never shows values), one tiny live call
uv run wheelhouse catalog                # the actions agents may request, with their tier
uv run wheelhouse check web01 service_restart service=nginx       # dry run: needs_approval
uv run wheelhouse check web01 service_status "service=nginx;reboot" # dry run: refused
```

With the [lab](lab/README.md) running:

```bash
I="--inventory lab/wheelhouse.lab.yaml"
uv run wheelhouse $I hosts                                         # reachable, POSIX shell checked
uv run wheelhouse $I run db01 mysql_query database=app "sql=SELECT status, COUNT(*) FROM orders GROUP BY status"
uv run wheelhouse $I request web01 service_restart service=nginx  # recorded, prints the step hash
uv run wheelhouse approve <step hash> --by <your name>             # signed, single use, 30 minutes
uv run wheelhouse $I run web01 service_restart service=nginx --approval approvals/<file>.json
uv run wheelhouse $I ledger verify                                 # every decision and execution, hash-chained
uv run wheelhouse $I mcp                                           # MCP server for Claude Code or Copilot (look only)
```

Every decision (allowed, held for approval or refused) and every execution is recorded in the ledger. Approver names never enter it; they are pseudonymised.

## Configuration

Copy your keys into a `.env` file in the folder you run Wheelhouse from (the repository's `.gitignore` excludes it):

```
ANTHROPIC_API_KEY=...
OPENROUTER_API_KEY=...
WHEELHOUSE_APPROVAL_KEY=...   # signs approvals; generate with: python -c "import secrets; print(secrets.token_hex(32))"
# OLLAMA_BASE_URL=http://localhost:11434   optional, for a local model
```

Keep the approval key away from any agent process: whoever can read it can sign approvals. Moving to public-key approvals is planned for Sprint 2 ([safety model](docs/safety-model.md)).

An inventory file (`wheelhouse.yaml`, or `--inventory PATH`) lists the hosts, their SSH details and the services Wheelhouse may name. See the lab's generated `lab/wheelhouse.lab.yaml` for the format.

## Project history

This repository started in May 2025 as the *Autonomous IT Support Agent* proof of concept, kept under the tag [`v1-poc`](../../tree/v1-poc). Wheelhouse is a rebuild; why is recorded in [decision 0001](docs/decisions/0001-rebuild-from-v1-poc.md).

## Related projects

- [twosystems](https://github.com/shashikantdev3/twosystems): decision models decide, LLMs think when unsure, humans sign off when both are unsure.
- [ProvenKit](https://github.com/shashikantdev3/provenkit): the AI Decision Record format used for Wheelhouse's ledger.

## Licence

Source-available under the [Business Source License 1.1](LICENSE): free for learning, evaluation and non-commercial use; companies running it in production need a commercial licence; each version becomes Apache-2.0 four years after release. Plain-English summary: [LICENSING.md](LICENSING.md).

## Author

Created by **Shashikant**.
