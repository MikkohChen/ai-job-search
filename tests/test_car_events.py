"""Acceptance tests for the pure M10 outcome ledger and replayable outbox."""

from __future__ import annotations

from dataclasses import replace
import unittest
from uuid import UUID

from car_job_search.application.integrity import application_checksum
from car_job_search.contracts import (
    ApplicationPackage,
    ApprovalAction,
    ApprovalRecord,
    OutcomeType,
    ReviewState,
)
from car_job_search.events import (
    DuplicateEvent,
    InvalidTransition,
    OutcomeLedger,
    UnknownPackage,
)


CHECKSUM = "a" * 64
APPROVED_AT = "2026-09-01T12:00:00Z"
VERIFIED_AT = "2026-09-01T12:30:00+00:00"
OCCURRED_AT = "2026-09-01T13:00:00+00:00"


def approved_package(*, package_id: str = "package-1") -> ApplicationPackage:
    package = ApplicationPackage(
        package_id=package_id,
        job_id="job-1",
        version=1,
        resume_markdown="# Resume\n",
        application_markdown="# Application\n",
        claims=(),
        keywords=("Python",),
        source_manifest={"projection_checksum": CHECKSUM},
        checksum="b" * 64,
        review_state=ReviewState.RELEASE_CANDIDATE,
        review_findings=(),
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


def outcome_approval(
    package: ApplicationPackage,
    *,
    approved_at: str = APPROVED_AT,
) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id=f"approval-{package.package_id}",
        package_checksum=package.checksum,
        action=ApprovalAction.EMIT_OUTCOME,
        approver="synthetic-reviewer",
        approved_at=approved_at,
        expires_at=None,
    )


def registered_ledger() -> OutcomeLedger:
    ledger = OutcomeLedger()
    package = approved_package()
    ledger.register_package(package, outcome_approval(package), VERIFIED_AT)
    return ledger


