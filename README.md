# Wheelhouse

**A self-hosted crew of AI agents that migrates a data estate, then runs it, and proves every action it took.**

> **Status: Sprint 2 of 11 (October 2026).** What exists today: the reactive crew (Lookout, Diver, Assayer, Navigator, Helmsman) working one incident end to end in a five-host lab with real systemd; the safety gate (Lockkeeper); Ed25519 approvals from a local approval console; a tamper-evident ledger in the ProvenKit format; model providers; an MCP server; recorded drills. Next: a scored set of 20 to 30 drills. See the [roadmap](docs/roadmap.md). This README only describes what exists or is clearly marked as planned.

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

### One incident, end to end (lab)

With the [lab](lab/README.md) running, in two terminals:

```bash
I="--inventory lab/wheelhouse.lab.yaml"
docker exec lab-web01-1 systemctl stop nginx                     # break something
uv run wheelhouse $I watch                                       # terminal 1: the crew
uv run wheelhouse $I console --as lab-operator --key lab/.secrets/approvers/lab-operator.key  # terminal 2
```

1. **Lookout** sees nginx is inactive on web01 and opens an incident.
2. **Diver** investigates with read-only actions only (status, logs) and writes a diagnosis in which every claim quotes the evidence.
3. **Assayer** checks every quote word for word against what the hosts returned. No verified root cause, no plan.
4. **Navigator** proposes the fix as catalog steps (`sudo -n systemctl start nginx`), each with a check (`service_status` must show `active (running)`) and a rollback note.
5. You open the console link, read the evidence and the exact command, and approve. The console signs with your Ed25519 key; it never runs anything.
6. **Helmsman** (in the watch loop, which holds no key) runs the step, checks it, and closes the incident. Every decision and execution is in the ledger: `uv run wheelhouse $I ledger verify`.

No lab? Replay a recorded drill to the real crew with your configured model:

```bash
uv run python lab/drill.py run nginx-stopped     # about $0.002 with Claude Haiku
```

### Single actions (lab)

```bash
uv run wheelhouse $I hosts                                         # reachable, POSIX shell checked
uv run wheelhouse $I run db01 mysql_query database=app "sql=SELECT status, COUNT(*) FROM orders GROUP BY status"
uv run wheelhouse $I request web01 service_restart service=nginx  # recorded, prints the step hash
uv run wheelhouse $I approve <step hash> --by lab-operator --key lab/.secrets/approvers/lab-operator.key
uv run wheelhouse $I run web01 service_restart service=nginx --approval approvals/<file>.json
uv run wheelhouse $I mcp                                           # MCP server for Claude Code or Copilot (look only)
```

Every decision (allowed, held for approval or refused) and every execution is recorded in the ledger. Approver names never enter it; they are pseudonymised.

## Configuration

Copy your keys into a `.env` file in the folder you run Wheelhouse from (the repository's `.gitignore` excludes it):

```
ANTHROPIC_API_KEY=...
OPENROUTER_API_KEY=...
# WHEELHOUSE_MODEL=claude-haiku-5-5        the crew's model (default); an OpenRouter or Ollama model id also works
# WHEELHOUSE_LEDGER_KEY=...                optional, 32+ characters: pseudonymises names in the ledger
# OLLAMA_BASE_URL=http://localhost:11434   optional, for a local model
```

Each approver creates their own key pair; the private key never leaves their machine:

```bash
uv run wheelhouse keys new dev        # writes ~/.wheelhouse/approvers/dev.key, prints the public key
```

An inventory file (`wheelhouse.yaml`, or `--inventory PATH`) lists the hosts, their SSH details, the services Wheelhouse may name, and the approvers' public keys:

```yaml
known_hosts: known_hosts
approvers:
  dev: ed25519:...            # from 'wheelhouse keys new dev'
hosts:
  web01: {address: 10.0.0.11, user: wheelhouse, identity_file: keys/wheelhouse, services: [nginx]}
```

The lab's generated `lab/wheelhouse.lab.yaml` is a complete example.

## Contributing

Install the pre-commit hooks once (`uv tool install pre-commit`, then `pre-commit install`). They run gitleaks and refuse committed virtualenvs; CI runs the same scan over the full history. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Project history

This repository started in May 2025 as the *Autonomous IT Support Agent* proof of concept, kept under the tag [`v1-poc`](../../tree/v1-poc). Wheelhouse is a rebuild; why is recorded in [decision 0001](docs/decisions/0001-rebuild-from-v1-poc.md).

## Related projects

- [twosystems](https://github.com/shashikantdev3/twosystems): decision models decide, LLMs think when unsure, humans sign off when both are unsure.
- [ProvenKit](https://github.com/shashikantdev3/provenkit): the AI Decision Record format used for Wheelhouse's ledger.

## Licence

Source-available under the [Business Source License 1.1](LICENSE): free for learning, evaluation and non-commercial use; companies running it in production need a commercial licence; each version becomes Apache-2.0 four years after release. Plain-English summary: [LICENSING.md](LICENSING.md).

## Author

Created by **Shashikant**.
