from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from wheelhouse.safety import (
    ActionSpec,
    Approval,
    ApprovalAuthority,
    Catalog,
    Lockkeeper,
    Param,
    Tier,
    Verdict,
)

NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
KEY = b"k" * 32


def keeper() -> Lockkeeper:
    return Lockkeeper(authority=ApprovalAuthority(KEY))


def approve(k: Lockkeeper, host: str, action: str, args: dict[str, str], **kw: object) -> Approval:
    first = k.decide(host, action, args, now=NOW)
    assert first.step_hash is not None
    assert k.authority is not None
    return k.authority.grant(first.step_hash, "shashikant", now=NOW, **kw)  # type: ignore[arg-type]


def test_look_runs_without_approval() -> None:
    d = keeper().decide("web01", "disk_usage", now=NOW)
    assert d.verdict is Verdict.RUN and d.tier is Tier.LOOK
    assert d.argv == ("df", "-h")


def test_touch_needs_approval() -> None:
    d = keeper().decide("web01", "service_restart", {"service": "nginx"}, now=NOW)
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert d.step_hash


def test_touch_runs_with_matching_approval() -> None:
    k = keeper()
    approval = approve(k, "web01", "service_restart", {"service": "nginx"})
    d = k.decide("web01", "service_restart", {"service": "nginx"}, approval, now=NOW)
    assert d.verdict is Verdict.RUN
    assert "shashikant" in d.reason


def test_approval_is_single_use() -> None:
    k = keeper()
    approval = approve(k, "web01", "service_restart", {"service": "nginx"})
    assert k.decide("web01", "service_restart", {"service": "nginx"}, approval, now=NOW).may_run
    again = k.decide("web01", "service_restart", {"service": "nginx"}, approval, now=NOW)
    assert again.verdict is Verdict.NEEDS_APPROVAL and "already been used" in again.reason


@pytest.mark.parametrize(
    ("host", "args"),
    [("web02", {"service": "nginx"}), ("web01", {"service": "mysql"})],
)
def test_approval_does_not_transfer_to_another_step(host: str, args: dict[str, str]) -> None:
    k = keeper()
    approval = approve(k, "web01", "service_restart", {"service": "nginx"})
    d = k.decide(host, "service_restart", args, approval, now=NOW)
    assert d.verdict is Verdict.NEEDS_APPROVAL
    assert "different step" in d.reason


def test_approval_does_not_transfer_to_another_action() -> None:
    k = keeper()
    approval = approve(k, "web01", "service_start", {"service": "nginx"})
    d = k.decide("web01", "service_stop", {"service": "nginx"}, approval, now=NOW)
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_expired_approval() -> None:
    k = keeper()
    approval = approve(
        k, "web01", "service_restart", {"service": "nginx"}, ttl=timedelta(minutes=5)
    )
    later = NOW + timedelta(minutes=6)
    d = k.decide("web01", "service_restart", {"service": "nginx"}, approval, now=later)
    assert d.verdict is Verdict.NEEDS_APPROVAL and "expired" in d.reason


def test_forged_or_altered_approvals_are_rejected() -> None:
    k = keeper()
    good = approve(k, "web01", "service_restart", {"service": "nginx"})
    forgeries = [
        Approval(good.step_hash, "anyone", NOW, NOW + timedelta(minutes=1), "n", ""),
        Approval(good.step_hash, "anyone", NOW, NOW + timedelta(minutes=1), "n", "00" * 32),
        replace(good, approver="someone-else"),
        replace(good, expires_at=good.expires_at + timedelta(hours=1)),
        replace(good, nonce="fresh-nonce"),
        ApprovalAuthority(b"x" * 32).grant(good.step_hash, "shashikant", now=NOW),
    ]
    for forged in forgeries:
        d = k.decide("web01", "service_restart", {"service": "nginx"}, forged, now=NOW)
        assert d.verdict is Verdict.NEEDS_APPROVAL, forged


def test_naive_times_are_refused_not_crashing() -> None:
    k = keeper()
    good = approve(k, "web01", "service_restart", {"service": "nginx"})
    naive = replace(good, approved_at=good.approved_at.replace(tzinfo=None))
    d = k.decide("web01", "service_restart", {"service": "nginx"}, naive, now=NOW)
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_without_authority_touch_never_runs() -> None:
    signed = approve(keeper(), "web01", "service_restart", {"service": "nginx"})
    d = Lockkeeper().decide("web01", "service_restart", {"service": "nginx"}, signed, now=NOW)
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_authority_rules() -> None:
    with pytest.raises(ValueError):
        ApprovalAuthority(b"short")
    auth = ApprovalAuthority(KEY)
    with pytest.raises(ValueError):
        auth.grant("x", "  ", now=NOW)
    with pytest.raises(ValueError):
        auth.grant("x", "a", now=NOW, ttl=timedelta(hours=9))
    with pytest.raises(ValueError):
        auth.grant("x", "a", now=datetime(2026, 10, 19))
    assert "key" not in repr(auth).replace("key=***", "")


