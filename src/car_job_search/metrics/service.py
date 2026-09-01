"""Pure, append-only VARR measurement for generated application packages."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, localcontext
from types import MappingProxyType

from car_job_search.approval import verify_approval
from car_job_search.application.integrity import package_integrity_valid, package_lineage_valid
from car_job_search.application.service import build_application, revise_application
from car_job_search.contracts import (
    ApplicationPackage,
    ApprovalAction,
    ApprovalRecord,
    EvidenceStatus,
    FitAssessment,
    GateStatus,
    ReviewState,
    Verdict,
)
from car_job_search.review import ValidationReport, review_package


_VALIDATOR_NAMES = frozenset(
    {"ats", "company_role", "evidence", "integrity", "keywords", "linkage", "policy", "schema"}
)


class PackageGateError(ValueError):
    """Base class for package-gate ledger boundary failures."""


class UnknownPackage(PackageGateError):
    """Raised when a review or approval references an unregistered package."""


class PackageVersionMismatch(PackageGateError):
    """Raised when a package ID is known but the version is not registered."""


class PackageChecksumMismatch(PackageGateError):
    """Raised when a review or approval is not bound to the recorded package snapshot."""


class DuplicatePackageConflict(PackageGateError):
    """Raised when a generated package ID/version is replayed with different content."""


@dataclass(frozen=True)
class PackageGateSnapshot:
    """An immutable observation of every VARR gate for one package version."""

    package_id: str
    version: int
    package_checksum: str
    fit_passed: bool
    evidence_passed: bool
    ats_passed: bool | None = None
    reviewer_passed: bool | None = None
    approval_passed: bool | None = None
    reviewed_checksum: str | None = None
    approval_id: str | None = None
    approval_verified_at: str | None = None

    @property
    def gates(self) -> MappingProxyType:
        """Return all five gate outcomes; ``None`` means the gate is not yet observed."""
        return MappingProxyType(
            {
                "fit": self.fit_passed,
                "evidence": self.evidence_passed,
                "ats": self.ats_passed,
                "reviewer": self.reviewer_passed,
                "approval": self.approval_passed,
            }
        )

    @property
    def ready(self) -> bool:
        """Return whether all five required VARR gates have explicitly passed."""
        return all(gate is True for gate in self.gates.values())


@dataclass(frozen=True)
class VARRMeasurement:
    """A deterministic VARR numerator, denominator, and percentage."""

    numerator: int
    denominator: int
    rate: Decimal | None


class PackageGateLedger:
    """Maintain an append-only, in-memory gate history for generated packages."""

    def __init__(self) -> None:
        self._packages: dict[tuple[str, int], ApplicationPackage] = {}
        self._latest: dict[tuple[str, int], PackageGateSnapshot] = {}
        self._history: list[PackageGateSnapshot] = []

    @property
    def package_gates(self) -> tuple[PackageGateSnapshot, ...]:
        """Return the latest complete gate snapshot for every registered package version."""
        return tuple(self._latest[key] for key in self._packages)

    @property
    def history(self) -> tuple[PackageGateSnapshot, ...]:
        """Return every immutable ledger observation in append order."""
        return tuple(self._history)

    def register(
        self, package: ApplicationPackage, assessment: FitAssessment
    ) -> PackageGateSnapshot:
        """Register a generated package against its authoritative fit assessment."""
        if not isinstance(package, ApplicationPackage):
            raise PackageGateError("package must be an ApplicationPackage")
        if not isinstance(assessment, FitAssessment):
            raise PackageGateError("assessment must be a FitAssessment")
        key = (package.package_id, package.version)
        existing = self._packages.get(key)
        if existing is not None:
            if existing == package:
                return self._latest[key]
            raise DuplicatePackageConflict("package_id and version already identify different content")

        foundational_valid = _package_integrity_and_manifest_are_valid(package)
        snapshot = PackageGateSnapshot(
            package_id=package.package_id,
            version=package.version,
            package_checksum=package.checksum,
            fit_passed=foundational_valid and _fit_assessment_is_linked(package, assessment),
            evidence_passed=foundational_valid and _claims_are_linked(package, assessment),
        )
        self._packages[key] = package
        self._append(key, snapshot)
        return snapshot

    def generate_and_register(
        self,
        assessment: FitAssessment,
        projection: object,
        posting: object,
        claims: Sequence[object],
        module_names: Sequence[str],
        keywords: Sequence[str],
        max_characters: int,
    ) -> ApplicationPackage:
        """Build a package and register it in the VARR denominator in one operation."""
        package = build_application(
            assessment,
            projection,
            posting,
            claims,
            module_names,
            keywords,
            max_characters,
        )
        self.register(package, assessment)
        return package

    def revise_and_register(
        self,
        original: ApplicationPackage,
        assessment: FitAssessment,
        projection: object,
        posting: object,
        claims: Sequence[object],
        module_names: Sequence[str],
        keywords: Sequence[str],
        max_characters: int,
    ) -> ApplicationPackage:
        """Revise one registered package and register its new version before returning it."""
        _, registered, _ = self._registered(original)
        if original != registered:
            raise PackageChecksumMismatch("revision original does not match the registered package")
        revised = revise_application(
            original,
            assessment,
            projection,
            posting,
            claims,
            module_names,
            keywords,
            max_characters,
        )
        self.register(revised, assessment)
        return revised

    def record_review(
        self,
        report: ValidationReport,
        posting: object,
        assessment: FitAssessment,
        projection: object,
        additional_findings: Sequence[object] = (),
    ) -> PackageGateSnapshot:
        """Record a report only when it matches a fresh review of the registered package."""
        reviewed_package, _, validator_results = _review_report_values(report)
        key, original, current = self._registered(reviewed_package)
        expected = review_package(original, posting, assessment, projection, additional_findings)
        if report != expected:
            raise PackageChecksumMismatch("review report does not match the registered package review")

        reviewer_passed = (
            reviewed_package.review_state is ReviewState.RELEASE_CANDIDATE
            and all(validator_results.values())
        )
        snapshot = replace(
            current,
            ats_passed=validator_results["ats"],
            reviewer_passed=reviewer_passed,
            reviewed_checksum=reviewed_package.checksum,
        )
        return self._append(key, snapshot)

    def review_and_record(
        self,
        package: ApplicationPackage,
        posting: object,
        assessment: FitAssessment,
        projection: object,
        additional_findings: Sequence[object] = (),
    ) -> ApplicationPackage:
        """Run the public review implementation and append its resulting gate observation."""
        report = review_package(package, posting, assessment, projection, additional_findings)
        self.record_review(report, posting, assessment, projection, additional_findings)
        return report.package

    def record_approval(
        self,
        reviewed_package: ApplicationPackage,
        approval: ApprovalRecord,
        verified_at: str,
    ) -> PackageGateSnapshot:
        """Record only a current SEND approval verified against the recorded review snapshot."""
        key, _, current = self._registered(reviewed_package)
        if current.reviewed_checksum != reviewed_package.checksum:
            raise PackageChecksumMismatch("approval package does not match the recorded review snapshot")
        if not isinstance(approval, ApprovalRecord) or approval.package_checksum != reviewed_package.checksum:
            raise PackageChecksumMismatch("approval checksum does not match the reviewed package")

        verify_approval(reviewed_package, ApprovalAction.SEND, approval, verified_at)
        snapshot = replace(
            current,
            approval_passed=True,
            approval_id=approval.approval_id,
            approval_verified_at=verified_at,
        )
        return self._append(key, snapshot)

    def measurement(self) -> VARRMeasurement:
        """Return VARR over every registered generated package version."""
        denominator = len(self._latest)
        numerator = sum(snapshot.ready for snapshot in self._latest.values())
        return VARRMeasurement(numerator, denominator, _percentage(numerator, denominator))

    def _registered(
        self, package: ApplicationPackage
    ) -> tuple[tuple[str, int], ApplicationPackage, PackageGateSnapshot]:
        if not isinstance(package, ApplicationPackage):
            raise PackageGateError("package must be an ApplicationPackage")
        key = (package.package_id, package.version)
        original = self._packages.get(key)
        if original is None:
            if any(item.package_id == package.package_id for item in self._packages.values()):
                raise PackageVersionMismatch("package_id is registered at a different version")
            raise UnknownPackage("package_id and version are not registered")
        return key, original, self._latest[key]

    def _append(
        self, key: tuple[str, int], snapshot: PackageGateSnapshot
    ) -> PackageGateSnapshot:
        current = self._latest.get(key)
        if current == snapshot:
            return current
        self._latest[key] = snapshot
        self._history.append(snapshot)
        return snapshot


def _package_integrity_and_manifest_are_valid(package: ApplicationPackage) -> bool:
    return package_integrity_valid(package) and package_lineage_valid(package)


def _fit_assessment_is_linked(package: ApplicationPackage, assessment: FitAssessment) -> bool:
    return (
        package.job_id == assessment.job_id
        and package.source_manifest.get("assessment_id") == assessment.assessment_id
        and package.source_manifest.get("projection_checksum") == assessment.projection_checksum
        and not any(gate.status is GateStatus.FAIL for gate in assessment.gate_results)
        and (assessment.verdict is Verdict.ACT or assessment.human_override)
    )


def _claims_are_linked(package: ApplicationPackage, assessment: FitAssessment) -> bool:
    assessment_evidence = set(assessment.evidence_refs)
    return all(
        claim.status is EvidenceStatus.VERIFIED
        and bool(claim.evidence_ids)
        and bool(claim.source_versions)
        and set(claim.evidence_ids).issubset(assessment_evidence)
        for claim in package.claims
    )


def _review_report_values(
    report: object,
) -> tuple[ApplicationPackage, tuple[object, ...], Mapping[str, bool]]:
    if not isinstance(report, ValidationReport):
        raise PackageGateError("report must be a ValidationReport")
    package = getattr(report, "package", None)
    findings = getattr(report, "findings", None)
    validator_results = getattr(report, "validator_results", None)
    if not isinstance(package, ApplicationPackage):
        raise PackageGateError("report must contain an ApplicationPackage")
    if not isinstance(findings, tuple) or findings != package.review_findings:
        raise PackageChecksumMismatch("report findings do not match the reviewed package")
    if not isinstance(validator_results, Mapping) or set(validator_results) != _VALIDATOR_NAMES:
        raise PackageGateError("report must contain every named validator result")
    if any(not isinstance(value, bool) for value in validator_results.values()):
        raise PackageGateError("report validator results must be boolean")
    return package, findings, validator_results


def _percentage(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = 28
        return (Decimal(numerator) * Decimal(100)) / Decimal(denominator)
