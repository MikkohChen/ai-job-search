"""Resolve candidate claims only against exact admitted projection evidence."""

from __future__ import annotations

import hashlib

from car_job_search.contracts import EvidenceClaim, EvidenceStatus, RuntimeProjection


class EvidenceResolutionError(ValueError):
    """Base error for deterministic evidence-resolution failures."""


class ConflictingEvidence(EvidenceResolutionError):
    """Raised when requested evidence IDs belong to different canonical claims."""


class EvidenceBelowThreshold(EvidenceResolutionError):
    """Available for callers that require errors instead of an unverified result."""


class NoEvidence(EvidenceResolutionError):
    """Available to consumers that require a typed no-evidence error."""


VERIFICATION_THRESHOLD = 80


def resolve_claim(
    text: str,
    projection: RuntimeProjection,
    evidence_ids: tuple[str, ...] | list[str] = (),
) -> EvidenceClaim:
    """Return a read-only evidence verdict; P0 accepts only exact normalized text."""
    normalized_text = _normalized_text(text)
    requested_ids = _evidence_ids(evidence_ids)
    claims_by_evidence = _claims_by_evidence(projection)

    if not requested_ids:
        return _result(normalized_text, (), 0, EvidenceStatus.UNVERIFIED, ())
    if any(evidence_id not in claims_by_evidence for evidence_id in requested_ids):
        return _result(normalized_text, requested_ids, 0, EvidenceStatus.REJECTED, ())

    source_claims = {claims_by_evidence[evidence_id] for evidence_id in requested_ids}
    if len(source_claims) != 1:
        raise ConflictingEvidence("requested evidence IDs span canonical claims")
    source_claim = source_claims.pop()
    if (
        _match_key(normalized_text) != _match_key(source_claim.text)
        or set(requested_ids) != set(source_claim.evidence_ids)
    ):
        return _result(normalized_text, requested_ids, 0, EvidenceStatus.REJECTED, ())
    if (
        source_claim.status is EvidenceStatus.REJECTED
    ):
        return _claim_from_source(source_claim, normalized_text, EvidenceStatus.REJECTED)
    if (
        source_claim.status is not EvidenceStatus.VERIFIED
        or source_claim.confidence < VERIFICATION_THRESHOLD
    ):
        return _claim_from_source(source_claim, normalized_text, EvidenceStatus.UNVERIFIED)
    return _claim_from_source(source_claim, normalized_text, EvidenceStatus.VERIFIED)


def _claim_from_source(
    source_claim: EvidenceClaim, text: str, status: EvidenceStatus
) -> EvidenceClaim:
    return EvidenceClaim(
        claim_id=source_claim.claim_id,
        text=text,
        evidence_ids=source_claim.evidence_ids,
        confidence=source_claim.confidence,
        status=status,
        source_versions=source_claim.source_versions,
    )


def _claims_by_evidence(projection: RuntimeProjection) -> dict[str, EvidenceClaim]:
    if not isinstance(projection, RuntimeProjection):
        raise TypeError("projection must be a RuntimeProjection")
    claims_by_evidence: dict[str, EvidenceClaim] = {}
    for claim in projection.evidence_claims:
        for evidence_id in claim.evidence_ids:
            if evidence_id in claims_by_evidence:
                raise ConflictingEvidence("projection contains duplicate evidence IDs")
            claims_by_evidence[evidence_id] = claim
    return claims_by_evidence


def _evidence_ids(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        raise TypeError("evidence_ids must be a tuple or list of unique non-empty strings")
    evidence_ids = tuple(value)
    if any(not isinstance(evidence_id, str) or not evidence_id.strip() for evidence_id in evidence_ids):
        raise ValueError("evidence_ids must contain only non-empty strings")
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("evidence_ids must be unique")
    return evidence_ids


def _normalized_text(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("text must be a non-empty string")
    normalized_text = " ".join(text.split())
    if not normalized_text:
        raise ValueError("text must be a non-empty string")
    return normalized_text


def _match_key(text: str) -> str:
    return _normalized_text(text).casefold()


def _result(
    text: str,
    evidence_ids: tuple[str, ...],
    confidence: int,
    status: EvidenceStatus,
    source_versions: tuple[str, ...],
) -> EvidenceClaim:
    claim_id = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return EvidenceClaim(
        claim_id=f"claim-{claim_id}",
        text=text,
        evidence_ids=evidence_ids,
        confidence=confidence,
        status=status,
        source_versions=source_versions,
    )
