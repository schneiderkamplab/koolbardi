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

