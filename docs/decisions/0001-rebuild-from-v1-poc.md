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

GitGuardian flagged hard-coded tutorial default passwords in the old Vagrant scripts, and then sample keys inside a Python virtualenv that the first 2025 commit had included by mistake (`env/`, 32,482 files of installed libraries). None were real credentials. Because the repository was a few hours old under this name, with no other clones, the history was rewritten once with `git filter-repo`: the Vagrant scripts, the virtualenv, bytecode caches and the old lab passwords were removed from every commit, and `main` and the `v1-poc` tag were force-pushed with new commit IDs. The repository went from 179 MB to about 4 MB.

From Sprint 2, secrets are stopped before they are committed instead: a gitleaks pre-commit hook, a gitleaks scan of the full history in CI, GitHub push protection, and a check that refuses committed virtualenvs. History is not rewritten again without a real reason. The lab's own passwords are generated per machine by `lab/setup_lab.py` and never committed.
