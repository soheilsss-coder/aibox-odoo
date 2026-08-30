"""
Security Testing (roadmap #50) - run via 13_security_testing.sh, not
directly (needs the demo users' real API keys, same as
11_evaluation_suite.py/.sh - see that file for why a wrapper is
needed at all).

WHAT THIS FILE IS FOR, AND HOW IT DIFFERS FROM THE OTHER TWO TEST
FILES (read this before assuming it's redundant with them):

  - 05_acceptance_tests.py proves the PERMISSION LOGIC is correct,
    calling tool methods directly inside the Odoo process. Its own
    "Security Testing" section (scenarios 11-21) already covers most
    of what roadmap #50 asks for ("deliberate attempts to bypass
    every permission") - self-approval, cross-department documents,
    the v17 department task rule, access-grant expiry, direct
    res.groups writes, RISK_5 blocking, gateway allowlist denial.

  - 11_evaluation_suite.py proves the HTTP CONTROLLER is correct for
    the HAPPY path over real HTTP - valid keys, valid payloads, the
    right status codes.

  - THIS FILE is the missing third angle: it plays an ATTACKER
    talking to the HTTP layer, sending things a well-behaved frontend
    never would - malformed keys, injection-shaped strings, oversized
    payloads, cross-user id guessing, wrong methods, and enough
    traffic to trip the auth-failure flood limiter added in v19. A
    few of these scenarios exist specifically to prove two gaps found
    by reading the v18 gateway.py source line-by-line were actually
    closed in v19, not just described as closed:
      1. Unlimited invalid-API-key probing (the old rate limiter was
         only ever checked AFTER a successful lookup).
      2. /api/chat accepting any thread_id with no ownership check.

Like 11_evaluation_suite.py, exits non-zero only on a HARD scenario
failure. The flood-limiter scenario is SLOW (30+ requests against the
same endpoint) and opt-in via --run-slow, same convention as that
file's rate-limit test.
"""

import argparse
import json
import sys
import time

import requests

results = []


