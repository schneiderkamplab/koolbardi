import json

from koolbardi.pipeline import (
    allocate_counts,
    assistant_generation_control,
    finalize,
    generation_word_budget,
    user_generation_prompt,
)
from koolbardi.config import KoolbardiConfig
from koolbardi.pipeline import advance
from koolbardi.queue import TaskQueue


def test_allocate_counts_is_exact_and_deterministic():
    counts = allocate_counts(17, {"short": 0.2, "medium": 0.35, "long": 0.35, "near": 0.1})
    assert sum(counts.values()) == 17
    assert counts == allocate_counts(17, {"short": 0.2, "medium": 0.35, "long": 0.35, "near": 0.1})


def test_followup_generation_is_meta_context_not_training_messages():
    messages = [
        {"role": "user", "content": "How do I grow basil?"},
        {"role": "assistant", "content": "Give it light and regular water."},
    ]
    prompt = user_generation_prompt("en", "Use natural English.", 3, 512, 1024, messages)
    assert "next user message" in prompt
    assert '"role": "assistant"' in prompt
    assert "Return the user message only" in prompt


def test_initial_generation_can_be_given_a_completion_safe_word_limit():
    prompt = user_generation_prompt("en", "Use natural English.", 2, 512, 1023, max_user_words=120)
    assert "within about 120 words" in prompt
    assert "finish it completely" in prompt


def test_assistant_control_is_budgeted_and_language_specific():
    assert "84 ord" in assistant_generation_control("da", 200)
    assert "120 words" in assistant_generation_control("en", 200)
    assert generation_word_budget("da", 200, 1) < generation_word_budget("da", 200, 0)


def test_advance_routes_through_enabled_instruction_audit(tmp_path):
    root = tmp_path / "campaign"
    instruction = root / "instruction"
    instruction.mkdir(parents=True)
    source = instruction / "en-general-default-000000.jsonl"
    source.write_text('{"instruction":"Explain gravity clearly."}\n', encoding="utf-8")
    config = KoolbardiConfig.model_validate({
        "name": "test",
        "tokenizer_path": "unused",
        "output_dir": str(root),
        "lanes": [{
            "language": "en", "accepted_target": 1,
            "system_prompts": {"general": "English"},
            "complexity_shares": {"general": 1.0},
        }],
        "servers": {"base_urls": ["http://localhost:1"], "model": "test"},
        "instruction_audit": {"enabled": True},
    })
    queue = TaskQueue(root / "queue.sqlite3")
    assert advance(config, queue) == 1
    assert queue.count("instruction_audit", "pending") == 1
    assert queue.count("response", "pending") == 0


def test_finalize_retains_accepted_rows_above_target(tmp_path, monkeypatch):
    class FakeTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            if messages and isinstance(messages[0], list):
                return [
                    list(range(sum(len(message["content"]) for message in conversation)))
                    for conversation in messages
                ]
            return list(range(sum(len(message["content"]) for message in messages)))

    root = tmp_path / "campaign"
    audit_dir = root / "audit"
    audit_dir.mkdir(parents=True)
    rows = [
        {
            "id": f"row-{index}",
            "language_lane": "en",
            "user_complexity_level": "general",
            "length_band": "default",
            "messages": [
                {"role": "user", "content": f"Question {index}"},
                {"role": "assistant", "content": "A complete useful answer."},
            ],
            "audit": {"accepted": True},
        }
        for index in range(2)
    ]
    (audit_dir / "part.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    config = KoolbardiConfig.model_validate({
        "name": "test",
        "tokenizer_path": "unused",
        "output_dir": str(root),
        "lanes": [{
            "language": "en", "accepted_target": 1,
            "system_prompts": {"general": "English"},
            "complexity_shares": {"general": 1.0},
        }],
        "servers": {"base_urls": ["http://localhost:1"], "model": "test"},
        "final_selection": {"targets": {"en": 1}, "retain_surplus": True},
    })
    monkeypatch.setattr(
        "koolbardi.pipeline.AutoTokenizer.from_pretrained", lambda *args, **kwargs: FakeTokenizer()
    )
    output = root / "final.jsonl"
    report = finalize(config, output)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2
    assert report["lanes"]["en"]["target"] == 1
    assert report["lanes"]["en"]["rows"] == 2
    assert report["lanes"]["en"]["surplus"] == 1


def test_finalize_exact_selection_balances_complexity_and_length(tmp_path, monkeypatch):
    class FakeTokenizer:
        def apply_chat_template(self, messages, **kwargs):
            if messages and isinstance(messages[0], list):
                return [
                    list(range(sum(len(message["content"]) for message in conversation)))
                    for conversation in messages
                ]
            return list(range(sum(len(message["content"]) for message in messages)))

    root = tmp_path / "campaign"
    audit_dir = root / "audit"
    audit_dir.mkdir(parents=True)
    rows = []
    for complexity in ("accessible", "general"):
        for index in range(4):
            rows.append({
                "id": f"{complexity}-{index}",
                "language_lane": "en",
                "user_complexity_level": complexity,
                "length_band": "default",
                "messages": [
                    {"role": "user", "content": f"Question {complexity} {index}"},
                    {"role": "assistant", "content": "A complete useful answer."},
                ],
                "audit": {"accepted": True},
            })
    (audit_dir / "part.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    config = KoolbardiConfig.model_validate({
        "name": "test", "tokenizer_path": "unused", "output_dir": str(root),
        "lanes": [{
            "language": "en", "accepted_target": 8,
            "system_prompts": {"accessible": "Simple", "general": "General"},
            "complexity_shares": {"accessible": 0.5, "general": 0.5},
        }],
        "servers": {"base_urls": ["http://localhost:1"], "model": "test"},
        "final_selection": {"targets": {"en": 4}},
    })
    monkeypatch.setattr(
        "koolbardi.pipeline.AutoTokenizer.from_pretrained", lambda *args, **kwargs: FakeTokenizer()
    )
    output = root / "final.jsonl"
    report = finalize(config, output)
    selected = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(selected) == 4
    assert sum(row["user_complexity_level"] == "accessible" for row in selected) == 2
    assert report["lanes"]["en"]["rows"] == 4
