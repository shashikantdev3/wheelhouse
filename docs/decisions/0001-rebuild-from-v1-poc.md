# 0001. Rebuild from the v1 proof of concept

- Status: Accepted
- Date: 2026-10-19

## Context

The first version (May 2025, tag `v1-poc`) was a Flask app with a regex classifier, model-written shell commands run with `shell=True` on the local machine, a disabled safety check, and no tests. It proved the idea and the lab, not the engineering.

## Decision

Rebuild from scratch under the name Wheelhouse. Keep the history and the tag `v1-poc` so the starting point stays visible. Keep the Vagrant lab scripts under `lab/vagrant/` as an optional lab; the main lab moves to Docker Compose so it runs in CI.

## Consequences

Nothing from the old code is reused directly. The old README claims (RBAC, Celery, FastAPI) are dropped; the new README states only what exists.
