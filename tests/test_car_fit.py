import inspect
import unittest

import car_job_search.fit as fit
from car_job_search.contracts import (
    EvidenceClaim,
    EvidenceStatus,
    GateResult,
    GateStatus,
    RuntimeProjection,
    Verdict,
)
from car_job_search.intake.service import normalize_posting
from car_job_search.projection.service import build_projection


def projection():
    return build_projection(
        {
            "projection_id": "synthetic-projection",
            "generated_at": "2026-09-01T09:00:00Z",
            "artifacts": [{"artifact_id": "career-facts", "version": "1.0.0"}],
            "evidence_claims": [
                {
                    "claim_id": "claim-delivery",
                    "text": "Led a synthetic delivery program.",
                    "evidence_ids": ["evidence-delivery"],
                    "confidence": 96,
                    "status": "verified",
                    "source_artifact_ids": ["career-facts"],
                }
            ],
            "role_targets": ["Synthetic Product Lead"],
            "constraints": {},
            "approved_modules": {},
        }
    )


def projection_with_claim(*, projection_id, evidence_id, status):
    return build_projection(
        {
            "projection_id": projection_id,
            "generated_at": "2026-09-01T09:00:00Z",
            "artifacts": [{"artifact_id": "career-facts", "version": "1.0.0"}],
            "evidence_claims": [
                {
                    "claim_id": f"claim-{projection_id}",
                    "text": "Synthetic claim.",
                    "evidence_ids": [evidence_id],
                    "confidence": 96,
                    "status": status,
                    "source_artifact_ids": ["career-facts"],
                }
            ],
            "role_targets": ["Synthetic Product Lead"],
            "constraints": {},
            "approved_modules": {},
        }
    )


def posting():
    return normalize_posting(
        "Company: Synthetic Atlas Labs\nRole: Platform Engineer\n",
        captured_at="2026-09-01T09:00:00Z",
    )


def passing_gate():
    return GateResult(
        name="eligibility", status=GateStatus.PASS, source="candidate", reason="eligible"
    )


