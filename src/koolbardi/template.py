from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from transformers import AutoTokenizer


@dataclass(frozen=True)
class NativeTemplate:
    prefix: str
    prefix_token_ids: list[int]
    turn_boundary: str
    turn_boundary_token_ids: list[int]
    tokenizer_hash: str
    template_hash: str


def load_native_template(tokenizer_path: str, system_prompt: str) -> NativeTemplate:
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_path, trust_remote_code=True)
    sentinel = "KOOLBARDI_SENTINEL_7f595e89"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": sentinel},
    ]
    rendered = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    if rendered.count(sentinel) != 1:
        raise ValueError("tokenizer template did not preserve the unique user sentinel")
    prefix, suffix = rendered.split(sentinel)
    if not suffix:
        raise ValueError("cannot derive native user-turn boundary from tokenizer template")
    boundary = suffix.split("\n", 1)[0]
    if not boundary.strip():
        boundary = suffix
    prefix_ids = tokenizer.encode(prefix, add_special_tokens=False)
    boundary_ids = tokenizer.encode(boundary, add_special_tokens=False)
    template = tokenizer.chat_template or ""
    tokenizer_files = sorted(Path(tokenizer_path).glob("*token*")) if Path(tokenizer_path).exists() else []
    digest = sha256()
    for path in tokenizer_files:
        if path.is_file():
            digest.update(path.name.encode())
            digest.update(path.read_bytes())
    return NativeTemplate(
        prefix=prefix,
        prefix_token_ids=prefix_ids,
        turn_boundary=boundary,
        turn_boundary_token_ids=boundary_ids,
        tokenizer_hash=digest.hexdigest(),
        template_hash=sha256(template.encode()).hexdigest(),
    )


def sanitize_instruction(text: str, boundary: str) -> str:
    if boundary in text:
        text = text.split(boundary, 1)[0]
    text = text.strip()
    forbidden = ("<|turn>", "<turn|>", "<|im_start|>", "<|im_end|>")
    if not text or any(token in text for token in forbidden):
        raise ValueError("empty instruction or leaked chat control token")
    return text

