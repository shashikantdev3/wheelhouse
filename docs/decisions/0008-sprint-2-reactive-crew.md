# 0008. Sprint 2: the reactive crew, Ed25519 approvals and the approval console

Date: 20 October 2026. Status: Accepted.

## Context

Sprint 2's exit check: one incident goes end to end, detected, investigated with cited evidence, planned, approved, executed and verified. Sprint 1 left two known weaknesses: approvals signed with a shared HMAC key (whoever can read it can approve), and no check that what the model says is grounded in what the hosts returned.

## Decisions

1. **Lookout is rules first (System 1), with no model.** Probe output (systemd state, disk use) is parsed by plain code, so detection is cheap, deterministic and testable. Timer-driven jobs are judged only on failed runs. A learned decision model for triage (the twosystems ladder) is deferred to Sprint 3, where the drill set gives it something to be measured against; it will sit behind the same interface and be asked only when the rules are unsure.
2. **Diver may only use Look actions.** The model picks the next action; plain code checks it is a Look action on an inventory host before it reaches the gate, and Diver never passes an approval. Host output reaches the model inside data blocks with a random tag that the content cannot contain.
3. **No plan without verified evidence (Assayer).** Every claim cites evidence ids and quotes the exact text it relies on. Plain code checks each quote word for word (ignoring case and spacing) against the cited output. If the root cause fails, no plan is made and a person takes over.
4. **Navigator proposes, code validates.** Steps must be Touch actions the gate would accept with an approval, on listed hosts and services, each with a read-only check and the text its output must show. The exact command and step hash are fixed before anyone is asked.
5. **Ed25519 approvals replace HMAC.** Each approver has their own key pair (`wheelhouse keys new NAME`); the inventory lists public keys. The runner and Helmsman hold no secret, so the process that executes changes cannot approve them, and each approval proves who gave it. The old secret is kept only to pseudonymise names in the ledger (`WHEELHOUSE_LEDGER_KEY`; the Sprint 1 name is still read).
6. **Separation of duties.** The approval console signs and never runs anything; the watch loop runs approved steps and cannot sign.
7. **The console is a small standard-library web server, not FastAPI and HTMX.** It needs four pages, no JavaScript and no new dependencies. It binds to 127.0.0.1, checks the Host header, needs a session from a one-time login link (HttpOnly, SameSite=Strict cookie), checks a CSRF token and the digest of the plan the person saw, escapes all text and sends a strict Content-Security-Policy. It can move to a framework when Sprint 5 adds dashboards.
8. **Helmsman stops at the first problem.** A refused step, a failed command or a check that does not show the expected text stops the run; later steps do not run, nothing is retried, and the incident goes to a person.
9. **Recorded drills.** `lab/drill.py` injects a fault in the lab, records every Look action's output, and replays it to the real crew without the lab, with a real model or a scripted one. This is the start of Sprint 3's evaluation harness.
10. **Secret scanning before commit.** After the history rewrite of 19 October (decision 0001), gitleaks runs as a pre-commit hook and over the full history in CI, and committed virtualenvs are refused.

## Results

- Lab, real SSH and systemd, scripted model: nginx stopped on web01 went detect, investigate, verify, plan, approve (Ed25519), start, check, resolved (`tests/lab/test_crew_lab.py`).
- Live model (Claude Haiku 5.5) on the recorded drills: 6 of 6 runs resolved (3 nginx, 3 memcached), about $0.0015 to $0.0025 per incident across Diver and Navigator.
- Two findings from live runs, both fixed: replies were cut off at the token limit (limit raised, the prompt asks for brevity, a cut-off reply now says so); and a recording polluted by repeated test stops led Navigator to decline to restart nginx because "an unidentified actor keeps stopping it". That refusal was the right call on that evidence; the drill was re-recorded on a fresh container.

## Review

An independent reviewer tried to make a Touch step run without a valid, unused approval from a listed key for that exact step, through Diver, Navigator, Helmsman, replays and store races, and could not. Never actions stayed refused. Verdict: pass with fixes. All eleven findings were fixed in the same change, each with a regression test:

1. **High.** The console signed the step hash stored in the incident file without recomputing it, so anyone able to write the state folder (including the watch process) could get a person to sign a different step than the one shown. Now the console re-renders every step from the catalog and the inventory before showing or signing it and refuses on any mismatch, and every approval is bound to the incident id and the plan digest (a signed `context`); Lockkeeper accepts it only where that context is expected, so a crew approval cannot be used from the command line or for another incident or plan.
2. Diver could manufacture "evidence" (a `SELECT 'text'` or a ping of a made-up name echoes the text back). Assayer now removes agent-chosen argument values before matching and only counts evidence that was collected; Diver may only ping inventory hosts and name listed services and databases.
3. A check could be chosen to always pass. Each Touch action now has a fixed check (`service_status` on the same service), and the expected text may not appear in the check's own arguments.
4. Lookout read journal lines appended by `systemctl status`, and treated a crash loop (`activating (auto-restart)`) as healthy. It now reads only the unit header and treats crash loops as down.
5. A crash could stop the watch loop or leave an incident executing forever. Errors are now caught per incident (a step that crashed is marked "may have run"), investigations are capped at two, executions stuck for 30 minutes go to a person, and damaged incident files are skipped.
6. Approvals for steps that never ran stayed on the incident. Helmsman now clears them when it finishes.
7. Incident files were readable by every local user. Folder 0700, files 0600.
8. Injected log text could steer Diver to ping an attacker's domain or query any database. Fixed with 2.
9. The incident title, Lookout's detection line and Diver's claims reached prompts outside the data fences. They are fenced now.
10. The console's login link worked more than once, a non-ASCII token crashed the handler, and connections had no time limit. Fixed.
11. Signatures were decoded leniently, and an approver's clock running a few seconds ahead caused refusals. Strict decoding, 60 seconds of allowed skew.

## Honest limits

- Assayer checks that claims are grounded in the evidence, not that the reasoning is right: a true quote can support a wrong conclusion, and log lines can be written by an attacker. A person still reads the diagnosis before approving.
- Detection covers stopped services, failed timer jobs, nearly full disks and unreachable hosts. Everything else comes with the drills and Barometer.
- The incident store is JSON files with a file lock: fine for one deployment, not for many clients (Sprint 11).
- Approvals stored with an incident are bearer tokens for that one step until they are used or expire; they cannot be reused and are bound to the step hash.