class FitEngineTests(unittest.TestCase):
    def assess(self, **overrides):
        values = {
            "projection": projection(),
            "posting": posting(),
            "gate_results": (passing_gate(),),
            "job_fit": 90,
            "requirements_reality": 90,
            "strategic_value": 90,
            "overall_fit": 90,
            "confidence": 90,
            "evidence_refs": ("evidence-delivery",),
            "material_gaps": (),
            "human_override": False,
        }
        values.update(overrides)
        return fit.assess_fit(**values)

    def test_failed_hard_gate_overrides_a_99_score(self):
        assessment = self.assess(
            gate_results=(
                GateResult(
                    name="work-authorization",
                    status=GateStatus.FAIL,
                    source="candidate",
                    reason="not eligible",
                ),
            ),
            overall_fit=99,
        )

        self.assertEqual(assessment.verdict, Verdict.PASS)

    def test_failed_hard_gate_overrides_a_human_override(self):
        assessment = self.assess(
            gate_results=(
                GateResult(
                    name="work-authorization",
                    status=GateStatus.FAIL,
                    source="candidate",
                    reason="not eligible",
                ),
            ),
            overall_fit=99,
            human_override=True,
        )

        self.assertEqual(assessment.verdict, Verdict.PASS)

    def test_below_70_is_pass_without_a_human_override(self):
        assessment = self.assess(overall_fit=69)

        self.assertEqual(assessment.verdict, Verdict.PASS)

    def test_unknown_or_flagged_gate_requires_consideration(self):
        assessment = self.assess(
            gate_results=(
                GateResult(
                    name="location",
                    status=GateStatus.UNKNOWN,
                    source=None,
                    reason="posting is unclear",
                ),
            )
        )

        self.assertEqual(assessment.verdict, Verdict.CONSIDER)

    def test_flagged_gate_requires_consideration(self):
        assessment = self.assess(
            gate_results=(
                GateResult(
                    name="location",
                    status=GateStatus.FLAG,
                    source="candidate",
                    reason="requires review",
                ),
            )
        )

        self.assertEqual(assessment.verdict, Verdict.CONSIDER)

    def test_material_gap_requires_consideration(self):
        assessment = self.assess(material_gaps=("required domain experience",))

        self.assertEqual(assessment.verdict, Verdict.CONSIDER)

    def test_low_confidence_requires_consideration(self):
        assessment = self.assess(confidence=79)

        self.assertEqual(assessment.verdict, Verdict.CONSIDER)

    def test_confidence_at_80_is_actionable(self):
        assessment = self.assess(confidence=80)

        self.assertEqual(assessment.verdict, Verdict.ACT)

    def test_exact_70_with_complete_evidence_is_actionable(self):
        assessment = self.assess(overall_fit=70)

        self.assertEqual(assessment.verdict, Verdict.ACT)

    def test_positive_requirements_assessment_requires_evidence_references(self):
        with self.assertRaises(fit.GateEvidenceMissing):
            self.assess(evidence_refs=())

    def test_evidence_references_must_be_non_empty_and_unique(self):
        for evidence_refs in (("",), ("evidence-delivery", "evidence-delivery")):
            with self.subTest(evidence_refs=evidence_refs):
                with self.assertRaises(fit.GateEvidenceMissing):
                    self.assess(evidence_refs=evidence_refs)

    def test_fabricated_or_cross_projection_evidence_is_rejected(self):
        for evidence_ref in ("evidence-fabricated", "evidence-other-projection"):
            with self.subTest(evidence_ref=evidence_ref):
                with self.assertRaises(fit.GateEvidenceMissing):
                    self.assess(evidence_refs=(evidence_ref,))

    def test_rejected_source_claim_cannot_satisfy_fit_evidence(self):
        rejected = projection_with_claim(
            projection_id="rejected-projection",
            evidence_id="evidence-rejected",
            status="rejected",
        )

        with self.assertRaises(fit.GateEvidenceMissing):
            self.assess(projection=rejected, evidence_refs=("evidence-rejected",))

    def test_duplicate_projection_evidence_ids_fail_the_fit_evidence_boundary(self):
        duplicate_evidence = "evidence-duplicated"
        duplicate_projection = RuntimeProjection(
            projection_id="duplicate-evidence-projection",
            generated_at="2026-09-01T09:00:00Z",
            source_versions={"career-facts": "1.0.0"},
            evidence_claims=(
                EvidenceClaim(
                    claim_id="claim-one",
                    text="First synthetic claim.",
                    evidence_ids=(duplicate_evidence,),
                    confidence=96,
                    status=EvidenceStatus.VERIFIED,
                    source_versions=("career-facts@1.0.0",),
                ),
                EvidenceClaim(
                    claim_id="claim-two",
                    text="Second synthetic claim.",
                    evidence_ids=(duplicate_evidence,),
                    confidence=96,
                    status=EvidenceStatus.VERIFIED,
                    source_versions=("career-facts@1.0.0",),
                ),
            ),
            role_targets=("Synthetic Product Lead",),
            constraints={},
            approved_modules={},
            checksum="a" * 64,
        )

        with self.assertRaises(fit.GateEvidenceMissing):
            self.assess(
                projection=duplicate_projection,
                evidence_refs=(duplicate_evidence,),
            )

    def test_score_outside_contract_range_is_rejected_by_the_service(self):
        with self.assertRaises(fit.ScoreOutOfRange):
            self.assess(overall_fit=101)

    def test_boolean_and_negative_scores_are_rejected_by_the_service(self):
        for score_name, score in (("job_fit", True), ("requirements_reality", -1)):
            with self.subTest(score_name=score_name, score=score):
                with self.assertRaises(fit.ScoreOutOfRange):
                    self.assess(**{score_name: score})

    def test_assessment_id_is_deterministic_from_posting_projection_and_decision_inputs(self):
        first = self.assess()
        second = self.assess()
        changed = self.assess(strategic_value=89)

        self.assertEqual(first.assessment_id, second.assessment_id)
        self.assertNotEqual(first.assessment_id, changed.assessment_id)
        self.assertEqual(first.job_id, posting().job_id)
        self.assertEqual(first.projection_checksum, projection().checksum)

    def test_public_api_has_no_builder_or_external_action(self):
        self.assertEqual(
            fit.__all__,
            ["AssessmentIncomplete", "GateEvidenceMissing", "ScoreOutOfRange", "assess_fit"],
        )
        self.assertEqual(
            {
                name
                for name, value in vars(fit).items()
                if not name.startswith("_") and callable(value)
            },
            {"AssessmentIncomplete", "GateEvidenceMissing", "ScoreOutOfRange", "assess_fit"},
        )
        self.assertEqual(
            tuple(inspect.signature(fit.assess_fit).parameters),
            (
                "projection",
                "posting",
                "gate_results",
                "job_fit",
                "requirements_reality",
                "strategic_value",
                "overall_fit",
                "confidence",
                "evidence_refs",
                "material_gaps",
                "human_override",
            ),
        )


if __name__ == "__main__":
    unittest.main()
