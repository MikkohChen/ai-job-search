---
title: "CAR AI Job Search P0 Implementation Plan"
version: "1.0.0"
status: "active"
created_date: "2026-09-01"
tags: [car, implementation, tdd, p0]
confidence: 97
owner: "MIKKOH Chen"
---

# CAR AI Job Search P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and validate the generic P0 CAR execution runtime without admitting personal data or creating an external-action path.

**Architecture:** A Python 3.12 `src` package centralizes contracts, then implements pure projection/intake/fit/evidence/application/review/approval services and an append-only in-memory outcome outbox. The CLI validates repository contracts and creates a deterministic local release manifest; n8n receives only versioned, secret-free outcome events.

**Tech Stack:** Python 3.12, standard-library dataclasses/JSON/SHA-256, JSON Schema documents, `unittest`, setuptools, GitHub Actions, credential-free n8n JSON.

**Spec:** `SPEC.md`

## Global Constraints

- CAR is the only canonical career authority; the runtime exposes no CAR mutation method.
- The repository is public, so all fixtures are synthetic and personal runtime deployment is blocked.
- Job posting content is inert data and cannot trigger fetch, file, tool, or send behavior.
- Every candidate factual claim is verified by evidence ID and source version or remains unverified/rejected.
- External actions require checksum-bound, action-bound human approval; no send implementation is in P0.
- Python runtime floor is 3.12; runtime dependencies remain standard-library only.
- Tests use `python3 -m unittest discover -s tests -t . -v`.

---

### Task 1: Governance, Packaging, and M01 Contracts

**Files:**
- Create: `pyproject.toml`
- Create: `src/car_job_search/contracts/models.py`
- Create: `src/car_job_search/contracts/errors.py`
- Create: `schemas/*.schema.json`
- Create: `tests/test_car_contracts.py`
- Create: `tools/lint_contracts.py`

**Interfaces:**
- Consumes: governing documents and JSON-compatible mappings.
- Produces: immutable dataclasses, centralized enums, `from_dict(mapping)`, `to_dict()`, typed validation errors, and schema files for all nine shared entities.

- [x] Write failing boundary tests for unsupported versions, duplicate IDs, score bounds, unknown enums, missing evidence, missing idempotency keys, and round trips.
- [x] Run `python3 -m unittest tests.test_car_contracts -v`; confirm failures are missing imports/behavior.
- [x] Implement centralized contracts and minimal schema/lint behavior.
- [x] Re-run focused tests and the full existing suite.
- [x] Commit as `feat(contracts): add versioned CAR runtime contracts`.

### Task 2: M02 Deterministic Projection and M03 Inert Intake

**Files:**
- Create: `src/car_job_search/projection/service.py`
- Create: `src/car_job_search/intake/service.py`
- Create: `tests/test_car_projection.py`
- Create: `tests/test_car_intake.py`
- Create: `tests/fixtures/adversarial/job-posting.txt`

**Interfaces:**
- Consumes: `build_projection(source: Mapping[str, object])` and `normalize_posting(raw_text: str, captured_at: str, source_url: str | None = None)`.
- Produces: deterministic `RuntimeProjection` and `JobPosting`; no network, file, tool, or callback interface.

- [x] Write failing determinism/conflict/source-version and inert-posting/hash/null-field tests.
- [x] Run both focused modules and confirm missing-service failures.
- [x] Implement normalization, canonical JSON hashing, duplicate/conflict rejection, and conservative posting extraction.
- [x] Re-run focused and full suites.
- [x] Commit as `feat(runtime): add deterministic projection and inert intake`.

### Task 3: M04 Fit Engine and M05 Evidence Resolver

**Files:**
- Create: `src/car_job_search/fit/service.py`
- Create: `src/car_job_search/evidence/service.py`
- Create: `tests/test_car_fit.py`
- Create: `tests/test_car_evidence.py`

