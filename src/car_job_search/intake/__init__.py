"""Inert job-posting intake API."""

from .service import (
    EmptyPosting,
    FetchDenied,
    NormalizationIncomplete,
    UntrustedDirectiveDetected,
    normalize_posting,
)

__all__ = [
    "EmptyPosting",
    "FetchDenied",
    "NormalizationIncomplete",
    "UntrustedDirectiveDetected",
    "normalize_posting",
]
