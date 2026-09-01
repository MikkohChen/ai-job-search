"""Acceptance tests for the pure M08 checksum-bound approval gate."""

from __future__ import annotations

from dataclasses import replace
import inspect
import unittest

import car_job_search.approval as approval
from car_job_search.application.integrity import application_checksum, package_integrity_valid
from car_job_search.contracts import (
    ApplicationPackage,
    ApprovalAction,
    ApprovalRecord,
    FindingStatus,
    ReviewFinding,
    ReviewSeverity,
    ReviewState,
)


CHECKSUM = "a" * 64
APPROVED_AT = "2026-09-01T12:00:00Z"
VERIFIED_AT = "2026-09-01T12:30:00+00:00"


def release_candidate(*, review_findings: tuple[ReviewFinding, ...] = ()) -> ApplicationPackage:
    """Create a minimal intact package whose review has passed."""
    package = ApplicationPackage(
        package_id="package-1",
        job_id="job-1",
        version=1,
        resume_markdown="# Resume\n",
        application_markdown="# Application\n",
        claims=(),
        keywords=("Python",),
        source_manifest={"projection_checksum": CHECKSUM},
        checksum="b" * 64,
        review_state=ReviewState.RELEASE_CANDIDATE,
        review_findings=review_findings,
    )
    return replace(
        package,
        checksum=application_checksum(
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
        ),
    )


def blocking_finding(status: FindingStatus) -> ReviewFinding:
    return ReviewFinding(
        finding_id=f"finding-{status.value}",
        rule_id="review.blocking",
        severity=ReviewSeverity.BLOCKING,
        status=status,
        artifact_ref="application_markdown",
        message="A blocking review finding remains.",
    )


def record_for(
    package: ApplicationPackage,
    *,
    action: ApprovalAction = ApprovalAction.SEND,
    expires_at: str | None = "2026-09-01T13:00:00Z",
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="approval-1",
        package_checksum=package.checksum,
        action=action,
        approver="synthetic-reviewer",
        approved_at=APPROVED_AT,
        expires_at=expires_at,
    )


class ApprovalGateTests(unittest.TestCase):
    def test_returns_the_exact_nonexpiring_record_for_an_intact_release_candidate(self):
        package = release_candidate()
        record = record_for(package, expires_at=None)

        self.assertIs(
            approval.verify_approval(package, ApprovalAction.SEND, record, VERIFIED_AT), record
        )

    def test_rejects_a_package_that_has_not_passed_review(self):
        package = replace(release_candidate(), review_state=ReviewState.DRAFT)

        with self.assertRaises(approval.PackageNotReleaseCandidate):
            approval.verify_approval(package, ApprovalAction.SEND, record_for(package), VERIFIED_AT)

    def test_rejects_blocking_findings_with_any_status_in_directly_constructed_candidates(self):
        for status in FindingStatus:
            with self.subTest(status=status):
                package = release_candidate(review_findings=(blocking_finding(status),))
                self.assertTrue(package_integrity_valid(package))

                with self.assertRaises(approval.PackageNotReleaseCandidate):
                    approval.verify_approval(
                        package, ApprovalAction.SEND, record_for(package), VERIFIED_AT
                    )

    def test_rejects_erased_blocker_history_with_a_stale_checksum(self):
        reviewed_package = release_candidate(
            review_findings=(blocking_finding(FindingStatus.RESOLVED),)
        )
        erased_history = replace(reviewed_package, review_findings=())
        self.assertTrue(package_integrity_valid(reviewed_package))
        self.assertFalse(package_integrity_valid(erased_history))

        with self.assertRaises(approval.ChecksumChanged):
            approval.verify_approval(
                erased_history, ApprovalAction.SEND, record_for(reviewed_package), VERIFIED_AT
            )

    def test_rejects_an_edited_artifact_even_when_the_stored_checksum_matches_approval(self):
        package = replace(release_candidate(), application_markdown="# Edited application\n")

        with self.assertRaises(approval.ChecksumChanged):
            approval.verify_approval(package, ApprovalAction.SEND, record_for(package), VERIFIED_AT)

    def test_rejects_absent_or_untyped_approval_records(self):
        package = release_candidate()

        for candidate in (None, object()):
            with self.subTest(approval=candidate):
                with self.assertRaises(approval.ApprovalMissing):
                    approval.verify_approval(package, ApprovalAction.SEND, candidate, VERIFIED_AT)

    def test_rejects_a_record_bound_to_a_different_checksum(self):
        package = release_candidate()
        record = replace(record_for(package), package_checksum="c" * 64)

        with self.assertRaises(approval.ChecksumChanged):
            approval.verify_approval(package, ApprovalAction.SEND, record, VERIFIED_AT)

    def test_rejects_a_different_or_unknown_requested_action(self):
        package = release_candidate()
        record = record_for(package, action=ApprovalAction.ARCHIVE)

        for action in (ApprovalAction.SEND, "invented"):
            with self.subTest(action=action):
                with self.assertRaises(approval.ActionMismatch):
                    approval.verify_approval(package, action, record, VERIFIED_AT)

    def test_rejects_verification_before_approval_at_or_after_expiry_or_without_timezone(self):
        package = release_candidate()
        record = record_for(package)

        for verified_at in (
            "2026-09-01T11:59:59Z",
            "2026-09-01T13:00:00Z",
            "2026-09-01T12:30:00",
            "not-a-time",
        ):
            with self.subTest(verified_at=verified_at):
                with self.assertRaises(approval.ApprovalStale):
                    approval.verify_approval(package, ApprovalAction.SEND, record, verified_at)

    def test_public_api_exposes_only_pure_approval_verification(self):
        expected = {
            "ActionMismatch",
            "ApprovalMissing",
            "ApprovalStale",
            "ChecksumChanged",
            "PackageNotReleaseCandidate",
            "verify_approval",
        }
        self.assertEqual(approval.__all__, sorted(expected))
        self.assertEqual(
            {
                name
                for name, value in vars(approval).items()
                if not name.startswith("_") and callable(value)
            },
            expected,
        )
        self.assertEqual(
            tuple(inspect.signature(approval.verify_approval).parameters),
            ("package", "requested_action", "approval", "verified_at"),
        )


if __name__ == "__main__":
    unittest.main()
