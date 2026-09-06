"""Build replaceable runtime projections from versioned canonical exports."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import Any

from car_job_search.contracts import (
    EvidenceClaim,
    EvidenceStatus,
    RuntimeProjection,
    SCHEMA_VERSION,
)
from car_job_search.contracts.errors import SchemaViolation


class ProjectionError(SchemaViolation):
    """Base error for rejected canonical projection input."""


class MissingRequiredArtifact(ProjectionError):
    """A required canonical artifact or its version metadata is absent."""


class DuplicateEvidenceId(ProjectionError):
    """An evidence identifier was admitted more than once."""


class ConflictingCanonicalClaim(ProjectionError):
    """Normalized canonical claims disagree and require verification."""

    def __init__(self, message: str, verification_item: Mapping[str, object]) -> None:
        super().__init__(message)
        self.verification_item = MappingProxyType(dict(verification_item))


class ProjectionDrift(ProjectionError):
    """A supplied projection cannot be reproduced from its canonical export."""


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MissingRequiredArtifact(f"{name} must be a mapping")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MissingRequiredArtifact(f"{name} must be a non-empty string")
    return value.strip()


def _sequence(value: object, name: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise MissingRequiredArtifact(f"{name} must be a sequence")
    return value


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def _metric_signature(value: str) -> str:
    return re.sub(r"(?<![\w.])\d+(?:\.\d+)?(?:\s*%)?", "<metric>", value)


def _verification_item(claim_ids: tuple[str, str], normalized_claim: str) -> Mapping[str, object]:
    return {
        "code": "conflicting_canonical_claim",
        "claim_ids": claim_ids,
        "normalized_claim": normalized_claim,
        "status": "requires_verification",
    }


def _canonical_checksum(value: Mapping[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonicalize_mapping(value: Mapping[str, object]) -> dict[str, object]:
    return {
        _text(key, "mapping key"): _canonicalize_value(item)
        for key, item in sorted(value.items(), key=lambda entry: _text(entry[0], "mapping key"))
    }


def _canonicalize_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _canonicalize_mapping(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return sorted(
            (_canonicalize_value(item) for item in value),
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
        )
    return value


def _source_versions(source: Mapping[str, object]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_artifact in _sequence(source.get("artifacts"), "artifacts"):
        artifact = _mapping(raw_artifact, "artifact")
        artifact_id = _text(artifact.get("artifact_id"), "artifact_id")
        version = _text(artifact.get("version"), f"artifact {artifact_id} version")
        if artifact_id in versions:
            raise MissingRequiredArtifact(f"duplicate artifact_id: {artifact_id}")
        versions[artifact_id] = version
    if not versions:
        raise MissingRequiredArtifact("at least one versioned artifact is required")
    return dict(sorted(versions.items()))


def _claims(source: Mapping[str, object], versions: Mapping[str, str]) -> tuple[EvidenceClaim, ...]:
    claims: list[EvidenceClaim] = []
    evidence_ids: set[str] = set()
    normalized_claims: dict[str, tuple[str, tuple[object, ...]]] = {}
    metric_claims: dict[str, tuple[str, tuple[object, ...]]] = {}
    claim_ids: set[str] = set()
    for raw_claim in _sequence(source.get("evidence_claims", ()), "evidence_claims"):
        claim = _mapping(raw_claim, "evidence claim")
        claim_id = _text(claim.get("claim_id"), "claim_id")
        if claim_id in claim_ids:
            raise ConflictingCanonicalClaim(
                f"duplicate claim_id: {claim_id}",
                _verification_item((claim_id, claim_id), claim_id),
            )
        claim_ids.add(claim_id)
        text = _text(claim.get("text"), "claim text")
        status = _text(claim.get("status"), "claim status")
        confidence = claim.get("confidence")
        raw_evidence_ids = tuple(sorted(_text(value, "evidence_id") for value in _sequence(claim.get("evidence_ids", ()), "evidence_ids")))
        if len(raw_evidence_ids) != len(set(raw_evidence_ids)) or evidence_ids.intersection(raw_evidence_ids):
            raise DuplicateEvidenceId("duplicate evidence ID")
        evidence_ids.update(raw_evidence_ids)
        artifact_ids = tuple(sorted(_text(value, "source_artifact_id") for value in _sequence(claim.get("source_artifact_ids", ()), "source_artifact_ids")))
        if not artifact_ids:
            raise MissingRequiredArtifact(f"claim {claim_id} requires source artifact IDs")
        if any(artifact_id not in versions for artifact_id in artifact_ids):
            raise MissingRequiredArtifact(f"claim {claim_id} references an unknown artifact")
        source_versions = tuple(f"{artifact_id}@{versions[artifact_id]}" for artifact_id in artifact_ids)
        signature = (status, confidence, raw_evidence_ids, source_versions)
        normalized_text = _normalized_text(text)
        existing_claim = normalized_claims.get(normalized_text)
        if existing_claim and existing_claim[1] != signature:
            raise ConflictingCanonicalClaim(
                f"conflicting canonical claim: {text}",
                _verification_item((existing_claim[0], claim_id), normalized_text),
            )
        normalized_claims[normalized_text] = (claim_id, signature)
        metric_signature = _metric_signature(normalized_text)
        existing_metric_claim = metric_claims.get(metric_signature)
        if existing_metric_claim and existing_metric_claim[1] != signature:
            raise ConflictingCanonicalClaim(
                f"conflicting canonical metric claim: {text}",
                _verification_item((existing_metric_claim[0], claim_id), metric_signature),
            )
        metric_claims[metric_signature] = (claim_id, signature)
        claims.append(
            EvidenceClaim(
                claim_id=claim_id,
                text=" ".join(text.split()),
                evidence_ids=raw_evidence_ids,
                confidence=confidence,
                status=status,
                source_versions=source_versions,
            )
        )
    return tuple(sorted(claims, key=lambda item: item.claim_id))


def build_projection(source: Mapping[str, object]) -> RuntimeProjection:
    """Build a deterministic, read-only RuntimeProjection from a CAR export."""
    source = _mapping(source, "source")
    projection_id = _text(source.get("projection_id"), "projection_id")
    generated_at = _text(source.get("generated_at"), "generated_at")
    versions = _source_versions(source)
    claims = _claims(source, versions)
    role_targets = tuple(sorted(_text(value, "role_target") for value in _sequence(source.get("role_targets", ()), "role_targets")))
    constraints = _canonicalize_mapping(_mapping(source.get("constraints", {}), "constraints"))
    approved_modules = {
        _text(key, "approved module name"): _text(value, "approved module text")
        for key, value in _mapping(source.get("approved_modules", {}), "approved_modules").items()
    }
    verified_claim_texts = {
        _normalized_text(claim.text)
        for claim in claims
        if claim.status is EvidenceStatus.VERIFIED
    }
    unsupported_modules = tuple(
        name
        for name, content in sorted(approved_modules.items())
        if _normalized_text(content) not in verified_claim_texts
    )
    if unsupported_modules:
        raise MissingRequiredArtifact(
            "approved module copy must exactly match a verified evidence claim: "
            + ", ".join(unsupported_modules)
        )
    semantic_value = {
        "schema_version": SCHEMA_VERSION,
        "projection_id": projection_id,
        "source_versions": versions,
        "evidence_claims": [claim.to_dict() for claim in claims],
        "role_targets": role_targets,
        "constraints": constraints,
        "approved_modules": dict(sorted(approved_modules.items())),
    }
    checksum = _canonical_checksum(semantic_value)
    expected_checksum = source.get("expected_checksum")
    if expected_checksum is not None and checksum != expected_checksum:
        raise ProjectionDrift("expected checksum does not match the generated projection")
    return RuntimeProjection(
        projection_id=projection_id,
        generated_at=generated_at,
        source_versions=versions,
        evidence_claims=claims,
        role_targets=role_targets,
        constraints=constraints,
        approved_modules=dict(sorted(approved_modules.items())),
        checksum=checksum,
    )
