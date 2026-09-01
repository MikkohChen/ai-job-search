import unittest

from car_job_search.contracts import (
    ApplicationPackage,
    EvidenceClaim,
    EvidenceStatus,
    FitAssessment,
    JobPosting,
    OutcomeEvent,
    RuntimeProjection,
    SchemaViolation,
    UnknownEnum,
    UnsupportedVersion,
    Verdict,
    validate_unique_ids,
)


class ContractBoundaryTests(unittest.TestCase):
    def test_rejects_scores_below_zero_and_above_one_hundred(self):
        for confidence in (-1, 101):
            with self.subTest(confidence=confidence):
                with self.assertRaises(SchemaViolation):
                    EvidenceClaim(
                        claim_id="claim-1",
                        text="Reduced processing time by 30%.",
                        evidence_ids=("evidence-1",),
                        confidence=confidence,
                        status=EvidenceStatus.VERIFIED,
                        source_versions=("artifact-1@1.0.0",),
                    )

    def test_verified_claim_requires_evidence_and_source_version(self):
        with self.assertRaisesRegex(SchemaViolation, "evidence IDs"):
            EvidenceClaim(
                claim_id="claim-1",
                text="Reduced processing time by 30%.",
                evidence_ids=(),
                confidence=95,
                status=EvidenceStatus.VERIFIED,
                source_versions=("artifact-1@1.0.0",),
            )

    def test_unsupported_contract_version_fails_closed(self):
        with self.assertRaises(UnsupportedVersion):
            EvidenceClaim.from_dict(
                {
                    "schema_version": "2.0.0",
                    "claim_id": "claim-1",
                    "text": "Synthetic claim.",
                    "evidence_ids": ["evidence-1"],
                    "confidence": 95,
                    "status": "verified",
                    "source_versions": ["artifact-1@1.0.0"],
                }
            )

    def test_unknown_enum_fails_closed(self):
        payload = {
            "schema_version": "1.0.0",
            "assessment_id": "assessment-1",
            "job_id": "job-1",
            "projection_checksum": "a" * 64,
            "gate_results": [],
            "job_fit": 90,
            "requirements_reality": 90,
            "strategic_value": 90,
            "overall_fit": 90,
            "confidence": 90,
            "verdict": "invented",
            "evidence_refs": ["evidence-1"],
            "material_gaps": [],
        }
        with self.assertRaises(UnknownEnum):
            FitAssessment.from_dict(payload)

    def test_duplicate_stable_identifiers_are_rejected(self):
        with self.assertRaisesRegex(SchemaViolation, "duplicate identifier"):
            validate_unique_ids(["claim-1", "claim-1"])

    def test_outcome_event_requires_idempotency_key(self):
        with self.assertRaisesRegex(SchemaViolation, "idempotency"):
            OutcomeEvent(
                event_id="123e4567-e89b-12d3-a456-426614174000",
                package_id="package-1",
                event_type="approved",
                occurred_at="2026-09-01T09:00:00Z",
                source="synthetic-test",
                idempotency_key="",
            )


class ContractRoundTripTests(unittest.TestCase):
    def test_runtime_projection_round_trip_retains_semantic_value(self):
        claim = EvidenceClaim(
            claim_id="claim-1",
            text="Reduced synthetic processing time by 30%.",
            evidence_ids=("evidence-1",),
            confidence=98,
            status=EvidenceStatus.VERIFIED,
            source_versions=("artifact-1@1.0.0",),
        )
        projection = RuntimeProjection(
            projection_id="projection-1",
            generated_at="2026-09-01T09:00:00Z",
            source_versions={"artifact-1": "1.0.0"},
            evidence_claims=(claim,),
            role_targets=("Synthetic Engineer",),
            constraints={"work_mode": "remote"},
            approved_modules={"summary": "Synthetic summary."},
            checksum="a" * 64,
        )
        self.assertEqual(RuntimeProjection.from_dict(projection.to_dict()), projection)

    def test_missing_posting_fields_stay_explicitly_unknown(self):
        posting = JobPosting.from_dict(
            {
                "schema_version": "1.0.0",
                "job_id": "job-1",
                "company": "Example Company",
                "role": "Example Role",
                "raw_text": "Example Company\nExample Role",
                "source_url": None,
                "captured_at": "2026-09-01T09:00:00Z",
                "raw_text_hash": "b" * 64,
                "requirements": [],
                "preferred_requirements": [],
                "responsibilities": [],
                "unresolved_fields": ["location", "compensation"],
            }
        )
        self.assertIsNone(posting.location)
        self.assertIsNone(posting.compensation)

    def test_application_package_round_trip_preserves_nested_claims(self):
        claim = EvidenceClaim(
            claim_id="claim-1",
            text="Synthetic claim.",
            evidence_ids=("evidence-1",),
            confidence=98,
            status=EvidenceStatus.VERIFIED,
            source_versions=("artifact-1@1.0.0",),
        )
        package = ApplicationPackage(
            package_id="package-1",
            job_id="job-1",
            version=1,
            resume_markdown="# Resume\n",
            application_markdown="# Application\n",
            claims=(claim,),
            keywords=("Python",),
            source_manifest={"projection_checksum": "a" * 64},
            checksum="c" * 64,
        )
        self.assertEqual(ApplicationPackage.from_dict(package.to_dict()), package)
        self.assertEqual(package.claims[0].status, EvidenceStatus.VERIFIED)

    def test_verdict_enum_is_centralized(self):
        self.assertEqual(Verdict.ACT.value, "act")


if __name__ == "__main__":
    unittest.main()
