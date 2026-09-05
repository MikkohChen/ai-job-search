---
title: "CAR AI Job Search Source Manifest"
version: "1.0.0"
status: "go-generic-no-go-personal-runtime"
created_date: "2026-09-01"
tags: [car, provenance, security, scan]
confidence: 98
owner: "MIKKOH Chen"
---

# CAR AI Job Search Source Manifest

## Decision

| Field | Evidence |
|---|---|
| Implementation gate | `GO_GENERIC` |
| Personal-runtime gate | `BLOCK_RELEASE` |
| Reason | `MikkohChen/ai-job-search` is a public fork; no real CAR or candidate data may enter it |
| Permitted scope | Generic runtime, synthetic fixtures, local tests, credential-free workflow export |
| Prohibited scope | Real CAR projections, resumes, contact/salary data, secrets, live external writes |

## Verified Repository State

| Field | Value |
|---|---|
| Worktree | `/Users/mikkohchen/Developer/mkkh-labs/ai-job-search-car-p0` |
| Branch | `codex/car-ai-job-search-p0` |
| P0 code commit | `f781526b07baf853eca32ec04c006e0621673d2a` |
| Origin | `MikkohChen/ai-job-search` — `PUBLIC` |
| Origin default branch | `master` |

## Sources

| Source | Version / identity | SHA-256 / commit | Authority | State |
|---|---|---|---|---|
| Implementation baseline | `MikkohChen/ai-job-search`, original public-fork baseline | `4c38f7ce4c73448e8158d78dfbed47562690cd5c` | Existing implementation | [K] |
| Upstream reference | `MadsLorentzen/ai-job-search` | `4c38f7ce4c73448e8158d78dfbed47562690cd5c` | Selective pattern source | [K] |
| Strategy | `1.0.0` | `0bdfb50fa60ecb5eeb2a0afa1ec29390efc2d16655b57bf04d574ffdf784c0de` | Product/security/KPI authority | [K] |
| Execution pack | `1.0.0` | `7c41b4c01a66e2505fed8e05de1082687257c2891f4644f26986fa51226b5291` | Implementation authority | [K] |
| GitHub Actions docs | Context7 `/websites/github_en_actions` | consulted 2026-09-01 | CI security guidance | [W 2026-09-01] |
| n8n docs | Context7 `/n8n-io/n8n-docs` | consulted 2026-09-01 | Workflow export/error guidance | [W 2026-09-01] |
| Python Packaging User Guide | Context7 `/websites/packaging_python_en` | consulted 2026-09-01 | `pyproject.toml` and build guidance | [W 2026-09-01] |

## CAR Inputs

| Artifact | Version | Admission |
|---|---|---|
| Real CAR artifacts | unknown | Not admitted: public repository |
| Synthetic test projection | `fixture-v1` | Admitted for generic verification only |

## Authority Model

| System | Authority |
|---|---|
| CAR | Canonical career truth |
| GitHub repository | Code and tests |
| Linear | Execution queue only |
| Notion | Operational/read/enrichment view only |
| n8n | Event validation, deduplication, retry, quarantine, routing only |
| Runtime | Generated, replaceable, noncanonical |

## External Dependencies

| Package / service | Purpose | Constraint | Verification |
|---|---|---|---|
| Python | Runtime | `>=3.12` | uv-managed CPython 3.12.13 is installed locally |
| setuptools | PEP 517 build backend | bounded build-system requirement | [W 2026-09-01] |
| build | Execute `python3 -m build` | dev-only | [W 2026-09-01] |
| PyYAML | Existing repository skill lint | dev-only | Existing CI requirement |
| GitHub Actions | CI | least privilege and full commit SHAs | [W 2026-09-01] |
| n8n | Outcome routing | no credentials in export; live route unverified | [W 2026-09-01] |

## Open Gaps

The canonical open-item ledger is `docs/launch-report.md`. It contains `[O-01]` through
`[O-08]` with owner, exact verification, and release impact; this manifest does not fork it.

## Decisions

| ID | Decision | Source | Confidence |
|---|---|---|---:|
| DEC-001 | Preserve CAR as the only career authority | Strategy S1-S7 | 99 |
| DEC-002 | Implement generic code only in this public fork | Foundry preflight 5.2 | 99 |
| DEC-003 | Use standard-library runtime validation; keep build/lint packages dev-only | Execution pack + dependency minimization | 97 |
| DEC-004 | Treat live n8n, Linear, Notion, and external sends as unverified and unauthorized | Strategy S5/S7 | 99 |

## SCAN Gate

| Criterion | Result |
|---|---|
| P0 source provenance | PASS — 100% named |
| Unknown source authority | PASS — no silent authority |
| Attachment integrity | PASS — v1.0.0 frontmatter and checksums recorded |
| Private-data destination safety | PASS for synthetic-only work; FAIL for personal runtime |
| Critical contradiction | PASS for generic implementation; `BLOCK_RELEASE` retained for deployment |
