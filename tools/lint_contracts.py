#!/usr/bin/env python3
"""Lint CAR schemas, extracted contracts, and prohibited authority paths."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_FILES = {
    "application-package.schema.json",
    "approval-record.schema.json",
    "evidence-claim.schema.json",
    "fit-assessment.schema.json",
    "interview-pack.schema.json",
    "job-posting.schema.json",
    "outcome-event.schema.json",
    "review-finding.schema.json",
    "runtime-projection.schema.json",
}


def extract(pack: str, heading: str, next_header: str | None) -> str:
    start = pack.index(heading)
    end = pack.index(next_header, start) if next_header else len(pack)
    return pack[start:end].rstrip("\n-") + "\n"


def lint() -> list[str]:
    errors: list[str] = []
    schema_dir = ROOT / "schemas"
    present = {path.name for path in schema_dir.glob("*.schema.json")}
    missing = sorted(SCHEMA_FILES - present)
    if missing:
        errors.append(f"missing schemas: {', '.join(missing)}")
    for path in sorted(schema_dir.glob("*.schema.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{path.relative_to(ROOT)}: {error}")
            continue
        if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{path.relative_to(ROOT)}: wrong JSON Schema dialect")
        if value.get("properties", {}).get("schema_version", {}).get("const") != "1.0.0":
            errors.append(f"{path.relative_to(ROOT)}: schema_version must be const 1.0.0")
        if value.get("additionalProperties") is not False:
            errors.append(f"{path.relative_to(ROOT)}: additionalProperties must be false")
    model_files = list((ROOT / "src" / "car_job_search").rglob("*.py"))
    for path in model_files:
        if path.name == "models.py":
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"class\s+\w+\([^)]*Enum", text):
            errors.append(f"{path.relative_to(ROOT)}: shared enum authority belongs in contracts/models.py")
        if re.search(r"\b(?:write|update|mutate)_car\b", text, re.IGNORECASE):
            errors.append(f"{path.relative_to(ROOT)}: canonical CAR write API is prohibited")
    pack = (ROOT / "execution-pack-car-ai-job-search-integration.md").read_text(encoding="utf-8")
    expected = {
        ROOT / "CLAUDE.md": extract(pack, "# CLAUDE.md\n", '\n---\n\nextract_to: "./SPEC.md"'),
        ROOT / "SPEC.md": extract(pack, "# SPEC.md\n", '\n---\n\nextract_to: "./docs/RUNBOOK.md"'),
        ROOT / "docs" / "RUNBOOK.md": extract(pack, "# RUNBOOK.md\n", None),
    }
    for path, content in expected.items():
        if path.read_text(encoding="utf-8") != content:
            errors.append(f"{path.relative_to(ROOT)}: differs from execution-pack extraction")
    return errors


if __name__ == "__main__":
    failures = lint()
    if failures:
        print("\n".join(f"ERROR: {failure}" for failure in failures), file=sys.stderr)
        raise SystemExit(1)
    print(f"contract lint: OK ({len(SCHEMA_FILES)} schemas, extraction and authority checks)")
