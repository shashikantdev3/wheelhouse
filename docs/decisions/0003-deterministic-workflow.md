# 0003. Deterministic workflow with LLM steps

- Status: Accepted
- Date: 2026-10-19

## Context

Free agent loops are hard to replay, audit and evaluate. Clients and auditors need to know why each step happened.

## Decision

Incidents and migrations move through fixed, persisted states. Models produce content inside a state (a triage label, an investigation summary, a plan). Code decides transitions. Every model call records inputs (hashed where sensitive), model and version, tokens and cost.

## Consequences

Less "magic", more predictability. Runs can be replayed against recorded inputs, which makes the drill scorecard and regression tests possible.
