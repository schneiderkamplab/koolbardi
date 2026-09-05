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

from .client import OpenAIClientPool, gather_bounded
from .config import KoolbardiConfig, SamplingConfig
from .diversity import DiversityAssigner, diversity_condition
from .io import atomic_write_jsonl, read_jsonl
from .queue import Task, TaskQueue
from .template import (
    chat_token_count,
    load_native_template,
    sanitize_instruction,
)
from .validation import (
    validate_generation_completion,
    validate_instruction,
    validate_text_pair,
)


AUDIT_PROMPT = """Evaluate one supervised assistant turn in this synthetic training conversation. Return one JSON object only with:
accepted (boolean), language (da or en), instruction_quality (1-5), response_quality (1-5),
coherent (boolean), safe (boolean), category (short string), difficulty (short string), reason (short string).
Expected language: {language}
Turn: {turn_index}/{turn_count}
Conversation through the assistant turn:
{transcript}
"""

INSTRUCTION_AUDIT_PROMPT = """Evaluate this proposed user request before an answer is generated. Return one JSON object only with:
accepted (boolean), language (da or en), quality (1-5), topic_adherent (boolean),
mode_adherent (boolean), realistic (boolean), answerable (boolean), persona_coherent (boolean),
useful_for_training (boolean), safe (boolean), category (short string), reason (short string).
Reject requests that are incoherent, incomplete, meta-generation leakage, unanswerable as written,
unsafe training material, or do not meaningfully match the requested topic/mode/persona. Do not reject
minor stylistic imperfections when the request remains useful and answerable.
Expected language: {language}
Requested diversity controls: {diversity}
User request: {instruction}
"""

INSTRUCTION_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "accepted": {"type": "boolean"},
        "language": {"type": "string", "enum": ["da", "en"]},
        "quality": {"type": "integer", "minimum": 1, "maximum": 5},
        "topic_adherent": {"type": "boolean"},
        "mode_adherent": {"type": "boolean"},
        "realistic": {"type": "boolean"},
        "answerable": {"type": "boolean"},
        "persona_coherent": {"type": "boolean"},
        "useful_for_training": {"type": "boolean"},
        "safe": {"type": "boolean"},
        "category": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "accepted", "language", "quality", "topic_adherent", "mode_adherent",
        "realistic", "answerable", "persona_coherent", "useful_for_training",
        "safe", "category", "reason",
    ],
    "additionalProperties": False,
}

TURN_AUDIT_SCHEMA = {
    "type": "object",
    "properties": {
        "accepted": {"type": "boolean"},
        "language": {"type": "string", "enum": ["da", "en"]},
        "instruction_quality": {"type": "integer", "minimum": 1, "maximum": 5},
        "response_quality": {"type": "integer", "minimum": 1, "maximum": 5},
        "coherent": {"type": "boolean"},
        "safe": {"type": "boolean"},
        "category": {"type": "string"},
        "difficulty": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "accepted", "language", "instruction_quality", "response_quality",
        "coherent", "safe", "category", "difficulty", "reason",
    ],
    "additionalProperties": False,
}


def user_generation_prompt(
    language: str,
    generation_condition: str,
    desired_exchanges: int,
    minimum_tokens: int,
    maximum_tokens: int,
    messages: list[dict] | None = None,
    max_user_words: int | None = None,
) -> str:
    language_name = "Danish" if language == "da" else "English"
    if messages:
        context = json.dumps(messages, ensure_ascii=False)
        task = (
            "Continue the conversation below by writing only the next user message. "
            "It must respond naturally to the assistant's latest message, preserve context, "
            "and create a useful opportunity for the assistant to continue.\n"
            f"Conversation: {context}"
        )
    else:
        task = (
            "Write only the first user message of a realistic conversation. It must be a "
            "natural, self-contained request with enough substance for meaningful follow-up."
        )
    word_limit = (
        f" Keep this user message within about {max_user_words} words and finish it completely.\n"
        if max_user_words is not None else ""
    )
    return (
        f"You generate user turns for a high-quality conversational training dataset. {task}\n"
        f"Required language: {language_name}.\n"
        f"The complete conversation will have {desired_exchanges} user/assistant exchanges "
        f"and approximately {minimum_tokens}-{maximum_tokens} tokens.\n"
        f"{word_limit}"
        f"Additional requirements: {generation_condition}\n"
        "Return the user message only: no role label, analysis, quotation marks, alternatives, "
        "or commentary about this generation task."
    )


