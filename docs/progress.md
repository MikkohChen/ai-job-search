---
title: "CAR AI Job Search Build Progress"
version: "1.0.0"
status: "in-progress"
created_date: "2026-09-01"
tags: [car, progress, p0]
confidence: 97
owner: "MIKKOH Chen"
---

# CAR AI Job Search Build Progress

## Current State

| Field | Value |
|---|---|
| Phase | DELIVER |
| Current module | P0 acceptance complete; operational launch blocked |
| Current branch/worktree | `codex/car-ai-job-search-p0` / `/Users/mikkohchen/Developer/mkkh-labs/ai-job-search-car-p0` |
| Last green code commit | `b5e38271c53c8fe08fd5754adf2d3f9b9358b322` |
| Overall status | Generic P0 implementation complete; personal deployment `NO-GO` |

## Completed

| Module | Commit | Tests | Status |
|---|---|---|---|
| SCAN + M01 Contracts | `7e55879` | 10 focused; 332 full-suite; contract lint | PASS |
| M02 Projection + M03 Job Intake | `3e01635` | 31 focused; 353 full-suite; independent review | PASS |
| M04 Fit + M05 Evidence | `40fd93e` | 29 focused; 382 full-suite; contract lint; independent review | PASS |
| M06 Application + M07 Review + M08 Approval | `a1bf0f0` | 62 focused; 424 full-suite; contract lint; independent review | PASS |
| M10 Outcomes + validation/release CLI | `d9252fd` | 48 focused; 458 full-suite; contract lint; independent review | PASS |
| CI + VARR + inactive n8n contract | `b5e3827` | 57 focused; 487 full-suite; build/lint/validate; independent review | PASS local |

## Current Failure

| Test | Cause | Owner | Next action |
|---|---|---|---|
| Personal operational release | Public destination and unauthenticated approval authority | MIKKOH Chen | Resolve `[O-01]` and `[O-03]` in `docs/launch-report.md` |

## Decisions

| ID | Decision | Source | Confidence |
|---|---|---|---:|
| DEC-001 | CAR remains the only career authority | Strategy S1-S7 | 99 |
| DEC-002 | Public fork receives synthetic fixtures only | Foundry preflight 5.2 | 99 |
| DEC-003 | Standard-library runtime; dev-only build/lint dependencies | Dependency policy | 97 |
| DEC-004 | M02 and M03 may run in parallel with disjoint files after M01 lock | Execution architecture 4.3 | 98 |
| DEC-005 | Constraint arrays are normalized as set-like projection inputs before semantic hashing | SPEC M02 deterministic arrays | 98 |
| DEC-006 | Missing posting sections remain empty typed tuples and are also listed as unresolved | Runbook 9.3 + explicit unknown contract | 98 |
| DEC-007 | Supported generation and revision run through the VARR ledger-owned API | Foundry ST-19 | 98 |
| DEC-008 | M09 is deferred while P0 operational release is `NO-GO` | Foundry AC-M/release logic | 99 |

## Rulings

