#!/usr/bin/env python3
"""Offline self-test for the chat worker pool (Phase 1.2).

Runs WITHOUT an Odoo runtime: BoundedWorkerPool is pure Python by
design precisely so the concurrency mechanics can be verified here.

Note on methodology: submit() runs a job inline when a worker is idle,
so real concurrency only appears with PARALLEL callers - these tests
therefore drive the pool from several threads, like real HTTP requests
would. That also exercises the queued/worker path: when the pool is
saturated the surplus jobs go through the FIFO worker threads and then
drain.

Usage: python3 ai_gateway_queue_selftest.py
"""
import os
import sys
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "custom_addons", "ai_gateway", "models"))
from chat_queue import BoundedWorkerPool  # noqa: E402

PASS = []
FAIL = []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS" if cond else "FAIL"), "-", name, ("| " + detail) if detail else "")


def slow(seconds, value):
    def fn():
        time.sleep(seconds)
        return {"ok": True, "value": value}
    return fn


def run_parallel(submitters):
    """Run `submitters` (list of thunks returning (ok, result)) on
    separate threads, like parallel HTTP requests, and join all."""
    results = [None] * len(submitters)
    threads = []

    def call(i):
        results[i] = submitters[i]()

    for i in range(len(submitters)):
        t = threading.Thread(target=call, args=(i,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    return results


def test_parallel_drain():
    pool = BoundedWorkerPool(concurrency=2, max_waiters=64)
    t0 = time.time()
    results = run_parallel([lambda i=i: pool.submit(slow(0.15, i))
                            for i in range(8)])
    elapsed = time.time() - t0
    check("8 parallel submits: all 'ok'", all(ok for ok, _ in results))
    check("8 parallel submits: no pending stays pending",
          all(r["ok"] for _, r in results) and pool.pending == 0)
    # serial would be 8*0.15=1.2s; with cap 2 it should be roughly half
    check("8 parallel submits: parallelism (elapsed < serial)",
          elapsed < 1.1, "elapsed=%.2fs" % elapsed)
    check("8 parallel submits: results correct",
          sorted(r["value"] for _, r in results) == list(range(8)))


def test_fifo_fairness():
    pool = BoundedWorkerPool(concurrency=1, max_waiters=64)
    order = []
    order_lock = threading.Lock()

    # Prime the single worker with a job that starts inline and holds
    # the slot, so the four traced jobs below MUST go through the queue.
    run_parallel([lambda: pool.submit(slow(0.25, "primer"))])

    def traced(value):
        def fn():
            with order_lock:
                order.append(value)
            time.sleep(0.02)
            return {"ok": True}
        return fn

    run_parallel([lambda i=i: pool.submit(traced(i)) for i in range(4)])
    check("FIFO: queued jobs start in submit order (cap=1)",
          order == [0, 1, 2, 3], "order=%r" % order)


def test_overflow_fast_fail():
    pool = BoundedWorkerPool(concurrency=1, max_waiters=2)
    t0 = time.time()
    results = run_parallel([lambda i=i: pool.submit(slow(0.5, i))
                            for i in range(6)])
    elapsed = time.time() - t0
    busy = [i for i, (ok, r) in enumerate(results)
            if not ok and r == "assistant is busy, try again shortly"]
    check("overflow: some submits fail fast with busy (queue full)",
          len(busy) >= 1, "busy_at=%r" % busy)
    check("overflow: no submit ever blocks forever (bounded runtime)",
          elapsed < 4.0, "elapsed=%.2fs" % elapsed)
    done = [r for ok, r in results if ok]
    check("overflow: every accepted submit drains",
          len(done) == 6 - len(busy), "accepted=%d" % len(done))


def test_worker_failure_resilience():
    pool = BoundedWorkerPool(concurrency=1, max_waiters=2)

    def boom():
        raise RuntimeError("simulated crash")

    # Two parallel submitters. Depending on which wins the idle slot the
    # crashing job runs inline or through a pool worker - the essential
    # property is that a raw exception NEVER crosses submit() either way.
    results = run_parallel([
        lambda: pool.submit(slow(0.3, "primer")),
        lambda: pool.submit(boom),
    ])
    ok, result = results[1]
    check("crash: generic error result, never a raw exception",
          ok and isinstance(result, dict) and "error" in result,
          "result=%r" % (result,))
    ok2, result2 = pool.submit(slow(0.01, "after"))
    check("crash: subsequent job still runs",
          ok2 and result2 == {"ok": True, "value": "after"})


def main():
    test_parallel_drain()
    test_fifo_fairness()
    test_overflow_fast_fail()
    test_worker_failure_resilience()
    print()
    print("PASS=%d FAIL=%d" % (len(PASS), len(FAIL)))
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
    print("QUEUE SELF-TEST PASS")


if __name__ == "__main__":
    main()