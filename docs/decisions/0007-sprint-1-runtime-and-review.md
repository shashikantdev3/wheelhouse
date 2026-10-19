# 0007. Sprint 1: runtime, ledger, lab, and their review

- Status: Accepted
- Date: 2026-10-19

## Decisions

- **SSH through the system client**, not a Python SSH library: standard behaviour, pinned host keys in a dedicated known_hosts file, user config ignored, no forwarding. The remote command is `timeout -k 5 N` plus the shlex-quoted action, and the login shell must be POSIX.
- **Ledger in the ProvenKit AI Decision Record format 0.1.** Canonical form per its section 5 (nulls and empties dropped, RFC 8785), chained per section 6, validated against the vendored schema in tests. Approver and agent names are pseudonymised with a key derived from the deployment key. Content (arguments, output) is stored as hashes only.
- **Every decision is recorded before anything runs**; executions are recorded after.
- **MCP server** exposes look actions and change requests only. It is never given the approval key.
- **Lab** of five Ubuntu hosts with real systemd, reached over SSH on localhost: nginx, a small orders API with memcached, MariaDB with a read-only socket account, RabbitMQ, and a timer-driven ETL job. Exact-command sudo rules per host; each host mounts only its own keys.
- **Providers** (Anthropic, OpenRouter, Ollama) through plain HTTP with usage and cost on every call. Prices are a dated table; unknown models get cost "unknown", not a guess.
- **Licence:** Business Source License 1.1 (decision 0005).

## Review findings and what changed

An independent review (verdict FAIL with one blocker, then fixed) found:

| Finding | Fix |
|---|---|
| Root ignore file missing in the working copy (keys, approvals and the ledger could be committed) | Root `.gitignore` covers `.env`, approvals, ledgers, caches and local inventories |
| One approval could run twice from two processes | Approval check, decision and record happen under the ledger's file lock, re-reading used nonces |
| The runner re-rendered the request after the check (a changing mapping could swap the service) | The decision carries the exact rendered action; arguments are read once; only plain `str` values |
| Client-side timeout left the remote command running | Remote `timeout -k 5 N`; verified in the lab (exit 124, nothing left running) |
| known_hosts paths with spaces were split by ssh | The value is quoted; quotes, `%` and line breaks are refused |
| Approval key loaded into the MCP server | MCP server gets no approval authority |
| Approval files world-readable and overwritable | Created exclusively, mode 0600; step hash format checked |
| Ledger floats differed from the ProvenKit reference verifier | Latency recorded as an integer; the reference's own canonicalisation is noted for the ProvenKit repo |
| Lab: every host mounted every secret; seed file with a password world-readable; sshd allowed forwarding and TTYs; journal readable for any unit | Per-host mounts; seed file 0600; `DisableForwarding`, `PermitTTY no`, `restrict` key; services limited to the inventory list |
| Unknown-host requests could fill the ledger; lone surrogates crashed a write; `ledger verify` crashed on bad UTF-8; repeated YAML keys were silently resolved | Rate limit checked before recording; text cleaned before hashing; verify reports instead of crashing; repeated keys refused |
| Server-side SQL limit promised but missing | `MAX_STATEMENT_TIME 30` on the lab's read-only account |
| MCP output block could be closed from inside | Random boundary per call |

## Still open

- Ed25519 approvals so the runner cannot sign (Sprint 2).
- An "execution started" record, so a crash mid-run is visible as such.
- Approvals bind the inventory host name, not the machine's identity.
- The lab CI job has not yet run on GitHub's runners.
