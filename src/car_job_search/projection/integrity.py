"""Internal integrity verification for M02 projection snapshots."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from car_job_search.contracts import RuntimeProjection


def projection_integrity_valid(projection: RuntimeProjection) -> bool:
    """Return whether a projection retains its exact M02 semantic checksum."""
    if not isinstance(projection, RuntimeProjection):
        return False
    semantic_value = {
        "schema_version": projection.schema_version,
        "projection_id": projection.projection_id,
        "source_versions": _dict_value(projection.source_versions),
        "evidence_claims": [claim.to_dict() for claim in projection.evidence_claims],
        "role_targets": list(projection.role_targets),
        "constraints": _dict_value(projection.constraints),
        "approved_modules": _dict_value(projection.approved_modules),
    }
    try:
        serialized = json.dumps(
            semantic_value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        )
    except (TypeError, ValueError):
        return False
    checksum = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return checksum == projection.checksum


def _dict_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _dict_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_dict_value(item) for item in value]
    return value