| ID | Ruling | Reason | Cost if wrong |
|---|---|---|---|
| RUL-001 | Use the approved strategy/execution pack as the design review | User explicitly made them governing and prohibited stopping after a new plan | Rework if the user intended an additional design approval gate |
| RUL-002 | Use external worktree path | Project-local worktree directory is not ignored; modifying `master` would violate the FIX boundary | Manual worktree cleanup after handoff |
| RUL-003 | Use `docs/progress.md` as the SDD ledger | Required durable file is inside the declared path set; `.superpowers/` is outside it | No auto-generated SDD review package |
| RUL-004 | Do not create fetch/directive execution paths merely to make named errors reachable | A dormant typed error is safer than widening M03 authority | Named errors remain nominal until an approved fetch adapter exists |
| RUL-005 | M04 consumes an explicit overall score instead of inventing dimension weights | The governing documents define thresholds but no aggregation formula | Caller must supply a validated overall score until CAR defines weights |
| RUL-006 | M05 verifies exact normalized claims only at P0 | Deterministic code cannot safely infer semantic paraphrase equivalence | Safe paraphrases require a separately reviewed evidence-preserving adapter |
| RUL-007 | M05 uses a fixed confidence threshold of 80 and a three-argument resolver surface | The execution plan fixes the API and SPEC fixes the critical confidence boundary | A new policy version is required to change the threshold |
| RUL-008 | P0 ATS readability means at least 80 visible ASCII alphanumeric characters per Markdown artifact | The governing documents require an objective extraction gate but specify no numeric threshold | Non-Latin or shorter valid artifacts require a policy-version change |
| RUL-009 | Projection-approved modules are CAR-approved copy, separately bound from candidate evidence claims | SPEC supplies approved modules and resolved claims as distinct M06 inputs | Module prose is trusted only while its projection checksum and rendered copy remain exact |
| RUL-010 | Blocking review findings are corrected only through immutable N+1 revision and fresh review | Same-version status replacement permits review-history bypasses | Corrections create additional package snapshots |
| RUL-011 | Package checksum binds content, review state, and ordered review history | Approval must fail after artifact or review metadata changes | Every review transition changes the package checksum |
| RUL-012 | Null approval expiry is permitted for P0 verification | ApprovalRecord explicitly specifies `expires_at/null` | Operational policy may later require a finite TTL |
| RUL-013 | M10 starts at APPROVED and uses a conservative forward-only lifecycle | M10 consumes approved packages; no broader transition graph is specified | CAR policy changes require a new event-contract version |
| RUL-014 | Correction events target the latest lifecycle event and declare a permitted replacement state | Append-only history must correct facts without rewriting prior events | Older non-latest events require a chained correction policy |
| RUL-015 | VARR is unknown at zero samples and measures every supported generated package version | A synthetic 1/1 proves instrumentation, not production performance | Production baseline requires a real approved sample |
| RUL-016 | n8n retry/dead-letter behavior remains live-runtime `UNVERIFIED` | The export is inactive and its routing node is a no-send placeholder | Authorized instance testing remains required |

## Open Items

The single reconciled ledger is `docs/launch-report.md` `[O-01]` through `[O-08]`.

## Next Exact Task

Move the personal runtime to a confirmed private repository and bind authenticated approval issuance.

## Commands Verified

| Command | Last result |
|---|---|
| `python3 -m unittest tests.test_car_contracts -v` | PASS — 10 tests |
| `python3 tools/lint_contracts.py` | PASS — 9 schemas |
| `python3 -m unittest discover -s tests -t . -v` | PASS — 332 tests, 6 skips |
| `python3 -m unittest tests.test_car_projection tests.test_car_intake -v` | PASS — 20 tests |
| `python3 -m unittest discover -s tests -t . -v` after M02/M03 | PASS — 353 tests, 6 skips |
| `python3 -m unittest tests.test_car_fit tests.test_car_evidence -v` | PASS — 29 tests |
| `python3 -m unittest discover -s tests -t . -v` after M04/M05 | PASS — 382 tests, 6 skips |
| `python3 -m unittest tests.test_car_contracts tests.test_car_projection tests.test_car_application tests.test_car_review tests.test_car_approval -v` | PASS — 62 tests |
| `python3 -m unittest discover -s tests -t . -v` after M06/M07/M08 | PASS — 424 tests, 6 skips |
| `python3 -m unittest tests.test_car_contracts tests.test_car_events tests.test_car_cli -v` | PASS — 48 tests |
| `python3 -m unittest discover -s tests -t . -v` after M10/CLI | PASS — 458 tests, 6 skips |
| `python3 -m car_job_search validate --all` | PASS — `validation: OK` |
| `python3 -m unittest tests.test_car_metrics tests.test_car_application tests.test_car_review tests.test_car_dry_run tests.test_car_policy -v` | PASS — 57 tests |
| `python3 -m unittest discover -s tests -t . -v` after Task 6 | PASS — 487 tests, 6 skips |
| `python3 tools/lint_contracts.py && python3 -m compileall -q src tests` | PASS — 9 schemas, exit 0 |
| `python3 -m build` | PASS — sdist and wheel created |
| `python3 -m car_job_search release package --output dist/release-manifest.json` | PASS — exact `b5e3827` manifest, 10 schemas |
