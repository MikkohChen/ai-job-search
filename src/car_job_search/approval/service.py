"""Pure verification for reviewed application-package approvals."""

from __future__ import annotations

from datetime import datetime

from car_job_search.application.integrity import package_integrity_valid
from car_job_search.contracts import (
    ApplicationPackage,
    ApprovalAction,
    ApprovalRecord,
    ReviewSeverity,
    ReviewState,
)


class ApprovalMissing(ValueError):
    """Raised when no typed approval record is supplied."""


class ApprovalStale(ValueError):
    """Raised when verification is outside the approval's valid interval."""


class ChecksumChanged(ValueError):
    """Raised when package contents or the approval checksum has changed."""


class ActionMismatch(ValueError):
    """Raised when a request is not bound to the approved action."""


class PackageNotReleaseCandidate(ValueError):
    """Raised when an approval is checked before independent review passes."""


def verify_approval(
    package: ApplicationPackage,
    requested_action: ApprovalAction | str,
    approval: ApprovalRecord | None,
    verified_at: str,
) -> ApprovalRecord:
    """Return ``approval`` only when it binds a current reviewed package to one action."""
    if not isinstance(package, ApplicationPackage):
        raise PackageNotReleaseCandidate("package must be an ApplicationPackage")
    if package.review_state is not ReviewState.RELEASE_CANDIDATE:
        raise PackageNotReleaseCandidate("package must be a release candidate")
    if any(
        finding.severity is ReviewSeverity.BLOCKING
        for finding in package.review_findings
    ):
        raise PackageNotReleaseCandidate("package has a blocking review finding")
    if not package_integrity_valid(package):
        raise ChecksumChanged("package contents no longer match its checksum")
    if not isinstance(approval, ApprovalRecord):
        raise ApprovalMissing("approval must be an ApprovalRecord")

    action = _approval_action(requested_action)
    if approval.package_checksum != package.checksum:
        raise ChecksumChanged("approval checksum does not match package checksum")
    if approval.action is not action:
        raise ActionMismatch("approval action does not match requested action")

    checked_at = _aware_datetime(verified_at)
    approved_at = _aware_datetime(approval.approved_at)
    if checked_at < approved_at:
        raise ApprovalStale("approval is not valid before approved_at")
    if approval.expires_at is not None and checked_at >= _aware_datetime(approval.expires_at):
        raise ApprovalStale("approval has expired")
    return approval


def _approval_action(value: ApprovalAction | str) -> ApprovalAction:
    if isinstance(value, ApprovalAction):
        return value
    try:
        return ApprovalAction(value)
    except (TypeError, ValueError) as error:
        raise ActionMismatch("requested action is not a known ApprovalAction") from error


def _aware_datetime(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ApprovalStale("verified_at must be a timezone-aware ISO-8601 timestamp")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ApprovalStale("verified_at must be a timezone-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ApprovalStale("verified_at must be a timezone-aware ISO-8601 timestamp")
    return parsed
