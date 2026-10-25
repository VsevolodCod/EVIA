"""Bounded, process-local reuse of validated immutable CSV profiles."""
from collections import OrderedDict
from concurrent.futures import Future
import json
from threading import Lock
from typing import Any, Callable


class ProfileCache:
    def __init__(self, *, max_entries: int = 32, max_bytes: int = 16 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict[tuple, bytes] = OrderedDict()
        self._pending: dict[tuple, Future] = {}
        self._bytes = 0
        self._lock = Lock()

    def get_or_compute(self, key: tuple, compute: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                pending = None
                owner = False
            else:
                pending = self._pending.get(key)
                owner = pending is None
                if owner:
                    pending = Future()
                    self._pending[key] = pending
        if cached is not None:
            return json.loads(cached)
        if not owner:
            # Concurrent readers of the same snapshot share one computation.
            # No global lock is held while waiting or doing database work.
            return json.loads(pending.result())
        try:
            encoded = json.dumps(compute(), ensure_ascii=False, allow_nan=False).encode('utf-8')
            with self._lock:
                if self.max_entries > 0 and len(encoded) <= self.max_bytes:
                    while self._entries and (
                        len(self._entries) >= self.max_entries
                        or self._bytes + len(encoded) > self.max_bytes
                    ):
                        _, evicted = self._entries.popitem(last=False)
                        self._bytes -= len(evicted)
                    self._entries[key] = encoded
                    self._bytes += len(encoded)
            pending.set_result(encoded)
            return json.loads(encoded)
        except BaseException as exc:
            # Failures are never cached; release all waiters even on interruption.
            pending.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._pending.pop(key, None)
