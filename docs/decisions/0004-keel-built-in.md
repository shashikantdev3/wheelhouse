# 0004. AI observability, FinOps, guardrails and security built in

- Status: Accepted
- Date: 2026-10-19

## Context

Comparable offerings partner with separate vendors for AI observability, evaluation and governance. That means more contracts, more data stores and more integration work for a small client.

## Decision

Keel is a module of Wheelhouse. It first watches Wheelhouse's own agents (traces, tokens, cost, evaluations, guardrail decisions), then accepts OpenTelemetry GenAI traces from any client AI app. Quartermaster owns cost and budgets; Master-at-Arms owns AI security; Assayer owns evaluations; Lockkeeper owns guardrails on actions.

## Consequences

Keel is scoped to what a managed services team needs, not a full replacement for dedicated AI observability platforms. The OpenTelemetry GenAI conventions are not stable yet, so attribute mapping lives in one adapter.
