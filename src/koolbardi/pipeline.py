from __future__ import annotations

import asyncio
import json
import math
import random
import time
import uuid
from collections import defaultdict
from hashlib import sha256
from pathlib import Path

from transformers import AutoTokenizer

from .client import OpenAIClientPool, gather_bounded, parse_json_object
from .config import KoolbardiConfig, SamplingConfig
from .io import atomic_write_jsonl, read_jsonl
from .queue import Task, TaskQueue
from .template import load_native_template, sanitize_instruction
from .validation import validate_text_pair


AUDIT_PROMPT = """Evaluate this synthetic training conversation. Return one JSON object only with:
accepted (boolean), language (da or en), instruction_quality (1-5), response_quality (1-5),
coherent (boolean), safe (boolean), category (short string), difficulty (short string), reason (short string).
Expected language: {language}
User: {instruction}
Assistant: {response}
"""


def initialize(config: KoolbardiConfig, queue: TaskQueue) -> int:
    added = 0
    rng = random.Random(config.seed)
    for lane in config.lanes:
        raw_target = math.ceil(lane.accepted_target * lane.oversample_factor)
        allocations = {key: int(raw_target * share) for key, share in lane.complexity_shares.items()}
        allocations[max(allocations, key=allocations.get)] += raw_target - sum(allocations.values())
        for complexity, count in allocations.items():
            shard_count = math.ceil(count / config.shard_size)
            remaining = count
            for shard in range(shard_count):
                size = min(config.shard_size, remaining)
                key = f"{lane.language}-{complexity}-{shard:06d}"
                payload = {
                    "language": lane.language,
                    "complexity": complexity,
                    "system_prompt": lane.system_prompts[complexity],
                    "count": size,
                    "seed": rng.randrange(2**63),
                }
                added += queue.add("instruction", key, payload)
                remaining -= size
    return added


def task_output(config: KoolbardiConfig, phase: str, shard_key: str) -> Path:
    return config.root / phase / f"{shard_key}.jsonl"


async def process_instruction(config: KoolbardiConfig, task: Task, pool: OpenAIClientPool) -> int:
    payload = task.payload
    native = load_native_template(config.tokenizer_path, payload["system_prompt"])
    async def generate(index: int) -> dict:
        # String prompts are used because they are portable across OpenAI-compatible servers.
        # The exact token IDs are retained in the receipt for server implementations that accept them.
        row_seed = payload["seed"] + index
        raw = await pool.completion(
            native.prefix, config.instruction_sampling, [native.turn_boundary], seed=row_seed
        )
        instruction = sanitize_instruction(raw, native.turn_boundary)
        row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{config.name}:{task.shard_key}:{index}:{row_seed}"))
        return {
            "id": row_id,
            "language_lane": payload["language"],
            "user_complexity_level": payload["complexity"],
            "magpie_system_prompt": payload["system_prompt"],
            "instruction": instruction,
            "generator": {
                "model": config.servers.model,
                "tokenizer_hash": native.tokenizer_hash,
                "template_hash": native.template_hash,
                "prefix_token_ids_sha256": sha256(json.dumps(native.prefix_token_ids).encode()).hexdigest(),
                "seed": row_seed,
                "sampling": config.instruction_sampling.model_dump(),
                "created_at": int(time.time()),
            },
        }

    rows = await gather_bounded(
        list(range(payload["count"])), generate, config.servers.concurrency_per_server * len(config.servers.base_urls)
    )
    failures = [row for row in rows if isinstance(row, BaseException)]
    if failures:
        raise RuntimeError(f"{len(failures)}/{len(rows)} instruction generations failed: {failures[0]!r}")
    return atomic_write_jsonl(task_output(config, "instruction", task.shard_key), rows)


async def process_response(config: KoolbardiConfig, task: Task, pool: OpenAIClientPool) -> int:
    source = Path(task.payload["source"])
    rows = list(read_jsonl(source))

    async def generate(row: dict) -> dict:
        response = await pool.chat(
            [{"role": "user", "content": row["instruction"]}], config.response_sampling
        )
        result = dict(row)
        result["messages"] = [
            {"role": "user", "content": row["instruction"]},
            {"role": "assistant", "content": response.strip()},
        ]
        result["response_generator"] = {
            "model": config.servers.model,
            "sampling": config.response_sampling.model_dump(),
            "created_at": int(time.time()),
        }
        return result

    results = await gather_bounded(
        rows, generate, config.servers.concurrency_per_server * len(config.servers.base_urls)
    )
    failures = [row for row in results if isinstance(row, BaseException)]
    if failures:
        raise RuntimeError(f"{len(failures)}/{len(results)} response generations failed: {failures[0]!r}")
    return atomic_write_jsonl(task_output(config, "response", task.shard_key), results)


