"""Pure, deterministic review gates for immutable application packages."""

from __future__ import annotations

import hashlib as _hashlib
import json as _json
import re as _re
from collections.abc import Mapping as _Mapping, Sequence as _Sequence
from dataclasses import dataclass as _dataclass
from types import MappingProxyType as _MappingProxyType

from car_job_search.application.integrity import (
    approved_modules_checksum as _approved_modules_checksum,
    application_checksum as _application_checksum,
    package_integrity_valid as _package_integrity_valid,
    package_lineage_valid as _package_lineage_valid,
    render_application_artifacts as _render_application_artifacts,
)
from car_job_search.intake import normalize_posting as _normalize_posting
from car_job_search.projection.integrity import (
    projection_integrity_valid as _projection_integrity_valid,
)
from car_job_search.contracts import (
    ApplicationPackage as _ApplicationPackage,
    EvidenceClaim as _EvidenceClaim,
    EvidenceStatus as _EvidenceStatus,
    FindingStatus as _FindingStatus,
    FitAssessment as _FitAssessment,
    JobPosting as _JobPosting,
    ReviewFinding as _ReviewFinding,
    ReviewSeverity as _ReviewSeverity,
    ReviewState as _ReviewState,
    RuntimeProjection as _RuntimeProjection,
)


class BlockingFinding(ValueError):
    """Raised only for an invalid review boundary involving blocking findings."""


class SchemaFailure(ValueError):
    """Raised when an input at the public review boundary has the wrong type."""


class ATSUnreadable(ValueError):
    """Typed review error for an unreadable application artifact."""


class PolicyViolation(ValueError):
    """Typed review error for a review-policy violation."""


@_dataclass(frozen=True)
class ValidationReport:
    """Immutable result of independent package validation."""

    package: _ApplicationPackage
    findings: tuple[_ReviewFinding, ...]
    validator_results: _Mapping[str, bool]

    def __post_init__(self) -> None:
        object.__setattr__(self, "findings", tuple(self.findings))
        object.__setattr__(
            self,
            "validator_results",
            _MappingProxyType(dict(sorted(self.validator_results.items()))),
        )


def review_package(
    package: _ApplicationPackage,
    posting: _JobPosting,
    assessment: _FitAssessment,
    projection: _RuntimeProjection,
    additional_findings: _Sequence[_ReviewFinding] = (),
) -> ValidationReport:
    """Return a reviewed package snapshot without taking any external action."""
    _validate_boundary(package, posting, assessment, projection, additional_findings)
    results = {
        "ats": _safe(_ats_readable, package),
        "company_role": _safe(_company_and_role_match, package, posting),
        "evidence": _safe(_evidence_is_admitted, package, projection),
        "integrity": _safe(_integrity_is_valid, package, projection),
        "keywords": _safe(_keywords_align, package, posting),
        "linkage": _safe(_linkage_is_exact, package, posting, assessment, projection),
        "policy": _safe(_blocking_status_is_valid, package, additional_findings),
        "schema": _safe(_schema_is_valid, package, posting, assessment, projection),
    }
    generated = tuple(
        _finding(rule_id, package, posting, assessment, projection)
        for rule_id, passed in sorted(results.items())
        if not passed
    )
    merged = _merge_findings(package.review_findings, additional_findings, generated)
    has_open_blocker = any(
        finding.severity is _ReviewSeverity.BLOCKING and finding.status is _FindingStatus.OPEN
        for finding in merged
    )
    review_state = _ReviewState.BLOCKED if has_open_blocker else _ReviewState.RELEASE_CANDIDATE
    snapshot = _ApplicationPackage(
        package_id=package.package_id,
        job_id=package.job_id,
        version=package.version,
        resume_markdown=package.resume_markdown,
        application_markdown=package.application_markdown,
        claims=package.claims,
        keywords=package.keywords,
        source_manifest=package.source_manifest,
        checksum=_application_checksum(
            package.package_id,
            package.job_id,
            package.version,
            package.resume_markdown,
            package.application_markdown,
            package.claims,
            package.keywords,
            package.source_manifest,
            review_state,
            merged,
        ),
        review_state=review_state,
        review_findings=merged,
        schema_version=package.schema_version,
    )
    return ValidationReport(snapshot, merged, results)


