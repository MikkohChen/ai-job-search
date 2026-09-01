"""Acceptance tests for the append-only M10 VARR package-gate ledger."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import json
from pathlib import Path
import unittest

import car_job_search.metrics as metrics
import car_job_search.review as review
from car_job_search.application.integrity import application_checksum
from car_job_search.application.service import build_application, revise_application
from car_job_search.contracts import ApprovalAction, ApprovalRecord, GateResult, GateStatus, Verdict
from car_job_search.fit import assess_fit
from car_job_search.intake import normalize_posting
from car_job_search.projection import build_projection


FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "application-input.json"
APPROVED_AT = "2026-09-01T12:00:00Z"
VERIFIED_AT = "2026-09-01T12:30:00Z"


def inputs():
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projection = build_projection(source["projection"])
    posting = normalize_posting(**source["posting"])
    assessment = assess_fit(
        projection=projection,
        posting=posting,
        gate_results=(GateResult("eligibility", GateStatus.PASS, "candidate", "eligible"),),
        job_fit=90,
        requirements_reality=90,
        strategic_value=90,
        overall_fit=90,
        confidence=90,
        evidence_refs=("evidence-delivery", "evidence-observability", "evidence-systems"),
    )
    return assessment, projection, posting


def generated():
    assessment, projection, posting = inputs()
    return build_application(
        assessment=assessment,
        projection=projection,
        posting=posting,
        claims=projection.evidence_claims,
        module_names=("summary", "experience"),
        keywords=("Python", "distributed systems"),
        max_characters=4_000,
    )


def review_inputs():
    assessment, projection, posting = inputs()
    return posting, assessment, projection


def review_report(package):
    posting, assessment, projection = review_inputs()
    return review.review_package(package, posting, assessment, projection)


def send_approval(package):
    return ApprovalRecord(
        approval_id="approval-1",
        package_checksum=package.checksum,
        action=ApprovalAction.SEND,
        approver="synthetic-reviewer",
        approved_at=APPROVED_AT,
        expires_at="2026-09-01T13:00:00Z",
    )


class PackageGateLedgerTests(unittest.TestCase):
    def approve_complete_package(self, ledger, package):
        posting, assessment, projection = review_inputs()
        report = review_report(package)
        reviewed_package = report.package
        ledger.record_review(report, posting, assessment, projection)
        ledger.record_approval(reviewed_package, send_approval(reviewed_package), VERIFIED_AT)

    def test_returns_unknown_rate_with_no_generated_packages(self):
        measurement = metrics.PackageGateLedger().measurement()

        self.assertEqual((measurement.numerator, measurement.denominator), (0, 0))
        self.assertIsNone(measurement.rate)

    def test_measures_one_fully_gated_package_as_100_percent(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        ledger.register(package, inputs()[0])
        self.approve_complete_package(ledger, package)

        self.assertEqual(ledger.measurement().rate, Decimal("100"))
        self.assertEqual(len(ledger.package_gates), 1)
        self.assertTrue(ledger.package_gates[0].ready)
        self.assertTrue(all(value is True for value in ledger.package_gates[0].gates.values()))

    def test_measures_one_of_two_fully_gated_packages_as_50_percent(self):
        ledger = metrics.PackageGateLedger()
        original = generated()
        assessment, projection, posting = inputs()
        revised = revise_application(
            original,
            assessment,
            projection,
            posting,
            projection.evidence_claims,
            ("summary", "experience"),
            ("Python", "distributed systems"),
            4_000,
        )
        ledger.register(original, assessment)
        ledger.register(revised, assessment)
        self.approve_complete_package(ledger, original)

        measurement = ledger.measurement()
        self.assertEqual((measurement.numerator, measurement.denominator), (1, 2))
        self.assertEqual(measurement.rate, Decimal("50"))

    def test_exact_generated_package_replay_is_a_no_op(self):
        ledger = metrics.PackageGateLedger()
        package = generated()

        first = ledger.register(package, inputs()[0])
        second = ledger.register(package, inputs()[0])

        self.assertIs(first, second)
        self.assertEqual(len(ledger.package_gates), 1)
        self.assertEqual(len(ledger.history), 1)

    def test_conflicting_duplicate_is_rejected_without_replacing_registered_snapshot(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        ledger.register(package, inputs()[0])
        conflicting = replace(package, application_markdown="# Conflicting package\n")
        conflicting = replace(
            conflicting,
            checksum=application_checksum(
                conflicting.package_id,
                conflicting.job_id,
                conflicting.version,
                conflicting.resume_markdown,
                conflicting.application_markdown,
                conflicting.claims,
                conflicting.keywords,
                conflicting.source_manifest,
            ),
        )

        with self.assertRaises(metrics.DuplicatePackageConflict):
            ledger.register(conflicting, inputs()[0])

        self.assertEqual(ledger.package_gates[0].package_checksum, package.checksum)

    def test_incomplete_package_remains_in_the_denominator_with_all_gate_values_visible(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        ledger.register(package, inputs()[0])

        measurement = ledger.measurement()
        gates = ledger.package_gates[0].gates
        self.assertEqual((measurement.numerator, measurement.denominator), (0, 1))
        self.assertEqual(measurement.rate, Decimal("0"))
        self.assertEqual(gates["fit"], True)
        self.assertEqual(gates["evidence"], True)
        self.assertIsNone(gates["ats"])
        self.assertIsNone(gates["reviewer"])
        self.assertIsNone(gates["approval"])

    def test_rejects_unknown_packages_and_version_or_checksum_mismatches(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        report = review_report(package)
        reviewed_package = report.package
        posting, assessment, projection = review_inputs()

        with self.assertRaises(metrics.UnknownPackage):
            ledger.record_review(report, posting, assessment, projection)

        ledger.register(package, inputs()[0])
        wrong_version = replace(reviewed_package, version=2)
        with self.assertRaises(metrics.PackageVersionMismatch):
            ledger.record_review(
                replace(report, package=wrong_version), posting, assessment, projection
            )

        ledger.record_review(report, posting, assessment, projection)
        mismatched_approval = replace(send_approval(reviewed_package), package_checksum="0" * 64)
        with self.assertRaises(metrics.PackageChecksumMismatch):
            ledger.record_approval(reviewed_package, mismatched_approval, VERIFIED_AT)

    def test_fit_gate_uses_the_linked_assessment_not_only_package_integrity(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        blocked_assessment = replace(inputs()[0], verdict=Verdict.PASS)

        snapshot = ledger.register(package, blocked_assessment)

        self.assertFalse(snapshot.gates["fit"])
        self.assertTrue(snapshot.gates["evidence"])

    def test_generation_wrapper_registers_every_package_it_builds(self):
        ledger = metrics.PackageGateLedger()
        assessment, projection, posting = inputs()

        package = ledger.generate_and_register(
            assessment,
            projection,
            posting,
            projection.evidence_claims,
            ("summary", "experience"),
            ("Python", "distributed systems"),
            4_000,
        )

        self.assertEqual(ledger.measurement().denominator, 1)
        self.assertEqual(ledger.package_gates[0].package_checksum, package.checksum)

    def test_revise_and_register_counts_the_new_package_version_before_returning_it(self):
        ledger = metrics.PackageGateLedger()
        original = generated()
        assessment, projection, posting = inputs()
        ledger.register(original, assessment)

        revised = ledger.revise_and_register(
            original,
            assessment,
            projection,
            posting,
            projection.evidence_claims,
            ("summary", "experience"),
            ("Python", "distributed systems"),
            4_000,
        )

        self.assertEqual(revised.package_id, original.package_id)
        self.assertEqual(revised.version, original.version + 1)
        self.assertEqual(ledger.measurement().denominator, 2)
        self.assertEqual({item.version for item in ledger.package_gates}, {1, 2})

    def test_revise_and_register_rejects_an_unregistered_original_without_new_entry(self):
        ledger = metrics.PackageGateLedger()
        original = generated()
        assessment, projection, posting = inputs()

        with self.assertRaises(metrics.UnknownPackage):
            ledger.revise_and_register(
                original,
                assessment,
                projection,
                posting,
                projection.evidence_claims,
                ("summary", "experience"),
                ("Python", "distributed systems"),
                4_000,
            )

        self.assertEqual(ledger.measurement().denominator, 0)

    def test_review_gate_uses_named_validator_results_from_the_review_report(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        ledger.register(package, inputs()[0])
        report = review_report(package)
        posting, assessment, projection = review_inputs()

        snapshot = ledger.record_review(report, posting, assessment, projection)

        self.assertTrue(snapshot.gates["ats"])
        self.assertTrue(snapshot.gates["reviewer"])

    def test_rejects_a_forged_real_validation_report(self):
        ledger = metrics.PackageGateLedger()
        package = generated()
        ledger.register(package, inputs()[0])
        report = review_report(package)
        posting, assessment, projection = review_inputs()
        forged = review.ValidationReport(
            report.package,
            report.findings,
            {**report.validator_results, "ats": False},
        )

        with self.assertRaises(metrics.PackageChecksumMismatch):
            ledger.record_review(forged, posting, assessment, projection)


if __name__ == "__main__":
    unittest.main()
