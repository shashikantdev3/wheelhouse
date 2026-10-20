"""The approval console: a small local web page where a named person reviews an
incident and approves or rejects its plan.

What it shows is what gets approved: the exact command of every step, its step hash,
its check and its rollback note, next to the evidence and the claim check. Approving
signs one approval per step with the person's own Ed25519 key. The console never runs
anything; the watch loop (Helmsman) does, and it cannot sign.

Local only, and locked down:
- binds to 127.0.0.1; requests with any other Host header are refused (DNS rebinding);
- a one-time login link sets a session cookie (HttpOnly, SameSite=Strict); every
  request needs it, so other local users and other web pages cannot use the console;
- every form carries a CSRF token, and an approval carries the digest of the plan the
  person saw, so a plan that changed in between is not approved;
- every step is re-rendered from the catalog and the inventory before it is shown or
  signed: if the stored command or step hash does not match what the gate computes now,
  the console refuses to approve it. The incident file is never trusted for what to sign;
- each approval is bound to the incident and the plan digest, not only to the step;
- all text is HTML-escaped and a strict Content-Security-Policy allows no scripts.
"""

from __future__ import annotations

import hmac
import html
import re
import secrets
from datetime import timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from wheelhouse import __version__
from wheelhouse.crew.helmsman import approval_context
from wheelhouse.crew.incidents import Incident, IncidentStore, Plan, Status
from wheelhouse.crew.navigator import check_problem
from wheelhouse.runtime.inventory import Inventory
from wheelhouse.runtime.runner import preview
from wheelhouse.safety.approval_io import approval_to_dict
from wheelhouse.safety.approvals import ApproverKey
from wheelhouse.safety.lockkeeper import Lockkeeper
from wheelhouse.safety.tiers import Verdict

COOKIE = "wheelhouse_session"
MAX_BODY = 4096
APPROVAL_MINUTES = (15, 30, 60, 120)
_PATH = re.compile(r"^/incidents/(INC-\d{8}-\d{6}-[0-9a-f]{6})(/approve|/reject)?$")
HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "X-Frame-Options": "DENY",
}

CSS = """
body{font:15px/1.5 system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1c2330}
header{background:#14213d;color:#fff;padding:12px 24px;display:flex;gap:16px;align-items:center}
header a{color:#fff;text-decoration:none;font-weight:600}
main{max-width:1000px;margin:24px auto;padding:0 16px}
section{background:#fff;border:1px solid #dde1e7;border-radius:8px;padding:16px 20px;margin:16px 0}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:0 0 10px}
table{border-collapse:collapse;width:100%}td,th{text-align:left;padding:6px 8px;
border-bottom:1px solid #eceff3;vertical-align:top}
pre{background:#0f172a;color:#e2e8f0;padding:10px;border-radius:6px;overflow-x:auto;
white-space:pre-wrap;word-break:break-word;font-size:13px}
code{background:#eef1f5;padding:1px 4px;border-radius:4px;font-size:13px;word-break:break-all}
.s{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600;
background:#e5e7eb}
.awaiting_approval{background:#fde68a}.approved,.executing{background:#bfdbfe}
.resolved{background:#bbf7d0}.failed,.rejected,.needs_human{background:#fecaca}
.ok{color:#15803d;font-weight:600}.bad{color:#b91c1c;font-weight:600}
.muted{color:#64748b;font-size:13px}button{font:inherit;padding:8px 16px;border-radius:6px;
border:1px solid #14213d;cursor:pointer}button.go{background:#14213d;color:#fff}
form{display:inline-block;margin-right:16px}input[type=text]{width:280px;padding:7px}
@media (max-width:640px){main{padding:0 8px}td,th{padding:4px}}
"""


def e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _page(title: str, body: str, approver: str) -> bytes:
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{e(title)}</title><style>{CSS}</style></head><body>"
        f"<header><a href=/>Wheelhouse</a><span class=muted style=color:#cbd5e1>"
        f"approval console {e(__version__)} &middot; signed in as {e(approver)}</span></header>"
        f"<main>{body}</main></body></html>"
    ).encode()


def _args(args: dict[str, str]) -> str:
    return " ".join(f"{k}={v}" for k, v in args.items())


def _status(s: Status) -> str:
    return f"<span class='s {e(s.value)}'>{e(s.value.replace('_', ' '))}</span>"