def generation_word_budget(language: str, token_budget: int, attempt: int = 0) -> int:
    base = 0.42 if language == "da" else 0.60
    return max(24, int(token_budget * base * (0.78**attempt)))


def assistant_generation_control(language: str, token_budget: int, attempt: int = 0) -> str:
    word_budget = generation_word_budget(language, token_budget, attempt)
    if language == "da":
        return (
            "Svar naturligt på dansk. Giv et direkte, selvstændigt og afsluttet svar. "
            f"Brug højst cirka {word_budget} ord. Prioritér at afslutte svaret frem for "
            "ekstra detaljer, og stop ikke midt i en sætning eller liste."
        )
    return (
        "Respond naturally in English with a direct, self-contained, complete answer. "
        f"Use at most about {word_budget} words. Prioritize completing the answer over "
        "extra detail, and do not stop midway through a sentence or list."
    )


def allocate_counts(total: int, shares: dict[str, float]) -> dict[str, int]:
    exact = {key: total * share for key, share in shares.items()}
    allocated = {key: math.floor(value) for key, value in exact.items()}
    remainder = total - sum(allocated.values())
    order = sorted(shares, key=lambda key: (exact[key] - allocated[key], key), reverse=True)
    for key in order[:remainder]:
        allocated[key] += 1
    return allocated


def length_condition(language: str, minimum: int, maximum: int, exchanges: int) -> str:
    if language == "da":
        return (
            f" Brugerens emne skal naturligt kunne bære {exchanges} meningsfulde "
            f"bruger/assistent-udvekslinger og en samlet samtale på cirka {minimum}-{maximum} tokens."
        )
    return (
        f" The user's topic must naturally support {exchanges} meaningful user/assistant "
        f"exchanges and a complete conversation of roughly {minimum}-{maximum} tokens."
    )


def initialize(config: KoolbardiConfig, queue: TaskQueue) -> int:
    tasks: list[tuple[str, str, dict]] = []
    rng = random.Random(config.seed)
    for lane in config.lanes:
        assignment_offset = 0
        raw_target = math.ceil(lane.accepted_target * lane.oversample_factor)
        complexity_counts = allocate_counts(raw_target, lane.complexity_shares)
        for complexity, complexity_count in complexity_counts.items():
            band_counts = allocate_counts(
                complexity_count,
                {name: band.share for name, band in config.length_bands.items()},
            )
            for band_name, count in band_counts.items():
                band = config.length_bands[band_name]
                shard_count = math.ceil(count / config.shard_size)
                remaining = count
                for shard in range(shard_count):
                    size = min(config.shard_size, remaining)
                    key = f"{lane.language}-{complexity}-{band_name}-{shard:06d}"
                    payload = {
                        "language": lane.language,
                        "complexity": complexity,
                        "length_band": band_name,
                        "length_band_config": band.model_dump(),
                        "system_prompt": lane.system_prompts[complexity],
                        "count": size,
                        "seed": rng.randrange(2**63),
                        "assignment_start": assignment_offset,
                    }
                    tasks.append(("instruction", key, payload))
                    assignment_offset += size
                    remaining -= size
    return queue.add_many(tasks)


def task_output(config: KoolbardiConfig, phase: str, shard_key: str) -> Path:
    return config.root / phase / f"{shard_key}.jsonl"


