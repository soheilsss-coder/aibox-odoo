import os
from collections import deque
from threading import Lock, Condition, Event, Thread

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
    __slots__ = ("fn", "ready", "result")

    def __init__(self, fn):
        self.fn = fn
        self.ready = Event()
        self.result = None


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

    @property
    def pending(self):
        with self._lock:
            return len(self._queue)

    @property
    def active(self):
        with self._lock:
            return self._cap - self._idle

    def submit(self, fn):
        with self._lock:
            if self._idle > 0:
                self._idle -= 1
                inline = True
            else:
                if len(self._queue) >= self._max_waiters:
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
            return fn()
        except Exception:  # noqa: BLE001 - same contract as pooled workers
            return {"error": "generation failed, check server logs for details"}
        finally:
            with self._lock:
                self._idle += 1
                self._notify.notify()

    def _await_ready(self, job):
        if not job.ready.wait(self._job_timeout):
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
            result = None
            try:
                result = job.fn()
            except Exception:  # noqa: BLE001 - worker must survive any failure
                result = {"error": "generation failed, check server logs for details"}
            with self._lock:
                self._idle += 1
                self._notify.notify()
            job.result = result
            job.ready.set()


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