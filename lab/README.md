# Lab

Five Ubuntu hosts running real systemd, reachable over SSH on your own machine. The crew meets the same `systemctl`, `journalctl`, MariaDB and RabbitMQ it will meet on client servers. Faults are injected on purpose ("drills") so every diagnosis can be checked against a known root cause; Sprint 3 turns them into a scored set.

| Host | Port (127.0.0.1) | Runs |
|---|---|---|
| web01 | 2211 (web on 8081) | nginx, proxying to the orders API |
| app01 | 2212 | orders API (small Python service), memcached |
| db01 | 2213 | MariaDB with the `app` database |
| mq01 | 2214 | RabbitMQ |
| etl01 | 2215 | a systemd timer that summarises orders every minute |

## Start it

Needs Docker (Docker Desktop on Windows or macOS), OpenSSH and uv. From the repository root:

```bash
python lab/setup_lab.py                                  # keys, pinned host keys, sudo rules, inventory
docker compose -f lab/docker-compose.yml --profile build build base
docker compose -f lab/docker-compose.yml up -d --build
uv run wheelhouse --inventory lab/wheelhouse.lab.yaml hosts
```

Then try:

```bash
uv run wheelhouse --inventory lab/wheelhouse.lab.yaml run db01 mysql_query database=app "sql=SELECT status, COUNT(*) FROM orders GROUP BY status"
uv run wheelhouse --inventory lab/wheelhouse.lab.yaml request web01 service_restart service=nginx
uv run wheelhouse --inventory lab/wheelhouse.lab.yaml approve <step hash> --by lab-operator --key lab/.secrets/approvers/lab-operator.key
uv run wheelhouse --inventory lab/wheelhouse.lab.yaml run web01 service_restart service=nginx --approval approvals/<file>.json
uv run wheelhouse --inventory lab/wheelhouse.lab.yaml ledger verify
WHEELHOUSE_LAB=1 uv run pytest tests/lab -v
```

Stop it with `docker compose -f lab/docker-compose.yml down`.

`setup_lab.py` also creates an approver, `lab-operator`, whose private key is `lab/.secrets/approvers/lab-operator.key` and whose public key is in the generated inventory.

## Drills

A drill injects a fault, records what every read-only action returns, and puts the fault right again:

```bash
uv run python lab/drill.py record nginx-stopped       # needs the lab
uv run python lab/drill.py run nginx-stopped          # no lab needed: replays to the real crew
```

`run` uses your configured model (`.env`), approves with a throwaway drill key and prints the evidence, the claim check, the plan, the result and the cost. Recordings are committed in `lab/drills/` (lab output only). Available: `nginx-stopped`, `memcached-stopped`. If you record your own, start from fresh containers (`docker compose -f lab/docker-compose.yml up -d --force-recreate`): old stops in the journal change what the crew concludes.

## What the lab shows about real deployments

- A dedicated `wheelhouse` account with a `restrict`-ed key, sshd with forwarding and TTYs off, and host keys pinned in advance.
- Exact-command sudo rules per host (no wildcards). Wheelhouse's own gate is a client-side control; these rules are the host's own boundary.
- A read-only MariaDB account reached through the local socket (no password), limited to the `app` schema, with a 30-second statement limit.
- Each host can only read its own keys.

## Lab only

The containers run privileged so systemd can work. Keys and the ETL job's database password are generated on your machine by `setup_lab.py` into `lab/.secrets/` (git-ignored); the repository holds no passwords. Never reuse any of them outside the lab.

The original five-VM Vagrant lab from v1 was removed from the main branch because its scripts contained the public tutorial's default passwords. It is still available in the `v1-poc` tag.