class OutcomeLedgerTests(unittest.TestCase):
    def test_registers_only_a_package_verified_for_emit_outcome(self):
        package = approved_package()
        ledger = OutcomeLedger()

        registered = ledger.register_package(package, outcome_approval(package), VERIFIED_AT)

        self.assertIs(registered, package)
        self.assertEqual(ledger.packages, (package,))

    def test_replays_identical_event_without_duplicate_event_or_outbox_records(self):
        ledger = registered_ledger()

        first = ledger.append_outcome(
            "package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "event-1"
        )
        replay = ledger.append_outcome(
            "package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "event-1"
        )

        self.assertIs(replay[0], first[0])
        self.assertIs(replay[1], first[1])
        self.assertEqual(len(ledger.events), 1)
        self.assertEqual(len(ledger.outbox), 1)
        self.assertEqual(UUID(first[0].event_id).version, 5)

    def test_quarantines_same_idempotency_key_with_different_payload(self):
        ledger = registered_ledger()
        ledger.append_outcome("package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "event-1")

        with self.assertRaises(DuplicateEvent):
            ledger.append_outcome(
                "package-1", OutcomeType.SUBMITTED, OCCURRED_AT, "candidate", "event-1"
            )

        self.assertEqual(len(ledger.events), 1)
        self.assertEqual(ledger.quarantine[-1].reason, "duplicate_event")

    def test_quarantines_invalid_lifecycle_transition_without_appending(self):
        ledger = registered_ledger()
        ledger.append_outcome("package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "approved")

        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1", OutcomeType.OFFER, OCCURRED_AT, "candidate", "invalid-offer"
            )

        self.assertEqual([event.event_type for event in ledger.events], [OutcomeType.APPROVED])
        self.assertEqual(ledger.quarantine[-1].reason, "invalid_transition")

    def test_quarantines_unknown_outcome_types_with_the_raw_value(self):
        ledger = registered_ledger()

        with self.assertRaises(InvalidTransition):
            ledger.append_outcome("package-1", "invented", OCCURRED_AT, "candidate", "unknown-type")

        self.assertEqual(ledger.quarantine[-1].reason, "unknown_outcome_type")
        self.assertEqual(ledger.quarantine[-1].event_type, "invented")

    def test_rejects_unknown_packages_with_a_typed_error(self):
        ledger = OutcomeLedger()

        with self.assertRaises(UnknownPackage):
            ledger.append_outcome(
                "unknown-package", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "unknown"
            )

    def test_enforces_conservative_lifecycle_and_correction_evidence(self):
        ledger = registered_ledger()
        ledger.append_outcome("package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "approved")
        ledger.append_outcome("package-1", OutcomeType.SUBMITTED, OCCURRED_AT, "candidate", "submitted")
        ledger.append_outcome("package-1", OutcomeType.INTERVIEW, OCCURRED_AT, "candidate", "interview")
        offer, _ = ledger.append_outcome(
            "package-1", OutcomeType.OFFER, OCCURRED_AT, "candidate", "offer"
        )

        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1", OutcomeType.INTERVIEW, OCCURRED_AT, "candidate", "after-offer"
            )
        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1", OutcomeType.CORRECTION, OCCURRED_AT, "candidate", "bare-correction"
            )

        correction, _ = ledger.append_outcome(
            "package-1",
            OutcomeType.CORRECTION,
            OCCURRED_AT,
            "candidate",
            "evidenced-correction",
            evidence_ref="evidence-1",
            correction_of=offer.event_id,
            corrected_event_type=OutcomeType.REJECTED,
        )
        self.assertEqual(correction.event_type, OutcomeType.CORRECTION)
        self.assertEqual(correction.correction_of, offer.event_id)
        self.assertEqual(correction.corrected_event_type, OutcomeType.REJECTED)
        self.assertEqual(ledger.lifecycle_state("package-1"), OutcomeType.REJECTED)

    def test_rejects_outcomes_before_approval_or_before_last_accepted_instant(self):
        package = approved_package()
        ledger = OutcomeLedger()
        ledger.register_package(package, outcome_approval(package), VERIFIED_AT)

        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1", OutcomeType.APPROVED, "2026-09-01T11:59:59Z", "candidate", "before-approval"
            )
        self.assertEqual(ledger.quarantine[-1].reason, "invalid_transition")

        ledger.append_outcome(
            "package-1", OutcomeType.APPROVED, "2026-09-01T13:00:00Z", "candidate", "approved"
        )
        ledger.append_outcome(
            "package-1", OutcomeType.SUBMITTED, "2026-09-01T08:30:00-05:00", "candidate", "submitted"
        )
        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1", OutcomeType.INTERVIEW, "2026-09-01T13:15:00Z", "candidate", "out-of-order"
            )

        self.assertEqual(ledger.lifecycle_state("package-1"), OutcomeType.SUBMITTED)

    def test_correction_must_target_latest_lifecycle_event_and_permitted_replacement(self):
        ledger = registered_ledger()
        approved, _ = ledger.append_outcome(
            "package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "approved"
        )
        submitted, _ = ledger.append_outcome(
            "package-1", OutcomeType.SUBMITTED, OCCURRED_AT, "candidate", "submitted"
        )

        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1",
                OutcomeType.CORRECTION,
                OCCURRED_AT,
                "candidate",
                "stale-target",
                evidence_ref="evidence-1",
                correction_of=approved.event_id,
                corrected_event_type=OutcomeType.WITHDRAWN,
            )
        with self.assertRaises(InvalidTransition):
            ledger.append_outcome(
                "package-1",
                OutcomeType.CORRECTION,
                OCCURRED_AT,
                "candidate",
                "bad-replacement",
                evidence_ref="evidence-1",
                correction_of=submitted.event_id,
                corrected_event_type=OutcomeType.OFFER,
            )

    def test_rejects_drafted_even_for_an_approved_package(self):
        ledger = registered_ledger()

        with self.assertRaises(InvalidTransition):
            ledger.append_outcome("package-1", OutcomeType.DRAFTED, OCCURRED_AT, "candidate", "draft")

    def test_delivery_attempts_are_immutable_and_failures_keep_outbox_replayable(self):
        ledger = registered_ledger()
        event, record = ledger.append_outcome(
            "package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "approved"
        )

        failed = ledger.record_delivery(event.event_id, succeeded=False, error="gateway unavailable")
        self.assertFalse(ledger.outbox[0].delivered)
        self.assertEqual(failed.error, "gateway unavailable")

        succeeded = ledger.record_delivery(event.event_id, succeeded=True)
        self.assertTrue(ledger.outbox[0].delivered)
        self.assertEqual(ledger.attempts, (failed, succeeded))
        self.assertEqual(record.event_id, event.event_id)

        replayed_success = ledger.record_delivery(event.event_id, succeeded=True)
        self.assertIs(replayed_success, succeeded)
        self.assertEqual(ledger.attempts, (failed, succeeded))

        replayed_event, replayed_record = ledger.append_outcome(
            "package-1", OutcomeType.APPROVED, OCCURRED_AT, "candidate", "approved"
        )
        self.assertIs(replayed_event, event)
        self.assertTrue(replayed_record.delivered)
        self.assertIs(replayed_record, ledger.outbox[0])
        self.assertIsNot(replayed_record, record)

        with self.assertRaises(InvalidTransition):
            ledger.record_delivery(event.event_id, succeeded=False, error="contradictory retry")

    def test_requires_aware_timestamps_and_exposes_only_immutable_tuples(self):
        ledger = registered_ledger()

        with self.assertRaises(ValueError):
            ledger.append_outcome(
                "package-1", OutcomeType.APPROVED, "2026-09-01T13:00:00", "candidate", "naive"
            )

        self.assertIsInstance(ledger.events, tuple)
        self.assertIsInstance(ledger.outbox, tuple)
        self.assertIsInstance(ledger.quarantine, tuple)
        self.assertIsInstance(ledger.attempts, tuple)


if __name__ == "__main__":
    unittest.main()