async def process_audit(config: KoolbardiConfig, task: Task, pool: OpenAIClientPool) -> int:
    source = Path(task.payload["source"])
    rows = list(read_jsonl(source))
    sampling = SamplingConfig(temperature=config.audit.temperature, top_p=1.0, max_tokens=config.audit.max_tokens)

    async def audit(row: dict) -> dict:
        instruction = row["messages"][0]["content"]
        response = row["messages"][1]["content"]
        deterministic = validate_text_pair(instruction, response, row["language_lane"])
        result = dict(row)
        if not deterministic.accepted:
            result["audit"] = {"accepted": False, "reason": deterministic.reason, "deterministic": True}
            return result
        prompt = AUDIT_PROMPT.format(
            language=row["language_lane"], instruction=instruction, response=response
        )
        raw = await pool.chat([{"role": "user", "content": prompt}], sampling)
        judged = parse_json_object(raw)
        judged["accepted"] = bool(
            judged.get("accepted")
            and judged.get("coherent")
            and judged.get("safe")
            and judged.get("language") == row["language_lane"]
            and int(judged.get("instruction_quality", 0)) >= 4
            and int(judged.get("response_quality", 0)) >= 4
        )
        judged["deterministic_language_uncertain"] = deterministic.uncertain_language
        judged["model"] = config.audit.model or config.servers.model
        result["audit"] = judged
        return result

    results = await gather_bounded(
        rows, audit, config.servers.concurrency_per_server * len(config.servers.base_urls)
    )
    failures = [row for row in results if isinstance(row, BaseException)]
    if failures:
        raise RuntimeError(f"{len(failures)}/{len(results)} audits failed: {failures[0]!r}")
    return atomic_write_jsonl(task_output(config, "audit", task.shard_key), results)


PROCESSORS = {"instruction": process_instruction, "response": process_response, "audit": process_audit}


def advance(config: KoolbardiConfig, queue: TaskQueue) -> int:
    added = 0
    for source in sorted((config.root / "instruction").glob("*.jsonl")):
        added += queue.add("response", source.stem, {"source": str(source)})
    for source in sorted((config.root / "response").glob("*.jsonl")):
        added += queue.add("audit", source.stem, {"source": str(source)})
    return added


async def run_worker(config: KoolbardiConfig, queue: TaskQueue, phase: str, once: bool = False) -> int:
    pool = OpenAIClientPool(config.servers)
    processed = 0
    while task := queue.claim(phase):
        try:
            await PROCESSORS[phase](config, task, pool)
            queue.finish(task.id)
            processed += 1
        except BaseException as exc:
            queue.fail(task.id, repr(exc), config.servers.max_retries)
        if once:
            break
    return processed


def finalize(config: KoolbardiConfig, output: Path) -> dict:
    tokenizer = AutoTokenizer.from_pretrained(config.tokenizer_path, trust_remote_code=True)
    candidates: dict[str, list[tuple[int, dict]]] = defaultdict(list)
    seen: set[str] = set()
    rejected = 0
    for path in sorted((config.root / "audit").glob("*.jsonl")):
        for row in read_jsonl(path):
            if not row.get("audit", {}).get("accepted"):
                rejected += 1
                continue
            normalized = " ".join(row["messages"][0]["content"].casefold().split())
            digest = sha256(normalized.encode()).hexdigest()
            if digest in seen:
                rejected += 1
                continue
            seen.add(digest)
            rendered = tokenizer.apply_chat_template(row["messages"], tokenize=True, add_generation_prompt=False)
            if len(rendered) > config.max_sequence_tokens:
                rejected += 1
                continue
            row["rendered_token_count"] = len(rendered)
            row.pop("instruction", None)
            candidates[row["language_lane"]].append((len(rendered), row))

    lane_targets = {lane.language: lane.accepted_target for lane in config.lanes}
    final_rows: list[dict] = []
    report = {"config_hash": config.receipt_hash(), "rejected": rejected, "lanes": {}}
    for language, target in lane_targets.items():
        rows = sorted(candidates[language], key=lambda item: sha256(item[1]["id"].encode()).digest())[:target]
        final_rows.extend(row for _, row in rows)
        report["lanes"][language] = {"rows": len(rows), "tokens": sum(tokens for tokens, _ in rows), "target": target}
    final_rows.sort(key=lambda row: row["id"])
    atomic_write_jsonl(output, final_rows)
    report["rows"] = len(final_rows)
    report["tokens"] = sum(row["rendered_token_count"] for row in final_rows)
    report_path = output.with_suffix(output.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