def render_list(incidents: list[Incident]) -> str:
    if not incidents:
        return "<section><h1>Incidents</h1><p>No incidents. Lookout has nothing open.</p></section>"
    rows = "".join(
        f"<tr><td><a href='/incidents/{e(i.id)}'>{e(i.id)}</a></td><td>{_status(i.status)}</td>"
        f"<td>{e(i.host)}</td><td>{e(i.title)}</td>"
        f"<td class=muted>{e(i.created_at.strftime('%Y-%m-%d %H:%M UTC'))}</td></tr>"
        for i in incidents
    )
    return (
        "<section><h1>Incidents</h1><table><tr><th>Id</th><th>Status</th><th>Host</th>"
        f"<th>What</th><th>Opened</th></tr>{rows}</table></section>"
    )


def plan_problems(plan: Plan, inventory: Inventory, lockkeeper: Lockkeeper) -> list[str]:
    """Re-check every stored step against what the gate computes now."""
    problems = []
    for n, step in enumerate(plan.steps, 1):
        d = preview(inventory, lockkeeper, step.host, step.action, step.args)
        if d.verdict is not Verdict.NEEDS_APPROVAL or not d.step_hash:
            problems.append(f"step {n}: the gate does not accept it ({d.reason})")
        elif d.step_hash != step.step_hash or list(d.argv) != step.argv:
            problems.append(f"step {n}: the stored command does not match the catalog")
        bad = check_problem(
            step.action, step.args, step.verify.action, step.verify.args, step.verify.expect
        )
        if bad:
            problems.append(f"step {n}: {bad}")
        spec = next((x for x in lockkeeper.catalog.specs() if x.name == step.action), None)
        if spec is not None and step.rollback != (
            spec.rollback_note or "no rollback note in the catalog"
        ):
            problems.append(f"step {n}: the stored rollback note does not match the catalog")
    return problems


def render_incident(i: Incident, csrf: str, problems: list[str] | None = None) -> str:
    parts = [
        f"<section><h1>{e(i.title)}</h1><p>{_status(i.status)} "
        f"<span class=muted>{e(i.id)} &middot; host {e(i.host)} &middot; "
        f"severity {e(i.severity)}</span></p></section>"
    ]
    if i.diagnosis is not None:
        checks = {c.role: c for c in (i.verification.checks if i.verification else [])}
        rows = []
        claims = [("root_cause", i.diagnosis.root_cause)] + [
            (f"supporting-{n}", c) for n, c in enumerate(i.diagnosis.supporting, 1)
        ]
        for role, c in claims:
            chk = checks.get(role)
            mark = (
                "<span class=ok>verified</span>"
                if chk and chk.ok
                else f"<span class=bad>not verified: {e(chk.problem if chk else 'unchecked')}"
                "</span>"
            )
            rows.append(
                f"<tr><td>{e(role.replace('_', ' '))}</td><td>{e(c.text)}<br>"
                f"<span class=muted>quote from {e(', '.join(c.evidence))}:</span> "
                f"<code>{e(c.quote)}</code></td><td>{mark}</td></tr>"
            )
        parts.append(
            f"<section><h2>Diagnosis (Diver), checked by Assayer</h2><p>{e(i.diagnosis.summary)}"
            f" <span class=muted>confidence {e(i.diagnosis.confidence)}</span></p>"
            f"<table>{''.join(rows)}</table></section>"
        )
    if i.plan is not None:
        steps = "".join(
            f"<tr><td>{n}</td><td><b>{e(s.action)}</b> on {e(s.host)}<br>{e(s.why)}"
            f"<pre>{e(' '.join(s.argv))}</pre>"
            f"<span class=muted>step hash</span> <code>{e(s.step_hash)}</code><br>"
            f"<span class=muted>check:</span> {e(s.verify.action)} "
            f"{e(_args(s.verify.args))} must show <code>{e(s.verify.expect)}</code><br>"
            f"<span class=muted>rollback:</span> {e(s.rollback)}</td></tr>"
            for n, s in enumerate(i.plan.steps, 1)
        )
        parts.append(
            f"<section><h2>Plan (Navigator)</h2><p>{e(i.plan.summary)}</p>"
            f"<p class=muted>Risk: {e(i.plan.risk)}</p><table>{steps}</table>"
        )
        if problems:
            parts.append(
                "<p class=bad>This plan cannot be approved: "
                + e("; ".join(problems))
                + ". Reject it and investigate by hand.</p>"
            )
        if i.status is Status.AWAITING_APPROVAL:
            options = "".join(
                f"<option value={m}{' selected' if m == 30 else ''}>{m} minutes</option>"
                for m in APPROVAL_MINUTES
            )
            parts.append(
                (
                    ""
                    if problems
                    else f"<p><form method=post action='/incidents/{e(i.id)}/approve'>"
                    f"<input type=hidden name=csrf value='{e(csrf)}'>"
                    f"<input type=hidden name=digest value='{e(i.plan.digest())}'>"
                    f"<select name=minutes>{options}</select> "
                    "<button class=go>Approve these exact steps</button></form>"
                )
                + f"<form method=post action='/incidents/{e(i.id)}/reject'>"
                f"<input type=hidden name=csrf value='{e(csrf)}'>"
                "<input type=text name=reason maxlength=300 placeholder='Why (optional)'> "
                "<button>Reject</button></form></p>"
            )
        parts.append("</section>")
    if i.results:
        done = "".join(
            f"<tr><td><code>{e(r.step_hash[:16])}</code></td><td>"
            f"{'<span class=ok>done</span>' if r.verified else '<span class=bad>stopped</span>'}"
            f"</td><td>{e(r.detail)}</td></tr>"
            for r in i.results
        )
        parts.append(f"<section><h2>Execution (Helmsman)</h2><table>{done}</table></section>")
    ev = "".join(
        f"<details><summary><b>{e(x.id)}</b> {e(x.action)} {e(_args(x.args))} on {e(x.host)} "
        f"<span class=muted>({e(x.status)}, by {e(x.collected_by)}, ledger "
        f"{e((x.decision_id or '-')[:8])})</span></summary><pre>{e(x.output)}</pre></details>"
        for x in i.evidence
    )
    parts.append(f"<section><h2>Evidence</h2>{ev or '<p>None yet.</p>'}</section>")
    if i.usage:
        spend = "".join(
            f"<tr><td>{e(a)}</td><td>{u.calls}</td><td>{u.input_tokens}</td>"
            f"<td>{u.output_tokens}</td>"
            f"<td>{f'${u.cost_usd:.5f}' if u.cost_known else 'unknown'}</td></tr>"
            for a, u in i.usage.items()
        )
        parts.append(
            "<section><h2>Model use</h2><table><tr><th>Agent</th><th>Calls</th><th>Input</th>"
            f"<th>Output</th><th>Cost</th></tr>{spend}</table></section>"
        )
    log = "".join(
        f"<tr><td class=muted>{e(x.at.strftime('%H:%M:%S'))}</td><td>{e(x.who)}</td>"
        f"<td>{e(x.what)}</td></tr>"
        for x in i.events
    )
    parts.append(f"<section><h2>Timeline</h2><table>{log}</table></section>")
    return "".join(parts)


