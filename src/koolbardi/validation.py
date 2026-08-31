from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from lingua import Language, LanguageDetectorBuilder


_DETECTOR = LanguageDetectorBuilder.from_languages(Language.DANISH, Language.ENGLISH).build()
_CODE_RE = re.compile(r"```|\b(def|class|function|SELECT|import|const|let)\b|[{};]{2,}", re.I)


@dataclass(frozen=True)
class ValidationResult:
    accepted: bool
    reason: str
    detected_language: str | None = None
    uncertain_language: bool = False


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

