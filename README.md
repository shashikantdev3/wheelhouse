# Wheelhouse

**A self-hosted crew of AI agents that migrates a data estate, then runs it, and proves every action it took.**

> **Status: Sprint 0 (October 2026).** What exists today is the safety core (Lockkeeper), the action catalog and a command line. The agents, lab and console are being built in the open, sprint by sprint. See the [roadmap](docs/roadmap.md). This README only describes what exists or is clearly marked as planned.

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

## Try the safety core

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run wheelhouse doctor                       # which model keys are configured (never shows values)
uv run wheelhouse catalog                      # the actions agents may request, with their tier
uv run wheelhouse check web01 service_status service=nginx      # verdict: run (Look)
uv run wheelhouse check web01 service_restart service=nginx     # verdict: needs_approval (Touch)
uv run wheelhouse check web01 service_status "service=nginx;reboot"   # verdict: refused
uv run pytest
```

`check` is a dry run: it shows Lockkeeper's verdict and never executes anything.

## Configuration

Copy your keys into a `.env` file in the project folder (it is git-ignored):

```
ANTHROPIC_API_KEY=...
OPENROUTER_API_KEY=...
WHEELHOUSE_APPROVAL_KEY=...   # signs approvals; generate with: python -c "import secrets; print(secrets.token_hex(32))"
# OLLAMA_BASE_URL=http://localhost:11434   optional, for a local model
```

## Project history

This repository started in May 2025 as the *Autonomous IT Support Agent* proof of concept, kept under the tag [`v1-poc`](../../tree/v1-poc). Wheelhouse is a rebuild; why is recorded in [decision 0001](docs/decisions/0001-rebuild-from-v1-poc.md).

## Related projects

- [twosystems](https://github.com/shashikantdev3/twosystems): decision models decide, LLMs think when unsure, humans sign off when both are unsure.
- [ProvenKit](https://github.com/shashikantdev3/provenkit): the AI Decision Record format used for Wheelhouse's ledger.

## Licence

Being finalised; see [decision 0005](docs/decisions/0005-licence.md). Until then, no licence is granted for the rebuilt code beyond viewing it on GitHub.

## Author

Created by **Shashikant**.
