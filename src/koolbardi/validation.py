from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from lingua import Language, LanguageDetectorBuilder


_DETECTOR = LanguageDetectorBuilder.from_languages(Language.DANISH, Language.ENGLISH).build()
_CODE_RE = re.compile(r"```|\b(def|class|function|SELECT|import|const|let)\b|[{};]{2,}", re.I)
_META_RE = re.compile(
    r"\b(generation task|required language|additional requirements|"
    r"return the user message only|do not mention these instructions)\b",
    re.I,
)
_INCOMPLETE_LAST_WORDS = {
    "a", "af", "an", "and", "at", "but", "de", "den", "der", "det",
    "eller", "en", "er", "et", "for", "har", "hvis", "i", "if", "is",
    "kan", "med", "men", "når", "of", "og", "om", "or", "på", "skal",
    "som", "the", "til", "to", "vil", "with",
}


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str
    detected_language: str | None = None
    uncertain_language: bool = False


def validate_instruction(instruction: str, expected_language: str) -> ValidationResult:
    text = instruction.strip()
    if not text:
        return ValidationResult(False, "empty instruction")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\t\r" for char in text):
        return ValidationResult(False, "invalid control character")
    if _META_RE.search(text):
        return ValidationResult(False, "generation-control leakage")
    if len(text) < 20:
        return ValidationResult(False, "instruction too short to be useful")
    if _CODE_RE.search(text) or len(text) < 80:
        return ValidationResult(True, "language audit required", uncertain_language=True)
    confidence = _DETECTOR.compute_language_confidence_values(text)
    if not confidence:
        return ValidationResult(True, "language audit required", uncertain_language=True)
    best = confidence[0]
    detected = "da" if best.language == Language.DANISH else "en"
    if best.value < 0.80:
        return ValidationResult(True, "language audit required", detected, True)
    if detected != expected_language:
        return ValidationResult(False, "language mismatch", detected)
    return ValidationResult(True, "ok", detected)


def validate_generation_completion(text: str, finish_reason: str | None) -> ValidationResult:
    if finish_reason != "stop":
        return ValidationResult(False, f"generation finish_reason={finish_reason!r}")
    stripped = text.rstrip()
    if not stripped:
        return ValidationResult(False, "empty generation")
    if stripped.count("```") % 2:
        return ValidationResult(False, "unclosed code fence")
    visible = stripped.rstrip("*_`~ ")
    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", visible.casefold())
    if words and words[-1] in _INCOMPLETE_LAST_WORDS:
        return ValidationResult(False, "generation ends with an incomplete function word")
    if visible[-1] not in ".!?…;:)]}'\"|$`":
        return ValidationResult(False, "generation has no complete terminal boundary")
    return ValidationResult(True, "complete")


def validate_text_pair(instruction: str, response: str, expected_language: str) -> ValidationResult:
    if not instruction.strip() or not response.strip():
        return ValidationResult(False, "empty instruction or response")
    if any(unicodedata.category(char) == "Cc" and char not in "\n\t\r" for char in instruction + response):
        return ValidationResult(False, "invalid control character")
    combined = f"{instruction}\n{response}"
    if len(combined) < 80 or _CODE_RE.search(combined):
        return ValidationResult(True, "language audit required", uncertain_language=True)
    confidence = _DETECTOR.compute_language_confidence_values(combined)
    if not confidence:
        return ValidationResult(True, "language audit required", uncertain_language=True)
    best = confidence[0]
    detected = "da" if best.language == Language.DANISH else "en"
    if best.value < 0.80:
        return ValidationResult(True, "language audit required", detected, True)
    if detected != expected_language:
        return ValidationResult(False, "language mismatch", detected)
    return ValidationResult(True, "ok", detected)
