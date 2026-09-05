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


class LengthBandConfig(BaseModel):
    min_tokens: int
    max_tokens: int
    share: float
    min_exchanges: int = 1
    max_exchanges: int = 1

    @model_validator(mode="after")
    def validate_band(self) -> "LengthBandConfig":
        if self.min_tokens < 1 or self.max_tokens < self.min_tokens:
            raise ValueError("length-band token bounds are invalid")
        if self.min_exchanges < 1 or self.max_exchanges < self.min_exchanges:
            raise ValueError("length-band exchange bounds are invalid")
        if self.share <= 0:
            raise ValueError("length-band share must be positive")
        return self


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
    concurrency_per_server: int = 448
    timeout_seconds: float = 600.0
    max_retries: int = 4

    @model_validator(mode="after")
    def validate_server_limits(self) -> "ServerConfig":
        if not self.base_urls:
            raise ValueError("at least one server URL is required")
        if self.concurrency_per_server < 1:
            raise ValueError("concurrency_per_server must be positive")
        return self


class AuditConfig(BaseModel):
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 384


class InstructionAuditConfig(AuditConfig):
    enabled: bool = False
    minimum_quality: int = 4


class PhaseWorkersConfig(BaseModel):
    instruction: int = 4
    instruction_audit: int = 4
    response: int = 4
    audit: int = 4

    @model_validator(mode="after")
    def validate_workers(self) -> "PhaseWorkersConfig":
        if min(self.instruction, self.instruction_audit, self.response, self.audit) < 1:
            raise ValueError("phase worker counts must be positive")
        return self


class DiversityConfig(BaseModel):
    catalog_path: str
    persona_store_path: str


class FinalSelectionConfig(BaseModel):
    targets: dict[Literal["da", "en"], int]
    audit_buffer: float = 1.05
    response_retention_fallback: float = 0.97
    require_targets: bool = True
    retain_surplus: bool = False

    @model_validator(mode="after")
    def validate_selection(self) -> "FinalSelectionConfig":
        if not self.targets or min(self.targets.values()) < 1:
            raise ValueError("final-selection targets must be positive")
        if self.audit_buffer < 1.0:
            raise ValueError("audit_buffer must be at least 1")
        if not 0 < self.response_retention_fallback <= 1:
            raise ValueError("response_retention_fallback must be in (0, 1]")
        return self


class KoolbardiConfig(BaseModel):
    name: str
    seed: int = 0
    tokenizer_path: str
    output_dir: str
    shard_size: int = 2048
    max_sequence_tokens: int = 4096
    soft_sequence_tokens: int = 3968
    min_user_tokens: int = 64
    min_assistant_tokens: int = 192
    length_bands: dict[str, LengthBandConfig] = Field(
        default_factory=lambda: {
            "default": LengthBandConfig(
                min_tokens=1, max_tokens=3968, share=1.0,
                min_exchanges=1, max_exchanges=1,
            )
        }
    )
    lanes: list[LaneConfig]
    servers: ServerConfig
    instruction_sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    response_sampling: SamplingConfig = Field(
        default_factory=lambda: SamplingConfig(temperature=0.2, max_tokens=3072)
    )
    instruction_audit: InstructionAuditConfig = Field(default_factory=InstructionAuditConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    phase_workers: PhaseWorkersConfig = Field(default_factory=PhaseWorkersConfig)
    diversity: DiversityConfig | None = None
    final_selection: FinalSelectionConfig | None = None

    @model_validator(mode="after")
    def validate_lanes(self) -> "KoolbardiConfig":
        languages = [lane.language for lane in self.lanes]
        if len(languages) != len(set(languages)):
            raise ValueError("language lanes must be unique")
        if self.soft_sequence_tokens > self.max_sequence_tokens:
            raise ValueError("soft_sequence_tokens cannot exceed max_sequence_tokens")
        if any(band.max_tokens > self.soft_sequence_tokens for band in self.length_bands.values()):
            raise ValueError("length-band maximum cannot exceed soft_sequence_tokens")
        if abs(sum(band.share for band in self.length_bands.values()) - 1.0) > 1e-8:
            raise ValueError("length-band shares must sum to 1")
        if self.final_selection is not None:
            unknown = set(self.final_selection.targets) - set(languages)
            if unknown:
                raise ValueError(f"final-selection targets have unknown lanes: {sorted(unknown)}")
        return self

    @property
    def root(self) -> Path:
        return Path(self.output_dir)

    def receipt_hash(self) -> str:
        return sha256(self.model_dump_json().encode()).hexdigest()


def load_config(path: Path) -> KoolbardiConfig:
    with path.open(encoding="utf-8") as handle:
        return KoolbardiConfig.model_validate(yaml.safe_load(handle))
