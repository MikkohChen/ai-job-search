import unittest

from car_job_search.contracts import EvidenceStatus
from car_job_search.projection.service import (
    ConflictingCanonicalClaim,
    DuplicateEvidenceId,
    MissingRequiredArtifact,
    ProjectionDrift,
    build_projection,
)


def synthetic_export(*, generated_at="2026-09-01T09:00:00Z"):
    return {
        "projection_id": "synthetic-projection",
        "generated_at": generated_at,
        "artifacts": [
            {"artifact_id": "career-facts", "version": "1.0.0"},
            {"artifact_id": "approved-copy", "version": "2.0.0"},
        ],
        "evidence_claims": [
            {
                "claim_id": "claim-delivery",
                "text": "Led a synthetic delivery program.",
                "evidence_ids": ["evidence-delivery"],
                "confidence": 96,
                "status": "verified",
                "source_artifact_ids": ["career-facts"],
            },
            {
                "claim_id": "claim-exploration",
                "text": "Explored a synthetic market.",
                "evidence_ids": [],
                "confidence": 0,
                "status": "unverified",
                "source_artifact_ids": ["career-facts"],
            },
        ],
        "role_targets": ["Synthetic Product Lead", "Synthetic Operator"],
        "constraints": {"work_mode": "remote"},
        "approved_modules": {"summary": "Synthetic approved summary."},
    }


class ProjectionTests(unittest.TestCase):
    def test_identical_normalized_exports_have_a_deterministic_checksum(self):
        first = synthetic_export(generated_at="2026-09-01T09:00:00Z")
        second = synthetic_export(generated_at="2026-09-01T10:00:00Z")
        second["artifacts"].reverse()
        second["evidence_claims"].reverse()
        second["role_targets"].reverse()

        projection_one = build_projection(first)
        projection_two = build_projection(second)

        self.assertEqual(projection_one.checksum, projection_two.checksum)
        self.assertNotEqual(projection_one.generated_at, projection_two.generated_at)

    def test_nested_constraint_maps_and_arrays_are_deterministic(self):
        first = synthetic_export()
        first["constraints"] = {
            "preferences": {"regions": ["NYC", "Remote"], "travel": {"maximum": 20}},
            "priorities": ["first", "second"],
        }
        second = synthetic_export()
        second["constraints"] = {
            "priorities": ["second", "first"],
            "preferences": {"travel": {"maximum": 20}, "regions": ["Remote", "NYC"]},
        }

        projection_one = build_projection(first)
        projection_two = build_projection(second)

        self.assertEqual(projection_one.checksum, projection_two.checksum)
        self.assertEqual(projection_one.constraints["priorities"], ("first", "second"))

    def test_each_admitted_artifact_requires_a_source_version(self):
        source = synthetic_export()
        del source["artifacts"][1]["version"]

        with self.assertRaises(MissingRequiredArtifact):
            build_projection(source)

    def test_duplicate_evidence_ids_across_claims_fail_closed(self):
        source = synthetic_export()
        source["evidence_claims"][1]["evidence_ids"] = ["evidence-delivery"]

        with self.assertRaises(DuplicateEvidenceId):
            build_projection(source)

    def test_conflicting_normalized_canonical_claims_fail_closed(self):
        source = synthetic_export()
        source["evidence_claims"].append(
            {
                "claim_id": "claim-delivery-revision",
                "text": "  led  a SYNTHETIC delivery program. ",
                "evidence_ids": ["evidence-revision"],
                "confidence": 96,
                "status": "verified",
                "source_artifact_ids": ["career-facts"],
            }
        )

        with self.assertRaises(ConflictingCanonicalClaim):
            build_projection(source)

    def test_conflicting_metric_claims_emit_a_machine_readable_verification_item(self):
        source = synthetic_export()
        source["evidence_claims"] = [
            {
                "claim_id": "claim-metric-one",
                "text": "Improved synthetic onboarding by 30%.",
                "evidence_ids": ["evidence-metric-one"],
                "confidence": 96,
                "status": "verified",
                "source_artifact_ids": ["career-facts"],
            },
            {
                "claim_id": "claim-metric-two",
                "text": "Improved synthetic onboarding by 35%.",
                "evidence_ids": ["evidence-metric-two"],
                "confidence": 96,
                "status": "verified",
                "source_artifact_ids": ["career-facts"],
            },
        ]

        with self.assertRaises(ConflictingCanonicalClaim) as raised:
            build_projection(source)

        self.assertEqual(raised.exception.verification_item["code"], "conflicting_canonical_claim")
        self.assertEqual(raised.exception.verification_item["claim_ids"], ("claim-metric-one", "claim-metric-two"))

    def test_unverified_claims_remain_explicitly_unverified(self):
        projection = build_projection(synthetic_export())
        claim = next(claim for claim in projection.evidence_claims if claim.claim_id == "claim-exploration")

        self.assertEqual(claim.status, EvidenceStatus.UNVERIFIED)
        self.assertEqual(claim.evidence_ids, ())

    def test_projection_package_exports_only_the_approved_callable_surface(self):
        import car_job_search.projection as projection

        expected = (
            "ConflictingCanonicalClaim",
            "DuplicateEvidenceId",
            "MissingRequiredArtifact",
            "ProjectionDrift",
            "build_projection",
        )
        public_callables = {
            name for name, value in vars(projection).items() if not name.startswith("_") and callable(value)
        }

        self.assertEqual(projection.__all__, list(expected))
        self.assertEqual(public_callables, set(expected))

    def test_expected_checksum_mismatch_raises_projection_drift(self):
        source = synthetic_export()
        source["expected_checksum"] = "0" * 64

        with self.assertRaises(ProjectionDrift):
            build_projection(source)


if __name__ == "__main__":
    unittest.main()