def _validate_boundary(
    package: object,
    posting: object,
    assessment: object,
    projection: object,
    additional_findings: object,
) -> None:
    if not isinstance(package, _ApplicationPackage):
        raise SchemaFailure("package must be an ApplicationPackage")
    if not isinstance(posting, _JobPosting):
        raise SchemaFailure("posting must be a JobPosting")
    if not isinstance(assessment, _FitAssessment):
        raise SchemaFailure("assessment must be a FitAssessment")
    if not isinstance(projection, _RuntimeProjection):
        raise SchemaFailure("projection must be a RuntimeProjection")
    if not isinstance(additional_findings, _Sequence) or isinstance(
        additional_findings, (str, bytes)
    ):
        raise SchemaFailure("additional_findings must be a sequence of ReviewFinding values")
    if any(not isinstance(finding, _ReviewFinding) for finding in additional_findings):
        raise SchemaFailure("additional_findings must contain only ReviewFinding values")


def _safe(validator: object, *values: object) -> bool:
    try:
        return bool(validator(*values))
    except Exception:
        return False


def _schema_is_valid(
    package: _ApplicationPackage,
    posting: _JobPosting,
    assessment: _FitAssessment,
    projection: _RuntimeProjection,
) -> bool:
    _ApplicationPackage.from_dict(package.to_dict())
    _JobPosting.from_dict(posting.to_dict())
    _FitAssessment.from_dict(assessment.to_dict())
    _RuntimeProjection.from_dict(projection.to_dict())
    return True


def _linkage_is_exact(
    package: _ApplicationPackage,
    posting: _JobPosting,
    assessment: _FitAssessment,
    projection: _RuntimeProjection,
) -> bool:
    expected_manifest = {
        "assessment_id": assessment.assessment_id,
        "posting_hash": posting.raw_text_hash,
        "projection_checksum": projection.checksum,
    }
    return (
        package.job_id == posting.job_id == assessment.job_id
        and assessment.projection_checksum == projection.checksum
        and all(package.source_manifest.get(key) == value for key, value in expected_manifest.items())
        and _projection_integrity_valid(projection)
        and _module_manifest_is_exact(package.source_manifest, projection)
        and _package_lineage_valid(package)
        and posting == _normalize_posting(
            posting.raw_text, posting.captured_at, posting.source_url
        )
        and _artifacts_are_exact(package, posting, projection)
    )


def _integrity_is_valid(
    package: _ApplicationPackage, projection: _RuntimeProjection
) -> bool:
    return _package_integrity_valid(package) and _projection_integrity_valid(projection)


def _module_manifest_is_exact(
    manifest: _Mapping[str, str], projection: _RuntimeProjection
) -> bool:
    expected_keys = {
        "assessment_id",
        "posting_hash",
        "projection_checksum",
        "approved_module_names",
        "approved_modules_checksum",
        "lineage_fingerprint",
        "lineage_inputs",
    }
    if set(manifest) != expected_keys:
        return False
    names_value = manifest.get("approved_module_names")
    checksum = manifest.get("approved_modules_checksum")
    if not isinstance(names_value, str) or not isinstance(checksum, str):
        return False
    try:
        names = _json.loads(names_value)
    except (TypeError, ValueError):
        return False
    if (
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or not name for name in names)
        or len(names) != len(set(names))
        or _json.dumps(names, separators=(",", ":"), ensure_ascii=True) != names_value
    ):
        return False
    if any(name not in projection.approved_modules for name in names):
        return False
    modules = tuple((name, projection.approved_modules[name]) for name in names)
    return checksum == _approved_modules_checksum(modules)


def _artifacts_are_exact(
    package: _ApplicationPackage,
    posting: _JobPosting,
    projection: _RuntimeProjection,
) -> bool:
    names_value = package.source_manifest.get("approved_module_names")
    if not isinstance(names_value, str):
        return False
    try:
        names = _json.loads(names_value)
    except (TypeError, ValueError):
        return False
    if not isinstance(names, list) or any(name not in projection.approved_modules for name in names):
        return False
    modules = tuple((name, projection.approved_modules[name]) for name in names)
    expected_resume, expected_application = _render_application_artifacts(
        posting, modules, package.claims, package.keywords
    )
    return (
        package.resume_markdown == expected_resume
        and package.application_markdown == expected_application
    )


