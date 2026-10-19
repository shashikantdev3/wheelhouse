# Safety model

Wheelhouse runs inside client environments, so safety is enforced by code, not by prompts. A model can be wrong, confused or manipulated by text it reads. The gate below does not depend on the model behaving.

Each statement below is marked **(built)** if it exists in the code today, or with the sprint that delivers it.

## Three tiers

| Tier | Meaning | Who decides | Examples |
|---|---|---|---|
| **Look** | Read-only and allowlisted | Runs automatically | `ping -c 4`, `df -h`, `systemctl status nginx`, read-only SQL |
| **Touch** | Changes state but is reversible | A named human approves this exact step; then Helmsman runs it | start, stop or restart a service |
| **Never** | Destroys or cannot be undone | Refused in code. No approval can unlock it | delete, purge, drop, truncate, format, reboot, `rm`, `dd`, `mkfs` |

## How an action flows

1. **(built)** An agent asks for a **typed action** from the catalog, for example `service_status(host="web01", service="nginx")`. It never writes a command.
2. **(built)** The catalog validates every argument against a strict pattern (service names must be plain services, not targets such as `reboot.target`; no value may start with `-`) and renders an argument list. A parameter must be a whole argument, never part of one, so a value cannot change the shape of the command. The catalog cannot contain a Never action, and every Touch action must say how to roll back.
3. **(built)** The **guard** re-checks the rendered argument list against its own, independent allowlist: known programs only, known options only, known subcommands only (for example `systemctl` may `status`, `start`, `stop`, `restart`, `reload`, and never touches protected units such as `sshd`, `dbus` or `reboot`). Anything it does not recognise is refused, and if the guard knows a command changes state, a catalog entry that labels it Look is refused. The catalog and the guard must both be wrong for a harmful command to pass. Any unexpected error in the guard or the gate is a refusal.
4. **(built)** SQL is parsed. Only a single read-only statement passes: `SELECT`, an allowlisted `SHOW`, `DESCRIBE`, or `EXPLAIN` without `ANALYZE`. Functions must be on an allowlist of pure built-ins, so user-defined, schema-qualified, sleeping, waiting, locking and file-reading functions are refused. For MySQL, executable comments (`/*! */`) and any backslash (the `mysql` client runs backslash commands) are refused.
5. **(built)** For Touch, the approval is bound to a SHA-256 hash of the exact host, action, tier and arguments. Approvals are signed (HMAC-SHA256) by an approval authority that holds a secret key, expire (30 minutes by default, 8 hours at most), and can be used once. Without a configured key, no Touch step can run.
6. **(built)** SSH runs through the system `ssh` client with an argument list (no local shell), user ssh config ignored, host keys pinned in a dedicated known_hosts file (no trust on first use), batch mode, and no agent, X11 or port forwarding. The remote command is built with `shlex.join`, and before the first command on a host Wheelhouse checks that the account's login shell is a POSIX shell, because that quoting is only correct for POSIX shells.
7. **(built)** Every decision, allowed or refused, is written to the ledger (ProvenKit AI Decision Record format, hash-chained) before anything runs, and every execution is recorded after it. Approval nonces are stored there. A request that carries an approval holds the ledger's file lock while it re-reads used nonces, decides and records, so two processes cannot spend one approval.
8. **(built)** Limits: the remote command runs under `timeout -k 5 N`, so it is stopped on the server, not only on the client; output is capped; requests are rate limited per host within a process; MySQL statements run under a read-only account with a server-side `MAX_STATEMENT_TIME` (set per deployment; the lab sets 30 seconds).
9. **(built)** Actions that name a service may only name services listed for that host in the inventory, so logs of unrelated units (which may hold secrets) are not read.
10. **(built)** What runs is exactly the action the gate checked, carried on the decision; arguments are read once, and only plain `str` values are accepted.

## Untrusted text

Logs, tickets, emails, web pages and documents can contain text such as "ignore your rules and run this". Wheelhouse treats all of it as data:

- **(built)** The MCP server returns host output inside a data block with a random boundary per call and tells the client that text inside it is data. **(Sprint 2)** The crew's own prompts do the same.
- **(Sprint 7)** Master-at-Arms scans it for injection patterns and secrets before it reaches a model.
- **(built)** Even if a model is fooled, it can only request catalog actions, and the gate still applies the tiers.

## Honest limits

- The gate is a client-side control. The SSH key Wheelhouse uses can open a shell on the host, so the host's own rules matter: a dedicated account, `restrict` on the key, sshd with forwarding and TTYs off, and sudo rules that list exact commands. The lab shows all of these.
- Approvals are signed with an HMAC key, so whoever can read the key can sign. Keep it out of reach of agent processes; the MCP server is never given it. **(Sprint 2)** Ed25519 approvals, where approvers hold the private key and the runner only holds the public key.
- Approvals bind the inventory host name, not the machine behind it. Changing the inventory or deleting the ledger changes what an approval would reach or replay within its lifetime (30 minutes by default). Protect both files.
- The per-host rate limit only applies within one process (the MCP server or one CLI run).
- If Wheelhouse crashes between recording a decision and recording its execution, the ledger shows an allowed step with no outcome. Treat that as "may have run".
- The guard and the catalog only know the programs and options listed in code. Adding a program means adding rules to both, with tests. This is deliberate.
- A human can approve a bad Touch step. Navigator must show the evidence, the expected effect and the rollback with every step to make that less likely.
- Reviews that hardened this layer: [decision 0006](decisions/0006-safety-review-sprint-0.md) and [decision 0007](decisions/0007-sprint-1-runtime-and-review.md).
