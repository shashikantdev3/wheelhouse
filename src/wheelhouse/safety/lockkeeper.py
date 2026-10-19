"""Lockkeeper: the gate every action passes through.

Plain code, no model. It renders the request through the catalog, re-checks the result
with the guard (a second allowlist), and returns RUN, NEEDS_APPROVAL or REFUSED. It
never runs anything itself.

Single use: when a Touch step is cleared to run, its approval's nonce is recorded and
cannot clear another run. In Sprint 0 this record lives in memory; Sprint 1 moves it
into the ledger so it survives restarts.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from wheelhouse.safety.approvals import Approval, ApprovalAuthority, step_hash
from wheelhouse.safety.catalog import Catalog, CatalogError, RenderedAction, default_catalog
from wheelhouse.safety.guard import changes_state, destructive_reason
from wheelhouse.safety.tiers import Tier, Verdict

_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]{0,252}")


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    tier: Tier
    reason: str
    host: str
    action: str
    argv: tuple[str, ...] = ()
    step_hash: str | None = None

    @property
    def may_run(self) -> bool:
        return self.verdict is Verdict.RUN


class Lockkeeper:
    def __init__(
        self, catalog: Catalog | None = None, authority: ApprovalAuthority | None = None
    ) -> None:
        self.catalog = catalog if catalog is not None else default_catalog()
        self.authority = authority
        self._used_nonces: set[str] = set()

    def decide(
        self,
        host: str,
        action: str,
        args: Mapping[str, object] | None = None,
        approval: Approval | None = None,
        now: datetime | None = None,
    ) -> Decision:
        """Decide whether an action may run now. A RUN verdict for a Touch step uses up
        its approval, so call this once, right before execution."""
        now = now or datetime.now(UTC)

        if not isinstance(action, str):
            return Decision(Verdict.REFUSED, Tier.NEVER, "action must be a name", str(host), "?")
        if args is not None and not isinstance(args, Mapping):
            return Decision(
                Verdict.REFUSED, Tier.NEVER, "arguments must be a mapping", str(host), action
            )
        if approval is not None and not isinstance(approval, Approval):
            return Decision(
                Verdict.REFUSED, Tier.NEVER, "approval has the wrong type", str(host), action
            )
        if not isinstance(host, str) or not _HOST.fullmatch(host):
            return Decision(Verdict.REFUSED, Tier.NEVER, "invalid host name", str(host), action)

        try:
            rendered = self.catalog.render(action, args or {})
        except CatalogError as err:
            return Decision(Verdict.REFUSED, Tier.NEVER, f"not in the catalog: {err}", host, action)

        try:
            return self._gate(host, rendered, approval, now)
        except Exception as err:  # noqa: BLE001 - the gate must fail closed
            return Decision(
                Verdict.REFUSED,
                Tier.NEVER,
                f"gate error ({type(err).__name__}); refused",
                host,
                action,
            )

    def _gate(
        self, host: str, rendered: RenderedAction, approval: Approval | None, now: datetime
    ) -> Decision:
        danger = destructive_reason(rendered.argv)
        if danger:
            return Decision(
                Verdict.REFUSED, Tier.NEVER, f"guard: {danger}", host, rendered.name, rendered.argv
            )

        digest = step_hash(host, rendered)

        if rendered.tier is Tier.LOOK and changes_state(rendered.argv):
            return Decision(
                Verdict.REFUSED,
                Tier.NEVER,
                "catalog labels a state-changing command as Look; fix the catalog",
                host,
                rendered.name,
                rendered.argv,
            )

        if rendered.tier is Tier.LOOK:
            return Decision(
                Verdict.RUN,
                Tier.LOOK,
                "read-only action",
                host,
                rendered.name,
                rendered.argv,
                digest,
            )

        if rendered.tier is Tier.TOUCH:

            def ask(reason: str) -> Decision:
                return Decision(
                    Verdict.NEEDS_APPROVAL,
                    Tier.TOUCH,
                    reason,
                    host,
                    rendered.name,
                    rendered.argv,
                    digest,
                )

            if approval is None:
                return ask("changes state; a named human must approve this exact step")
            if self.authority is None:
                return ask("no approval authority is configured, so no approval can be checked")
            problem = self.authority.problem(approval, digest, now)
            if problem:
                return ask(problem)
            if approval.nonce in self._used_nonces:
                return ask("approval has already been used")
            self._used_nonces.add(approval.nonce)
            return Decision(
                Verdict.RUN,
                Tier.TOUCH,
                f"approved by {approval.approver}",
                host,
                rendered.name,
                rendered.argv,
                digest,
            )

        return Decision(
            Verdict.REFUSED,
            Tier.NEVER,
            "Never actions cannot run",
            host,
            rendered.name,
            rendered.argv,
        )
