"""
Generator orchestrator: manages multiprocessing workers and result collection.
"""

import os
import time
from multiprocessing import Process, Queue, Event, Value
from dataclasses import dataclass
from typing import Callable, Optional

from revanity.core import DEST_NAME_HASHES, compute_name_hash
from revanity.matcher import MatchPattern, MatchMode, validate_hex_pattern, estimate_difficulty
from revanity.worker import search_worker


@dataclass
class GeneratorResult:
    """A single vanity address match."""
    private_key: bytes
    identity_hash: bytes
    dest_hash_hex: str
    dest_type: str
    elapsed: float
    total_checked: int
    rate: float


@dataclass
class GeneratorStats:
    """Live stats during generation."""
    total_checked: int = 0
    elapsed: float = 0.0
    rate: float = 0.0
    is_running: bool = False
    results_found: int = 0


class VanityGenerator:
    """Orchestrates parallel vanity address generation.

    Usage:
        gen = VanityGenerator(pattern="dead", mode=MatchMode.PREFIX)
        gen.on_progress = lambda stats: print(f"{stats.rate:.0f} keys/sec")
        gen.on_result = lambda result: print(f"Found: {result.dest_hash_hex}")
        gen.start()
        # ... poll periodically ...
        gen.stop()
    """

    def __init__(
        self,
        pattern: str,
        mode: MatchMode = MatchMode.PREFIX,
        dest_type: str = "lxmf.delivery",
        num_workers: int = 0,
        case_sensitive: bool = False,
    ):
        if mode in (MatchMode.PREFIX, MatchMode.SUFFIX, MatchMode.CONTAINS):
            self.pattern_str = validate_hex_pattern(pattern)
        else:
            self.pattern_str = pattern

        self.match_pattern = MatchPattern(
            mode=mode,
            pattern=self.pattern_str,
            case_sensitive=case_sensitive,
        )

        if dest_type in DEST_NAME_HASHES:
            self.name_hash = DEST_NAME_HASHES[dest_type]
        else:
            parts = dest_type.split(".")
            if len(parts) < 2:
                raise ValueError(
                    f"Invalid destination type: {dest_type}. Use format 'app.aspect'"
                )
            self.name_hash = compute_name_hash(dest_type)

        self.dest_type = dest_type
        self.num_workers = num_workers if num_workers > 0 else max(1, (os.cpu_count() or 2) - 1)

        # Callbacks
        self.on_progress: Optional[Callable[[GeneratorStats], None]] = None
        self.on_result: Optional[Callable[[GeneratorResult], None]] = None
        self.on_complete: Optional[Callable[[], None]] = None

        # Internal state
        self._workers: list[Process] = []
        self._result_queue: Optional[Queue] = None
        self._stop_event: Optional[Event] = None
        self._counter: Optional[Value] = None
        self._start_time: float = 0
        self._results: list[GeneratorResult] = []
        self._is_running = False

    def get_difficulty(self) -> dict:
        """Get difficulty estimate for the current pattern."""
        return estimate_difficulty(self.match_pattern)

    def start(self) -> None:
        """Start worker processes (non-blocking)."""
        if self._is_running:
            raise RuntimeError("Generator is already running")

        self._result_queue = Queue()
        self._stop_event = Event()
        self._counter = Value("Q", 0)
        self._start_time = time.time()
        self._results = []
        self._is_running = True

        for i in range(self.num_workers):
            p = Process(
                target=search_worker,
                args=(
                    self.name_hash,
                    self.match_pattern,
                    self._result_queue,
                    self._stop_event,
                    self._counter,
                ),
                daemon=True,
                name=f"revanity-worker-{i}",
            )
            p.start()
            self._workers.append(p)

    def poll(self) -> GeneratorStats:
        """Poll for progress and results. Call periodically from UI/CLI."""
        stats = GeneratorStats()

        if not self._is_running:
            stats.is_running = False
            return stats

        # Drain result queue
        while not self._result_queue.empty():
            try:
                prv_bytes, identity_hash, dest_hex = self._result_queue.get_nowait()
                elapsed = time.time() - self._start_time
                total = self._counter.value

                result = GeneratorResult(
                    private_key=prv_bytes,
                    identity_hash=identity_hash,
                    dest_hash_hex=dest_hex,
                    dest_type=self.dest_type,
                    elapsed=elapsed,
                    total_checked=total,
                    rate=total / elapsed if elapsed > 0 else 0,
                )
                self._results.append(result)

                if self.on_result:
                    self.on_result(result)
            except Exception:
                break

        elapsed = time.time() - self._start_time
        total = self._counter.value

        stats.total_checked = total
        stats.elapsed = elapsed
        stats.rate = total / elapsed if elapsed > 0 else 0
        stats.is_running = self._is_running
        stats.results_found = len(self._results)

        if self.on_progress:
            self.on_progress(stats)

        # Check if workers have finished (stop_event was set by a worker finding a match)
        if self._stop_event.is_set() and all(not w.is_alive() for w in self._workers):
            self._is_running = False
            if self.on_complete:
                self.on_complete()

        return stats

    def stop(self) -> list[GeneratorResult]:
        """Stop all workers and return collected results."""
        if self._stop_event:
            self._stop_event.set()

        for w in self._workers:
            w.join(timeout=2.0)
            if w.is_alive():
                w.terminate()

        # Final drain of result queue
        if self._result_queue:
            while not self._result_queue.empty():
                try:
                    prv_bytes, identity_hash, dest_hex = self._result_queue.get_nowait()
                    elapsed = time.time() - self._start_time
                    total = self._counter.value if self._counter else 0
                    self._results.append(GeneratorResult(
                        private_key=prv_bytes,
                        identity_hash=identity_hash,
                        dest_hash_hex=dest_hex,
                        dest_type=self.dest_type,
                        elapsed=elapsed,
                        total_checked=total,
                        rate=total / elapsed if elapsed > 0 else 0,
                    ))
                except Exception:
                    break

        self._workers = []
        self._is_running = False
        return self._results

    @property
    def results(self) -> list[GeneratorResult]:
        return list(self._results)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def run_blocking(self, progress_interval: float = 0.5) -> list[GeneratorResult]:
        """Run synchronously with periodic progress callbacks. For CLI use."""
        self.start()
        try:
            while self._is_running:
                time.sleep(progress_interval)
                self.poll()
        except KeyboardInterrupt:
            pass
        finally:
            return self.stop()