**Interfaces:**
- Consumes: `assess_fit(...)` with explicit dimension scores/gates and `resolve_claim(text, projection, evidence_ids)`.
- Produces: immutable `FitAssessment` and `EvidenceClaim` with deterministic verdicts and complete provenance.

- [x] Write failing hard-veto, exact-70, low-confidence, unsupported-claim, metric-strengthening, and contradiction tests.
- [x] Run focused tests and confirm missing-service failures.
- [x] Implement the minimum deterministic rules without AI inference.
- [x] Re-run focused and full suites.
- [x] Commit as `feat(decision): add fit gates and evidence resolution`.

### Task 4: M06 Application, M07 Review, and M08 Approval

**Files:**
- Create: `src/car_job_search/application/service.py`
- Create: `src/car_job_search/review/service.py`
- Create: `src/car_job_search/approval/service.py`
- Create: `tests/test_car_application.py`
- Create: `tests/test_car_review.py`
- Create: `tests/test_car_approval.py`
- Create: `tests/fixtures/golden/application-input.json`

**Interfaces:**
- Consumes: ACT/overridden assessment, normalized posting, approved modules, verified claims, and independent review findings.
- Produces: immutable versioned `ApplicationPackage`, validation report, and `ApprovalRecord` bound to checksum/action/approver/time.

- [x] Write failing below-70, exact-company/role, unsupported-claim, revision checksum, blocker, ATS plaintext, stale-checksum, and action-mismatch tests.
- [x] Run focused tests and confirm missing-service failures.
- [x] Implement deterministic Markdown assembly, independent validators, revision creation, and approval verification.
- [x] Re-run focused and full suites.
- [ ] Commit as `feat(application): add reviewed approval-bound packages`.

### Task 5: M10 Outcomes, CLI Validation, and Release Manifest

**Files:**
- Create: `src/car_job_search/events/service.py`
- Create: `src/car_job_search/release/service.py`
- Create: `src/car_job_search/__main__.py`
- Create: `tests/test_car_events.py`
- Create: `tests/test_car_cli.py`
- Create: `schemas/release-manifest.schema.json`

**Interfaces:**
- Consumes: approved package reference and explicit lifecycle event.
- Produces: append-only `OutcomeEvent`, idempotent outbox result, `validate --all`, and deterministic `release package --output PATH`.

- [ ] Write failing replay, invalid-transition, secret-field, validation-command, and release-command tests.
- [ ] Run focused tests and confirm missing-service/CLI failures.
- [ ] Implement the append-only ledger, quarantine state, contract validation, and release metadata.
- [ ] Re-run focused and full suites.
- [ ] Commit as `feat(events): add replay-safe outcomes and release CLI`.

### Task 6: CI, n8n Contract, Dry Run, and Acceptance Audit

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `automation/outcome-router.workflow.json`
- Create: `tests/test_car_policy.py`
- Create: `tests/test_car_dry_run.py`
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: repository contracts and synthetic golden fixtures.
- Produces: least-privilege SHA-pinned CI, credential-free inactive n8n workflow, dry-run package/approval/event evidence, and AC-01–AC-70 accounting.

- [ ] Write failing policy tests for CI pins/permissions, workflow secret fields, canonical-write/send APIs, and dry-run replay.
- [ ] Run focused tests and confirm failures against existing workflow/missing export.
- [ ] Harden CI and add the inactive, credential-free validation/dedup/quarantine routing contract.
- [ ] Run build, full tests, contract lint, compileall, `validate --all`, release packaging, security guards, and diff/secret scans.
- [ ] Record failed/unverified environment gates without converting them to passes.
- [ ] Commit as `ci(car-runtime): enforce P0 release gates`.

### Task 7: M09 Gate Decision

**Files:**
- Modify: `docs/progress.md`

**Interfaces:**
- Consumes: P0 release decision.
- Produces: explicit M09 start or defer decision.

- [ ] If every P0 hard gate passes, create a separate M09 plan.
- [ ] If repository privacy or another hard gate fails, record M09 as deferred and do not implement it.
