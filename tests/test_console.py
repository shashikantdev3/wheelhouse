import http.client
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import pytest

from wheelhouse.console import Console
from wheelhouse.crew import Crew, IncidentStore, Model, Status

from tests.crew_fakes import DIAGNOSIS, NEXT_LOGS, PLAN, Estate, ScriptedModel, make_runner
from tests.keys import SHASHIKANT


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[tuple[Console, IncidentStore, str]]:
    estate = Estate()
    runner = make_runner(tmp_path, estate)
    store = IncidentStore(runner.inventory.state)
    crew = Crew(runner, store, Model(ScriptedModel([NEXT_LOGS, DIAGNOSIS, PLAN])))
    estate.running[("web01", "nginx")] = False
    iid = crew.run_once().sweep.opened[0]

    def evil_title(i):  # type: ignore[no-untyped-def]
        i.title = "<script>alert(1)</script>"

    store.update(iid, evil_title)
    console = Console(store, SHASHIKANT, runner.inventory, port=0)
    server = console.server()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield console, store, iid
    server.shutdown()
    server.server_close()


def call(
    console: Console,
    method: str,
    path: str,
    body: dict[str, str] | None = None,
    cookie: str | None = None,
    host: str | None = None,
    origin: str | None = None,
) -> http.client.HTTPResponse:
    conn = http.client.HTTPConnection("127.0.0.1", console.port, timeout=5)
    headers = {"Host": host or f"127.0.0.1:{console.port}"}
    if cookie:
        headers["Cookie"] = cookie
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = urlencode(body)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, path, body=data, headers=headers)
    return conn.getresponse()


def login(console: Console) -> str:
    res = call(console, "GET", f"/login?token={console.login_token}")
    assert res.status == 303
    cookie = res.getheader("Set-Cookie") or ""
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    return cookie.split(";")[0]


def test_needs_login_and_right_host(setup: tuple[Console, IncidentStore, str]) -> None:
    console, _, _ = setup
    assert call(console, "GET", "/").status == 401
    assert call(console, "GET", "/login?token=wrong").status == 401
    cookie = login(console)
    assert call(console, "GET", "/", cookie=cookie).status == 200
    assert call(console, "GET", "/", cookie=cookie, host="evil.example:80").status == 421
    assert call(console, "GET", "/", cookie="wheelhouse_session=guess").status == 401


def test_page_is_escaped_and_locked_down(setup: tuple[Console, IncidentStore, str]) -> None:
    console, _, iid = setup
    cookie = login(console)
    res = call(console, "GET", f"/incidents/{iid}", cookie=cookie)
    page = res.read().decode()
    assert res.status == 200
    assert "<script>" not in page and "&lt;script&gt;" in page
    assert "default-src 'none'" in (res.getheader("Content-Security-Policy") or "")
    assert "sudo -n systemctl start nginx" in page  # the exact command is shown
    assert "Approve these exact steps" in page


def test_approve_needs_csrf_and_same_origin(setup: tuple[Console, IncidentStore, str]) -> None:
    console, store, iid = setup
    cookie = login(console)
    plan = store.get(iid).plan
    assert plan is not None
    form = {"csrf": console.csrf, "digest": plan.digest(), "minutes": "30"}
    path = f"/incidents/{iid}/approve"
    assert call(console, "POST", path, {**form, "csrf": "x"}, cookie).status == 403
    assert call(console, "POST", path, form, cookie, origin="https://evil.example").status == 403
    assert call(console, "POST", path, form).status == 401
    assert store.get(iid).status is Status.AWAITING_APPROVAL
    res = call(console, "POST", path, form, cookie, origin=f"http://127.0.0.1:{console.port}")
    assert res.status == 303
    approved = store.get(iid)
    assert approved.status is Status.APPROVED and len(approved.approvals) == 1
    # A second click is refused, not double-signed.
    assert call(console, "POST", path, form, cookie).status == 409


def test_unknown_paths_and_big_bodies(setup: tuple[Console, IncidentStore, str]) -> None:
    console, _, _ = setup
    cookie = login(console)
    assert call(console, "GET", "/incidents/../../etc/passwd", cookie=cookie).status == 404
    assert (
        call(console, "GET", "/incidents/INC-20990101-000000-abcdef", cookie=cookie).status == 404
    )
    big = {"csrf": console.csrf, "reason": "x" * 5000}
    res = call(console, "POST", "/incidents/INC-20990101-000000-abcdef/reject", big, cookie)
    assert res.status == 413


def test_login_link_works_once(setup: tuple[Console, IncidentStore, str]) -> None:
    console, _, _ = setup
    token = console.login_token
    login(console)
    assert call(console, "GET", f"/login?token={token}").status == 401
    assert call(console, "GET", "/login?token=%C3%A9").status == 401
