import json

from koolbardi.config import KoolbardiConfig
from koolbardi.queue import TaskQueue
from koolbardi.selection import select_audit_tasks, select_response_tasks


def config(root, target):
    return KoolbardiConfig.model_validate({
        "name": "selection-test",
        "tokenizer_path": "unused",
        "output_dir": str(root),
        "lanes": [{
            "language": "en",
            "accepted_target": 10,
            "system_prompts": {"general": "English"},
            "complexity_shares": {"general": 1.0},
        }],
        "servers": {"base_urls": ["http://localhost:1"], "model": "test"},
        "final_selection": {
            "targets": {"en": target},
            "audit_buffer": 1.0,
            "response_retention_fallback": 1.0,
        },
    })


def write_rows(path, count, audited=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index in range(count):
        row = {"id": f"{path.stem}-{index}"}
        if audited:
            row["instruction_audit"] = {"accepted": True}
        rows.append(row)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_response_selection_can_be_extended_as_stable_superset(tmp_path):
    root = tmp_path / "campaign"
    queue = TaskQueue(root / "queue.sqlite3")
    keys = [f"en-general-default-{index:06d}" for index in range(3)]
    for key in keys:
        source = root / "instruction_audit" / f"{key}.jsonl"
        write_rows(source, 2, audited=True)
        queue.add("response", key, {"source": str(source)})

    first = select_response_tasks(config(root, 2), queue)
    assert first["selected_pending_shards"] == 1
    initially_selected = set(first["selected_shard_keys"])

    extended = select_response_tasks(config(root, 4), queue)
    assert extended["selected_pending_shards"] == 2
    assert initially_selected < set(extended["selected_shard_keys"])


def test_audit_selection_can_be_extended_as_stable_superset(tmp_path):
    root = tmp_path / "campaign"
    queue = TaskQueue(root / "queue.sqlite3")
    keys = [f"en-general-default-{index:06d}" for index in range(3)]
    for key in keys:
        response = root / "response" / f"{key}.jsonl"
        write_rows(response, 2)
        queue.add("audit", key, {"source": str(response)})

    first = select_audit_tasks(config(root, 2), queue)
    assert first["selected_shards"] == 1
    initially_selected = set(first["selected_shard_keys"])

    extended = select_audit_tasks(config(root, 4), queue)
    assert extended["selected_shards"] == 2
    assert initially_selected < set(extended["selected_shard_keys"])
