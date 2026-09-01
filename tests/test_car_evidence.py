"""Acceptance tests for the deterministic P0 evidence resolver."""

from __future__ import annotations

import unittest
import inspect

import car_job_search.evidence as evidence
from car_job_search.contracts import EvidenceClaim, EvidenceStatus, RuntimeProjection
from car_job_search.evidence import ConflictingEvidence, NoEvidence, resolve_claim


def _projection(*claims: EvidenceClaim) -> RuntimeProjection:
    return RuntimeProjection(
        projection_id="projection-evidence-1",
        generated_at="2026-09-01T12:00:00Z",
        source_versions={"resume": "1.0.0", "case-study": "2.0.0"},
        evidence_claims=claims,
        role_targets=("data engineer",),
        constraints={},
        approved_modules={},
        checksum="a" * 64,
    )


class ResolveClaimTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metric_claim = EvidenceClaim(
            claim_id="claim-metric-30",
            text="Reduced processing time by 30%.",
            evidence_ids=("evidence-metric-30",),
            confidence=98,
            status=EvidenceStatus.VERIFIED,
            source_versions=("case-study@2.0.0",),
        )
        self.ownership_claim = EvidenceClaim(
            claim_id="claim-ownership",
            text="Owned the customer migration.",
            evidence_ids=("evidence-ownership",),
            confidence=92,
            status=EvidenceStatus.VERIFIED,
            source_versions=("resume@1.0.0",),
        )
        self.low_confidence_claim = EvidenceClaim(
            claim_id="claim-low-confidence",
            text="Managed the synthetic release.",
            evidence_ids=("evidence-low-confidence",),
            confidence=79,
            status=EvidenceStatus.VERIFIED,
            source_versions=("resume@1.0.0",),
        )
        self.multi_evidence_claim = EvidenceClaim(
            claim_id="claim-two-sources",
            text="Built the synthetic platform.",
            evidence_ids=("evidence-platform-1", "evidence-platform-2"),
            confidence=80,
            status=EvidenceStatus.VERIFIED,
            source_versions=("resume@1.0.0", "case-study@2.0.0"),
        )
        self.projection = _projection(
            self.metric_claim,
            self.ownership_claim,
            self.low_confidence_claim,
            self.multi_evidence_claim,
        )

    def test_verifies_exact_normalized_admitted_claim_with_complete_provenance(self):
        result = resolve_claim(
            "  reduced PROCESSING time by 30%.  ",
            self.projection,
            evidence_ids=("evidence-metric-30",),
        )

        self.assertEqual(result.claim_id, "claim-metric-30")
        self.assertEqual(result.text, "reduced PROCESSING time by 30%.")
        self.assertEqual(result.evidence_ids, ("evidence-metric-30",))
        self.assertEqual(result.confidence, 98)
        self.assertEqual(result.status, EvidenceStatus.VERIFIED)
        self.assertEqual(result.source_versions, ("case-study@2.0.0",))

    def test_leaves_claim_unverified_without_admitted_evidence_ids(self):
        result = resolve_claim("Reduced processing time by 30%.", self.projection)

        self.assertEqual(result.status, EvidenceStatus.UNVERIFIED)
        self.assertEqual(result.evidence_ids, ())
        self.assertEqual(result.source_versions, ())

    def test_rejects_unknown_or_metric_strengthened_evidence_claims(self):
        unknown = resolve_claim(
            "Reduced processing time by 30%.",
            self.projection,
            evidence_ids=("unknown-evidence",),
        )
        strengthened = resolve_claim(
            "Reduced processing time by 35%.",
            self.projection,
            evidence_ids=("evidence-metric-30",),
        )

        self.assertEqual(unknown.status, EvidenceStatus.REJECTED)
        self.assertEqual(strengthened.status, EvidenceStatus.REJECTED)

    def test_threshold_equality_verifies_and_below_threshold_stays_unverified(self):
        equal = resolve_claim(
            "Built the synthetic platform.",
            self.projection,
            evidence_ids=("evidence-platform-1", "evidence-platform-2"),
        )
        result = resolve_claim(
            "Managed the synthetic release.",
            self.projection,
            evidence_ids=("evidence-low-confidence",),
        )

        self.assertEqual(equal.status, EvidenceStatus.VERIFIED)
        self.assertEqual(equal.confidence, 80)
        self.assertEqual(result.status, EvidenceStatus.UNVERIFIED)
        self.assertEqual(result.confidence, 79)
        self.assertEqual(result.source_versions, ("resume@1.0.0",))

    def test_requires_review_when_ids_span_different_canonical_claims(self):
        with self.assertRaises(ConflictingEvidence):
            resolve_claim(
                "Reduced processing time by 30%.",
                self.projection,
                evidence_ids=("evidence-metric-30", "evidence-ownership"),
            )

    def test_rejects_partial_admission_of_a_canonical_evidence_set(self):
        result = resolve_claim(
            "Built the synthetic platform.",
            self.projection,
            evidence_ids=("evidence-platform-1",),
        )

        self.assertEqual(result.status, EvidenceStatus.REJECTED)

    def test_preserves_unverified_or_rejected_canonical_source_status(self):
        unverified = EvidenceClaim(
            claim_id="claim-unverified",
            text="Directed the synthetic launch.",
            evidence_ids=("evidence-unverified",),
            confidence=99,
            status=EvidenceStatus.UNVERIFIED,
            source_versions=("resume@1.0.0",),
        )
        rejected = EvidenceClaim(
            claim_id="claim-rejected",
            text="Held the synthetic credential.",
            evidence_ids=("evidence-rejected",),
            confidence=99,
            status=EvidenceStatus.REJECTED,
            source_versions=("resume@1.0.0",),
        )
        projection = _projection(unverified, rejected)

        unverified_result = resolve_claim(
            unverified.text, projection, evidence_ids=unverified.evidence_ids
        )
        rejected_result = resolve_claim(
            rejected.text, projection, evidence_ids=rejected.evidence_ids
        )

        self.assertEqual(unverified_result.status, EvidenceStatus.UNVERIFIED)
        self.assertEqual(rejected_result.status, EvidenceStatus.REJECTED)

    def test_rejects_blank_or_malformed_boundary_inputs(self):
        cases = (
            ("", self.projection, ("evidence-metric-30",)),
            (None, self.projection, ("evidence-metric-30",)),
            ("Reduced processing time by 30%.", object(), ("evidence-metric-30",)),
            ("Reduced processing time by 30%.", self.projection, "evidence-metric-30"),
            ("Reduced processing time by 30%.", self.projection, ("",)),
            ("Reduced processing time by 30%.", self.projection, ("evidence-metric-30",) * 2),
        )

        for text, projection, evidence_ids in cases:
            with self.subTest(text=text, evidence_ids=evidence_ids):
                with self.assertRaises((TypeError, ValueError)):
                    resolve_claim(text, projection, evidence_ids=evidence_ids)

    def test_detects_projection_wide_duplicate_evidence_ids_without_overwrite(self):
        duplicate = EvidenceClaim(
            claim_id="claim-duplicate-id",
            text="Different canonical claim.",
            evidence_ids=("evidence-metric-30",),
            confidence=98,
            status=EvidenceStatus.VERIFIED,
            source_versions=("resume@1.0.0",),
        )

        with self.assertRaises(ConflictingEvidence):
            resolve_claim(
                self.metric_claim.text,
                _projection(self.metric_claim, duplicate),
                evidence_ids=self.metric_claim.evidence_ids,
            )

    def test_rejected_claim_fallback_is_stable(self):
        first = resolve_claim(
            "Reduced processing time by 35%.",
            self.projection,
            evidence_ids=("evidence-metric-30",),
        )
        second = resolve_claim(
            "Reduced processing time by 35%.",
            self.projection,
            evidence_ids=("evidence-metric-30",),
        )

        self.assertEqual(first, second)

    def test_public_api_has_only_read_only_resolution_surface(self):
        self.assertEqual(
            evidence.__all__,
            ["ConflictingEvidence", "EvidenceBelowThreshold", "NoEvidence", "resolve_claim"],
        )
        self.assertEqual(
            {
                name
                for name, value in vars(evidence).items()
                if not name.startswith("_") and callable(value)
            },
            {"ConflictingEvidence", "EvidenceBelowThreshold", "NoEvidence", "resolve_claim"},
        )
        self.assertEqual(
            tuple(inspect.signature(evidence.resolve_claim).parameters),
            ("text", "projection", "evidence_ids"),
        )


if __name__ == "__main__":
    unittest.main()
