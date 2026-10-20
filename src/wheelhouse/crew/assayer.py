"""Assayer's claim check: no plan without verified evidence.

Plain code, no model. A claim passes only if it cites evidence that exists and was
actually collected (not a refusal), and its quote appears, word for word, in the
output of one of the cited evidence items (case and runs of whitespace ignored).
Arguments the agent chose itself (a SQL statement, a ping target) are removed from
the output before matching, because commands echo them: otherwise Diver could write
its own "evidence" with SELECT 'any text'. Only service names (checked against the
inventory) and line counts are kept, and query and ping output cannot verify a claim
at all, since a query can assemble any text from fragments. The diagnosis is verified
only if the root cause passes. Supporting claims that fail are kept, marked as
unverified, and are not shown to Navigator.
"""

from __future__ import annotations

import re

from wheelhouse.crew.diver import claims
from wheelhouse.crew.incidents import Claim, ClaimCheck, Diagnosis, Evidence, Verification

MIN_QUOTE = 6
MAX_QUOTE = 300
MAX_CITED = 5
_SPACE = re.compile(r"\s+")
KEPT_ARGS = frozenset({"service", "lines"})
# Actions whose output can be shaped by the arguments the agent wrote (a query can build
# any sentence from fragments). Their output can inform an investigation but cannot
# verify a claim.
UNQUOTABLE = frozenset({"mysql_query", "ping"})
COLLECTED = frozenset({"ok", "failed"})


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip().casefold()


_WORD = re.compile(r"[\w.\-:/]{4,}")


def _searchable(e: Evidence) -> str:
    """The evidence output with agent-chosen argument values removed: the whole value,
    and every word of it, since a query echoes its literals and aliases as headers."""
    text = _norm(e.output)
    for key, value in e.args.items():
        v = _norm(value)
        if key in KEPT_ARGS or not v:
            continue
        for piece in sorted({v, *_WORD.findall(v)}, key=len, reverse=True):
            text = text.replace(piece, " \u2591 ")
    return text


def claim_problem(claim: Claim, evidence: dict[str, Evidence]) -> str | None:
    if not claim.evidence:
        return "cites no evidence"
    if len(claim.evidence) > MAX_CITED:
        return f"cites more than {MAX_CITED} evidence items"
    missing = [e for e in claim.evidence if e not in evidence]
    if missing:
        return f"cites evidence that does not exist: {', '.join(missing[:3])}"
    quote = _norm(claim.quote)
    if len(quote) < MIN_QUOTE or not any(ch.isalnum() for ch in quote):
        return "quote is too short to check"
    if len(quote) > MAX_QUOTE:
        return "quote is too long"
    cited = [evidence[e] for e in claim.evidence]
    usable = [e for e in cited if e.status in COLLECTED and e.action not in UNQUOTABLE]
    if not usable:
        return (
            "cites no evidence that can verify a claim (refused, not collected, or output "
            "shaped by the agent's own arguments)"
        )
    if not any(quote in _searchable(e) for e in usable):
        return "quote does not appear in the cited evidence"
    return None


def verify(diagnosis: Diagnosis, evidence: list[Evidence]) -> Verification:
    by_id = {e.id: e for e in evidence}
    checks = []
    for role, claim in claims(diagnosis):
        problem = claim_problem(claim, by_id)
        checks.append(ClaimCheck(role=role, text=claim.text, ok=problem is None, problem=problem))
    return Verification(verified=checks[0].ok, checks=checks)


def verified_claims(diagnosis: Diagnosis, verification: Verification) -> list[Claim]:
    ok_roles = {c.role for c in verification.checks if c.ok}
    return [claim for role, claim in claims(diagnosis) if role in ok_roles]
