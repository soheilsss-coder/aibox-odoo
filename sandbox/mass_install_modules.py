#!/usr/bin/env python3
"""Install EVERY installable Odoo module, in batches, auto-bisecting failures.

The vendor runs this ONCE on a freshly installed appliance when the customer
bought "the whole catalogue". Safe to re-run: already-installed modules are
skipped. Progress prints to stdout; the summary line lists any module that
refused to install (usually a missing python/system dependency - install it,
re-run, done).

Run:  AIBOX_WS=/opt/aibox/data python3 sandbox/mass_install_modules.py
"""
import json
import os
import subprocess
import sys
import time

WS = os.environ.get("AIBOX_WS", "/opt/aibox/data")
ODOO = os.path.join(WS, "src/odoo/odoo-bin")
CONF = os.path.join(WS, "conf/odoo.conf")
LOG = os.path.join(WS, "logs/odoo.log")
DB = os.environ.get("AIBOX_DB", "aibox")
VENV = os.path.join(WS, "venv/bin/python")
BATCH = int(os.environ.get("AIBOX_BATCH", "40"))
TIME_BUDGET = int(os.environ.get("AIBOX_TIME_BUDGET", "7000"))


def odoo_shell(script):
    r = subprocess.run([VENV, ODOO, "shell", "-c", CONF, "-d", DB, "--stop-after-init"],
                       input=script, text=True, capture_output=True, timeout=600)
    return r.stdout


def db(sql):
    """Direct SQL through the venv's psycopg2 via odoo shell is slow; use
    the odoo shell's own cursor instead (works regardless of socket paths)."""
    out = odoo_shell(
        "env.cr.execute(%r)\n"
        "rows = env.cr.fetchall()\n"
        "import json as j; print('SQLRES' + j.dumps([list(map(str, r)) for r in rows]))\n"
        "env.cr.rollback()\n" % sql)
    for line in out.splitlines():
        if line.startswith("SQLRES"):
            return json.loads(line[6:])
    return []


def logline():
    try:
        with open(LOG, errors="ignore") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def install(names):
    before = logline()
    r = subprocess.run(
        [VENV, ODOO, "-c", CONF, "-d", DB, "-i", ",".join(names),
         "--stop-after-init", "--max-cron-threads=0"],
        timeout=1800, capture_output=True, text=True)
    try:
        new = open(LOG, errors="ignore").read().splitlines()[before:]
    except OSError:
        new = []
    err = [l for l in new if ("ERROR" in l or "CRITICAL" in l)
           and "test framework" not in l and "bad query" not in l
           and "SERIALIZATION" not in l]
    if r.returncode != 0 or err:
        return False, "\n".join(err[:6] or [r.stderr[-500:]])
    return True, ""


def states():
    return dict(db("SELECT state, count(*) FROM ir_module_module GROUP BY state"))


def bisect(names, depth=0):
    if not names:
        return [], []
    ok, err = install(names)
    if ok:
        return names, []
    if len(names) == 1 or depth > 6:
        print("FAILED-MODULE %s :: %s" % (names[0], err.splitlines()[-1][:160] if err else "exit!=0"), flush=True)
        db("UPDATE ir_module_module SET state='uninstalled' WHERE name='%s' "
           "AND state IN ('to install','to upgrade')" % names[0].replace("'", "''"))
        return [], [names[0]]
    mid = len(names) // 2
    print("  bisect %d -> %d/%d" % (len(names), mid, len(names) - mid), flush=True)
    ok1, f1 = bisect(names[:mid], depth + 1)
    ok2, f2 = bisect(names[mid:], depth + 1)
    return ok1 + ok2, f1 + f2


def main():
    installed = {r[0] for r in db("SELECT name FROM ir_module_module WHERE state='installed'")}
    all_states = db("SELECT name, state FROM ir_module_module")
    todo = sorted(n for n, st in all_states if st == "uninstalled" and n not in installed)
    print("== mass install: %d modules to go (%d already installed)" % (len(todo), len(installed)), flush=True)
    t0 = time.time()
    all_fail = []
    for i in range(0, len(todo), BATCH):
        if time.time() - t0 > TIME_BUDGET:
            print("== time budget reached - re-run the script to continue", flush=True)
            break
        batch = [n for n in todo[i:i + BATCH]
                 if n not in {r[0] for r in db("SELECT name FROM ir_module_module WHERE state='installed'")}]
        if not batch:
            continue
        print("-- batch %d (%d): %s .. %s" % (i // BATCH + 1, len(batch), batch[0], batch[-1]), flush=True)
        _ok, fail = bisect(batch)
        all_fail += fail
        print("   state now: %s" % states(), flush=True)
    print("== DONE: failed=%d :: %s" % (len(all_fail), all_fail), flush=True)
    print("final states: %s" % states(), flush=True)


if __name__ == "__main__":
    sys.exit(main())
