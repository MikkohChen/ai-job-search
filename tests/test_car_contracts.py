import unittest
from copy import deepcopy

from car_job_search.contracts import (
    ApplicationPackage,
    ApprovalAction,
    ApprovalRecord,
    EvidenceClaim,
    EvidenceStatus,
    FindingStatus,
    FitAssessment,
    GateResult,
    GateStatus,
    InterviewPack,
    InterviewStage,
    JobPosting,
    OutcomeEvent,
    ReviewFinding,
    ReviewSeverity,
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

    def test_outcome_event_requires_uuid_and_aware_timestamp(self):
        for event_id, occurred_at in (
            ("not-a-uuid", "2026-09-01T09:00:00Z"),
            ("123e4567-e89b-12d3-a456-426614174000", "2026-09-01T09:00:00"),
        ):
            with self.subTest(event_id=event_id, occurred_at=occurred_at):
                with self.assertRaises(SchemaViolation):
                    OutcomeEvent(
                        event_id=event_id,
                        package_id="package-1",
                        event_type="approved",
                        occurred_at=occurred_at,
                        source="synthetic-test",
                        idempotency_key="event-1",
                    )

    def test_outcome_correction_requires_and_round_trips_typed_lineage(self):
        event = OutcomeEvent(
            event_id="123e4567-e89b-12d3-a456-426614174000",
            package_id="package-1",
            event_type="correction",
            occurred_at="2026-09-01T09:00:00Z",
            source="synthetic-test",
            idempotency_key="correction-1",
            evidence_ref="evidence-1",
            correction_of="123e4567-e89b-12d3-a456-426614174001",
            corrected_event_type="withdrawn",
        )

        self.assertEqual(OutcomeEvent.from_dict(event.to_dict()), event)
        for event_type, correction_of, corrected_event_type in (
            ("correction", None, "withdrawn"),
            ("approved", "123e4567-e89b-12d3-a456-426614174001", "withdrawn"),
            ("correction", "not-a-uuid", "withdrawn"),
        ):
            with self.subTest(event_type=event_type, correction_of=correction_of):
                with self.assertRaises(SchemaViolation):
                    OutcomeEvent(
                        event_id="123e4567-e89b-12d3-a456-426614174000",
                        package_id="package-1",
                        event_type=event_type,
                        occurred_at="2026-09-01T09:00:00Z",
                        source="synthetic-test",
                        idempotency_key="correction-invalid",
                        evidence_ref="evidence-1",
                        correction_of=correction_of,
                        corrected_event_type=corrected_event_type,
                    )

        with self.assertRaises(SchemaViolation):
            OutcomeEvent(
                event_id="123e4567-e89b-12d3-a456-426614174000",
                package_id="package-1",
                event_type="correction",
                occurred_at="2026-09-01T09:00:00Z",
                source="synthetic-test",
                idempotency_key="correction-without-evidence",
                correction_of="123e4567-e89b-12d3-a456-426614174001",
                corrected_event_type="withdrawn",
            )

    def test_job_posting_mapping_rejects_wrong_types_missing_fields_and_bad_formats(self):
        valid = {
            "schema_version": "1.0.0",
            "job_id": "job-1",
            "company": "Example Company",
            "role": "Example Role",
            "raw_text": "Example Company\nExample Role",
            "source_url": "https://example.com/jobs/1",
            "captured_at": "2026-09-01T09:00:00Z",
            "raw_text_hash": "b" * 64,
            "requirements": ["Python"],
            "preferred_requirements": [],
            "responsibilities": [],
            "unresolved_fields": [],
        }
        mutations = (
            ("company", 7),
            ("role", []),
            ("source_url", 7),
            ("source_url", "not a URL"),
            ("source_url", "https://[::1"),
            ("captured_at", "not a timestamp"),
            ("requirements", [7]),
        )
        for field, bad_value in mutations:
            with self.subTest(field=field, bad_value=bad_value):
                payload = {**valid, field: bad_value}
                with self.assertRaises(SchemaViolation):
                    JobPosting.from_dict(payload)

        missing = dict(valid)
        del missing["requirements"]
        with self.assertRaises(SchemaViolation):
            JobPosting.from_dict(missing)

    def test_deserializers_reject_coercion_and_required_field_defaults(self):
        claim = EvidenceClaim(
            claim_id="claim-1",
            text="Synthetic claim.",
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
            constraints={},
            approved_modules={"summary": claim.text},
            checksum="a" * 64,
        )
        assessment = FitAssessment(
            assessment_id="assessment-1",
            job_id="job-1",
            projection_checksum="a" * 64,
            gate_results=(GateResult("eligibility", GateStatus.PASS, None, "eligible"),),
            job_fit=90,
            requirements_reality=90,
            strategic_value=90,
            overall_fit=90,
            confidence=90,
            verdict=Verdict.ACT,
            evidence_refs=("evidence-1",),
        )
        package = ApplicationPackage(
            package_id="package-1",
            job_id="job-1",
            version=1,
            resume_markdown="# Resume",
            application_markdown="# Application",
            claims=(claim,),
            keywords=("Python",),
            source_manifest={"projection_checksum": "a" * 64},
            checksum="c" * 64,
        )
        finding = ReviewFinding(
            finding_id="finding-1",
            rule_id="evidence.claim",
            severity=ReviewSeverity.BLOCKING,
            status=FindingStatus.OPEN,
            artifact_ref="resume_markdown",
            message="Synthetic finding.",
        )
        approval = ApprovalRecord(
            approval_id="approval-1",
            package_checksum="d" * 64,
            action=ApprovalAction.ARCHIVE,
            approver="synthetic-reviewer",
            approved_at="2026-09-01T12:00:00Z",
        )
        outcome = OutcomeEvent(
            event_id="123e4567-e89b-12d3-a456-426614174000",
            package_id="package-1",
            event_type="approved",
            occurred_at="2026-09-01T12:00:00Z",
            source="synthetic-test",
            idempotency_key="event-1",
        )
        cases = (
            (EvidenceClaim.from_dict, claim.to_dict(), "claim_id", 7),
            (RuntimeProjection.from_dict, projection.to_dict(), "projection_id", 7),
            (GateResult.from_dict, assessment.gate_results[0].to_dict(), "name", 7),
            (FitAssessment.from_dict, assessment.to_dict(), "human_override", "false"),
            (ReviewFinding.from_dict, finding.to_dict(), "message", 7),
            (ApprovalRecord.from_dict, approval.to_dict(), "approver", 7),
            (OutcomeEvent.from_dict, outcome.to_dict(), "source", 7),
        )
        for loader, original, field, bad_value in cases:
            with self.subTest(loader=loader.__qualname__, field=field):
                payload = deepcopy(original)
                payload[field] = bad_value
                with self.assertRaises(SchemaViolation):
                    loader(payload)

        missing_review_state = package.to_dict()
        del missing_review_state["review_state"]
        with self.assertRaises(SchemaViolation):
            ApplicationPackage.from_dict(missing_review_state)


class ContractRoundTripTests(unittest.TestCase):
    def test_runtime_projection_deep_freezes_nested_mappings_and_arrays(self):
        projection = RuntimeProjection(
            projection_id="projection-1",
            generated_at="2026-09-01T09:00:00Z",
            source_versions={"artifact-1": "1.0.0"},
            evidence_claims=(),
            role_targets=(),
            constraints={"preferences": {"regions": ["NYC", "Remote"]}},
            approved_modules={"summary": "Synthetic summary."},
            checksum="a" * 64,
        )

        with self.assertRaises(TypeError):
            projection.constraints["preferences"] = {}
        with self.assertRaises(TypeError):
            projection.constraints["preferences"]["regions"] = ()
        self.assertEqual(projection.constraints["preferences"]["regions"], ("NYC", "Remote"))

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

    def test_application_package_deep_freezes_snapshot_collections(self):
        source_manifest = {"projection_checksum": "a" * 64}
        package = ApplicationPackage(
            package_id="package-1",
            job_id="job-1",
            version=1,
            resume_markdown="# Resume\n",
            application_markdown="# Application\n",
            claims=[],
            keywords=["Python"],
            source_manifest=source_manifest,
            checksum="c" * 64,
        )

        source_manifest["projection_checksum"] = "b" * 64
        self.assertEqual(package.claims, ())
        self.assertEqual(package.keywords, ("Python",))
        self.assertEqual(package.source_manifest["projection_checksum"], "a" * 64)
        with self.assertRaises(TypeError):
            package.source_manifest["projection_checksum"] = "d" * 64

    def test_review_finding_round_trip_and_evidence_immutability(self):
        finding = ReviewFinding(
            finding_id="finding-1",
            rule_id="evidence.claim",
            severity=ReviewSeverity.BLOCKING,
            status=FindingStatus.OPEN,
            artifact_ref="resume_markdown",
            message="Claim is not admitted.",
            evidence_refs=["evidence-1"],
        )

        self.assertEqual(finding.evidence_refs, ("evidence-1",))
        self.assertEqual(ReviewFinding.from_dict(finding.to_dict()), finding)

        package = ApplicationPackage(
            package_id="package-1",
            job_id="job-1",
            version=1,
            resume_markdown="# Resume\n",
            application_markdown="# Application\n",
            claims=(),
            keywords=(),
            source_manifest={"projection_checksum": "a" * 64},
            checksum="c" * 64,
            review_findings=[finding],
        )
        self.assertEqual(package.review_findings, (finding,))
        self.assertEqual(ApplicationPackage.from_dict(package.to_dict()), package)

    def test_approval_round_trip_requires_aware_ordered_timestamps(self):
        approval = ApprovalRecord(
            approval_id="approval-1",
            package_checksum="d" * 64,
            action=ApprovalAction.ARCHIVE,
            approver="synthetic-reviewer",
            approved_at="2026-09-01T12:00:00Z",
            expires_at="2026-09-01T13:00:00+00:00",
        )

        self.assertEqual(ApprovalRecord.from_dict(approval.to_dict()), approval)
        for approved_at, expires_at in (
            ("2026-09-01T12:00:00", None),
            ("not-a-time", None),
            ("2026-09-01T12:00:00Z", "2026-09-01T12:00:00Z"),
            ("2026-09-01T12:00:00Z", "2026-09-01T11:59:59Z"),
        ):
            with self.subTest(approved_at=approved_at, expires_at=expires_at):
                with self.assertRaises(SchemaViolation):
                    ApprovalRecord(
                        approval_id="approval-1",
                        package_checksum="d" * 64,
                        action=ApprovalAction.ARCHIVE,
                        approver="synthetic-reviewer",
                        approved_at=approved_at,
                        expires_at=expires_at,
                    )

    def test_interview_pack_round_trip_deep_freezes_nested_answer_maps(self):
        answers = [{"question_id": "q-1", "evidence": ["evidence-1"]}]
        pack = InterviewPack(
            interview_id="interview-1",
            package_id="package-1",
            package_checksum="a" * 64,
            stage=InterviewStage.RECRUITER,
            questions=("Tell me about the synthetic result.",),
            answer_maps=answers,
            evidence_ids=("evidence-1",),
            gap_bridges=("State the verified boundary.",),
        )

        answers[0]["evidence"].append("mutated")
        self.assertEqual(pack.answer_maps[0]["evidence"], ("evidence-1",))
        with self.assertRaises(TypeError):
            pack.answer_maps[0]["question_id"] = "changed"
        self.assertEqual(InterviewPack.from_dict(pack.to_dict()), pack)

    def test_verdict_enum_is_centralized(self):
        self.assertEqual(Verdict.ACT.value, "act")


if __name__ == "__main__":
    unittest.main()
