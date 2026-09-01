"""Build immutable application packages without inference or side effects."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from types import MappingProxyType

from car_job_search.contracts import (
    ApplicationPackage,
    EvidenceClaim,
    EvidenceStatus,
    FitAssessment,
    GateStatus,
    JobPosting,
    RuntimeProjection,
    Verdict,
)
from car_job_search.intake import normalize_posting
from car_job_search.projection.integrity import projection_integrity_valid

from .integrity import (
    PackageIntegrityError,
    application_checksum,
    approved_modules_checksum,
    lineage_fingerprint,
    package_integrity_valid,
    package_lineage_valid,
    render_application_artifacts,
)


class FitGateClosed(ValueError):
    """Raised when an assessment cannot authorize application construction."""


class UnsupportedClaim(ValueError):
    """Raised when supplied claims or keywords lack exact admitted provenance."""


class MissingRequiredModule(ValueError):
    """Raised when selected approved copy modules are absent or invalid."""


class PackageTooLong(ValueError):
    """Raised when the assembled package exceeds its explicit character cap."""


def build_application(
    assessment: FitAssessment,
    projection: RuntimeProjection,
    posting: JobPosting,
    claims: Sequence[EvidenceClaim],
    module_names: Sequence[str],
    keywords: Sequence[str],
    max_characters: int,
) -> ApplicationPackage:
    """Return version-one package from caller-selected, fully verified inputs."""
    _validate_fit(assessment, projection, posting)
    verified_claims = _verified_claims(claims, projection, assessment)
    modules = _approved_modules(module_names, projection)
    source_keywords = _keywords(keywords, posting)
    return _assemble(
        assessment,
        projection,
        posting,
        verified_claims,
        modules,
        source_keywords,
        max_characters,
        version=1,
    )


def revise_application(
    original: ApplicationPackage,
    assessment: FitAssessment,
    projection: RuntimeProjection,
    posting: JobPosting,
    claims: Sequence[EvidenceClaim],
    module_names: Sequence[str],
    keywords: Sequence[str],
    max_characters: int,
) -> ApplicationPackage:
    """Return a new version of one package; the original remains unchanged."""
    if not isinstance(original, ApplicationPackage):
        raise FitGateClosed("original must be an ApplicationPackage")
    if not package_integrity_valid(original):
        raise PackageIntegrityError("original package checksum is invalid")
    if not package_lineage_valid(original):
        raise PackageIntegrityError("original package lineage is invalid")
    _validate_fit(assessment, projection, posting)
    _validate_original_source(original, assessment, projection, posting)
    verified_claims = _verified_claims(claims, projection, assessment)
    modules = _approved_modules(module_names, projection)
    source_keywords = _keywords(keywords, posting)
    revised = _assemble(
        assessment,
        projection,
        posting,
        verified_claims,
        modules,
        source_keywords,
        max_characters,
        version=original.version + 1,
        lineage_inputs=original.source_manifest["lineage_inputs"],
        lineage_value=original.source_manifest["lineage_fingerprint"],
        package_id=original.package_id,
    )
    return revised


def _validate_fit(
    assessment: FitAssessment, projection: RuntimeProjection, posting: JobPosting
) -> None:
    if not isinstance(assessment, FitAssessment):
        raise FitGateClosed("assessment must be a FitAssessment")
    if not isinstance(projection, RuntimeProjection):
        raise FitGateClosed("projection must be a RuntimeProjection")
    if not projection_integrity_valid(projection):
        raise FitGateClosed("projection must retain its M02 semantic checksum")
    if not isinstance(posting, JobPosting):
        raise FitGateClosed("posting must be a JobPosting")
    normalized_posting = normalize_posting(
        posting.raw_text,
        captured_at=posting.captured_at,
        source_url=posting.source_url,
    )
    if normalized_posting != posting:
        raise FitGateClosed("posting must exactly match its inert normalized snapshot")
    if assessment.job_id != posting.job_id:
        raise FitGateClosed("assessment job_id must match posting job_id")
    if assessment.projection_checksum != projection.checksum:
        raise FitGateClosed("assessment must match projection checksum")
    if not isinstance(posting.company, str) or not posting.company.strip():
        raise FitGateClosed("posting company must be a non-empty normalized value")
    if not isinstance(posting.role, str) or not posting.role.strip():
        raise FitGateClosed("posting role must be a non-empty normalized value")
    if any(gate.status is GateStatus.FAIL for gate in assessment.gate_results):
        raise FitGateClosed("a failed hard gate blocks application construction")
    if assessment.verdict is not Verdict.ACT and not assessment.human_override:
        raise FitGateClosed("assessment must be ACT or have an explicit human override")


def _verified_claims(
    claims: Sequence[EvidenceClaim], projection: RuntimeProjection, assessment: FitAssessment
) -> tuple[EvidenceClaim, ...]:
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        raise UnsupportedClaim("claims must be a sequence of verified EvidenceClaim values")
    selected = tuple(claims)
    if any(not isinstance(claim, EvidenceClaim) for claim in selected):
        raise UnsupportedClaim("claims must contain only EvidenceClaim values")
    if len({claim.claim_id for claim in selected}) != len(selected):
        raise UnsupportedClaim("claims must not repeat claim IDs")
    projection_evidence_ids = tuple(
        evidence_id
        for projection_claim in projection.evidence_claims
        for evidence_id in projection_claim.evidence_ids
    )
    if len(projection_evidence_ids) != len(set(projection_evidence_ids)):
        raise UnsupportedClaim("projection contains duplicate evidence IDs")
    admitted = {claim.claim_id: claim for claim in projection.evidence_claims}
    assessment_evidence_refs = set(assessment.evidence_refs)
    for claim in selected:
        if claim.status is not EvidenceStatus.VERIFIED or admitted.get(claim.claim_id) != claim:
            raise UnsupportedClaim("claim must exactly match a verified projection claim")
        if any(evidence_id not in assessment_evidence_refs for evidence_id in claim.evidence_ids):
            raise UnsupportedClaim("claim evidence IDs must be included in assessment evidence_refs")
    return selected


def _approved_modules(
    module_names: Sequence[str], projection: RuntimeProjection
) -> tuple[tuple[str, str], ...]:
    if not isinstance(module_names, Sequence) or isinstance(module_names, (str, bytes)):
        raise MissingRequiredModule("module_names must be a sequence of module names")
    names = tuple(module_names)
    if not names or any(not isinstance(name, str) or not name.strip() for name in names):
        raise MissingRequiredModule("at least one non-empty module name is required")
    if len(set(names)) != len(names):
        raise MissingRequiredModule("module_names must be unique")
    modules: list[tuple[str, str]] = []
    for name in names:
        content = projection.approved_modules.get(name)
        if not isinstance(content, str) or not content.strip():
            raise MissingRequiredModule(f"approved module is missing: {name}")
        modules.append((name, content))
    return tuple(modules)


def _keywords(keywords: Sequence[str], posting: JobPosting) -> tuple[str, ...]:
    if not isinstance(keywords, Sequence) or isinstance(keywords, (str, bytes)):
        raise UnsupportedClaim("keywords must be a sequence of exact posting terms")
    terms = tuple(keywords)
    if any(not isinstance(term, str) or not term.strip() for term in terms):
        raise UnsupportedClaim("keywords must contain only non-empty strings")
    if len(set(terms)) != len(terms):
        raise UnsupportedClaim("keywords must be unique")
    if any(
        re.search(rf"(?<![\w.+#/-]){re.escape(term)}(?![\w.+#/-])", posting.raw_text)
        is None
        for term in terms
    ):
        raise UnsupportedClaim("keywords must be exact terms from the captured posting")
    return terms


def _assemble(
    assessment: FitAssessment,
    projection: RuntimeProjection,
    posting: JobPosting,
    claims: tuple[EvidenceClaim, ...],
    modules: tuple[tuple[str, str], ...],
    keywords: tuple[str, ...],
    max_characters: int,
    *,
    version: int,
    lineage_inputs: str | None = None,
    lineage_value: str | None = None,
    package_id: str | None = None,
) -> ApplicationPackage:
    if isinstance(max_characters, bool) or not isinstance(max_characters, int) or max_characters < 1:
        raise PackageTooLong("max_characters must be a positive integer")
    resume_markdown, application_markdown = render_application_artifacts(
        posting, modules, claims, keywords
    )
    if len(resume_markdown) + len(application_markdown) > max_characters:
        raise PackageTooLong("assembled package exceeds max_characters")
    base_manifest = {
        "assessment_id": assessment.assessment_id,
        "posting_hash": posting.raw_text_hash,
        "projection_checksum": projection.checksum,
    }
    if lineage_inputs is None or lineage_value is None:
        lineage_inputs, lineage_value = lineage_fingerprint(
            base_manifest, claims, modules, keywords
        )
    if package_id is None:
        package_id = f"package-{lineage_value}"
    source_manifest = MappingProxyType(
        {
            **base_manifest,
            "approved_module_names": json.dumps(
                [name for name, _ in modules], separators=(",", ":"), ensure_ascii=True
            ),
            "approved_modules_checksum": approved_modules_checksum(modules),
            "lineage_fingerprint": lineage_value,
            "lineage_inputs": lineage_inputs,
        }
    )
    return ApplicationPackage(
        package_id=package_id,
        job_id=posting.job_id,
        version=version,
        resume_markdown=resume_markdown,
        application_markdown=application_markdown,
        claims=claims,
        keywords=keywords,
        source_manifest=source_manifest,
        checksum=application_checksum(
            package_id,
            posting.job_id,
            version,
            resume_markdown,
            application_markdown,
            claims,
            keywords,
            source_manifest,
        ),
    )


def _validate_original_source(
    original: ApplicationPackage,
    assessment: FitAssessment,
    projection: RuntimeProjection,
    posting: JobPosting,
) -> None:
    expected = {
        "assessment_id": assessment.assessment_id,
        "posting_hash": posting.raw_text_hash,
        "projection_checksum": projection.checksum,
    }
    if original.job_id != posting.job_id or any(
        original.source_manifest.get(key) != value for key, value in expected.items()
    ):
        raise FitGateClosed("original package source manifest does not match revision inputs")
