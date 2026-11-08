"""A bounded local job runner: a few worker threads and a finite queue, nothing else.

No external queue or broker. Jobs are plain callables; if the process stops, queued and
running audits are marked ``interrupted`` on the next start (see ``AuditStore``).
"""

import queue
import threading
from collections.abc import Callable


class QueueFull(RuntimeError):
    """The queue is at capacity; try again later."""


class JobRunner:
    def __init__(self, workers: int = 1, max_queued: int = 10) -> None:
        self._queue: queue.Queue[Callable[[], None] | None] = queue.Queue(max_queued)
        self._idle = threading.Condition()
        self._pending = 0
        self._closed = False
        self._threads = [
            threading.Thread(target=self._work, name=f"audit-worker-{i}", daemon=True)
            for i in range(workers)
        ]
        for thread in self._threads:
            thread.start()

    @property
    def alive(self) -> bool:
        return not self._closed and all(t.is_alive() for t in self._threads)

    @property
    def has_room(self) -> bool:
        """Whether a job submitted now would be queued (advisory: a concurrent submit
        may still take the slot, so callers must also handle ``QueueFull``)."""
        return not self._closed and not self._queue.full()

    def submit(self, job: Callable[[], None]) -> None:
        if self._closed:
            raise QueueFull("the job runner has been shut down")
        with self._idle:
            try:
                self._queue.put_nowait(job)
            except queue.Full:
                raise QueueFull("too many audits are queued; try again later") from None
            self._pending += 1

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            if job is None:
                return
            try:
                job()
            except Exception:  # the pipeline records its own failures
                pass
            finally:
                with self._idle:
                    self._pending -= 1
                    self._idle.notify_all()

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Block until every submitted job has finished (for tests and shutdown)."""
        with self._idle:
            return self._idle.wait_for(lambda: self._pending == 0, timeout)

    def shutdown(self, wait: bool = True) -> None:
        self._closed = True
        for _ in self._threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass  # daemon threads end with the process
        if wait:
            for thread in self._threads:
                thread.join(timeout=5)