async def process_instruction(config: KoolbardiConfig, task: Task, pool: OpenAIClientPool) -> int:
    payload = task.payload
    band = payload["length_band_config"]
    native_cache = {}
    assigner = None
    if config.diversity is not None:
        assigner = DiversityAssigner(
            config.diversity.catalog_path,
            config.diversity.persona_store_path,
            payload["language"],
            config.seed,
        )

    async def generate(index: int) -> dict:
        # String prompts are used because they are portable across OpenAI-compatible servers.
        # The exact token IDs are retained in the receipt for server implementations that accept them.
        row_seed = payload["seed"] + index
        rng = random.Random(row_seed ^ 0x4B4F4F4C)
        desired_exchanges = rng.randint(band["min_exchanges"], band["max_exchanges"])
        assignment = (
            assigner.assignment(int(payload.get("assignment_start", 0)) + index)
            if assigner is not None else None
        )
        generation_condition = payload["system_prompt"] + length_condition(
            payload["language"], band["min_tokens"], band["max_tokens"], desired_exchanges
        )
        if assignment is not None:
            generation_condition += diversity_condition(payload["language"], assignment)
        native_key = payload["system_prompt"]
        native = native_cache.get(native_key)
        if native is None:
            native = load_native_template(config.tokenizer_path, payload["system_prompt"])
            native_cache[native_key] = native
        initial_word_budget = max(
            50,
            min(
                280,
                int(
                    max(
                        config.min_user_tokens,
                        band["max_tokens"]
                        - desired_exchanges * config.min_assistant_tokens
                        - (desired_exchanges - 1) * config.min_user_tokens,
                    )
                    * 0.30
                ),
            ),
        )
        generated = None
        generation_prompt = ""
        generation_attempt = 0
        for generation_attempt in range(3):
            generation_prompt = user_generation_prompt(
                payload["language"],
                generation_condition,
                desired_exchanges,
                band["min_tokens"],
                band["max_tokens"],
                max_user_words=max(50, int(initial_word_budget * (0.72**generation_attempt))),
            )
            generated = await pool.chat_result(
                [{"role": "user", "content": generation_prompt}],
                config.instruction_sampling,
                seed=row_seed + generation_attempt * 1_000_003,
            )
            if generated["finish_reason"] != "length":
                break
        if generated is None or generated["finish_reason"] == "length":
            raise ValueError("initial user generation exhausted its output budget")
        instruction = sanitize_instruction(generated["content"], native.turn_boundary)
        row_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{config.name}:{task.shard_key}:{index}:{row_seed}"))
        result = {
            "id": row_id,
            "language_lane": payload["language"],
            "user_complexity_level": payload["complexity"],
            "length_band": payload["length_band"],
            "length_band_config": band,
            "desired_exchanges": desired_exchanges,
            "magpie_system_prompt": generation_condition,
            "instruction": instruction,
            "generator": {
                "model": config.servers.model,
                "tokenizer_hash": native.tokenizer_hash,
                "template_hash": native.template_hash,
                "prefix_token_ids_sha256": sha256(json.dumps(native.prefix_token_ids).encode()).hexdigest(),
                "user_generation_method": "explicit_native_chat",
                "user_generation_prompt_sha256": sha256(generation_prompt.encode()).hexdigest(),
                "seed": row_seed,
                "sampling": config.instruction_sampling.model_dump(),
                "finish_reason": generated["finish_reason"],
                "generation_attempt": generation_attempt + 1,
                "created_at": int(time.time()),
            },
        }
        if assignment is not None:
            result["diversity"] = {
                "topic_id": assignment.topic["id"],
                "topic_domain": assignment.topic["domain"],
                "interaction_mode": assignment.mode["id"],
                "persona_source": assignment.persona["source"],
                "persona_source_id": assignment.persona["source_id"],
                "catalog": Path(config.diversity.catalog_path).name,
            }
        return result

    try:
        rows = await gather_bounded(
            list(range(payload["count"])), generate,
            config.servers.concurrency_per_server * len(config.servers.base_urls),
        )
    finally:
        if assigner is not None:
            assigner.close()
    failures = [row for row in rows if isinstance(row, BaseException)]
    if failures:
        failure_limit = max(8, math.ceil(len(rows) * 0.02))
        if len(failures) > failure_limit:
            raise RuntimeError(
                f"{len(failures)}/{len(rows)} instruction generations failed: {failures[0]!r}"
            )
        atomic_write_jsonl(
            config.root / "instruction_failures" / f"{task.shard_key}.jsonl",
            [
                {"index": index, "error": repr(row)}
                for index, row in enumerate(rows)
                if isinstance(row, BaseException)
            ],
        )
        rows = [row for row in rows if not isinstance(row, BaseException)]
    return atomic_write_jsonl(task_output(config, "instruction", task.shard_key), rows)


