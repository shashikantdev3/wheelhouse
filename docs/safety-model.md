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
6. **(built)** For SSH, the command string is built with `shlex.join`, so a remote shell receives every argument quoted. Tests check that every catalog action survives this round trip. **(Sprint 1)** The SSH transport itself.
7. **(Sprint 1)** Every decision, allowed or refused, is written to the ledger. Used approval nonces are stored there too; until then they are kept in memory and reset on restart.
8. **(Sprint 1)** Look actions get enforced limits: the catalog timeout applied by the transport, a per-host rate limit, and for SQL a server-side execution time limit (MySQL `MAX_EXECUTION_TIME`) under a read-only database account.

## Untrusted text

Logs, tickets, emails, web pages and documents can contain text such as "ignore your rules and run this". Wheelhouse treats all of it as data:

- **(Sprint 2)** It is passed to models inside clearly marked data blocks, never as instructions.
- **(Sprint 7)** Master-at-Arms scans it for injection patterns and secrets before it reaches a model.
- **(built)** Even if a model is fooled, it can only request catalog actions, and the gate still applies the tiers.

## Honest limits

- The guard and the catalog only know the programs and options listed in code. Adding a program means adding rules to both, with tests. This is deliberate.
- A Look query can still be slow (a large join). Until the Sprint 1 limits exist, the catalog timeout is metadata only.
- A human can approve a bad Touch step. Navigator must show the evidence, the expected effect and the rollback with every step to make that less likely.
- Approvals are only as safe as the approval key and the host Wheelhouse runs on. Use read-only accounts for Look and a separate, narrow account for Touch.
- The review that hardened this layer is summarised in [decision 0006](decisions/0006-safety-review-sprint-0.md).
