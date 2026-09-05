from __future__ import annotations

import json
import math
import time
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

from .config import KoolbardiConfig
from .io import read_jsonl
from .pipeline import allocate_counts
from .queue import TaskQueue


def _cell(shard_key: str) -> tuple[str, str, str]:
    language, complexity, band, _ = shard_key.split("-", 3)
    return language, complexity, band


def _row_count(path: Path) -> int:
    with path.open(encoding="utf-8") as handle:
        return sum(1 for _ in handle)


def _accepted_source_count(path: Path) -> int:
    return sum(
        bool(row.get("instruction_audit", {}).get("accepted"))
        for row in read_jsonl(path)
    )


def _cell_quotas(config: KoolbardiConfig, buffered: bool) -> dict[tuple[str, str, str], int]:
    selection = config.final_selection
    if selection is None:
        return {}
    lanes = {lane.language: lane for lane in config.lanes}
    quotas: dict[tuple[str, str, str], int] = {}
    for language, target in selection.targets.items():
        if buffered:
            target = math.ceil(target * selection.audit_buffer)
        complexity_quotas = allocate_counts(target, lanes[language].complexity_shares)
        for complexity, complexity_target in complexity_quotas.items():
            band_quotas = allocate_counts(
                complexity_target,
                {name: band.share for name, band in config.length_bands.items()},
            )
            for band, quota in band_quotas.items():
                quotas[(language, complexity, band)] = quota
    return quotas


def _stable_order(config: KoolbardiConfig, stage: str, shard_key: str) -> bytes:
    return sha256(f"{config.seed}:{stage}:{shard_key}".encode()).digest()


