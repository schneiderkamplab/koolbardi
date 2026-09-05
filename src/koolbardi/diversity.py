from __future__ import annotations

import json
import math
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class DiversityAssignment:
    topic: dict
    mode: dict
    persona: dict


class DiversityAssigner:
    """Deterministic, marginally balanced topic/mode/persona assignment."""

    def __init__(self, catalog_path: str, persona_store_path: str, language: str, seed: int):
        with Path(catalog_path).open(encoding="utf-8") as handle:
            catalog = yaml.safe_load(handle)
        self.topics = [
            {"domain": domain["id"], **topic}
            for domain in catalog["domains"]
            for topic in domain["topics"]
        ]
        self.modes = list(catalog["modes"])
        if len(self.topics) < 100:
            raise ValueError("controlled diversity requires at least 100 topics")
        if not self.modes:
            raise ValueError("controlled diversity requires interaction modes")
        self.language = language
        self.seed = seed
        rng = random.Random(f"{seed}:{language}:catalog")
        rng.shuffle(self.topics)
        rng.shuffle(self.modes)
        self.connection = sqlite3.connect(
            f"file:{Path(persona_store_path).resolve()}?mode=ro", uri=True, timeout=60
        )
        row = self.connection.execute(
            "SELECT COUNT(*) FROM personas WHERE language=?", (language,)
        ).fetchone()
        self.persona_count = int(row[0])
        if self.persona_count < 1:
            raise ValueError(f"persona store has no {language!r} records")
        candidate = 1 + 2 * (seed % max(1, self.persona_count // 2))
        while math.gcd(candidate, self.persona_count) != 1:
            candidate += 2
        self.persona_stride = candidate
        self.persona_offset = seed % self.persona_count

    def close(self) -> None:
        self.connection.close()

    def assignment(self, index: int) -> DiversityAssignment:
        topic = self.topics[index % len(self.topics)]
        # For a fixed topic, successive cycles visit every mode when the catalog
        # sizes are not coprime (128 topics and 20 modes in v1).
        mode_index = (index + index // len(self.topics)) % len(self.modes)
        mode = self.modes[mode_index]
        persona_position = (
            self.persona_offset + index * self.persona_stride
        ) % self.persona_count
        row = self.connection.execute(
            "SELECT source_id, payload FROM personas WHERE language=? AND position=?",
            (self.language, persona_position),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"missing persona at {self.language}:{persona_position}")
        persona = json.loads(row[1])
        persona["source_id"] = row[0]
        return DiversityAssignment(topic=topic, mode=mode, persona=persona)


def diversity_condition(language: str, assignment: DiversityAssignment) -> str:
    label = "da" if language == "da" else "en"
    topic = assignment.topic[label]
    mode = assignment.mode[label]
    persona = assignment.persona
    context = "; ".join(
        f"{key}: {persona[key]}"
        for key in ("age_band", "occupation", "education", "interests", "profile")
        if persona.get(key)
    )
    embedded = assignment.mode.get("embedded_input", False)
    if language == "da":
        source_requirement = (
            " Brugerbeskeden skal selv indeholde den tekst eller de data, der skal bearbejdes."
            if embedded else ""
        )
        return (
            f" Emne: {topic}. Interaktionsform: {mode}. "
            f"Brug denne personkontekst som diskret inspiration: {context}. "
            "Skriv en konkret, realistisk forespørgsel; nævn ikke emneetiketten, "
            "interaktionsformen, personaen eller denne instruktion."
            f"{source_requirement}"
        )
    source_requirement = (
        " The user message itself must include the text or data to be processed."
        if embedded else ""
    )
    return (
        f" Topic: {topic}. Interaction mode: {mode}. "
        f"Use this person context as subtle inspiration: {context}. "
        "Write a concrete, realistic request; do not mention the topic label, "
        "interaction mode, persona, or these instructions."
        f"{source_requirement}"
    )
