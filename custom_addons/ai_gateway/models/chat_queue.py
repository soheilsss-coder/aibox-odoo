import os
import time
import uuid
from collections import deque
from statistics import median
from threading import Lock, Condition, Event, Thread

try:
    import redis
except ImportError:  # pragma: no cover - the native lock is optional in source-only tests
    redis = None

# Bounded worker pool to keep one heavy assistant turn (LLM generation,
# document analysis, OCR, embedding) from blocking every other request.
#
# Why a queue at all: the box runs ONE vLLM engine and the Odoo model
# methods execute in the request thread. If 20 chat requests arrive at
# once and each runs immediately, they either thrash the single GPU or
# time out at the engine. This pool caps concurrent expensive turns to
# `concurrency` and runs the surplus through a FIFO wait queue, so a
# heavy turn never holds the server hostage and overflow fails fast
# with a clear "busy" error instead of piling up forever.
#
# Scope, stated honestly: this is a process-local pool. In Odoo's
# threaded mode a process serves many requests at once and this bounds
# the per-process concurrency of heavy turns - the granularity that
# matches a single GPU. Cross-process global coordination of several
# Odoo workers behind one engine is the documented follow-up to be
# sized from real load during runtime certification, not assumed here.
#
# Pure-Python on purpose: this module must be importable and testable
# WITHOUT an Odoo runtime (see ai_gateway_queue_selftest.py at the repo
# root). It never imports odoo; the gateway decides what `fn` runs.

_POOL_CONCURRENCY = int(os.environ.get("AI_CHAT_QUEUE_CONCURRENCY", "2"))
_POOL_MAX_WAITERS = int(os.environ.get("AI_CHAT_QUEUE_MAX_WAITERS", "10"))
_JOB_TIMEOUT = float(os.environ.get("AI_CHAT_QUEUE_TIMEOUT", "180.0"))


class _Job(object):
    __slots__ = ("fn", "ready", "result", "submitted_at")

    def __init__(self, fn):
        self.fn = fn
        self.ready = Event()
        self.result = None
        self.submitted_at = time.monotonic()


class BoundedWorkerPool(object):
    """Producer/consumer FIFO pool with a fixed number of worker threads.

    submit(fn) -> (ok, result)
        * If a worker is idle the job runs INLINE on the calling thread
          (the common single-request case keeps its own environment and
          adds no thread hop).
        * Otherwise the job is enqueued and a worker thread executes it;
          the caller blocks on the job's ready event with a timeout.
        * If the wait queue is already full, submit returns
          (False, "busy ...") immediately - fast fail instead of an
          unbounded pile-up.

    Worker failures never kill the pool: the job result becomes a
    generic error and the worker loops on.
    """

    def __init__(self, concurrency=None, max_waiters=None, job_timeout=None):
        self._cap = max(1, int(concurrency if concurrency is not None else _POOL_CONCURRENCY))
        self._max_waiters = max(1, int(max_waiters if max_waiters is not None else _POOL_MAX_WAITERS))
        self._job_timeout = float(job_timeout if job_timeout is not None else _JOB_TIMEOUT)
        self._idle = self._cap
        self._queue = deque()
        self._workers = []
        self._lock = Lock()
        self._notify = Condition(self._lock)
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._timeouts = 0
        self._queue_wait_ms = deque(maxlen=1000)

    @property
    def pending(self):
        with self._lock:
            return len(self._queue)

    @property
    def active(self):
        with self._lock:
            return self._cap - self._idle

    def snapshot(self):
        """Return bounded operational counters for admin observability."""
        with self._lock:
            waits = list(self._queue_wait_ms)
            return {
                "capacity": self._cap,
                "active": self._cap - self._idle,
                "pending": len(self._queue),
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "timeouts": self._timeouts,
                "queue_wait_ms_p50": round(median(waits), 3) if waits else 0.0,
                "sample_size": len(waits),
            }

    def submit(self, fn):
        with self._lock:
            self._submitted += 1
            if self._idle > 0:
                self._idle -= 1
                self._queue_wait_ms.append(0.0)
                inline = True
            else:
                if len(self._queue) >= self._max_waiters:
                    self._failed += 1
                    return False, "assistant is busy, try again shortly"
                job = _Job(fn)
                self._queue.append(job)
                inline = False
                self._ensure_workers_locked()
                self._notify.notify()
        if inline:
            return True, self._run_inline(fn)
        awaited = self._await_ready(job)
        if awaited is not None:
            return awaited
        return True, job.result

    # -- internals ---------------------------------------------------

    def _run_inline(self, fn):
        try:
            result = fn()
            if isinstance(result, dict) and result.get("error"):
                with self._lock:
                    self._failed += 1
            return result
        except Exception:  # noqa: BLE001 - same contract as pooled workers
            with self._lock:
                self._failed += 1
            return {"error": "generation failed, check server logs for details"}
        finally:
            with self._lock:
                self._completed += 1
                self._idle += 1
                self._notify.notify()

    def _await_ready(self, job):
        if not job.ready.wait(self._job_timeout):
            with self._lock:
                self._timeouts += 1
            return False, "generation timed out in queue"
        return None

    def _ensure_workers_locked(self):
        while len(self._workers) < self._cap:
            worker = Thread(target=self._worker_loop, daemon=True, name="ai-chat-pool")
            worker.start()
            self._workers.append(worker)

    def _worker_loop(self):
        while True:
            with self._lock:
                while not self._queue:
                    self._notify.wait()
                job = self._queue.popleft()
                self._queue_wait_ms.append((time.monotonic() - job.submitted_at) * 1000)
            result = None
            try:
                result = job.fn()
            except Exception:  # noqa: BLE001 - worker must survive any failure
                result = {"error": "generation failed, check server logs for details"}
            with self._lock:
                self._completed += 1
                if isinstance(result, dict) and result.get("error"):
                    self._failed += 1
                self._idle += 1
                self._notify.notify()
            job.result = result
            job.ready.set()