class Console:
    def __init__(
        self, store: IncidentStore, signer: ApproverKey, inventory: Inventory, port: int = 8765
    ) -> None:
        self.store = store
        self.signer = signer
        self.inventory = inventory
        self.lockkeeper = Lockkeeper(sudo_users=inventory.sudo_users)
        self.port = port
        self.login_token = secrets.token_urlsafe(24)
        self.session = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(24)

    @property
    def allowed_hosts(self) -> set[str]:
        return {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}

    def approve(self, incident_id: str, digest: str, minutes: int) -> str | None:
        """Sign every step of the plan the person saw. Returns a problem or None."""
        if minutes not in APPROVAL_MINUTES:
            return "choose one of the offered approval times"
        problem: list[str] = []

        def change(i: Incident) -> None:
            if i.status is not Status.AWAITING_APPROVAL or i.plan is None:
                problem.append(f"this incident is {i.status.value}, not awaiting approval")
                return
            if not hmac.compare_digest(i.plan.digest().encode(), digest.encode()):
                problem.append("the plan changed after you opened it; review it again")
                return
            stale = plan_problems(i.plan, self.inventory, self.lockkeeper)
            if stale:
                problem.append("this plan cannot be approved: " + "; ".join(stale))
                return
            ttl = timedelta(minutes=minutes)
            context = approval_context(i)
            for step in i.plan.steps:
                i.approvals[step.step_hash] = approval_to_dict(
                    self.signer.grant(step.step_hash, ttl=ttl, context=context)
                )
            i.status = Status.APPROVED
            i.log(
                f"approver:{self.signer.name}",
                f"approved {len(i.plan.steps)} step(s), valid for {minutes} minutes",
            )

        self.store.update(incident_id, change)
        return problem[0] if problem else None

    def reject(self, incident_id: str, reason: str) -> str | None:
        problem: list[str] = []

        def change(i: Incident) -> None:
            if i.status is not Status.AWAITING_APPROVAL:
                problem.append(f"this incident is {i.status.value}, not awaiting approval")
                return
            i.status = Status.REJECTED
            i.log(f"approver:{self.signer.name}", f"rejected: {reason[:300] or 'no reason given'}")

        self.store.update(incident_id, change)
        return problem[0] if problem else None

    def server(self) -> ThreadingHTTPServer:
        srv = ThreadingHTTPServer(("127.0.0.1", self.port), _handler(self))
        self.port = int(srv.server_address[1])  # the real port when 0 was asked for
        return srv


