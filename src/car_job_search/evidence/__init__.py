"""Deterministic, read-only evidence resolution."""

from .service import ConflictingEvidence, EvidenceBelowThreshold, NoEvidence, resolve_claim

__all__ = ["ConflictingEvidence", "EvidenceBelowThreshold", "NoEvidence", "resolve_claim"]
