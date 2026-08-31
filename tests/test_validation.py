from koolbardi.template import sanitize_instruction
from koolbardi.validation import validate_text_pair


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
