from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Reglas explícitas (español rioplatense / neutro). No inferencia multimodal.
DEFAULT_SPATIAL_CUE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("deixis_aca", r"\b(?:ac[aá]|aqu[ií])\b"),
    ("fijate", r"\bfijat[eé]\b"),
    ("mira", r"\bmir[aá]\b"),
    ("este_boton", r"\beste\s+bot[oó]n\b"),
    ("esta_pantalla", r"\besta\s+(?:pantalla|vista|parte|secci[oó]n)\b"),
    ("clic_aca", r"\b(?:hago\s+)?clic(?:k)?(?:\s+(?:ac[aá]|aqu[ií]|ac[aá]|en\s+esto))?\b"),
    ("cuando_clic", r"\bcuando\s+(?:hago\s+)?clic(?:k)?\b"),
    ("tendria_aparecer", r"\b(?:tendr[ií]a\s+que|deber[ií]a)\s+aparecer\b"),
    ("esto_tendria", r"\besto\s+tendr[ií]a\s+que\b"),
    ("mira_lo_que", r"\bmir[aá]\s+lo\s+que\b"),
    ("senala_esto", r"\b(?:esto|eso)\s+(?:de\s+ac[aá]|de\s+aqu[ií])\b"),
)


@dataclass(frozen=True)
class SpatialCueMatch:
    pattern_id: str
    matched_text: str


def compile_patterns(
    patterns: tuple[tuple[str, str], ...] | None = None,
) -> list[tuple[str, re.Pattern[str]]]:
    source = patterns if patterns is not None else DEFAULT_SPATIAL_CUE_PATTERNS
    compiled: list[tuple[str, re.Pattern[str]]] = []
    for pattern_id, expression in source:
        compiled.append((pattern_id, re.compile(expression, re.IGNORECASE | re.UNICODE)))
    return compiled


def find_spatial_cues(
    text: str,
    compiled: list[tuple[str, re.Pattern[str]]] | None = None,
) -> list[SpatialCueMatch]:
    patterns = compiled if compiled is not None else compile_patterns()
    matches: list[SpatialCueMatch] = []
    seen: set[str] = set()
    for pattern_id, regex in patterns:
        found = regex.search(text)
        if not found:
            continue
        key = f"{pattern_id}:{found.group(0).casefold()}"
        if key in seen:
            continue
        seen.add(key)
        matches.append(SpatialCueMatch(pattern_id=pattern_id, matched_text=found.group(0)))
    return matches


def parse_extra_patterns(raw: str | None) -> tuple[tuple[str, str], ...]:
    """Formato: id:regex,id2:regex2 (coma separa pares)."""
    if raw is None or not raw.strip():
        return ()
    items: list[tuple[str, str]] = []
    for part in raw.split(","):
        piece = part.strip()
        if not piece:
            continue
        if ":" not in piece:
            raise ValueError(
                f"VISUAL_EVIDENCE_EXTRA_PATTERNS inválido ({piece!r}); usá id:regex"
            )
        pattern_id, expression = piece.split(":", 1)
        pattern_id = pattern_id.strip()
        expression = expression.strip()
        if not pattern_id or not expression:
            raise ValueError(f"Patrón incompleto en VISUAL_EVIDENCE_EXTRA_PATTERNS: {piece!r}")
        # Validar que compile.
        re.compile(expression)
        items.append((pattern_id, expression))
    return tuple(items)


def segment_as_cue_input(segment: dict[str, Any]) -> str:
    return str(segment.get("text") or "").strip()
