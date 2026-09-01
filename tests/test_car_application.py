"""Acceptance tests for the deterministic M06 application builder."""

from __future__ import annotations

import inspect
import json
from dataclasses import replace
from pathlib import Path
import unittest

import car_job_search.application as application
from car_job_search.contracts import (
    FindingStatus,
    GateResult,
    GateStatus,
    ReviewFinding,
    ReviewSeverity,
    ReviewState,
    Verdict,
)
from car_job_search.fit import assess_fit
from car_job_search.intake import normalize_posting
from car_job_search.projection import build_projection
from car_job_search.application.integrity import (
    application_checksum,
    package_integrity_valid,
    render_application_artifacts,
)


FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "application-input.json"


def inputs():
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projection = build_projection(source["projection"])
    posting = normalize_posting(**source["posting"])
    assessment = assess_fit(
        projection=projection,
        posting=posting,
        gate_results=(
            GateResult(
                name="eligibility",
                status=GateStatus.PASS,
                source="candidate",
                reason="eligible",
            ),
        ),
        job_fit=90,
        requirements_reality=90,
        strategic_value=90,
        overall_fit=90,
        confidence=90,
        evidence_refs=(
            "evidence-delivery",
            "evidence-observability",
            "evidence-systems",
        ),
    )
    return assessment, projection, posting


