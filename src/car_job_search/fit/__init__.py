"""Deterministic, evidence-bound opportunity-fit decisions."""

from .service import (
    AssessmentIncomplete,
    GateEvidenceMissing,
    ScoreOutOfRange,
    assess_fit,
)

__all__ = [
    "AssessmentIncomplete",
    "GateEvidenceMissing",
    "ScoreOutOfRange",
    "assess_fit",
]