async def process_response(config: KoolbardiConfig, task: Task, pool: OpenAIClientPool) -> int:
    source = Path(task.payload["source"])
    rows = list(read_jsonl(source))
    if config.instruction_audit.enabled:
        rows = [row for row in rows if row.get("instruction_audit", {}).get("accepted")]
    tokenizer = AutoTokenizer.from_pretrained(config.tokenizer_path, trust_remote_code=True)

    async def generate(row: dict) -> dict:
        messages = [{"role": "user", "content": row["instruction"]}]
        band = row["length_band_config"]
        target_max = min(int(band["max_tokens"]), config.soft_sequence_tokens)
        desired_exchanges = int(row["desired_exchanges"])
        turn_usage: list[dict] = []
        user_turn_usage: list[dict] = []
        finish_reason = "desired_exchanges"

        for exchange in range(desired_exchanges):
            if exchange > 0:
                current_tokens = chat_token_count(tokenizer, messages)
                remaining_exchanges = desired_exchanges - exchange
                future_after_this = remaining_exchanges - 1
                reserved = config.min_assistant_tokens + future_after_this * (
                    config.min_user_tokens + config.min_assistant_tokens + 12
                )
                fair_user_budget = max(
                    config.min_user_tokens,
                    (target_max - current_tokens) // max(1, remaining_exchanges * 3),
                )
                user_budget = min(
                    config.instruction_sampling.max_tokens,
                    target_max - current_tokens - reserved,
                    fair_user_budget,
                )
                if user_budget < config.min_user_tokens:
                    finish_reason = "insufficient_user_budget"
                    break
                user_sampling = config.instruction_sampling.model_copy(
                    update={"max_tokens": int(user_budget)}
                )
                raw_user = None
                user_result = None
                for user_attempt in range(config.servers.max_retries):
                    generation_prompt = user_generation_prompt(
                        row["language_lane"],
                        row["magpie_system_prompt"],
                        desired_exchanges,
                        band["min_tokens"],
                        band["max_tokens"],
                        messages,
                        max_user_words=generation_word_budget(
                            row["language_lane"], int(user_budget), user_attempt
                        ),
                    )
                    user_result = await pool.chat_result(
                        [{"role": "user", "content": generation_prompt}],
                        user_sampling,
                        seed=(
                            row["generator"]["seed"] + exchange * 2
                            + user_attempt * 1_000_003 + task.attempts * 10_000_019
                        ),
                    )
                    raw_user = sanitize_instruction(user_result["content"], "<turn|>")
                    if validate_generation_completion(
                        raw_user, user_result["finish_reason"]
                    ).accepted:
                        break
                else:
                    raise ValueError("follow-up user generation did not finish completely")
                messages.append(
                    {"role": "user", "content": raw_user}
                )
                user_turn_usage.append({
                    "exchange": exchange + 1,
                    "max_output_tokens": int(user_budget),
                    "actual_output_tokens": len(tokenizer.encode(raw_user, add_special_tokens=False)),
                    "finish_reason": user_result["finish_reason"],
                    "generation_attempt": user_attempt + 1,
                })

            prompt_tokens = chat_token_count(tokenizer, messages, add_generation_prompt=True)
            future_exchanges = desired_exchanges - exchange - 1
            reserved_for_users = future_exchanges * (config.min_user_tokens + 12)
            remaining_assistant_turns = future_exchanges + 1
            fair_assistant_budget = max(
                config.min_assistant_tokens,
                (target_max - prompt_tokens - reserved_for_users)
                // remaining_assistant_turns,
            )
            assistant_budget = min(
                config.response_sampling.max_tokens,
                target_max - prompt_tokens - reserved_for_users - 4,
                config.max_sequence_tokens - prompt_tokens - 4,
                fair_assistant_budget,
            )
            if assistant_budget < config.min_assistant_tokens:
                finish_reason = "insufficient_assistant_budget"
                if messages[-1]["role"] == "user" and exchange > 0:
                    messages.pop()
                break
            response_sampling = config.response_sampling.model_copy(
                update={"max_tokens": int(assistant_budget)}
            )
            response = None
            response_result = None
            for response_attempt in range(config.servers.max_retries):
                response_messages = [
                    {
                        "role": "system",
                        "content": assistant_generation_control(
                            row["language_lane"], int(assistant_budget), response_attempt
                        ),
                    },
                    *messages,
                ]
                response_result = await pool.chat_result(
                    response_messages,
                    response_sampling,
                    seed=(
                        row["generator"]["seed"] + exchange * 2 + 1
                        + response_attempt * 1_000_003 + task.attempts * 10_000_019
                    ),
                )
                response = response_result["content"].strip()
                if validate_generation_completion(
                    response, response_result["finish_reason"]
                ).accepted:
                    break
            else:
                raise ValueError("assistant generation did not finish completely")
            messages.append({"role": "assistant", "content": response})
            turn_usage.append(
                {
                    "exchange": exchange + 1,
                    "prompt_tokens": prompt_tokens,
                    "max_output_tokens": int(assistant_budget),
                    "actual_output_tokens": len(tokenizer.encode(response, add_special_tokens=False)),
                    "finish_reason": response_result["finish_reason"],
                    "generation_attempt": response_attempt + 1,
                    "rendered_tokens": chat_token_count(tokenizer, messages),
                }
            )

        rendered_tokens = chat_token_count(tokenizer, messages)
        actual_exchanges = sum(message["role"] == "assistant" for message in messages)
        result = dict(row)
        result["messages"] = messages
        result["rendered_token_count"] = rendered_tokens
        result["actual_exchanges"] = actual_exchanges
        result["length_valid"] = (
            int(band["min_tokens"]) <= rendered_tokens <= int(band["max_tokens"])
            and rendered_tokens <= config.max_sequence_tokens
            and actual_exchanges == desired_exchanges
        )
        result["finish_reason"] = finish_reason
        result["turn_token_usage"] = turn_usage
        result["user_turn_token_usage"] = user_turn_usage
        result["response_generator"] = {
            "model": config.servers.model,
            "sampling": config.response_sampling.model_dump(),
            "generation_only_completeness_control": True,
            "created_at": int(time.time()),
        }
        return result

    results = await gather_bounded(
        rows, generate, config.servers.concurrency_per_server * len(config.servers.base_urls)
    )
    failures = [row for row in results if isinstance(row, BaseException)]
    if failures:
        if len(failures) == len(results):
            raise RuntimeError(
                f"all {len(results)} response generations failed: {failures[0]!r}"
            )
        atomic_write_jsonl(
            config.root / "response_failures" / f"{task.shard_key}.jsonl",
            [
                {"index": index, "error": repr(result)}
                for index, result in enumerate(results)
                if isinstance(result, BaseException)
            ],
        )
        results = [result for result in results if not isinstance(result, BaseException)]
    return atomic_write_jsonl(task_output(config, "response", task.shard_key), results)


