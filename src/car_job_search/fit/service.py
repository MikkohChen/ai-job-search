"""Deterministic fit assessments with caller-supplied scores."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from car_job_search.contracts import (
    EvidenceStatus,
    FitAssessment,
    GateResult,
    GateStatus,
    JobPosting,
    RuntimeProjection,
    Verdict,
)


class AssessmentIncomplete(ValueError):
    """Raised when required assessment inputs are absent or malformed."""


class GateEvidenceMissing(AssessmentIncomplete):
    """Raised when a positive requirements assessment lacks evidence references."""


class ScoreOutOfRange(AssessmentIncomplete):
    """Raised when an explicit score is outside the contract range."""


def assess_fit(
    projection: RuntimeProjection,
    posting: JobPosting,
    gate_results: Sequence[GateResult],
    job_fit: int,
    requirements_reality: int,
    strategic_value: int,
    overall_fit: int,
    confidence: int,
    evidence_refs: Sequence[str],
    material_gaps: Sequence[str] = (),
    human_override: bool = False,
) -> FitAssessment:
    """Return an immutable assessment using only explicit decision inputs."""
    if not isinstance(projection, RuntimeProjection):
        raise AssessmentIncomplete("projection must be a RuntimeProjection")
    if not isinstance(posting, JobPosting):
        raise AssessmentIncomplete("posting must be a JobPosting")

    gates = _gates(gate_results)
    refs = _evidence_refs(evidence_refs, projection)
    gaps = _texts(material_gaps, "material_gaps")
    if not isinstance(human_override, bool):
        raise AssessmentIncomplete("human_override must be a boolean")

    scores = {
        "job_fit": job_fit,
        "requirements_reality": requirements_reality,
        "strategic_value": strategic_value,
        "overall_fit": overall_fit,
        "confidence": confidence,
    }
    for name, value in scores.items():
        _score(name, value)
    if requirements_reality > 0 and not refs:
        raise GateEvidenceMissing(
            "positive requirements_reality requires evidence_refs"
        )

    verdict = _verdict(
        gates, overall_fit, confidence, gaps, human_override
    )
    assessment_id = _assessment_id(
        posting.raw_text_hash,
        projection.checksum,
        gates,
        scores,
        refs,
        gaps,
        human_override,
    )
    return FitAssessment(
        assessment_id=assessment_id,
        job_id=posting.job_id,
        projection_checksum=projection.checksum,
        gate_results=gates,
        job_fit=job_fit,
        requirements_reality=requirements_reality,
        strategic_value=strategic_value,
        overall_fit=overall_fit,
        confidence=confidence,
        verdict=verdict,
        evidence_refs=refs,
        material_gaps=gaps,
        human_override=human_override,
    )


def _gates(value: Sequence[GateResult]) -> tuple[GateResult, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AssessmentIncomplete("gate_results must be a sequence of GateResult")
    gates = tuple(value)
    if any(not isinstance(gate, GateResult) for gate in gates):
        raise AssessmentIncomplete("gate_results must contain only GateResult values")
    return gates


def _texts(value: Sequence[str], name: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AssessmentIncomplete(f"{name} must be a sequence of non-empty strings")
    values = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in values):
        raise AssessmentIncomplete(f"{name} must be a sequence of non-empty strings")
    return values


def _evidence_refs(
    value: Sequence[str], projection: RuntimeProjection
) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GateEvidenceMissing("evidence_refs must be a sequence of non-empty strings")
    refs = tuple(value)
    if any(not isinstance(item, str) or not item.strip() for item in refs):
        raise GateEvidenceMissing("evidence_refs must be a sequence of non-empty strings")
    if len(refs) != len(set(refs)):
        raise GateEvidenceMissing("evidence_refs must be unique")
    projection_evidence_ids = tuple(
        evidence_id
        for claim in projection.evidence_claims
        for evidence_id in claim.evidence_ids
    )
    if len(projection_evidence_ids) != len(set(projection_evidence_ids)):
        raise GateEvidenceMissing("projection contains duplicate evidence IDs")
    admitted = {
        evidence_id
        for claim in projection.evidence_claims
        if claim.status is EvidenceStatus.VERIFIED
        for evidence_id in claim.evidence_ids
    }
    if any(reference not in admitted for reference in refs):
        raise GateEvidenceMissing("evidence_refs must resolve to verified projection evidence")
    return refs


def _score(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise ScoreOutOfRange(f"{name} must be an integer from 0 through 100")


def _verdict(
    gates: tuple[GateResult, ...],
    overall_fit: int,
    confidence: int,
    material_gaps: tuple[str, ...],
    human_override: bool,
) -> Verdict:
    if any(gate.status is GateStatus.FAIL for gate in gates):
        return Verdict.PASS
    if overall_fit < 70 and not human_override:
        return Verdict.PASS
    if any(gate.status in {GateStatus.UNKNOWN, GateStatus.FLAG} for gate in gates):
        return Verdict.CONSIDER
    if material_gaps or confidence < 80:
        return Verdict.CONSIDER
    if overall_fit >= 70:
        return Verdict.ACT
    return Verdict.CONSIDER


def _assessment_id(
    posting_hash: str,
    projection_checksum: str,
    gates: tuple[GateResult, ...],
    scores: dict[str, int],
    evidence_refs: tuple[str, ...],
    material_gaps: tuple[str, ...],
    human_override: bool,
) -> str:
    input_data = {
        "posting_hash": posting_hash,
        "projection_checksum": projection_checksum,
        "gate_results": [gate.to_dict() for gate in gates],
        "scores": scores,
        "evidence_refs": list(evidence_refs),
        "material_gaps": list(material_gaps),
        "human_override": human_override,
    }
    serialized = json.dumps(input_data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return f"fit-{hashlib.sha256(serialized.encode('utf-8')).hexdigest()}"