def select_response_tasks(config: KoolbardiConfig, queue: TaskQueue) -> dict:
    selection = config.final_selection
    if selection is None:
        return {"enabled": False}

    quotas = _cell_quotas(config, buffered=True)
    response_dir = config.root / "response"
    failure_dir = config.root / "response_failures"
    emitted: dict[tuple[str, str, str], int] = defaultdict(int)
    unresolved: dict[tuple[str, str, str], int] = defaultdict(int)
    for path in response_dir.glob("*.jsonl"):
        cell = _cell(path.stem)
        if cell not in quotas:
            continue
        emitted[cell] += _row_count(path)
        failure_path = failure_dir / path.name
        if failure_path.exists():
            unresolved[cell] += _row_count(failure_path)

    lane_emitted: dict[str, int] = defaultdict(int)
    lane_unresolved: dict[str, int] = defaultdict(int)
    for cell in quotas:
        lane_emitted[cell[0]] += emitted[cell]
        lane_unresolved[cell[0]] += unresolved[cell]

    retention = {}
    for cell in quotas:
        attempted = emitted[cell] + unresolved[cell]
        lane_attempted = lane_emitted[cell[0]] + lane_unresolved[cell[0]]
        if attempted:
            retention[cell] = emitted[cell] / attempted
        elif lane_attempted:
            retention[cell] = lane_emitted[cell[0]] / lane_attempted
        else:
            retention[cell] = selection.response_retention_fallback

    with queue.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            tasks = [dict(row) for row in conn.execute(
                "SELECT id,shard_key,payload,status FROM tasks WHERE phase='response'"
            )]
            baseline = dict(emitted)
            candidates: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
            running = []
            for task in tasks:
                cell = _cell(task["shard_key"])
                if cell not in quotas:
                    continue
                if task["status"] == "running":
                    source = Path(json.loads(task["payload"])["source"])
                    baseline[cell] = baseline.get(cell, 0) + _accepted_source_count(source) * retention[cell]
                    running.append(task["shard_key"])
                elif task["status"] in {"pending", "held"}:
                    source = Path(json.loads(task["payload"])["source"])
                    task["expected"] = _accepted_source_count(source) * retention[cell]
                    candidates[cell].append(task)

            selected_ids = []
            selected_keys = []
            projected = dict(baseline)
            for cell, quota in quotas.items():
                need = max(0.0, quota - baseline.get(cell, 0))
                accumulated = 0.0
                for task in sorted(
                    candidates[cell],
                    key=lambda item: _stable_order(config, "response", item["shard_key"]),
                ):
                    if accumulated >= need:
                        break
                    selected_ids.append(task["id"])
                    selected_keys.append(task["shard_key"])
                    accumulated += task["expected"]
                projected[cell] = baseline.get(cell, 0) + accumulated

            conn.execute(
                "UPDATE tasks SET status='held', error='held by configured response selection' "
                "WHERE phase='response' AND status IN ('pending','held')"
            )
            conn.executemany(
                "UPDATE tasks SET status='pending', error=NULL WHERE id=? AND status='held'",
                [(task_id,) for task_id in selected_ids],
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    receipt = {
        "created_at": int(time.time()),
        "targets": selection.targets,
        "audit_buffer": selection.audit_buffer,
        "selected_pending_shards": len(selected_ids),
        "running_shards": running,
        "projected_complete_rows": {
            language: round(sum(value for cell, value in projected.items() if cell[0] == language))
            for language in selection.targets
        },
        "cells": {
            "/".join(cell): {
                "quota": quotas[cell],
                "emitted": emitted[cell],
                "baseline_including_running": round(baseline.get(cell, 0)),
                "projected": round(projected.get(cell, 0)),
                "retention": retention[cell],
            }
            for cell in quotas
        },
        "selected_shard_keys": selected_keys,
    }
    path = config.root / "response-selection.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["receipt"] = str(path)
    return receipt


def select_audit_tasks(config: KoolbardiConfig, queue: TaskQueue) -> dict:
    selection = config.final_selection
    if selection is None:
        return {"enabled": False}

    quotas = _cell_quotas(config, buffered=True)
    response_files = {path.stem: path for path in (config.root / "response").glob("*.jsonl")}
    candidates: dict[tuple[str, str, str], list[tuple[str, int]]] = defaultdict(list)
    for key, path in response_files.items():
        cell = _cell(key)
        if cell in quotas:
            candidates[cell].append((key, _row_count(path)))

    selected_keys = set()
    selected_rows: dict[tuple[str, str, str], int] = defaultdict(int)
    for cell, quota in quotas.items():
        for key, rows in sorted(
            candidates[cell], key=lambda item: _stable_order(config, "audit", item[0])
        ):
            if selected_rows[cell] >= quota:
                break
            selected_keys.add(key)
            selected_rows[cell] += rows

    with queue.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            running = conn.execute(
                "SELECT COUNT(*) FROM tasks WHERE phase='audit' AND status='running'"
            ).fetchone()[0]
            if running:
                raise RuntimeError("cannot change audit selection while audit tasks are running")
            done_keys = {
                row[0] for row in conn.execute(
                    "SELECT shard_key FROM tasks WHERE phase='audit' AND status='done'"
                )
            }
            if not done_keys.issubset(selected_keys):
                raise RuntimeError("new audit selection would exclude already completed audit shards")
            conn.execute(
                "UPDATE tasks SET status='held', error='held by configured audit selection' "
                "WHERE phase='audit' AND status IN ('pending','held')"
            )
            conn.executemany(
                "UPDATE tasks SET status='pending', error=NULL "
                "WHERE phase='audit' AND shard_key=? AND status='held'",
                [(key,) for key in selected_keys],
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    receipt = {
        "created_at": int(time.time()),
        "targets": selection.targets,
        "audit_buffer": selection.audit_buffer,
        "selected_shards": len(selected_keys),
        "selected_rows": {
            language: sum(rows for cell, rows in selected_rows.items() if cell[0] == language)
            for language in selection.targets
        },
        "shortfalls": {
            "/".join(cell): max(0, quota - selected_rows[cell])
            for cell, quota in quotas.items()
            if selected_rows[cell] < quota
        },
        "selected_shard_keys": sorted(selected_keys),
    }
    path = config.root / "audit-selection.json"
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    receipt["receipt"] = str(path)
    return receipt