def test_unknown_action_refused() -> None:
    d = keeper().decide("web01", "delete_logs", now=NOW)
    assert d.verdict is Verdict.REFUSED


@pytest.mark.parametrize("host", ["-oProxyCommand=x", "web01;rm", "", "a b"])
def test_bad_host_refused(host: str) -> None:
    assert keeper().decide(host, "disk_usage", now=NOW).verdict is Verdict.REFUSED


def test_guard_overrides_a_wrong_catalog_entry() -> None:
    # A deployer adds a bad entry by mistake and labels it Look. The guard still refuses.
    bad = Catalog([ActionSpec("cleanup", Tier.LOOK, "oops", ("rm", "-rf", "/tmp/x"))])
    d = Lockkeeper(bad).decide("web01", "cleanup", now=NOW)
    assert d.verdict is Verdict.REFUSED and d.tier is Tier.NEVER


def test_guard_refuses_even_with_a_valid_approval() -> None:
    bad = Catalog(
        [
            ActionSpec(
                "wipe",
                Tier.TOUCH,
                "oops",
                ("rabbitmqctl", "purge_queue", "{q}"),
                {"q": Param("queue", r"[a-z]+")},
                rollback_note="none",
            )
        ]
    )
    k = Lockkeeper(bad, ApprovalAuthority(KEY))
    d = k.decide("mq01", "wipe", {"q": "orders"}, now=NOW)
    assert d.verdict is Verdict.REFUSED


def test_read_only_sql_through_lockkeeper() -> None:
    k = keeper()
    ok = k.decide("db01", "mysql_query", {"database": "app", "sql": "SELECT 1"}, now=NOW)
    assert ok.verdict is Verdict.RUN
    bad = k.decide("db01", "mysql_query", {"database": "app", "sql": "DELETE FROM t"}, now=NOW)
    assert bad.verdict is Verdict.REFUSED


# Second safety review (decision 0006).


def test_mis_tiered_state_change_is_refused() -> None:
    from wheelhouse.safety.catalog import SERVICE

    cat = Catalog(
        [
            ActionSpec(
                "oops", Tier.LOOK, "x", ("systemctl", "restart", "{service}"), {"service": SERVICE}
            )
        ]
    )
    d = Lockkeeper(cat).decide("web01", "oops", {"service": "nginx"}, now=NOW)
    assert d.verdict is Verdict.REFUSED


def test_every_default_look_action_is_read_only_to_the_guard() -> None:
    from wheelhouse.safety import default_catalog
    from wheelhouse.safety.guard import changes_state

    samples = {
        "target": "web01",
        "service": "nginx",
        "lines": "50",
        "database": "app",
        "sql": "SELECT 1",
        "vhost": "/",
    }
    cat = default_catalog()
    for spec in cat.specs():
        rendered = cat.render(spec.name, {k: samples[k] for k in spec.params})
        assert changes_state(rendered.argv) == (spec.tier is Tier.TOUCH), spec.name


@pytest.mark.parametrize(
    ("action", "args", "approval"),
    [
        (["x"], {}, None),
        ("service_status", ["service"], None),
        ("service_status", "service=nginx", None),
        ("service_restart", {"service": "nginx"}, "x"),
        (None, None, None),
    ],
)
def test_malformed_requests_are_refused_cleanly(action, args, approval) -> None:  # type: ignore[no-untyped-def]
    d = keeper().decide("web01", action, args, approval, now=NOW)
    assert d.verdict is Verdict.REFUSED


@pytest.mark.parametrize(
    "field_values",
    [{"approver": None}, {"approved_at": "2026"}, {"signature": 123}, {"nonce": None}],
)
def test_malformed_approvals_do_not_crash(field_values: dict[str, object]) -> None:
    k = keeper()
    good = approve(k, "web01", "service_restart", {"service": "nginx"})
    bad = replace(good, **field_values)  # type: ignore[arg-type]
    d = k.decide("web01", "service_restart", {"service": "nginx"}, bad, now=NOW)
    assert d.verdict is Verdict.NEEDS_APPROVAL


def test_grant_rejects_non_text_approver() -> None:
    with pytest.raises(ValueError):
        ApprovalAuthority(KEY).grant("h", None, now=NOW)  # type: ignore[arg-type]
