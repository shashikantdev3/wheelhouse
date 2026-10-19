"""The runner: gate, execute, record.

Every request goes through Lockkeeper. Every decision, allowed or not, and every
execution is written to the ledger. Nothing runs unless its decision has been recorded.

Single use across processes: for a request that carries an approval, the runner holds
the ledger's file lock while it re-reads used approvals, decides and records the
decision, so two processes cannot both spend the same approval.

What runs is exactly the action Lockkeeper checked (decision.rendered), never a second
rendering of the request.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime

from wheelhouse.ledger import Ledger, decision_record, execution_record
from wheelhouse.runtime.inventory import Inventory
from wheelhouse.runtime.transport import CommandResult, RateLimiter, Transport
from wheelhouse.safety import Approval, ApprovalAuthority, Decision, Lockkeeper, Tier, Verdict

_UNKNOWN_BUCKET = "?unknown-host"


@dataclass(frozen=True)
class RunResult:
    decision: Decision
    result: CommandResult | None = None

    @property
    def executed(self) -> bool:
        return self.result is not None


class Runner:
    def __init__(
        self,
        inventory: Inventory,
        transport: Transport,
        ledger: Ledger,
        authority: ApprovalAuthority | None = None,
        principal: str = "wheelhouse-cli",
        key: bytes | None = None,
    ) -> None:
        self.inventory = inventory
        self.transport = transport
        self.ledger = ledger
        self.principal = principal
        self.key = key
        self.lockkeeper = Lockkeeper(
            authority=authority,
            sudo_users=inventory.sudo_users,
            used_nonces=ledger.used_nonces(),
        )
        self.limiter = RateLimiter(inventory.limits.actions_per_minute)

    def _record(self, decision: Decision, approval: Approval | None) -> str:
        rec = self.ledger.append(
            decision_record(
                decision,
                policy_hash=self.lockkeeper.catalog.policy_hash(),
                principal=self.principal,
                key=self.key,
                approval=approval,
            )
        )
        return str(rec["decision_id"])

    def _refuse(self, host: str, action: str, reason: str) -> RunResult:
        decision = Decision(Verdict.REFUSED, Tier.NEVER, reason, host, action)
        self._record(decision, None)
        return RunResult(decision)

    def request(
        self,
        host: str,
        action: str,
        args: Mapping[str, object] | None = None,
        approval: Approval | None = None,
        execute: bool = True,
        now: datetime | None = None,
    ) -> RunResult:
        """Gate a request, record the decision, and run it if allowed and execute=True.
        With execute=False a Touch step is never cleared, so no approval is used up."""
        target = self.inventory.host(host) if isinstance(host, str) else None
        bucket = host if target is not None else _UNKNOWN_BUCKET
        if not self.limiter.allow(bucket):
            # Over the limit: refuse without writing, so a flood cannot fill the ledger.
            return RunResult(
                Decision(Verdict.REFUSED, Tier.NEVER, "rate limit reached", str(host), action)
            )
        if target is None:
            return self._refuse(str(host), str(action), "host is not in the inventory")

        service = (args or {}).get("service") if isinstance(args, Mapping) else None
        if service is not None and target.services and service not in target.services:
            return self._refuse(
                host, str(action), "service is not listed for this host in the inventory"
            )

        use_approval = approval if execute else None
        guard = self.ledger.locked() if use_approval is not None else nullcontext()
        with guard:
            if use_approval is not None:
                self.lockkeeper.refresh_used_nonces(self.ledger.used_nonces())
            decision = self.lockkeeper.decide(host, action, args, use_approval, now)
            decision_id = self._record(decision, use_approval if decision.may_run else None)

        if not (execute and decision.may_run) or decision.rendered is None:
            return RunResult(decision)

        result = self.transport.run(host, target, decision.rendered)
        self.ledger.append(
            execution_record(
                decision_id,
                decision,
                policy_hash=self.lockkeeper.catalog.policy_hash(),
                principal=self.principal,
                exit_code=result.exit_code,
                duration_ms=result.duration_ms,
                output=result.output,
                status=result.status,
                key=self.key,
            )
        )
        return RunResult(decision, result)
