# Wheelhouse: vision and positioning

## One line

Wheelhouse is a self-hosted crew of AI agents that migrates a data estate, then runs it, and proves every action it took.

## The problem

Small and mid-size IT service companies and data consultancies sell "managed services" and "modernisation" to their clients. Three things hurt them:

1. **Migration and operations are separate worlds.** Migration tools stop at cutover. Operations tools start blind, with no idea which tables, jobs and reports depend on each other.
2. **Prevented incidents are invisible.** A managed services team that stops a disk from filling at 3 a.m. gets no credit, because nothing broke. Clients see the bill, not the value.
3. **AI is entering production without control.** Agents and LLM apps burn tokens nobody tracks, read untrusted text that can carry prompt injection, and act with no record anyone can audit.

## What exists today (checked October 2026)

| Area | Examples | What they do not do |
|---|---|---|
| AI SRE agents | Cleric, Resolve.ai, Traversal, Azure SRE Agent | Mostly SaaS (logs leave the client network); app and infra focus, not data platforms; no migration |
| MSP L1 agents | ConnectWise zofiQ, NeoAgent, Mizo, Thread, Rewst | Endpoint and service desk tickets (password resets), not pipelines or warehouses |
| Migration | Databricks Lakebridge (free), Datafold, Bitwise Fulkrum | Stop at cutover; no day-2 operations |
| AI observability and governance | HoneyHive, Langfuse, Datadog LLM Observability | Separate product, separate bill, separate data store |

## What makes Wheelhouse different

1. **Migrate, then run, with one map.** The lineage map built during migration is the same map operations use. When a pipeline fails, the crew already knows what is downstream.
2. **Data platform operations, not laptops.** Pipeline failures, schema drift, late data, stuck jobs, disk and queue pressure on the hosts that run them.
3. **Self-hosted, any model.** Runs inside the client network. Works with Anthropic, OpenRouter, Azure AI Foundry or a local model through Ollama. Nothing leaves unless the client allows it.
4. **Proof, not promises.** Every diagnosis cites evidence. Every action is recorded in a tamper-evident ledger (ProvenKit format). A monthly proof pack shows the client what was watched, predicted, prevented and approved, by whom. "Prevented" is measured against a silent holdout, not claimed.
5. **AI control built in, not bolted on.** Observability, evaluations, token FinOps, guardrails and AI security are a module of the same product (Keel), first for Wheelhouse's own agents, then for any AI app the client runs.

## Three modules

| Module | Purpose | Crew |
|---|---|---|
| **Watch** | Managed services agent: reactive L1 watch plus proactive forecasting | Lookout, Barometer, Diver, Navigator, Helmsman, Bosun |
| **Move** | Migration factory: legacy ETL and warehouse to a governed lakehouse | Surveyor, Cartographer, Shipwright |
| **Keel** | AI observability, evaluations, token FinOps, guardrails, AI security | Quartermaster, Master-at-Arms |
| Shared | Safety, verification, records | Lockkeeper, Assayer, Purser |

See [crew.md](crew.md) for each agent's job and limits.

## Non-negotiable rules

- Read-only, allowlisted actions run without approval. Every change step runs only after a named human approves that exact step.
- No agent can delete, purge, drop, truncate or format anything. This is enforced in code, and no approval can unlock it.
- Text from logs, tickets, web pages and documents is data, never instructions.
- Claims in this README and in reports come from measured numbers only.

## Who it is for

- **First users:** an FDE or solutions engineer deploying it into a client's environment in a day.
- **First buyers:** small IT service companies and data consultancies (10 to 300 people) running managed data services.
- **Later:** integration with larger platforms (ITSM, RMM, cloud marketplaces).

## How it makes money (planned)

- Free: the self-hosted single-environment edition, source-available.
- Paid: the multi-client console, proof packs, SSO and support, priced per managed client environment per month.
- Early: paid pilots and setup work with 3 design partners.

## Related projects by the same author

- [twosystems](https://github.com/shashikantdev3/twosystems): System 1 decision model decides, System 2 LLM thinks when unsure, a human signs off when both are unsure. Wheelhouse uses this ladder for triage and approvals.
- [ProvenKit](https://github.com/shashikantdev3/provenkit): AI Decision Record format. Wheelhouse writes its ledger in this format.
- Attention Span: an AI news digest whose fact-checker pattern became Assayer's claim check.
