"""
Multiprocessing worker for vanity address generation.

IMPORTANT: This module must contain only top-level importable functions.
On macOS/Windows, multiprocessing uses 'spawn' which requires worker
targets to be importable by name from a module.
"""

from revanity.core import generate_and_hash
from revanity.matcher import MatchPattern


def search_worker(
    name_hash: bytes,
    pattern: MatchPattern,
    result_queue,
    stop_event,
    counter,
    batch_size: int = 500,
):
    """Worker process: generate keys in a tight loop and check for matches.

    Runs until a match is found or stop_event is set.

    Args:
        name_hash: Precomputed 10-byte name hash for target destination type.
        pattern: MatchPattern (will be compiled locally).
        result_queue: multiprocessing.Queue — push (prv_bytes, id_hash, dest_hex) on match.
        stop_event: multiprocessing.Event — signals all workers to stop.
        counter: multiprocessing.Value('Q') — shared total-keys-checked counter.
        batch_size: Keys to generate between stop_event checks.
    """
    compiled = pattern.compile()
    local_count = 0

    while not stop_event.is_set():
        for _ in range(batch_size):
            prv_bytes, identity_hash, dest_hex = generate_and_hash(name_hash)
            local_count += 1

            if compiled.matches(dest_hex):
                result_queue.put((prv_bytes, identity_hash, dest_hex))
                stop_event.set()
                with counter.get_lock():
                    counter.value += local_count
                return

        with counter.get_lock():
            counter.value += local_count
        local_count = 0

    if local_count > 0:
        with counter.get_lock():
            counter.value += local_count