def check(label, condition, detail="", hard=True):
    status = "PASS" if condition else ("FAIL" if hard else "INFO-FAIL")
    results.append((status, label, detail, hard))
    tag = status if hard else f"{status} (informational, not a gate)"
    print(f"[{tag}] {label}" + (f" - {detail}" if detail and not condition else ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--keys-file", required=True,
                         help="Path to a JSON file: {\"ceo\": \"<key>\", \"accountant\": \"<key>\", \"warehouse\": \"<key>\"}")
    parser.add_argument("--base-url", default="http://localhost:8069")
    parser.add_argument("--run-slow", action="store_true",
                         help="Also run the auth-failure flood test (sends 30+ requests with bad keys).")
    args = parser.parse_args()

    with open(args.keys_file) as f:
        keys = json.load(f)

    for role in ("ceo", "accountant", "warehouse"):
        if not keys.get(role):
            print(f"No API key found for demo role '{role}' - is the demo data installed? Aborting.")
            sys.exit(1)

    base = args.base_url.rstrip("/")

    def rpc(key, model, operation, payload=None, raw_json=None):
        body = raw_json if raw_json is not None else {
            "model": model, "operation": operation, "payload": payload or {}
        }
        return requests.post(
            f"{base}/api/rpc",
            headers={"X-API-Key": key, "Content-Type": "application/json"},
            json=body, timeout=15,
        )

    def chat(key, message, thread_id=None):
        body = {"message": message}
        if thread_id is not None:
            body["thread_id"] = thread_id
        return requests.post(
            f"{base}/api/chat", headers={"X-API-Key": key, "Content-Type": "application/json"},
            json=body, timeout=60,
        )

    # -------------------------------------------------------------
    # Scenario 1: injection-shaped "model" values are rejected by the
    # ^[a-z0-9_.]+$ regex, not passed through to env[model] where a
    # crafted string could do something unexpected.
    # -------------------------------------------------------------
    for bad_model in ["res.users; DROP TABLE res_users;--", "res_users' OR '1'='1",
                       "../../../etc/passwd", "res.users) OR (1=1"]:
        resp = rpc(keys["accountant"], bad_model, "search_read", {"domain": []})
        ok = resp.status_code == 200 and "invalid model name" in resp.json().get("error", "")
        check(f"Injection-shaped model name rejected: {bad_model[:40]!r}",
              ok, f"status={resp.status_code} body={resp.text[:200]}")

    # -------------------------------------------------------------
    # Scenario 2: an operation that isn't on the fixed allowed-verbs
    # list (e.g. trying to call an arbitrary model method by name) is
    # rejected, not routed to getattr(recordset, operation)().
    # -------------------------------------------------------------
    for bad_op in ["unlink_all", "__class__", "_patch_method", "execute_sql"]:
        resp = rpc(keys["accountant"], "res.partner", bad_op, {})
        ok = resp.status_code == 200 and "not allowed" in resp.json().get("error", "")
        check(f"Non-allowlisted operation rejected: {bad_op!r}",
              ok, f"status={resp.status_code} body={resp.text[:200]}")

    # -------------------------------------------------------------
    # Scenario 3: a deliberately oversized/deeply-structured payload
    # gets a clean JSON error, not a 500 with a stack trace (which
    # would leak server internals) and not a hang.
    # -------------------------------------------------------------
    huge_domain = [["name", "=", "x" * 200000]]
    resp = rpc(keys["accountant"], "res.partner", "search_read", {"domain": huge_domain, "limit": 1})
    check("Oversized payload does not crash the endpoint (no 5xx, no timeout)",
          resp.status_code < 500, f"status={resp.status_code} body={resp.text[:200]}")

    # -------------------------------------------------------------
    # Scenario 4: malformed JSON body -> a clean 4xx, not a stack trace.
    # -------------------------------------------------------------
    resp = requests.post(f"{base}/api/rpc", headers={"X-API-Key": keys["accountant"],
                          "Content-Type": "application/json"}, data="{not valid json", timeout=15)
    check("Malformed JSON body does not return a raw server error page",
          resp.status_code < 500, f"status={resp.status_code} body={resp.text[:200]}")

    # -------------------------------------------------------------
    # Scenario 5: wrong HTTP method on a POST-only JSON route is
    # refused by Odoo's own routing, never silently accepted.
    # -------------------------------------------------------------
    resp = requests.get(f"{base}/api/rpc", headers={"X-API-Key": keys["accountant"]}, timeout=15)
    check("GET on the POST-only /api/rpc route is refused (not silently accepted)",
          resp.status_code in (404, 405), f"status={resp.status_code}")

    # -------------------------------------------------------------
    # Scenario 6 (v19, roadmap #50): /api/chat thread-id ownership.
    # The accountant starts a thread; the warehouse user then sends a
    # message reusing that SAME thread_id. Before the v19 fix this
    # would have silently continued the accountant's private
    # conversation as the warehouse user. After the fix, a mismatched
    # owner must get a FRESH thread_id back, never the accountant's.
    # -------------------------------------------------------------
    resp_a = chat(keys["accountant"], "acceptance test message from accountant")
    if resp_a.status_code == 200 and "thread_id" in resp_a.json():
        accountant_thread_id = resp_a.json()["thread_id"]
        resp_b = chat(keys["warehouse"], "trying to reuse someone else's thread",
                       thread_id=accountant_thread_id)
        ok = (resp_b.status_code == 200
              and resp_b.json().get("thread_id") != accountant_thread_id)
        check("A user cannot reuse another user's chat thread_id (v19 fix)",
              ok, f"accountant_thread={accountant_thread_id} status={resp_b.status_code} body={resp_b.text[:200]}")
    else:
        print(f"[SKIP] Scenario 6 (chat thread ownership) - could not start a thread: "
              f"status={resp_a.status_code} body={resp_a.text[:200]}")

    # -------------------------------------------------------------
    # Scenario 7 (v19, roadmap #50, SLOW, opt-in with --run-slow):
    # the v19 IP-keyed auth-failure limiter (AI_GATEWAY_AUTH_FAIL_LIMIT,
    # default 30/min) actually kicks in for repeated invalid keys -
    # closing the pre-v19 gap where this path was never rate-limited
    # at all because the old limiter only ever ran AFTER a successful
    # key lookup.
    # -------------------------------------------------------------
    if args.run_slow:
        hit_limit = False
        for i in range(40):
            resp = requests.get(f"{base}/api/bootstrap",
                                 headers={"X-API-Key": f"not-a-real-key-{i:04d}"}, timeout=15)
            if resp.status_code == 429:
                hit_limit = True
                break
        check("Auth-failure flood limiter kicks in for repeated invalid keys (v19 fix)",
              hit_limit)
        # A DIFFERENT, VALID key from the same test-runner IP is also
        # blocked while the IP is over its failure budget - this is
        # expected (the limiter is IP-keyed, not key-keyed, since an
        # invalid key by definition can't identify who's attacking).
        # It clears again within the 60s sliding window.
        print("[INFO] The auth-failure limiter is IP-keyed, so a real key from the SAME "
              "test-runner machine may also see 429 for up to ~60s after this scenario - "
              "that is expected, not a bug, and clears on its own.")
    else:
        print("[SKIP] Auth-failure flood test (pass --run-slow to include it - sends 40+ requests "
              "with bad keys and will make /api/bootstrap briefly unavailable from this machine)")

    # ---------------------------------------------------------------
    hard_failures = [r for r in results if r[3] and r[0] == "FAIL"]
    print(f"\n{len(results) - len(hard_failures)}/{len(results)} checks passed "
          f"({len(hard_failures)} hard failures).")
    sys.exit(1 if hard_failures else 0)


if __name__ == "__main__":
    main()
