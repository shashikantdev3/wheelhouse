# 0002. Typed actions and a code gate, never model-written shell

- Status: Accepted
- Date: 2026-10-19

## Context

An ops agent reads untrusted text (logs, tickets) and acts on production systems. A model can be wrong or manipulated. Prompt rules alone cannot guarantee that nothing destructive runs.

## Decision

Agents request typed actions from a catalog. Arguments are validated against strict patterns and rendered to an argument list with no shell. Lockkeeper assigns a tier (Look, Touch, Never) and re-checks the rendered list with a destructive-command guard; SQL is parsed and only single read-only statements pass. Touch requires an approval bound to a hash of the exact step. Never cannot be approved.

## Consequences

New capabilities need a catalog entry and tests, which is slower than letting a model write commands. That is the point. The catalog becomes the main thing a client reviews before deployment.
