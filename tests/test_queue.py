from concurrent.futures import ThreadPoolExecutor

from koolbardi.queue import TaskQueue


def test_claim_is_atomic(tmp_path):
    queue = TaskQueue(tmp_path / "queue.sqlite3")
    assert queue.add("instruction", "a", {"count": 1})
    with ThreadPoolExecutor(max_workers=8) as executor:
        claimed = list(executor.map(lambda _: queue.claim("instruction"), range(8)))
    assert sum(task is not None for task in claimed) == 1


def test_partial_failure_retries_then_stops(tmp_path):
    queue = TaskQueue(tmp_path / "queue.sqlite3")
    queue.add("audit", "a", {})
    task = queue.claim("audit")
    queue.fail(task.id, "network", max_attempts=2)
    assert queue.claim("audit") is not None


def test_terminal_failures_can_be_reset_by_phase(tmp_path):
    queue = TaskQueue(tmp_path / "queue.sqlite3")
    queue.add("instruction", "a", {})
    task = queue.claim("instruction")
    queue.fail(task.id, "fixed later", max_attempts=1)
    assert queue.reset_failed("audit") == 0
    assert queue.reset_failed("instruction") == 1
    assert queue.claim("instruction") is not None


def test_phase_status_count(tmp_path):
    queue = TaskQueue(tmp_path / "queue.sqlite3")
    queue.add("audit", "a", {})
    assert queue.count("audit", "pending") == 1
    assert queue.count("audit", "failed") == 0


def test_add_many_is_atomic_and_ignores_duplicates(tmp_path):
    queue = TaskQueue(tmp_path / "queue.sqlite3")
    assert queue.add("instruction", "existing", {"count": 0})
    assert queue.add_many([
        ("instruction", "existing", {"count": 1}),
        ("instruction", "new", {"count": 2}),
    ]) == 1
    assert queue.count("instruction", "pending") == 2
