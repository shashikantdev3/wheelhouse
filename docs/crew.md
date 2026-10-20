# The crew

Each agent has one job, a fixed set of tools and a hard limit. An agent never runs a shell string it wrote itself. It picks a typed action from the catalog, and Lockkeeper decides whether that action may run.

## Watch (managed services)

| Agent | Job | Uses an LLM? | Can change anything? |
|---|---|---|---|
| **Lookout** (built) | Sweeps hosts with read-only probes; opens, deduplicates and closes incidents. Today: stopped services, failed timer jobs, full disks, unreachable hosts | Rules today; a decision model for triage in Sprint 3 | No |
| **Barometer** | Forecasts trouble before it happens: disk fill time, CPU and memory pressure, queue growth, late data, token budget overrun | No. Statistics (trend and seasonal baselines). The LLM only explains the forecast | No |
| **Diver** (built) | Investigates an incident with read-only actions and writes a diagnosis that quotes its evidence | Yes | No |
| **Navigator** (built) | Writes the remediation plan: typed steps, each with a check and a rollback, validated by code | Yes | No |
| **Helmsman** (built) | Runs approved steps only, one at a time, checks each result, stops at the first problem | No | Only approved Touch actions |
| **Bosun** | Sends warnings and reports: email, chat, incident reports, the shift handover | Yes, for wording | No |

## Move (migration)

| Agent | Job | Uses an LLM? | Can change anything? |
|---|---|---|---|
| **Surveyor** | Inventories the legacy estate: jobs, procedures, scripts, schedules, sizes; scores complexity | Little | No |
| **Cartographer** | Builds column-level lineage from parsed SQL | No (parser first) | No |
| **Shipwright** | Converts legacy code to the target platform. Deterministic transpiling first, the LLM only for what the parser cannot do | Yes, for the remainder | Writes only to a staging target, never the source |

## Keel (AI control)

| Agent | Job | Uses an LLM? | Can change anything? |
|---|---|---|---|
| **Quartermaster** | Token and cost accounting per agent, incident, client and model; budgets; optimisation advice (cheaper model routing, caching, context hygiene) with a measured saving | No | No |
| **Master-at-Arms** | AI security: flags prompt injection hidden in logs and tickets, secret leaks in prompts and outputs, tool misuse; runs red-team drills | Classifier plus rules | No |

## Shared

| Agent | Job | Uses an LLM? | Can change anything? |
|---|---|---|---|
| **Lockkeeper** (built) | The gate. Classifies every action as Look, Touch or Never; asks a human for Touch; refuses Never. Its core is plain code with no LLM | Decision model only for "is this worth asking a human" | No |
| **Assayer** (claim check built) | Verifies claims (every sentence of a diagnosis must cite evidence) and data parity (old vs new after migration); runs evaluations | Partly | No |
| **Purser** (ledger built) | Keeps the tamper-evident ledger (ProvenKit format) and the honest receipt; builds the monthly proof pack | No | No |
