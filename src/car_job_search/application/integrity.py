"""Canonical integrity calculation shared by build, review, and approval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence

from car_job_search.contracts import (
    ApplicationPackage,
    EvidenceClaim,
    JobPosting,
    ReviewFinding,
    ReviewState,
)


class PackageIntegrityError(ValueError):
    """Raised when a revision source has invalid package integrity or lineage."""


def application_checksum(
    package_id: str,
    job_id: str,
    version: int,
    resume_markdown: str,
    application_markdown: str,
    claims: Sequence[EvidenceClaim],
    keywords: Sequence[str],
    source_manifest: Mapping[str, str],
    review_state: ReviewState = ReviewState.DRAFT,
    review_findings: Sequence[ReviewFinding] = (),
) -> str:
    """Return the checksum for application content and bound review metadata."""
    payload = {
        "application_markdown": application_markdown,
        "claims": [claim.to_dict() for claim in claims],
        "job_id": job_id,
        "keywords": list(keywords),
        "package_id": package_id,
        "resume_markdown": resume_markdown,
        "review_findings": [finding.to_dict() for finding in review_findings],
        "review_state": (
            review_state.value if isinstance(review_state, ReviewState) else review_state
        ),
        "source_manifest": dict(source_manifest),
        "version": version,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def package_integrity_valid(package: ApplicationPackage) -> bool:
    """Return whether an application package still matches its bound content."""
    if not isinstance(package, ApplicationPackage):
        return False
    return package.checksum == application_checksum(
        package.package_id,
        package.job_id,
        package.version,
        package.resume_markdown,
        package.application_markdown,
        package.claims,
        package.keywords,
        package.source_manifest,
        package.review_state,
        package.review_findings,
    )


def render_application_artifacts(
    posting: JobPosting,
    modules: Sequence[tuple[str, str]],
    claims: Sequence[EvidenceClaim],
    keywords: Sequence[str],
) -> tuple[str, str]:
    """Render the exact deterministic resume and application artifacts for a package."""
    module_values = tuple(modules)
    claim_values = tuple(claims)
    keyword_values = tuple(keywords)
    return (
        _render_markdown("Resume", posting, module_values, claim_values),
        _render_markdown(
            "Application", posting, module_values, claim_values, keyword_values
        ),
    )


def _render_markdown(
    kind: str,
    posting: JobPosting,
    modules: tuple[tuple[str, str], ...],
    claims: tuple[EvidenceClaim, ...],
    keywords: tuple[str, ...] = (),
) -> str:
    lines = [
        f"# {posting.company}",
        f"## {posting.role}",
        f"Artifact: {kind}",
        "",
        "## Approved modules",
    ]
    lines.extend(content for _, content in modules)
    if len(claims) >= 3:
        lines.extend(("", "## Verified achievements"))
        lines.extend(f"- {claim.text}" for claim in claims[:3])
    if keywords:
        lines.extend(("", f"Keywords: {'; '.join(keywords)}"))
    return "\n".join(lines)


def lineage_fingerprint(
    base_manifest: Mapping[str, str],
    claims: Sequence[EvidenceClaim],
    modules: Sequence[tuple[str, str]],
    keywords: Sequence[str],
) -> tuple[str, str]:
    """Return the canonical initial-selection payload and its SHA-256 fingerprint."""
    payload = {
        "base_manifest": dict(base_manifest),
        "claims": [claim.to_dict() for claim in claims],
        "keywords": list(keywords),
        "modules": [{"content": content, "name": name} for name, content in modules],
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return serialized, hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def package_lineage_valid(package: ApplicationPackage) -> bool:
    """Return whether the package ID and stored lineage fingerprint agree."""
    if not isinstance(package, ApplicationPackage):
        return False
    manifest = package.source_manifest
    keys = ("assessment_id", "posting_hash", "projection_checksum", "lineage_inputs", "lineage_fingerprint")
    if any(not isinstance(manifest.get(key), str) or not manifest[key] for key in keys):
        return False
    try:
        parsed = json.loads(manifest["lineage_inputs"])
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, Mapping):
        return False
    base_manifest = {
        "assessment_id": manifest["assessment_id"],
        "posting_hash": manifest["posting_hash"],
        "projection_checksum": manifest["projection_checksum"],
    }
    if parsed.get("base_manifest") != base_manifest:
        return False
    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return (
        manifest["lineage_inputs"] == canonical
        and manifest["lineage_fingerprint"] == fingerprint
        and package.package_id == f"package-{fingerprint}"
    )


def approved_modules_checksum(modules: Sequence[tuple[str, str]]) -> str:
    """Return a deterministic checksum for caller-selected approved copy."""
    serialized = json.dumps(
        [{"content": content, "name": name} for name, content in modules],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
