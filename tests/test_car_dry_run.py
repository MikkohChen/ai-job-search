"""Synthetic, credential-free dry run for the inactive n8n outcome router."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import unittest

from car_job_search.application import FitGateClosed, UnsupportedClaim
from car_job_search.application.service import build_application
from car_job_search.approval import verify_approval
from car_job_search.contracts import (
    ApprovalAction,
    ApprovalRecord,
    EvidenceClaim,
    GateResult,
    GateStatus,
    OutcomeType,
    Verdict,
)
from car_job_search.events import DuplicateEvent, OutcomeLedger
from car_job_search.fit import assess_fit
from car_job_search.intake import normalize_posting
from car_job_search.metrics import PackageGateLedger
from car_job_search.projection import build_projection


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "automation" / "outcome-router.workflow.json"
FIXTURE = ROOT / "tests" / "fixtures" / "golden" / "application-input.json"
ADVERSARIAL_POSTING = ROOT / "tests" / "fixtures" / "adversarial" / "job-posting.txt"
OCCURRED_AT = "2026-09-01T13:00:00Z"
VERIFIED_AT = "2026-09-01T12:30:00Z"
ALLOWED_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "package_id",
        "event_type",
        "occurred_at",
        "source",
        "idempotency_key",
        "evidence_ref",
        "correction_of",
        "corrected_event_type",
        "payload_version",
    }
)
REQUIRED_EVENT_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "package_id",
        "event_type",
        "occurred_at",
        "source",
        "idempotency_key",
        "payload_version",
    }
)


def application_inputs():
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    projection = build_projection(source["projection"])
    posting = normalize_posting(**source["posting"])
    assessment = assess_fit(
        projection=projection,
        posting=posting,
        gate_results=(
            GateResult("eligibility", GateStatus.PASS, "synthetic", "eligible"),
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
    return projection, posting, assessment


def approved_package_and_ledger():
    projection, posting, assessment = application_inputs()
    gate_ledger = PackageGateLedger()
    package = gate_ledger.generate_and_register(
        assessment,
        projection,
        posting,
        projection.evidence_claims,
        ("summary", "experience"),
        ("Python", "distributed systems"),
        4_000,
    )
    reviewed = gate_ledger.review_and_record(package, posting, assessment, projection)
    send_approval = ApprovalRecord(
        approval_id="approval-synthetic-varr",
        package_checksum=reviewed.checksum,
        action=ApprovalAction.SEND,
        approver="synthetic-independent-reviewer",
        approved_at="2026-09-01T12:00:00Z",
        expires_at="2026-09-01T13:00:00Z",
    )
    gate_ledger.record_approval(reviewed, send_approval, VERIFIED_AT)
    measurement = gate_ledger.measurement()
    assert (measurement.numerator, measurement.denominator, measurement.rate) == (
        1,
        1,
        Decimal("100"),
    )
    approval = ApprovalRecord(
        approval_id="approval-synthetic-dry-run",
        package_checksum=reviewed.checksum,
        action=ApprovalAction.EMIT_OUTCOME,
        approver="synthetic-independent-reviewer",
        approved_at="2026-09-01T12:00:00Z",
        expires_at=None,
    )
    assert verify_approval(reviewed, ApprovalAction.EMIT_OUTCOME, approval, VERIFIED_AT) is approval
    ledger = OutcomeLedger()
    ledger.register_package(reviewed, approval, VERIFIED_AT)
    return projection, posting, assessment, reviewed, ledger


def simulate_router(
    payload: object,
    seen: dict[str, str],
    *,
    downstream_succeeds: bool = True,
) -> dict[str, object]:
    """Model the validation/dedup boundary; it deliberately has no send operation."""
    if not isinstance(payload, dict):
        return {
            "route": "manual_review",
            "state": "quarantine",
            "external_sends": 0,
            "received_type": type(payload).__name__,
        }
    forbidden = {name for name in payload if any(word in name.lower() for word in ("credential", "token", "password", "secret"))}
    unknown = set(payload).difference(ALLOWED_EVENT_FIELDS)
    missing = REQUIRED_EVENT_FIELDS.difference(payload)
    if forbidden or unknown or missing:
        return {"route": "manual_review", "state": "quarantine", "external_sends": 0}
    if payload["schema_version"] != "1.0.0" or payload["payload_version"] != "1.0.0":
        return {"route": "manual_review", "state": "quarantine", "external_sends": 0}
    if payload["event_type"] not in {item.value for item in OutcomeType}:
        return {"route": "manual_review", "state": "quarantine", "external_sends": 0}
    if any(not isinstance(payload[name], str) or not payload[name].strip() for name in REQUIRED_EVENT_FIELDS):
        return {"route": "manual_review", "state": "quarantine", "external_sends": 0}
    key = str(payload["idempotency_key"])
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    prior = seen.get(key)
    if prior == digest:
        return {"route": "no_op", "state": "replay", "external_sends": 0}
    if prior is not None:
        return {"route": "manual_review", "state": "quarantine", "external_sends": 0}
    if not downstream_succeeds:
        return {
            "route": "manual_review",
            "state": "retry_exhausted",
            "external_sends": 0,
            "retry_max_attempts": 3,
            "dead_letter_route": "manual_review",
        }
    seen[key] = digest
    return {
        "route": "operational_placeholder",
        "state": "accepted",
        "external_sends": 0,
        "retry_max_attempts": 3,
        "dead_letter_route": "manual_review",
    }


class OutcomeRouterWorkflowTests(unittest.TestCase):
    def test_export_is_inactive_credential_free_n8n_json_with_safe_routing_contract(self):
        workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))

        self.assertFalse(workflow["active"])
        self.assertEqual(workflow["meta"]["contract"], "OutcomeEvent v1")
        self.assertEqual(workflow["meta"]["live_import_runtime"], "UNVERIFIED")
        self.assertIsInstance(workflow["versionId"], str)
        self.assertEqual(workflow["settings"]["executionOrder"], "v1")
        self.assertNotIn("credentials", json.dumps(workflow).lower())
        self.assertFalse(any(node["type"].split(".")[-1] in {"linear", "notion", "httpRequest"} for node in workflow["nodes"]))

        nodes = {node["name"]: node for node in workflow["nodes"]}
        self.assertEqual(nodes["Receive OutcomeEvent"]["type"], "n8n-nodes-base.webhook")
        for name in (
            "Validate OutcomeEvent v1",
            "Deduplicate before downstream work",
            "Operational routing placeholder",
            "Record processed idempotency key",
            "Quarantine and manual review",
        ):
            self.assertEqual(nodes[name]["type"], "n8n-nodes-base.code")
        code = "\n".join(node["parameters"]["jsCode"] for node in workflow["nodes"] if node["type"] == "n8n-nodes-base.code")
        for required in (*ALLOWED_EVENT_FIELDS, "credential", "token", "password", "secret", "idempotency_key"):
            self.assertIn(required, code)
        self.assertIn("maxAttempts = 3", code)
        self.assertIn("uuidPattern", code)
        self.assertIn("validCorrection", code)
        self.assertIn("dead_letter", code)
        self.assertIn("manual_review", code)
        self.assertIn("replay_noop", code)
        dedup_code = nodes["Deduplicate before downstream work"]["parameters"]["jsCode"]
        record_code = nodes["Record processed idempotency key"]["parameters"]["jsCode"]
        self.assertNotIn("state.outcomeEventByIdempotencyKey[idempotencyKey] =", dedup_code)
        self.assertIn("state.outcomeEventByIdempotencyKey[key] =", record_code)
        self.assertEqual(
            workflow["connections"]["Operational routing placeholder"]["main"][0][0]["node"],
            "Record processed idempotency key",
        )

    def test_synthetic_dry_run_registers_one_approved_event_and_exact_replay_is_inert(self):
        _, _, assessment, package, ledger = approved_package_and_ledger()
        self.assertEqual(assessment.verdict, Verdict.ACT)
        event, outbox_record = ledger.append_outcome(
            package.package_id,
            OutcomeType.APPROVED,
            OCCURRED_AT,
            "synthetic-dry-run",
            "dry-run-approved-1",
        )
        payload = event.to_dict()
        seen: dict[str, str] = {}

        accepted = simulate_router(payload, seen)
        replay = simulate_router(payload, seen)

        self.assertEqual(len(ledger.events), 1)
        self.assertEqual(len(ledger.outbox), 1)
        self.assertEqual(outbox_record.event_id, event.event_id)
        self.assertEqual(accepted["route"], "operational_placeholder")
        self.assertEqual(replay, {"route": "no_op", "state": "replay", "external_sends": 0})
        self.assertEqual(accepted["external_sends"], 0)

    def test_router_quarantines_unknown_secret_or_conflicting_payload_without_external_send(self):
        _, _, _, package, ledger = approved_package_and_ledger()
        event, _ = ledger.append_outcome(
            package.package_id,
            OutcomeType.APPROVED,
            OCCURRED_AT,
            "synthetic-dry-run",
            "dry-run-approved-2",
        )
        payload = event.to_dict()
        seen: dict[str, str] = {}
        self.assertEqual(simulate_router(payload, seen)["state"], "accepted")

        secret_payload = {**payload, "api_token": "not-admitted"}
        conflict_payload = {**payload, "source": "different-source"}
        for candidate in (secret_payload, conflict_payload):
            with self.subTest(candidate=candidate):
                routed = simulate_router(candidate, seen)
                self.assertEqual(routed["route"], "manual_review")
                self.assertEqual(routed["state"], "quarantine")
                self.assertEqual(routed["external_sends"], 0)

    def test_router_quarantines_malformed_bodies_without_throwing_or_retaining_values(self):
        secret_value = "must-not-survive-quarantine"
        for candidate in (None, [], "text", 7, {"api_token": secret_value}):
            with self.subTest(candidate=candidate):
                routed = simulate_router(candidate, {})
                self.assertEqual(routed["route"], "manual_review")
                self.assertEqual(routed["state"], "quarantine")
                self.assertEqual(routed["external_sends"], 0)
                self.assertNotIn(secret_value, json.dumps(routed, sort_keys=True))

    def test_failed_downstream_work_does_not_consume_the_idempotency_key(self):
        _, _, _, package, ledger = approved_package_and_ledger()
        event, _ = ledger.append_outcome(
            package.package_id,
            OutcomeType.APPROVED,
            OCCURRED_AT,
            "synthetic-dry-run",
            "dry-run-approved-failure",
        )
        seen: dict[str, str] = {}

        failed = simulate_router(event.to_dict(), seen, downstream_succeeds=False)
        self.assertNotIn(event.idempotency_key, seen)
        retried = simulate_router(event.to_dict(), seen)

        self.assertEqual(failed["state"], "retry_exhausted")
        self.assertEqual(retried["state"], "accepted")
        self.assertIn(event.idempotency_key, seen)

    def test_hostile_posting_stays_inert_and_existing_fit_evidence_gates_hold(self):
        hostile = normalize_posting(
            ADVERSARIAL_POSTING.read_text(encoding="utf-8"),
            "2026-09-01T12:00:00Z",
        )
        self.assertEqual(hostile.company, "Synthetic Atlas Labs")
        self.assertEqual(hostile.role, "Platform Engineer")
        self.assertIn("rm -rf", hostile.raw_text)

        projection, posting, assessment = application_inputs()
        below_seventy = assess_fit(
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
        with self.assertRaises(FitGateClosed):
            build_application(
                below_seventy,
                projection,
                posting,
                projection.evidence_claims,
                ("summary",),
                ("Python",),
                4_000,
            )
        unsupported = replace(projection.evidence_claims[0], evidence_ids=("invented-evidence",))
        with self.assertRaises(UnsupportedClaim):
            build_application(
                assessment,
                projection,
                posting,
                (unsupported,),
                ("summary",),
                ("Python",),
                4_000,
            )


if __name__ == "__main__":
    unittest.main()
