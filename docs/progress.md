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
| Phase | GUIDE |
| Current module | M04 Fit Engine + M05 Evidence Resolver |
| Current branch/worktree | `codex/car-ai-job-search-p0` / `/Users/mikkohchen/Developer/mkkh-labs/ai-job-search-car-p0` |
| Last green commit | `7e55879` |
| Overall status | Generic P0 implementation active; personal deployment `BLOCK_RELEASE` |

## Completed

| Module | Commit | Tests | Status |
|---|---|---|---|
| SCAN + M01 Contracts | `7e55879` | 10 focused; 332 full-suite; contract lint | PASS |
| M02 Projection + M03 Job Intake | pending commit | 31 focused; 353 full-suite; independent review | PASS |

## Current Failure

| Test | Cause | Owner | Next action |
|---|---|---|---|
| None | N/A | N/A | Start M02/M03 RED tests |

## Decisions

| ID | Decision | Source | Confidence |
|---|---|---|---:|
| DEC-001 | CAR remains the only career authority | Strategy S1-S7 | 99 |
| DEC-002 | Public fork receives synthetic fixtures only | Foundry preflight 5.2 | 99 |
| DEC-003 | Standard-library runtime; dev-only build/lint dependencies | Dependency policy | 97 |
| DEC-004 | M02 and M03 may run in parallel with disjoint files after M01 lock | Execution architecture 4.3 | 98 |
| DEC-005 | Constraint arrays are normalized as set-like projection inputs before semantic hashing | SPEC M02 deterministic arrays | 98 |
| DEC-006 | Missing posting sections remain empty typed tuples and are also listed as unresolved | Runbook 9.3 + explicit unknown contract | 98 |

## Rulings

| ID | Ruling | Reason | Cost if wrong |
|---|---|---|---|
| RUL-001 | Use the approved strategy/execution pack as the design review | User explicitly made them governing and prohibited stopping after a new plan | Rework if the user intended an additional design approval gate |
| RUL-002 | Use external worktree path | Project-local worktree directory is not ignored; modifying `master` would violate the FIX boundary | Manual worktree cleanup after handoff |
| RUL-003 | Use `docs/progress.md` as the SDD ledger | Required durable file is inside the declared path set; `.superpowers/` is outside it | No auto-generated SDD review package |
| RUL-004 | Do not create fetch/directive execution paths merely to make named errors reachable | A dormant typed error is safer than widening M03 authority | Named errors remain nominal until an approved fetch adapter exists |

## Open Items

| ID | Issue | Blocking | Next action |
|---|---|---:|---|
| O-01 | Public repository | Yes, personal runtime/release | Move runtime to a confirmed private repository |
| O-02 | CAR export interface unknown | Yes, real projection | Provide versioned private export |
| O-03 | n8n/Linear/Notion bindings unavailable | No, local correctness | Verify in authorized test targets after privacy gate |

## Next Exact Task

Write and run failing M04 fit and M05 evidence acceptance tests in parallel.

## Commands Verified

| Command | Last result |
|---|---|
| `python3 -m unittest tests.test_car_contracts -v` | PASS — 10 tests |
| `python3 tools/lint_contracts.py` | PASS — 9 schemas |
| `python3 -m unittest discover -s tests -t . -v` | PASS — 332 tests, 6 skips |
| `python3 -m unittest tests.test_car_projection tests.test_car_intake -v` | PASS — 20 tests |
| `python3 -m unittest discover -s tests -t . -v` after M02/M03 | PASS — 353 tests, 6 skips |
