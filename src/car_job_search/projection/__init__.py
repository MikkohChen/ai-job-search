"""Deterministic, read-only projections from canonical CAR exports."""

from .service import (
    ConflictingCanonicalClaim,
    DuplicateEvidenceId,
    MissingRequiredArtifact,
    ProjectionDrift,
    build_projection,
)

__all__ = [
    "ConflictingCanonicalClaim",
    "DuplicateEvidenceId",
    "MissingRequiredArtifact",
    "ProjectionDrift",
    "build_projection",
]
