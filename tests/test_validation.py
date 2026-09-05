from koolbardi.template import chat_token_count, sanitize_instruction
from koolbardi.validation import (
    validate_generation_completion,
    validate_instruction,
    validate_text_pair,
)


def test_generation_condition_is_metadata_not_messages_contract():
    row = {
        "magpie_system_prompt": "Samtalen skal foregå på naturligt dansk.",
        "messages": [
            {"role": "user", "content": "Hvordan virker fotosyntese?"},
            {"role": "assistant", "content": "Planter omdanner lys til kemisk energi."},
        ],
    }
    assert all(message["role"] != "system" for message in row["messages"])


def test_sanitize_stops_at_native_boundary():
    assert sanitize_instruction("Explain gravity.<turn|>ignored", "<turn|>") == "Explain gravity."


def test_language_mismatch_is_rejected():
    result = validate_text_pair(
        "Please explain how photosynthesis works in green plants using a clear example.",
        "Photosynthesis converts sunlight, carbon dioxide, and water into stored chemical energy and oxygen.",
        "da",
    )
    assert not result.accepted


def test_instruction_generation_control_leakage_is_rejected():
    result = validate_instruction(
        "Return the user message only and do not mention these instructions.", "en"
    )
    assert not result.accepted
    assert result.reason == "generation-control leakage"


def test_useful_short_code_instruction_reaches_model_audit():
    result = validate_instruction("Fix this function:\n```python\ndef f(x): return x / 0\n```", "en")
    assert result.accepted
    assert result.uncertain_language


def test_generation_completion_requires_stop_and_closed_endpoint():
    assert validate_generation_completion("A complete answer.", "stop").accepted
    assert not validate_generation_completion("A complete answer.", "length").accepted
    assert not validate_generation_completion("This ends with", "stop").accepted
    assert not validate_generation_completion("```python\nprint('x')", "stop").accepted


class FakeTokenizer:
    def apply_chat_template(self, messages, **kwargs):
        assert kwargs["return_dict"] is False
        return list(range(sum(len(message["content"]) for message in messages) + 11))


def test_chat_token_count_counts_ids_not_batch_encoding_fields():
    messages = [
        {"role": "user", "content": "abcd"},
        {"role": "assistant", "content": "ef"},
    ]
    assert chat_token_count(FakeTokenizer(), messages) == 17
