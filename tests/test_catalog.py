import pytest

from wheelhouse.safety import ActionSpec, Catalog, CatalogError, Param, Tier, default_catalog
from wheelhouse.safety.catalog import SERVICE


def test_default_catalog_renders_every_action_without_guard_hits() -> None:
    from wheelhouse.safety.guard import destructive_reason

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
        assert destructive_reason(rendered.argv) is None, spec.name


@pytest.mark.parametrize(
    ("action", "args"),
    [
        ("service_status", {"service": "-H root@evil"}),
        ("service_status", {"service": "nginx; rm -rf /"}),
        ("service_status", {"service": "nginx rm"}),
        ("service_status", {"service": ""}),
        ("service_status", {"service": 5}),
        ("service_status", {}),
        ("service_status", {"service": "nginx", "extra": "x"}),
        ("service_logs", {"service": "nginx", "lines": "501"}),
        ("service_logs", {"service": "nginx", "lines": "0"}),
        ("mysql_query", {"database": "app", "sql": "DROP TABLE t"}),
        ("mysql_query", {"database": "app", "sql": "-e"}),
        ("ping", {"target": "-f"}),
        ("service_start", {"service": "reboot.target"}),
        ("service_stop", {"service": "dev-sda.mount"}),
        ("mysql_query", {"database": "a$b", "sql": "SELECT 1"}),
        ("rm_everything", {}),
    ],
)
def test_bad_requests_are_rejected(action: str, args: dict[str, object]) -> None:
    with pytest.raises(CatalogError):
        default_catalog().render(action, args)


def test_catalog_cannot_hold_never_actions() -> None:
    with pytest.raises(CatalogError):
        ActionSpec("wipe", Tier.NEVER, "x", ("true",))


def test_touch_needs_rollback_note() -> None:
    with pytest.raises(CatalogError):
        ActionSpec(
            "restart", Tier.TOUCH, "x", ("systemctl", "restart", "{service}"), {"service": SERVICE}
        )


def test_placeholders_must_be_whole_arguments() -> None:
    with pytest.raises(CatalogError):
        ActionSpec("bad", Tier.LOOK, "x", ("journalctl", "-u{service}"), {"service": SERVICE})


def test_program_cannot_be_a_parameter() -> None:
    with pytest.raises(CatalogError):
        ActionSpec("bad", Tier.LOOK, "x", ("{prog}",), {"prog": SERVICE})


def test_params_must_match_placeholders() -> None:
    with pytest.raises(CatalogError):
        ActionSpec("bad", Tier.LOOK, "x", ("df",), {"service": SERVICE})


def test_param_without_rule_is_rejected() -> None:
    cat = Catalog([ActionSpec("echo", Tier.LOOK, "x", ("echo", "{v}"), {"v": Param("any")})])
    with pytest.raises(CatalogError):
        cat.render("echo", {"v": "hello"})


def test_duplicate_actions_rejected() -> None:
    spec = ActionSpec("df", Tier.LOOK, "x", ("df",))
    with pytest.raises(CatalogError):
        Catalog([spec, spec])


def test_every_render_survives_a_remote_shell() -> None:
    import shlex

    samples = {
        "target": "web01",
        "service": "nginx",
        "lines": "50",
        "database": "app",
        "sql": "SELECT '$(id)', `c` FROM t WHERE a = 'x;y' AND b = \"z\"",
        "vhost": "/",
    }
    cat = default_catalog()
    for spec in cat.specs():
        rendered = cat.render(spec.name, {k: samples[k] for k in spec.params})
        assert shlex.split(rendered.remote_command()) == list(rendered.argv), spec.name
