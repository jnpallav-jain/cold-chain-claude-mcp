"""Bounded tool workers and per-request call/deadline budgets."""

import asyncio
from concurrent.futures import Future
from functools import lru_cache
import threading
import time
from src.services.errors import ServiceError


class ToolTimedOut(ServiceError):
    pass


class RequestBudget:
    def __init__(self, seconds, max_calls):
        self.deadline = time.monotonic() + seconds
        self.max_calls = max_calls
        self.calls = 0
        self._lock = threading.Lock()

    def reserve(self):
        with self._lock:
            if time.monotonic() >= self.deadline:
                raise ServiceError("Request execution deadline exhausted.")
            if self.calls >= self.max_calls:
                raise ServiceError("Request tool-call budget exhausted.")
            self.calls += 1
            return self.deadline - time.monotonic()


class BoundedWorkers:
    """Timed-out threads keep their slot until they finish; there is no unbounded queue."""

    def __init__(self, limit):
        self._slots = threading.BoundedSemaphore(limit)

    async def run(self, operation, *, seconds, cancel=None):
        if not self._slots.acquire(blocking=False):
            raise ServiceError(
                "Tool workers are busy; try again after the running operations finish."
            )
        future = Future()

        def worker():
            try:
                future.set_result(operation())
            except BaseException as error:
                future.set_exception(error)
            finally:
                self._slots.release()

        thread = threading.Thread(target=worker, daemon=True, name="cold-chain-tool")
        try:
            thread.start()
        except Exception:
            self._slots.release()
            raise ServiceError("Tool worker could not start.") from None
        wrapped = asyncio.wrap_future(future)
        # A late failure after timeout must not create an unhandled exception log containing diagnostics.
        wrapped.add_done_callback(
            lambda done: done.exception() if not done.cancelled() else None
        )
        try:
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout=seconds)
        except TimeoutError:
            if cancel:
                cancel()
            raise ToolTimedOut("Tool execution exceeded its time limit.") from None
        except asyncio.CancelledError:
            if cancel:
                cancel()
            raise


@lru_cache(maxsize=8)
def get_workers(limit, scope="business"):
    return BoundedWorkers(limit)
