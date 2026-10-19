# 0006. Safety review of Sprint 0

- Status: Accepted
- Date: 2026-10-19

## Context

An independent reviewer tried to break the first version of the safety core. It found that the guard was a deny list with gaps (unlisted wrappers such as `pkexec`, unlisted destructive programs, unlisted subcommands, mysql option prefixes and bundled short options), that systemd targets such as `reboot.target` could be started as a Touch action, that SQL function checks were a deny list (user-defined and waiting functions passed), that the mysql client's backslash commands were not considered, that approvals could be constructed by any code and reused within their lifetime, and that the docs described ledger, rate limits and scanning in the present tense.

## Decision

- The guard became a second allowlist: known programs, options and subcommands only; protected systemd units can never be started, stopped or restarted; only `sudo -n -u USER`, `timeout N` and `nice -n N` are unwrapped.
- Service parameters accept plain services only. Database names no longer accept `$`.
- SQL: allowlists for functions and `SHOW` kinds; schema-qualified function calls refused; backslashes refused for MySQL.
- Approvals are signed with HMAC-SHA256, carry a nonce and are single use. Naive timestamps are refused instead of crashing.
- `RenderedAction.remote_command()` quotes with `shlex.join`; a test round-trips every catalog action.
- The safety model marks each statement as built or planned, by sprint.

## Second review

A fresh reviewer re-tested the changes (verdict: pass, no blockers). Fixed in the same commit: the guard now reports whether a command changes state, and Lockkeeper refuses a state-changing command that the catalog labels Look; malformed requests and approvals are refused cleanly instead of raising; the guard and the gate turn any unexpected error into a refusal; a guard index error on repeated statement flags; more protected units (user and getty sessions, firewalls, time sync); nested sudo is refused.

## Still open (before anything executes on a real host)

- The SSH transport must use `remote_command()` only, and is reviewed again when built (Sprint 1).
- Used nonces move from memory to the ledger (Sprint 1).
- Enforced timeouts, rate limits and server-side SQL time limits (Sprint 1).
- Whether the mysql client acts on backslash commands inside comments is to be tested in the lab; the check refuses all backslashes either way.
- Pin the users `sudo` may switch to, per deployment.
- Run SQL clients with `--no-defaults` (mysql) and `-X` (psql), or a fixed defaults file, so planted client config files cannot change behaviour.
- `remote_command()` assumes a POSIX shell (sh, bash) on the remote account; check this in the transport.
- Read-only database accounts must not be able to read credential tables (for example `mysql.user`); the SQL check limits statement shape, not which tables are readable.
