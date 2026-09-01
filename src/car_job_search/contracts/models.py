"""Central versioned data contracts for the CAR execution runtime."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Mapping, Sequence, TypeVar

from .errors import DuplicateIdentifier, SchemaViolation, UnknownEnum, UnsupportedVersion


SCHEMA_VERSION = "1.0.0"
_E = TypeVar("_E", bound=Enum)


class EvidenceStatus(str, Enum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    REJECTED = "rejected"


class Verdict(str, Enum):
    ACT = "act"
    CONSIDER = "consider"
    PASS = "pass"


class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    FLAG = "flag"
    UNKNOWN = "unknown"


class ReviewSeverity(str, Enum):
    BLOCKING = "blocking"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    ACCEPTED_NONBLOCKING = "accepted_nonblocking"


class ReviewState(str, Enum):
    DRAFT = "draft"
    BLOCKED = "blocked"
    RELEASE_CANDIDATE = "release_candidate"


class ApprovalAction(str, Enum):
    ARCHIVE = "archive"
    SEND = "send"
    EMIT_OUTCOME = "emit_outcome"


class OutcomeType(str, Enum):
    DRAFTED = "drafted"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    OFFER = "offer"
    WITHDRAWN = "withdrawn"
    CORRECTION = "correction"


class InterviewStage(str, Enum):
    RECRUITER = "recruiter"
    HIRING_MANAGER = "hiring_manager"
    PANEL = "panel"
    FINAL = "final"


def _require_version(value: str) -> None:
    if value != SCHEMA_VERSION:
        raise UnsupportedVersion(f"unsupported schema version: {value!r}")


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaViolation(f"{name} must be a non-empty string")


def _require_score(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
        raise SchemaViolation(f"{name} must be an integer from 0 through 100")


def _require_checksum(name: str, value: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise SchemaViolation(f"{name} must be a lowercase SHA-256 hex digest")


def _enum(enum_type: type[_E], value: _E | str) -> _E:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise UnknownEnum(f"unknown {enum_type.__name__} value: {value!r}") from error


def validate_unique_ids(values: Sequence[str]) -> None:
    seen: set[str] = set()
    for value in values:
        _require_text("identifier", value)
        if value in seen:
            raise DuplicateIdentifier(f"duplicate identifier: {value}")
        seen.add(value)


@dataclass(frozen=True)
class EvidenceClaim:
    claim_id: str
    text: str
    evidence_ids: tuple[str, ...]
    confidence: int
    status: EvidenceStatus
    source_versions: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_text("claim_id", self.claim_id)
        _require_text("text", self.text)
        _require_score("confidence", self.confidence)
        object.__setattr__(self, "status", _enum(EvidenceStatus, self.status))
        validate_unique_ids(self.evidence_ids)
        if self.status is EvidenceStatus.VERIFIED:
            if not self.evidence_ids:
                raise SchemaViolation("verified claim requires evidence IDs")
            if not self.source_versions:
                raise SchemaViolation("verified claim requires source versions")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "claim_id": self.claim_id,
            "text": self.text,
            "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence,
            "status": self.status.value,
            "source_versions": list(self.source_versions),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceClaim":
        _require_version(str(value.get("schema_version", "")))
        return cls(
            claim_id=str(value.get("claim_id", "")),
            text=str(value.get("text", "")),
            evidence_ids=tuple(value.get("evidence_ids", ())),
            confidence=value.get("confidence"),
            status=_enum(EvidenceStatus, value.get("status")),
            source_versions=tuple(value.get("source_versions", ())),
            schema_version=str(value["schema_version"]),
        )

@dataclass(frozen=True)
class RuntimeProjection:
    projection_id: str
    generated_at: str
    source_versions: Mapping[str, str]
    evidence_claims: tuple[EvidenceClaim, ...]
    role_targets: tuple[str, ...]
    constraints: Mapping[str, Any]
    approved_modules: Mapping[str, str]
    checksum: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_text("projection_id", self.projection_id)
        _require_text("generated_at", self.generated_at)
        _require_checksum("checksum", self.checksum)
        if not self.source_versions:
            raise SchemaViolation("projection requires source versions")
        validate_unique_ids([claim.claim_id for claim in self.evidence_claims])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "projection_id": self.projection_id,
            "generated_at": self.generated_at,
            "source_versions": dict(self.source_versions),
            "evidence_claims": [claim.to_dict() for claim in self.evidence_claims],
            "role_targets": list(self.role_targets),
            "constraints": dict(self.constraints),
            "approved_modules": dict(self.approved_modules),
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RuntimeProjection":
        _require_version(str(value.get("schema_version", "")))
        return cls(
            projection_id=str(value.get("projection_id", "")),
            generated_at=str(value.get("generated_at", "")),
            source_versions=dict(value.get("source_versions", {})),
            evidence_claims=tuple(EvidenceClaim.from_dict(item) for item in value.get("evidence_claims", ())),
            role_targets=tuple(value.get("role_targets", ())),
            constraints=dict(value.get("constraints", {})),
            approved_modules=dict(value.get("approved_modules", {})),
            checksum=str(value.get("checksum", "")),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class JobPosting:
    job_id: str
    company: str | None
    role: str | None
    raw_text: str
    source_url: str | None
    captured_at: str
    raw_text_hash: str
    location: str | None = None
    work_mode: str | None = None
    compensation: str | None = None
    eligibility: str | None = None
    requirements: tuple[str, ...] = ()
    preferred_requirements: tuple[str, ...] = ()
    responsibilities: tuple[str, ...] = ()
    unresolved_fields: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_text("job_id", self.job_id)
        _require_text("raw_text", self.raw_text)
        _require_text("captured_at", self.captured_at)
        _require_checksum("raw_text_hash", self.raw_text_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "company": self.company,
            "role": self.role,
            "raw_text": self.raw_text,
            "source_url": self.source_url,
            "captured_at": self.captured_at,
            "raw_text_hash": self.raw_text_hash,
            "location": self.location,
            "work_mode": self.work_mode,
            "compensation": self.compensation,
            "eligibility": self.eligibility,
            "requirements": list(self.requirements),
            "preferred_requirements": list(self.preferred_requirements),
            "responsibilities": list(self.responsibilities),
            "unresolved_fields": list(self.unresolved_fields),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "JobPosting":
        _require_version(str(value.get("schema_version", "")))
        return cls(
            job_id=str(value.get("job_id", "")),
            company=value.get("company"),
            role=value.get("role"),
            raw_text=str(value.get("raw_text", "")),
            source_url=value.get("source_url"),
            captured_at=str(value.get("captured_at", "")),
            raw_text_hash=str(value.get("raw_text_hash", "")),
            location=value.get("location"),
            work_mode=value.get("work_mode"),
            compensation=value.get("compensation"),
            eligibility=value.get("eligibility"),
            requirements=tuple(value.get("requirements", ())),
            preferred_requirements=tuple(value.get("preferred_requirements", ())),
            responsibilities=tuple(value.get("responsibilities", ())),
            unresolved_fields=tuple(value.get("unresolved_fields", ())),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class GateResult:
    name: str
    status: GateStatus
    source: str | None
    reason: str

    def __post_init__(self) -> None:
        _require_text("gate name", self.name)
        _require_text("gate reason", self.reason)
        object.__setattr__(self, "status", _enum(GateStatus, self.status))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "status": self.status.value, "source": self.source, "reason": self.reason}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "GateResult":
        return cls(
            name=str(value.get("name", "")),
            status=_enum(GateStatus, value.get("status")),
            source=value.get("source"),
            reason=str(value.get("reason", "")),
        )


@dataclass(frozen=True)
class FitAssessment:
    assessment_id: str
    job_id: str
    projection_checksum: str
    gate_results: tuple[GateResult, ...]
    job_fit: int
    requirements_reality: int
    strategic_value: int
    overall_fit: int
    confidence: int
    verdict: Verdict
    evidence_refs: tuple[str, ...]
    material_gaps: tuple[str, ...] = ()
    human_override: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        for name in ("assessment_id", "job_id"):
            _require_text(name, getattr(self, name))
        _require_checksum("projection_checksum", self.projection_checksum)
        for name in ("job_fit", "requirements_reality", "strategic_value", "overall_fit", "confidence"):
            _require_score(name, getattr(self, name))
        object.__setattr__(self, "verdict", _enum(Verdict, self.verdict))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "assessment_id": self.assessment_id,
            "job_id": self.job_id,
            "projection_checksum": self.projection_checksum,
            "gate_results": [gate.to_dict() for gate in self.gate_results],
            "job_fit": self.job_fit,
            "requirements_reality": self.requirements_reality,
            "strategic_value": self.strategic_value,
            "overall_fit": self.overall_fit,
            "confidence": self.confidence,
            "verdict": self.verdict.value,
            "evidence_refs": list(self.evidence_refs),
            "material_gaps": list(self.material_gaps),
            "human_override": self.human_override,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FitAssessment":
        _require_version(str(value.get("schema_version", "")))
        return cls(
            assessment_id=str(value.get("assessment_id", "")),
            job_id=str(value.get("job_id", "")),
            projection_checksum=str(value.get("projection_checksum", "")),
            gate_results=tuple(GateResult.from_dict(item) for item in value.get("gate_results", ())),
            job_fit=value.get("job_fit"),
            requirements_reality=value.get("requirements_reality"),
            strategic_value=value.get("strategic_value"),
            overall_fit=value.get("overall_fit"),
            confidence=value.get("confidence"),
            verdict=_enum(Verdict, value.get("verdict")),
            evidence_refs=tuple(value.get("evidence_refs", ())),
            material_gaps=tuple(value.get("material_gaps", ())),
            human_override=bool(value.get("human_override", False)),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class ApplicationPackage:
    package_id: str
    job_id: str
    version: int
    resume_markdown: str
    application_markdown: str
    claims: tuple[EvidenceClaim, ...]
    keywords: tuple[str, ...]
    source_manifest: Mapping[str, str]
    checksum: str
    review_state: ReviewState = ReviewState.DRAFT
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        for name in ("package_id", "job_id", "resume_markdown", "application_markdown"):
            _require_text(name, getattr(self, name))
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise SchemaViolation("package version must be a positive integer")
        _require_checksum("checksum", self.checksum)
        object.__setattr__(self, "review_state", _enum(ReviewState, self.review_state))
        validate_unique_ids([claim.claim_id for claim in self.claims])

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "package_id": self.package_id,
            "job_id": self.job_id,
            "version": self.version,
            "resume_markdown": self.resume_markdown,
            "application_markdown": self.application_markdown,
            "claims": [claim.to_dict() for claim in self.claims],
            "keywords": list(self.keywords),
            "source_manifest": dict(self.source_manifest),
            "checksum": self.checksum,
            "review_state": self.review_state.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApplicationPackage":
        _require_version(str(value.get("schema_version", "")))
        return cls(
            package_id=str(value.get("package_id", "")),
            job_id=str(value.get("job_id", "")),
            version=value.get("version"),
            resume_markdown=str(value.get("resume_markdown", "")),
            application_markdown=str(value.get("application_markdown", "")),
            claims=tuple(EvidenceClaim.from_dict(item) for item in value.get("claims", ())),
            keywords=tuple(value.get("keywords", ())),
            source_manifest=dict(value.get("source_manifest", {})),
            checksum=str(value.get("checksum", "")),
            review_state=_enum(ReviewState, value.get("review_state", "draft")),
            schema_version=str(value["schema_version"]),
        )


@dataclass(frozen=True)
class ReviewFinding:
    finding_id: str
    rule_id: str
    severity: ReviewSeverity
    status: FindingStatus
    artifact_ref: str
    message: str
    evidence_refs: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        for name in ("finding_id", "rule_id", "artifact_ref", "message"):
            _require_text(name, getattr(self, name))
        object.__setattr__(self, "severity", _enum(ReviewSeverity, self.severity))
        object.__setattr__(self, "status", _enum(FindingStatus, self.status))


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    package_checksum: str
    action: ApprovalAction
    approver: str
    approved_at: str
    expires_at: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        for name in ("approval_id", "approver", "approved_at"):
            _require_text(name, getattr(self, name))
        _require_checksum("package_checksum", self.package_checksum)
        object.__setattr__(self, "action", _enum(ApprovalAction, self.action))


@dataclass(frozen=True)
class InterviewPack:
    interview_id: str
    package_id: str
    package_checksum: str
    stage: InterviewStage
    questions: tuple[str, ...]
    answer_maps: tuple[Mapping[str, Any], ...]
    evidence_ids: tuple[str, ...]
    gap_bridges: tuple[str, ...]
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_text("interview_id", self.interview_id)
        _require_text("package_id", self.package_id)
        _require_checksum("package_checksum", self.package_checksum)
        object.__setattr__(self, "stage", _enum(InterviewStage, self.stage))


@dataclass(frozen=True)
class OutcomeEvent:
    event_id: str
    package_id: str
    event_type: OutcomeType
    occurred_at: str
    source: str
    idempotency_key: str
    evidence_ref: str | None = None
    payload_version: str = SCHEMA_VERSION
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_version(self.payload_version)
        for name in ("event_id", "package_id", "occurred_at", "source"):
            _require_text(name, getattr(self, name))
        if not isinstance(self.idempotency_key, str) or not self.idempotency_key.strip():
            raise SchemaViolation("idempotency key is required")
        object.__setattr__(self, "event_type", _enum(OutcomeType, self.event_type))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "package_id": self.package_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at,
            "source": self.source,
            "idempotency_key": self.idempotency_key,
            "evidence_ref": self.evidence_ref,
            "payload_version": self.payload_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "OutcomeEvent":
        _require_version(str(value.get("schema_version", "")))
        return cls(
            event_id=str(value.get("event_id", "")),
            package_id=str(value.get("package_id", "")),
            event_type=_enum(OutcomeType, value.get("event_type")),
            occurred_at=str(value.get("occurred_at", "")),
            source=str(value.get("source", "")),
            idempotency_key=str(value.get("idempotency_key", "")),
            evidence_ref=value.get("evidence_ref"),
            payload_version=str(value.get("payload_version", "")),
            schema_version=str(value["schema_version"]),
        )