def _evidence_is_admitted(package: _ApplicationPackage, projection: _RuntimeProjection) -> bool:
    claims = tuple(package.claims)
    if len({claim.claim_id for claim in claims}) != len(claims):
        return False
    admitted = {claim.claim_id: claim for claim in projection.evidence_claims}
    if len(admitted) != len(projection.evidence_claims):
        return False
    evidence_ids: set[str] = set()
    for projection_claim in projection.evidence_claims:
        if not _complete_claim(projection_claim):
            return False
        if evidence_ids.intersection(projection_claim.evidence_ids):
            return False
        evidence_ids.update(projection_claim.evidence_ids)
    return all(
        _complete_claim(claim) and admitted.get(claim.claim_id) == claim for claim in claims
    )


def _complete_claim(claim: _EvidenceClaim) -> bool:
    return (
        claim.status is _EvidenceStatus.VERIFIED
        and claim.confidence >= 80
        and bool(claim.evidence_ids)
        and bool(claim.source_versions)
        and all(isinstance(value, str) and value.strip() for value in claim.evidence_ids)
        and all(isinstance(value, str) and value.strip() for value in claim.source_versions)
    )


def _company_and_role_match(package: _ApplicationPackage, posting: _JobPosting) -> bool:
    if not isinstance(posting.company, str) or not posting.company.strip():
        return False
    if not isinstance(posting.role, str) or not posting.role.strip():
        return False
    return all(
        artifact.splitlines()[:2] == [f"# {posting.company}", f"## {posting.role}"]
        for artifact in (package.resume_markdown, package.application_markdown)
    )


def _keywords_align(package: _ApplicationPackage, posting: _JobPosting) -> bool:
    return all(
        isinstance(keyword, str)
        and keyword.strip()
        and _whole_term(keyword, posting.raw_text)
        and _whole_term(keyword, package.application_markdown)
        for keyword in package.keywords
    )


def _whole_term(term: str, text: str) -> bool:
    return _re.search(rf"(?<![\w.+#/-]){_re.escape(term)}(?![\w.+#/-])", text) is not None


def _ats_readable(package: _ApplicationPackage) -> bool:
    return all(
        len(_re.findall(r"[A-Za-z0-9]", artifact)) >= 80
        for artifact in (package.resume_markdown, package.application_markdown)
    )


def _blocking_status_is_valid(
    package: _ApplicationPackage, additional_findings: _Sequence[_ReviewFinding]
) -> bool:
    return not any(
        finding.severity is _ReviewSeverity.BLOCKING
        and finding.status is not _FindingStatus.OPEN
        for finding in (*package.review_findings, *additional_findings)
    )


def _finding(
    rule_id: str,
    package: _ApplicationPackage,
    posting: _JobPosting,
    assessment: _FitAssessment,
    projection: _RuntimeProjection,
) -> _ReviewFinding:
    references = tuple(
        value
        for value in (package.package_id, posting.job_id, assessment.assessment_id, projection.projection_id)
        if isinstance(value, str) and value
    )
    payload = _json.dumps(
        {"rule_id": rule_id, "evidence_refs": references},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    finding_id = f"review-{_hashlib.sha256(payload.encode('utf-8')).hexdigest()}"
    return _ReviewFinding(
        finding_id=finding_id,
        rule_id=rule_id,
        severity=_ReviewSeverity.BLOCKING,
        status=_FindingStatus.OPEN,
        artifact_ref="application_package",
        message=f"{rule_id} validation failed.",
        evidence_refs=references,
    )


def _merge_findings(
    existing: _Sequence[_ReviewFinding],
    additional: _Sequence[_ReviewFinding],
    generated: _Sequence[_ReviewFinding],
) -> tuple[_ReviewFinding, ...]:
    merged = list(existing)
    known = {finding.finding_id: finding for finding in merged}
    for finding in sorted((*additional, *generated), key=lambda item: item.finding_id):
        previous = known.get(finding.finding_id)
        if previous is None:
            merged.append(finding)
            known[finding.finding_id] = finding
        elif previous != finding:
            collision = _ReviewFinding(
                finding_id=_collision_id(finding.finding_id),
                rule_id="schema",
                severity=_ReviewSeverity.BLOCKING,
                status=_FindingStatus.OPEN,
                artifact_ref="application_package",
                message="review finding identifiers must not conflict.",
                evidence_refs=(finding.finding_id,),
            )
            if collision.finding_id not in known:
                merged.append(collision)
                known[collision.finding_id] = collision
    return tuple(merged)


def _collision_id(finding_id: str) -> str:
    return "review-" + _hashlib.sha256(finding_id.encode("utf-8")).hexdigest()
