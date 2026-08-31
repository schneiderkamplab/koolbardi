from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator


class SamplingConfig(BaseModel):
    temperature: float = 1.0
    top_p: float = 1.0
    max_tokens: int = 512


class LaneConfig(BaseModel):
    language: Literal["da", "en"]
    accepted_target: int
    oversample_factor: float = 1.5
    system_prompts: dict[str, str]
    complexity_shares: dict[str, float]

    @model_validator(mode="after")
    def validate_complexities(self) -> "LaneConfig":
        if set(self.system_prompts) != set(self.complexity_shares):
            raise ValueError("system_prompts and complexity_shares must have identical keys")
        if abs(sum(self.complexity_shares.values()) - 1.0) > 1e-8:
            raise ValueError("complexity_shares must sum to 1")
        return self


class ServerConfig(BaseModel):
    base_urls: list[str]
    model: str
    api_key: str = "EMPTY"
    concurrency_per_server: int = 64
    timeout_seconds: float = 600.0
    max_retries: int = 4


class AuditConfig(BaseModel):
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 384


class KoolbardiConfig(BaseModel):
    name: str
    seed: int = 0
    tokenizer_path: str
    output_dir: str
    shard_size: int = 1000
    max_sequence_tokens: int = 4096
    lanes: list[LaneConfig]
    servers: ServerConfig
    instruction_sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    response_sampling: SamplingConfig = Field(
        default_factory=lambda: SamplingConfig(temperature=0.2, max_tokens=3072)
    )
    audit: AuditConfig = Field(default_factory=AuditConfig)

    @model_validator(mode="after")
    def validate_lanes(self) -> "KoolbardiConfig":
        languages = [lane.language for lane in self.lanes]
        if len(languages) != len(set(languages)):
            raise ValueError("language lanes must be unique")
        return self

    @property
    def root(self) -> Path:
        return Path(self.output_dir)

    def receipt_hash(self) -> str:
        return sha256(self.model_dump_json().encode()).hexdigest()


def load_config(path: Path) -> KoolbardiConfig:
    with path.open(encoding="utf-8") as handle:
        return KoolbardiConfig.model_validate(yaml.safe_load(handle))