def _handler(console: Console) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "wheelhouse-console"
        timeout = 10  # a slow or idle connection cannot hold a thread for long
        sys_version = ""

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            # Never log query strings: the login link carries a token.
            path = urlsplit(self.path).path
            print(f"console: {self.command} {path} -> {args[1] if len(args) > 1 else ''}")

        def _send(
            self, status: int, body: bytes = b"", extra: dict[str, str] | None = None
        ) -> None:
            self.send_response(status)
            for k, v in {**HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            if body:
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if body and self.command != "HEAD":
                self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            body = _page("Wheelhouse", f"<section><p>{e(message)}</p></section>", "-")
            self._send(status, body)

        def _host_ok(self) -> bool:
            if self.headers.get("Host", "") not in console.allowed_hosts:
                self._error(HTTPStatus.MISDIRECTED_REQUEST, "wrong host")
                return False
            return True

        def _session_ok(self) -> bool:
            cookies = self.headers.get("Cookie", "")
            for part in cookies.split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE and hmac.compare_digest(value.encode(), console.session.encode()):
                    return True
            self._error(
                HTTPStatus.UNAUTHORIZED, "Open the login link printed by 'wheelhouse console'."
            )
            return False

        def do_GET(self) -> None:  # noqa: N802
            if not self._host_ok():
                return
            url = urlsplit(self.path)
            if url.path == "/login":
                token = parse_qs(url.query).get("token", [""])[0]
                if not console.login_token or not hmac.compare_digest(
                    token.encode(), console.login_token.encode()
                ):
                    self._error(HTTPStatus.UNAUTHORIZED, "This login link is not valid.")
                    return
                console.login_token = ""  # one use only
                cookie = f"{COOKIE}={console.session}; HttpOnly; SameSite=Strict; Path=/"
                self._send(HTTPStatus.SEE_OTHER, extra={"Location": "/", "Set-Cookie": cookie})
                return
            if not self._session_ok():
                return
            if url.path == "/":
                body = render_list(console.store.all())
                self._send(HTTPStatus.OK, _page("Incidents", body, console.signer.name))
                return
            m = _PATH.match(url.path)
            if m and not m.group(2):
                try:
                    incident = console.store.get(m.group(1))
                except KeyError:
                    self._error(HTTPStatus.NOT_FOUND, "No such incident.")
                    return
                problems = (
                    plan_problems(incident.plan, console.inventory, console.lockkeeper)
                    if incident.plan is not None and incident.status is Status.AWAITING_APPROVAL
                    else []
                )
                body = render_incident(incident, console.csrf, problems)
                self._send(HTTPStatus.OK, _page(incident.title, body, console.signer.name))
                return
            self._error(HTTPStatus.NOT_FOUND, "Not found.")

        def do_POST(self) -> None:  # noqa: N802
            if not self._host_ok() or not self._session_ok():
                return
            origin = self.headers.get("Origin")
            if origin is not None and urlsplit(origin).netloc not in console.allowed_hosts:
                self._error(HTTPStatus.FORBIDDEN, "Cross-site request refused.")
                return
            m = _PATH.match(urlsplit(self.path).path)
            if not m or not m.group(2):
                self._error(HTTPStatus.NOT_FOUND, "Not found.")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request too large.")
                return
            form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            field = {k: v[0] for k, v in form.items() if v}
            if not hmac.compare_digest(field.get("csrf", "").encode(), console.csrf.encode()):
                self._error(HTTPStatus.FORBIDDEN, "Form token is not valid; reload the page.")
                return
            incident_id = m.group(1)
            try:
                if m.group(2) == "/approve":
                    try:
                        minutes = int(field.get("minutes", "0"))
                    except ValueError:
                        minutes = 0
                    problem = console.approve(incident_id, field.get("digest", ""), minutes)
                else:
                    problem = console.reject(incident_id, field.get("reason", ""))
            except KeyError:
                self._error(HTTPStatus.NOT_FOUND, "No such incident.")
                return
            if problem:
                self._error(HTTPStatus.CONFLICT, problem)
                return
            self._send(HTTPStatus.SEE_OTHER, extra={"Location": f"/incidents/{incident_id}"})

    return Handler
