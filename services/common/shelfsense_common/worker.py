"""Tiny worker runtime: a graceful, signal-aware loop shared by the stream workers.

Phase 1 uses this for heartbeat scaffolding. Phase 2 services replace the `tick` callback with
real work (read frames / consume events) while keeping the same graceful-shutdown behaviour.
"""
from __future__ import annotations

import signal
import threading
from collections.abc import Callable

from shelfsense_common.logging import get_logger

_log = get_logger("worker")


class GracefulRunner:
    """Run `tick` repeatedly until SIGTERM/SIGINT, then exit cleanly."""

    def __init__(self, service_name: str, interval_s: float = 5.0) -> None:
        self.service_name = service_name
        self.interval_s = interval_s
        self._stop = threading.Event()

    def _handle_signal(self, signum: int, _frame: object) -> None:
        _log.info("shutdown_signal", service=self.service_name, signal=signum)
        self._stop.set()

    def run(self, tick: Callable[[int], None]) -> None:
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)
        _log.info("worker_started", service=self.service_name, interval_s=self.interval_s)
        iteration = 0
        while not self._stop.is_set():
            try:
                tick(iteration)
            except Exception as exc:  # keep the worker alive; log and continue
                _log.error("tick_failed", service=self.service_name, error=str(exc))
            iteration += 1
            self._stop.wait(self.interval_s)
        _log.info("worker_stopped", service=self.service_name, iterations=iteration)