async def process_instruction_audit(
    config: KoolbardiConfig, task: Task, pool: OpenAIClientPool
) -> int:
    source = Path(task.payload["source"])
    rows = list(read_jsonl(source))
    sampling = SamplingConfig(
        temperature=config.instruction_audit.temperature,
        top_p=1.0,
        max_tokens=config.instruction_audit.max_tokens,
    )

    async def audit_instruction(row: dict) -> dict:
        result = dict(row)
        deterministic = validate_instruction(row.get("instruction", ""), row["language_lane"])
        if not deterministic.accepted:
            result["instruction_audit"] = {
                "accepted": False,
                "reason": deterministic.reason,
                "deterministic": True,
                "detected_language": deterministic.detected_language,
            }
            return result

        prompt = INSTRUCTION_AUDIT_PROMPT.format(
            language=row["language_lane"],
            diversity=row.get(
                "magpie_system_prompt",
                json.dumps(row.get("diversity", {}), ensure_ascii=False, sort_keys=True),
            ),
            instruction=row["instruction"],
        )
        try:
            judged = await pool.chat_json(
                [{"role": "user", "content": prompt}],
                sampling,
                INSTRUCTION_AUDIT_SCHEMA,
                seed=row["generator"]["seed"] + 7_000_001,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            result["instruction_audit"] = {
                "accepted": False,
                "reason": "instruction judge structured generation failed",
                "deterministic": False,
                "audit_error": repr(exc),
                "model": config.instruction_audit.model or config.servers.model,
            }
            return result

        required = (
            "topic_adherent", "mode_adherent", "realistic", "answerable",
            "persona_coherent", "useful_for_training", "safe",
        )
        judged["accepted"] = bool(
            judged.get("accepted")
            and judged.get("language") == row["language_lane"]
            and int(judged.get("quality", 0)) >= config.instruction_audit.minimum_quality
            and all(judged.get(field) for field in required)
        )
        judged["deterministic_language_uncertain"] = deterministic.uncertain_language
        judged["model"] = config.instruction_audit.model or config.servers.model
        result["instruction_audit"] = judged
        return result

    results = await gather_bounded(
        rows,
        audit_instruction,
        config.servers.concurrency_per_server * len(config.servers.base_urls),
    )
    failures = [row for row in results if isinstance(row, BaseException)]
    if failures:
        raise RuntimeError(
            f"{len(failures)}/{len(results)} instruction audits failed: {failures[0]!r}"
        )
    return atomic_write_jsonl(task_output(config, "instruction_audit", task.shard_key), results)


async def process_audit(config: KoolbardiConfig, task: Task, pool: OpenAIClientPool) -> int:
    source = Path(task.payload["source"])
    rows = list(read_jsonl(source))
    sampling = SamplingConfig(temperature=config.audit.temperature, top_p=1.0, max_tokens=config.audit.max_tokens)

    async def audit(row: dict) -> dict:
        result = dict(row)
        if not row.get("length_valid"):
            result["audit"] = {"accepted": False, "reason": "length or exchange target missed", "deterministic": True}
            return result
        turn_audits = []
        messages = row["messages"]
        assistant_positions = [i for i, message in enumerate(messages) if message["role"] == "assistant"]
        for turn_number, position in enumerate(assistant_positions, start=1):
            instruction = messages[position - 1]["content"]
            response = messages[position]["content"]
            usage = row.get("turn_token_usage", [])
            if turn_number > len(usage) or usage[turn_number - 1].get("finish_reason") != "stop":
                turn_audits.append({
                    "accepted": False,
                    "reason": "assistant generation did not record finish_reason=stop",
                    "deterministic": True,
                })
                continue
            completion = validate_generation_completion(response, "stop")
            if not completion.accepted:
                turn_audits.append({
                    "accepted": False,
                    "reason": completion.reason,
                    "deterministic": True,
                })
                continue
            deterministic = validate_text_pair(instruction, response, row["language_lane"])
            if not deterministic.accepted:
                turn_audits.append({"accepted": False, "reason": deterministic.reason, "deterministic": True})
                continue
            transcript = json.dumps(messages[: position + 1], ensure_ascii=False)
            prompt = AUDIT_PROMPT.format(
                language=row["language_lane"],
                turn_index=turn_number,
                turn_count=len(assistant_positions),
                transcript=transcript,
            )
            judged = await pool.chat_json(
                [{"role": "user", "content": prompt}],
                sampling,
                TURN_AUDIT_SCHEMA,
                seed=row["generator"]["seed"] + turn_number,
            )
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
            turn_audits.append(judged)
        result["turn_audits"] = turn_audits
        result["audit"] = {
            "accepted": bool(turn_audits) and all(turn.get("accepted") for turn in turn_audits),
            "turns": len(turn_audits),
            "model": config.audit.model or config.servers.model,
        }
        return result

    results = await gather_bounded(
        rows, audit, config.servers.concurrency_per_server * len(config.servers.base_urls)
    )
    failures = [result for result in results if isinstance(result, BaseException)]
    retryable = [
        failure
        for failure in failures
        if "structured generation did not finish: 'length'" not in str(failure)
    ]
    if retryable:
        raise RuntimeError(f"{len(failures)}/{len(results)} audits failed: {retryable[0]!r}")
    for index, result in enumerate(results):
        if not isinstance(result, BaseException):
            continue
        rejected = dict(rows[index])
        rejected["turn_audits"] = []
        rejected["audit"] = {
            "accepted": False,
            "turns": 0,
            "model": config.audit.model or config.servers.model,
            "request_failed": True,
            "reason": "structured judge output exceeded its maximum length",
        }
        results[index] = rejected
    return atomic_write_jsonl(task_output(config, "audit", task.shard_key), results)


PROCESSORS = {
    "instruction": process_instruction,
    "instruction_audit": process_instruction_audit,
    "response": process_response,
    "audit": process_audit,
}


def advance(config: KoolbardiConfig, queue: TaskQueue) -> int:
    tasks: list[tuple[str, str, dict]] = []
    instruction_sources = list((config.root / "instruction").glob("*.jsonl"))
    if config.diversity is not None:
        instruction_sources.sort(key=lambda path: sha256(path.stem.encode()).digest())
    else:
        instruction_sources.sort()
    for source in instruction_sources:
        phase = "instruction_audit" if config.instruction_audit.enabled else "response"
        tasks.append((phase, source.stem, {"source": str(source)}))
    if config.instruction_audit.enabled:
        for source in sorted((config.root / "instruction_audit").glob("*.jsonl")):
            tasks.append(("response", source.stem, {"source": str(source)}))
    for source in sorted((config.root / "response").glob("*.jsonl")):
        tasks.append(("audit", source.stem, {"source": str(source)}))
    return queue.add_many(tasks)


async def run_worker(config: KoolbardiConfig, queue: TaskQueue, phase: str, once: bool = False) -> int:
    pool = OpenAIClientPool(config.servers)
    processed = 0
    try:
        while task := queue.claim(phase):
            try:
                await PROCESSORS[phase](config, task, pool)
                queue.finish(task.id)
                processed += 1
            except BaseException as exc:
                queue.fail(task.id, repr(exc), config.servers.max_retries)
            if once:
                break
    finally:
        await pool.aclose()
    return processed


def finalize(config: KoolbardiConfig, output: Path) -> dict:
    tokenizer = AutoTokenizer.from_pretrained(config.tokenizer_path, trust_remote_code=True)
    candidates: dict[tuple[str, str, str], list[tuple[int, dict]]] = defaultdict(list)
    seen: set[str] = set()
    rejected = 0

    def add_candidates(rows: list[dict]) -> None:
        nonlocal rejected
        if not rows:
            return
        encoded = tokenizer.apply_chat_template(
            [row["messages"] for row in rows],
            tokenize=True,
            add_generation_prompt=False,
            return_dict=False,
        )
        if len(encoded) != len(rows):
            raise RuntimeError("batched chat-template output count mismatch")
        for row, token_ids in zip(rows, encoded, strict=True):
            rendered_tokens = len(token_ids)
            stored_tokens = row.get("rendered_token_count")
            if stored_tokens is not None and stored_tokens != rendered_tokens:
                raise RuntimeError(
                    f"{row.get('id')}: stored/recomputed token mismatch "
                    f"({stored_tokens} != {rendered_tokens})"
                )
            band_name = row["length_band"]
            band = config.length_bands[band_name]
            if not (band.min_tokens <= rendered_tokens <= band.max_tokens <= config.max_sequence_tokens):
                rejected += 1
                continue
            row["rendered_token_count"] = rendered_tokens
            row.pop("instruction", None)
            candidates[(
                row["language_lane"], row["user_complexity_level"], band_name
            )].append((rendered_tokens, row))

    batch: list[dict] = []
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
            batch.append(row)
            if len(batch) == 256:
                add_candidates(batch)
                batch = []
    add_candidates(batch)

    lanes = {lane.language: lane for lane in config.lanes}
    lane_targets = (
        config.final_selection.targets
        if config.final_selection is not None
        else {lane.language: lane.accepted_target for lane in config.lanes}
    )
    final_rows: list[dict] = []
    report = {"config_hash": config.receipt_hash(), "rejected": rejected, "lanes": {}}
    if config.instruction_audit.enabled:
        dimensions = {
            "language": "language_lane",
            "topic": "diversity.topic_id",
            "topic_domain": "diversity.topic_domain",
            "interaction_mode": "diversity.interaction_mode",
            "persona_source": "diversity.persona_source",
            "complexity": "user_complexity_level",
            "length_band": "length_band",
        }
        gate_counts: dict[str, dict[str, dict[str, int]]] = {
            dimension: defaultdict(lambda: {"accepted": 0, "rejected": 0})
            for dimension in dimensions
        }

        def nested_value(row: dict, dotted_key: str):
            value = row
            for key in dotted_key.split("."):
                value = value.get(key, {}) if isinstance(value, dict) else {}
            return value if value not in ({}, None, "") else "unknown"

        for path in sorted((config.root / "instruction_audit").glob("*.jsonl")):
            for row in read_jsonl(path):
                outcome = "accepted" if row.get("instruction_audit", {}).get("accepted") else "rejected"
                for dimension, dotted_key in dimensions.items():
                    gate_counts[dimension][str(nested_value(row, dotted_key))][outcome] += 1
        report["instruction_audit"] = {
            dimension: dict(sorted(values.items()))
            for dimension, values in gate_counts.items()
        }
    for language, target in lane_targets.items():
        lane_rows: list[tuple[int, dict]] = []
        band_report: dict[str, dict] = defaultdict(
            lambda: {"available": 0, "rows": 0, "tokens": 0, "target": 0, "surplus": 0, "shortfall": 0}
        )
        cell_report = {}
        complexity_quotas = allocate_counts(target, lanes[language].complexity_shares)
        for complexity, complexity_quota in complexity_quotas.items():
            band_quotas = allocate_counts(
                complexity_quota,
                {name: band.share for name, band in config.length_bands.items()},
            )
            for band_name, quota in band_quotas.items():
                available = sorted(
                    candidates[(language, complexity, band_name)],
                    key=lambda item: sha256(item[1]["id"].encode()).digest(),
                )
                rows = (
                    available
                    if config.final_selection is None or config.final_selection.retain_surplus
                    else available[:quota]
                )
                lane_rows.extend(rows)
                cell_report[f"{complexity}/{band_name}"] = {
                    "available": len(available),
                    "rows": len(rows),
                    "tokens": sum(tokens for tokens, _ in rows),
                    "target": quota,
                    "surplus": max(0, len(available) - quota),
                    "shortfall": max(0, quota - len(rows)),
                }
                band = band_report[band_name]
                band["available"] += len(available)
                band["rows"] += len(rows)
                band["tokens"] += sum(tokens for tokens, _ in rows)
                band["target"] += quota
                band["surplus"] += max(0, len(available) - quota)
                band["shortfall"] += max(0, quota - len(rows))
        final_rows.extend(row for _, row in lane_rows)
        report["lanes"][language] = {
            "rows": len(lane_rows),
            "tokens": sum(tokens for tokens, _ in lane_rows),
            "target": target,
            "surplus": max(0, len(lane_rows) - target),
            "shortfall": max(0, target - len(lane_rows)),
            "bands": dict(band_report),
            "cells": cell_report,
        }
    if (
        config.final_selection is not None
        and config.final_selection.require_targets
        and any(
            cell["shortfall"]
            for lane in report["lanes"].values()
            for cell in lane["cells"].values()
        )
    ):
        raise RuntimeError("balanced final-selection targets are not yet satisfied")
    final_rows.sort(key=lambda row: row["id"])
    atomic_write_jsonl(output, final_rows)
    report["rows"] = len(final_rows)
    report["tokens"] = sum(row["rendered_token_count"] for row in final_rows)
    report_path = output.with_suffix(output.suffix + ".report.json")
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report
