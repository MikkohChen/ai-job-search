"""Deterministic normalization for untrusted job-posting text."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from urllib.parse import urlparse

from car_job_search.contracts import JobPosting


class EmptyPosting(ValueError):
    """Raised when a posting contains no non-whitespace text."""


class FetchDenied(ValueError):
    """Raised by callers that attempt to fetch instead of provide pasted text."""


class UntrustedDirectiveDetected(ValueError):
    """Reserved for policy layers that choose to reject untrusted directives."""


class NormalizationIncomplete(ValueError):
    """Raised when intake metadata is malformed or incomplete."""


_FIELD_LABELS = {
    "company": "company",
    "role": "role",
    "location": "location",
    "work_mode": "work mode",
    "compensation": "compensation",
    "eligibility": "eligibility",
}
_SECTION_HEADINGS = {
    "requirements": "requirements",
    "preferred_requirements": "preferred requirements",
    "responsibilities": "responsibilities",
}
_UNRESOLVED_FIELDS = tuple(_FIELD_LABELS)


def normalize_posting(
    raw_text: str, captured_at: str, source_url: str | None = None
) -> JobPosting:
    """Return an immutable record without acting on any posting content."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise EmptyPosting("posting text must be non-empty")
    _validate_captured_at(captured_at)
    _validate_source_url(source_url)

    fields, sections, headings = _extract_labeled_content(raw_text)
    raw_text_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    return JobPosting(
        job_id=f"job-{raw_text_hash}",
        company=fields["company"],
        role=fields["role"],
        raw_text=raw_text,
        source_url=source_url,
        captured_at=captured_at,
        raw_text_hash=raw_text_hash,
        location=fields["location"],
        work_mode=fields["work_mode"],
        compensation=fields["compensation"],
        eligibility=fields["eligibility"],
        requirements=sections["requirements"],
        preferred_requirements=sections["preferred_requirements"],
        responsibilities=sections["responsibilities"],
        unresolved_fields=tuple(
            name for name in _UNRESOLVED_FIELDS if fields[name] is None
        )
        + tuple(
            name for name, values in sections.items() if not values and name not in headings
        ),
    )


def _extract_labeled_content(
    raw_text: str,
) -> tuple[dict[str, str | None], dict[str, tuple[str, ...]], set[str]]:
    fields = {name: None for name in _FIELD_LABELS}
    sections: dict[str, list[str]] = {name: [] for name in _SECTION_HEADINGS}
    headings: set[str] = set()
    active_section: str | None = None
    in_metadata_header = True

    for line in raw_text.splitlines():
        stripped = line.strip()
        label, value = _split_label(stripped)
        field_name = _field_name(label)
        if in_metadata_header and field_name is not None:
            if fields[field_name] is None:
                fields[field_name] = value or None
            active_section = None
            continue

        section_name = _section_name(stripped)
        if section_name is not None:
            active_section = section_name
            headings.add(section_name)
            in_metadata_header = False
            continue

        if active_section is not None and _is_bullet(stripped):
            sections[active_section].append(_strip_bullet(stripped))
            continue

        if stripped:
            active_section = None
            in_metadata_header = False
        else:
            in_metadata_header = False

    return fields, {name: tuple(values) for name, values in sections.items()}, headings


def _split_label(line: str) -> tuple[str, str]:
    if ":" not in line:
        return line, ""
    label, value = line.split(":", 1)
    return label.strip().casefold(), value.strip()


def _field_name(label: str) -> str | None:
    for name, accepted_label in _FIELD_LABELS.items():
        if label == accepted_label:
            return name
    return None


def _section_name(line: str) -> str | None:
    heading = line.rstrip(":").strip().casefold()
    for name, accepted_heading in _SECTION_HEADINGS.items():
        if heading == accepted_heading:
            return name
    return None


def _is_bullet(line: str) -> bool:
    return bool(re.match(r"^(?:[-*]|\d+[.)])\s+\S", line))


def _strip_bullet(line: str) -> str:
    return re.sub(r"^(?:[-*]|\d+[.)])\s+", "", line).strip()


def _validate_captured_at(captured_at: str) -> None:
    if not isinstance(captured_at, str) or not captured_at.strip():
        raise NormalizationIncomplete("captured_at must be a non-empty string")
    timestamp = captured_at[:-1] + "+00:00" if captured_at.endswith("Z") else captured_at
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as error:
        raise NormalizationIncomplete(
            "captured_at must be an ISO-8601 timestamp"
        ) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise NormalizationIncomplete("captured_at must include a timezone offset")


def _validate_source_url(source_url: str | None) -> None:
    if source_url is None:
        return
    if not isinstance(source_url, str):
        raise NormalizationIncomplete("source_url must be a string or None")
    try:
        parsed = urlparse(source_url)
    except ValueError as error:
        raise NormalizationIncomplete("source_url is malformed") from error
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise NormalizationIncomplete("source_url must be an absolute HTTP(S) URL")