class ApplicationBuilderTests(unittest.TestCase):
    def build(self, **overrides):
        assessment, projection, posting = inputs()
        values = {
            "assessment": assessment,
            "projection": projection,
            "posting": posting,
            "claims": projection.evidence_claims,
            "module_names": ("summary", "experience"),
            "keywords": ("Python", "distributed systems"),
            "max_characters": 4_000,
        }
        values.update(overrides)
        return application.build_application(**values)

    def test_builds_an_immutable_evidence_backed_package(self):
        package = self.build()

        self.assertEqual(package.job_id, inputs()[2].job_id)
        self.assertEqual(package.version, 1)
        self.assertIn("# Exact Atlas", package.resume_markdown)
        self.assertIn("Platform Engineer", package.resume_markdown)
        self.assertEqual(package.keywords, ("Python", "distributed systems"))
        self.assertEqual(package.claims, inputs()[1].evidence_claims)
        self.assertEqual(
            package.source_manifest,
            {
                "assessment_id": inputs()[0].assessment_id,
                "approved_module_names": '["summary","experience"]',
                "approved_modules_checksum": package.source_manifest["approved_modules_checksum"],
                "lineage_fingerprint": package.package_id.removeprefix("package-"),
                "lineage_inputs": package.source_manifest["lineage_inputs"],
                "posting_hash": inputs()[2].raw_text_hash,
                "projection_checksum": inputs()[1].checksum,
            },
        )
        self.assertEqual(package.application_markdown.count("- "), 3)
        with self.assertRaises(TypeError):
            package.source_manifest["posting_hash"] = "mutated"

    def test_rejects_non_actionable_or_hard_failed_assessments(self):
        assessment, projection, posting = inputs()
        blocked = assess_fit(
            projection=projection,
            posting=posting,
            gate_results=(
                GateResult("authorization", GateStatus.FAIL, "candidate", "ineligible"),
            ),
            job_fit=99,
            requirements_reality=99,
            strategic_value=99,
            overall_fit=99,
            confidence=99,
            evidence_refs=(
                "evidence-delivery",
                "evidence-observability",
                "evidence-systems",
            ),
            human_override=True,
        )
        non_actionable = assess_fit(
            projection=projection,
            posting=posting,
            gate_results=assessment.gate_results,
            job_fit=69,
            requirements_reality=69,
            strategic_value=69,
            overall_fit=69,
            confidence=90,
            evidence_refs=("evidence-delivery",),
        )

        for candidate in (blocked, non_actionable):
            with self.subTest(assessment=candidate.assessment_id):
                with self.assertRaises(application.FitGateClosed):
                    self.build(assessment=candidate)

    def test_allows_an_explicit_human_override_without_a_failed_gate(self):
        assessment, projection, posting = inputs()
        override = assess_fit(
            projection=projection,
            posting=posting,
            gate_results=assessment.gate_results,
            job_fit=69,
            requirements_reality=69,
            strategic_value=69,
            overall_fit=69,
            confidence=90,
            evidence_refs=(
                "evidence-delivery",
                "evidence-observability",
                "evidence-systems",
            ),
            human_override=True,
        )

        self.assertEqual(override.verdict, Verdict.CONSIDER)
        self.assertEqual(self.build(assessment=override).version, 1)

    def test_rejects_claims_without_exact_admitted_provenance(self):
        assessment, projection, posting = inputs()
        unsupported = projection.evidence_claims[0].__class__(
            claim_id=projection.evidence_claims[0].claim_id,
            text=projection.evidence_claims[0].text,
            evidence_ids=projection.evidence_claims[0].evidence_ids,
            confidence=projection.evidence_claims[0].confidence,
            status="verified",
            source_versions=("career-facts@9.9.9",),
        )

        with self.assertRaises(application.UnsupportedClaim):
            self.build(claims=(unsupported,))

    def test_rejects_unapproved_modules_and_posting_unsourced_keywords(self):
        with self.assertRaises(application.MissingRequiredModule):
            self.build(module_names=("invented",))
        with self.assertRaises(application.UnsupportedClaim):
            self.build(keywords=("Kubernetes",))
        with self.assertRaises(application.UnsupportedClaim):
            self.build(keywords=("Pyth",))
        with self.assertRaises(application.UnsupportedClaim):
            self.build(keywords=("C",))
        with self.assertRaises(application.UnsupportedClaim):
            self.build(keywords=("Node",))

    def test_rejects_forged_posting_fields_after_inert_renormalization(self):
        assessment, projection, posting = inputs()

        with self.assertRaises(application.FitGateClosed):
            self.build(posting=replace(posting, company="Forged Atlas"))

    def test_rejects_duplicate_projection_evidence_and_unassessed_claim_evidence(self):
        assessment, projection, posting = inputs()
        duplicate = replace(
            projection.evidence_claims[0], claim_id="claim-duplicate-evidence"
        )
        duplicate_projection = replace(
            projection, evidence_claims=projection.evidence_claims + (duplicate,)
        )
        limited_assessment = assess_fit(
            projection=projection,
            posting=posting,
            gate_results=assessment.gate_results,
            job_fit=90,
            requirements_reality=90,
            strategic_value=90,
            overall_fit=90,
            confidence=90,
            evidence_refs=("evidence-delivery",),
        )

        with self.assertRaises((application.FitGateClosed, application.UnsupportedClaim)):
            self.build(projection=duplicate_projection)
        with self.assertRaises(application.UnsupportedClaim):
            self.build(assessment=limited_assessment)

    def test_rejects_a_projection_with_tampered_approved_copy_for_build_and_revision(self):
        assessment, projection, posting = inputs()
        tampered = replace(
            projection,
            approved_modules={
                **projection.approved_modules,
                "summary": "Tampered approved copy.",
            },
        )
        original = self.build()

        with self.assertRaises(application.FitGateClosed):
            self.build(projection=tampered)
        with self.assertRaises(application.FitGateClosed):
            application.revise_application(
                original,
                assessment,
                tampered,
                posting,
                projection.evidence_claims,
                ("summary", "experience"),
                ("Python", "distributed systems"),
                4_000,
            )

    def test_omits_achievement_section_when_fewer_than_three_claims_are_verified(self):
        package = self.build(claims=inputs()[1].evidence_claims[:2])

        self.assertNotIn("## Verified achievements", package.application_markdown)
        self.assertNotIn("## Verified achievements", package.resume_markdown)

    def test_rejects_packages_over_the_explicit_character_limit(self):
        with self.assertRaises(application.PackageTooLong):
            self.build(max_characters=1)

    def test_revision_creates_a_new_checksum_without_mutating_the_original(self):
        original = self.build()
        revised = application.revise_application(
            original,
            *inputs(),
            claims=inputs()[1].evidence_claims,
            module_names=("summary", "experience"),
            keywords=("Python", "distributed systems"),
            max_characters=4_000,
        )

        self.assertEqual(original.version, 1)
        self.assertEqual(revised.version, 2)
        self.assertEqual(revised.package_id, original.package_id)
        self.assertNotEqual(revised.checksum, original.checksum)
        self.assertEqual(original.checksum, self.build().checksum)

    def test_initial_identity_binds_caller_ordered_selections(self):
        original = self.build()
        assessment, projection, posting = inputs()
        changed_claims = self.build(claims=tuple(reversed(projection.evidence_claims)))
        changed_modules = self.build(module_names=("experience", "summary"))
        changed_keywords = self.build(keywords=("distributed systems", "Python"))

        self.assertEqual(changed_claims.claims, tuple(reversed(projection.evidence_claims)))
        self.assertNotEqual(original.package_id, changed_claims.package_id)
        self.assertNotEqual(original.package_id, changed_modules.package_id)
        self.assertNotEqual(original.package_id, changed_keywords.package_id)
        self.assertEqual(
            original.source_manifest["lineage_fingerprint"],
            original.package_id.removeprefix("package-"),
        )

    def test_revision_rejects_invalid_integrity_and_forged_lineage(self):
        original = self.build()
        tampered = replace(original, checksum="0" * 64)
        forged_id = "package-" + "0" * 64
        forged = replace(
            original,
            package_id=forged_id,
            checksum=application_checksum(
                forged_id,
                original.job_id,
                original.version,
                original.resume_markdown,
                original.application_markdown,
                original.claims,
                original.keywords,
                original.source_manifest,
            ),
        )

        self.assertFalse(package_integrity_valid(tampered))
        self.assertTrue(package_integrity_valid(forged))
        for candidate in (tampered, forged):
            with self.subTest(package=candidate.package_id):
                with self.assertRaises(application.PackageIntegrityError):
                    application.revise_application(
                        candidate,
                        *inputs(),
                        claims=inputs()[1].evidence_claims,
                        module_names=("summary", "experience"),
                        keywords=("Python", "distributed systems"),
                        max_characters=4_000,
                    )

    def test_checksum_binds_review_state_and_history(self):
        original = self.build()
        finding = ReviewFinding(
            finding_id="finding-history",
            rule_id="evidence.claim",
            severity=ReviewSeverity.BLOCKING,
            status=FindingStatus.OPEN,
            artifact_ref="application_markdown",
            message="A blocking finding remains.",
        )
        reviewed = replace(
            original,
            review_state=ReviewState.BLOCKED,
            review_findings=(finding,),
        )
        bound = replace(
            reviewed,
            checksum=application_checksum(
                reviewed.package_id,
                reviewed.job_id,
                reviewed.version,
                reviewed.resume_markdown,
                reviewed.application_markdown,
                reviewed.claims,
                reviewed.keywords,
                reviewed.source_manifest,
                reviewed.review_state,
                reviewed.review_findings,
            ),
        )

        self.assertFalse(package_integrity_valid(reviewed))
        self.assertTrue(package_integrity_valid(bound))
        self.assertFalse(
            package_integrity_valid(
                replace(bound, review_state=ReviewState.DRAFT, review_findings=())
            )
        )

    def test_shared_renderer_reconstructs_the_exact_package_artifacts(self):
        package = self.build()
        _, projection, posting = inputs()
        modules = tuple(
            (name, projection.approved_modules[name])
            for name in ("summary", "experience")
        )

        self.assertEqual(
            render_application_artifacts(
                posting, modules, projection.evidence_claims, package.keywords
            ),
            (package.resume_markdown, package.application_markdown),
        )

    def test_public_api_has_only_builder_errors_and_pure_build_operations(self):
        expected = {
            "FitGateClosed",
            "UnsupportedClaim",
            "MissingRequiredModule",
            "PackageTooLong",
            "PackageIntegrityError",
            "build_application",
            "revise_application",
        }
        self.assertEqual(application.__all__, sorted(expected))
        self.assertEqual(
            {
                name
                for name, value in vars(application).items()
                if not name.startswith("_") and callable(value)
            },
            expected,
        )
        self.assertEqual(
            tuple(inspect.signature(application.build_application).parameters),
            (
                "assessment",
                "projection",
                "posting",
                "claims",
                "module_names",
                "keywords",
                "max_characters",
            ),
        )


if __name__ == "__main__":
    unittest.main()
