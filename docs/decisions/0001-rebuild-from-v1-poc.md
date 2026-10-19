# 0001. Rebuild from the v1 proof of concept

- Status: Accepted
- Date: 2026-10-19

## Context

The first version (May 2025, tag `v1-poc`) was a Flask app with a regex classifier, model-written shell commands run with `shell=True` on the local machine, a disabled safety check, and no tests. It proved the idea and the lab, not the engineering.

## Decision

Rebuild from scratch under the name Wheelhouse. Keep the history and the tag `v1-poc` so the starting point stays visible. Keep the Vagrant lab scripts under `lab/vagrant/` as an optional lab; the main lab moves to Docker Compose so it runs in CI.

## Consequences

Nothing from the old code is reused directly. The old README claims (RBAC, Celery, FastAPI) are dropped; the new README states only what exists.

## Update (19 Oct 2026)

The Vagrant scripts were removed from the main branch after GitGuardian flagged the hard-coded tutorial default passwords in them (`REMOVED`, `test`). They were never real credentials, but the repository should hold none. The scripts remain in the `v1-poc` tag. The lab's own ETL password is now generated per machine by `lab/setup_lab.py`. The commit history is not rewritten: the values were public tutorial defaults, already in the 2025 history, and rewriting would break the tag and existing clones.