class RedisConcurrencyLease(object):
    """Cross-process lease limiting expensive generations per inference pool.

    The process-local pool prevents one Odoo worker from overloading the GPU;
    this lease prevents N Odoo workers from each doing that independently.
    Redis ``SET NX EX`` provides an atomic slot claim and the expiry recovers
    slots after a killed worker. A missing or broken Redis URL leaves the
    source-only/dev compatibility path untouched; production gateway auth and
    rate limits already fail closed when Redis is unavailable.
    """

    def __init__(self, capacity=None, lease_seconds=None, wait_seconds=None):
        self.capacity = max(1, int(capacity if capacity is not None else os.environ.get("AI_CHAT_GLOBAL_CONCURRENCY", "2")))
        self.lease_seconds = max(10, int(lease_seconds if lease_seconds is not None else os.environ.get("AI_CHAT_LEASE_SECONDS", "240")))
        self.wait_seconds = max(0.0, float(wait_seconds if wait_seconds is not None else os.environ.get("AI_CHAT_GLOBAL_WAIT_SECONDS", "0.75")))
        self.url = os.environ.get("AI_GATEWAY_REDIS_URL")
        if os.environ.get("AI_GATEWAY_ENV", "development") == "production" and not self.url:
            raise RuntimeError("AI_GATEWAY_REDIS_URL is required for production inference leases")
        if os.environ.get("AI_GATEWAY_ENV", "development") == "production" and redis is None:
            raise RuntimeError("redis client is required for production inference leases")
        self._client = None
        self._lock = Lock()

    @property
    def enabled(self):
        return bool(self.url and redis is not None)

    def _get_client(self):
        if not self.enabled:
            return None
        with self._lock:
            if self._client is None:
                self._client = redis.Redis.from_url(self.url, decode_responses=True, socket_timeout=1)
            return self._client

    def acquire(self):
        """Return an opaque lease token, ``None`` if disabled, ``False`` on outage/full."""
        client = self._get_client()
        if client is None:
            return None
        token = uuid.uuid4().hex
        deadline = time.monotonic() + self.wait_seconds
        try:
            while True:
                for slot in range(self.capacity):
                    key = "ai:inference:lease:%d" % slot
                    if client.set(key, token, nx=True, ex=self.lease_seconds):
                        return (key, token)
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.025)
        except Exception:
            return False

    def release(self, lease):
        if not lease or lease is False:
            return
        client = self._get_client()
        if client is None:
            return
        key, token = lease
        try:
            # Delete only our own lease; never release a slot acquired after
            # our expiry by another worker.
            client.eval(
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end",
                1, key, token,
            )
        except Exception:
            # Expiry is the recovery path if Redis is already unavailable.
            return


_global_gate = None
_global_gate_lock = Lock()


def get_global_chat_gate():
    global _global_gate
    if _global_gate is None:
        with _global_gate_lock:
            if _global_gate is None:
                _global_gate = RedisConcurrencyLease()
    return _global_gate


_pool = None
_pool_lock = Lock()


def get_chat_pool():
    """Process-wide singleton pool (one per Odoo worker process)."""
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = BoundedWorkerPool()
    return _pool


def reset_chat_pool():
    """Test helper / worker re-init: drop the singleton."""
    global _pool
    with _pool_lock:
        _pool = None