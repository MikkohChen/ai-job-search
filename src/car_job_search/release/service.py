"""Inert repository validation and deterministic release metadata."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from car_job_search import __version__
from car_job_search.contracts import SCHEMA_VERSION


SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
RELEASE_SCHEMA_VERSION = "1.0.0"
_SOURCE_DOCUMENTS = {
    "Strategy": "strategy-car-ai-job-search-integration.md",
    "Execution pack": "execution-pack-car-ai-job-search-integration.md",
}
_CANONICAL_SCHEMA_FILES = frozenset(
    {
        "application-package.schema.json",
        "approval-record.schema.json",
        "evidence-claim.schema.json",
        "fit-assessment.schema.json",
        "interview-pack.schema.json",
        "job-posting.schema.json",
        "outcome-event.schema.json",
        "release-manifest.schema.json",
        "review-finding.schema.json",
        "runtime-projection.schema.json",
    }
)
_SCHEMA_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_SCHEMA_KEYWORDS = frozenset(
    {
        "$id",
        "$ref",
        "$schema",
        "additionalProperties",
        "allOf",
        "const",
        "default",
        "else",
        "enum",
        "format",
        "if",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "oneOf",
        "pattern",
        "properties",
        "required",
        "then",
        "type",
        "uniqueItems",
    }
)
_CARDINALITY_KEYWORDS = frozenset({"maxItems", "maxLength", "maxProperties", "minItems", "minLength", "minProperties"})
_NUMERIC_KEYWORDS = frozenset({"minimum", "maximum"})
_FORBIDDEN_PUBLIC_FUNCTION = re.compile(
    r"^(?:(?:sync|write|update|mutate)_(?:car|canonical)(?:_|$)|(?:car|canonical)_"
    r"(?:sync|write|update|mutate)(?:_|$)|apply(?:_|$)|(?:send|submit|deliver|dispatch)(?:_|$))"
)


class ReleaseRepositoryError(RuntimeError):
    """Raised when release metadata cannot be derived from the repository."""


class ReleaseDirtyTree(ReleaseRepositoryError):
    """Raised when packaging would not describe one committed repository state."""


class ReleaseOutputError(ReleaseRepositoryError):
    """Raised when the explicitly requested output cannot be safely written."""


def repository_root() -> Path:
    """Return the repository that contains this installed source tree."""
    return Path(__file__).resolve().parents[3]


def validate_repository(root_path: Path | None = None) -> list[str]:
    """Return all structural and authority validation failures without writing."""
    root = _root(root_path)
    errors = _validate_schema_documents(root)
    errors.extend(_validate_source_manifest(root))
    errors.extend(_validate_public_authority(root))
    errors.extend(_lint_extracted_contracts(root))
    return sorted(errors)


def package_release(output: Path, *, repository_root: Path | None = None) -> dict[str, Any]:
    """Write one deterministic manifest for a clean committed repository."""
    root = _root(repository_root)
    destination = _output_path(root, output)
    if not destination.parent.is_dir():
        raise ReleaseOutputError(f"output parent does not exist: {destination.parent}")
    if os.path.lexists(destination):
        try:
            os.lstat(destination)
        except FileNotFoundError:
            pass
        else:
            raise ReleaseOutputError(f"output path already exists: {destination}")
    _require_clean_repository(root)
    failures = validate_repository(root)
    if failures:
        raise ReleaseRepositoryError("release validation failed: " + "; ".join(failures))
    manifest = _release_manifest(root)
    _write_exclusive(destination, manifest)
    return manifest


def _root(value: Path | None) -> Path:
    root = (value or repository_root()).resolve()
    if not root.is_dir():
        raise ReleaseRepositoryError(f"repository root does not exist: {root}")
    return root


def _output_path(root: Path, output: Path) -> Path:
    destination = Path(output)
    return destination if destination.is_absolute() else root / destination


def _validate_schema_documents(root: Path) -> list[str]:
    schema_dir = root / "schemas"
    if not schema_dir.is_dir():
        return ["schemas: directory is missing"]
    paths = sorted(schema_dir.glob("*.schema.json"))
    errors: list[str] = []
    present = {path.name for path in paths}
    missing = sorted(_CANONICAL_SCHEMA_FILES - present)
    unknown = sorted(present - _CANONICAL_SCHEMA_FILES)
    if missing:
        errors.append("schemas: missing canonical schema documents: " + ", ".join(missing))
    if unknown:
        errors.append("schemas: unknown schema documents: " + ", ".join(unknown))
    identifiers: set[str] = set()
    documents: dict[str, dict[str, Any]] = {}
    for path in paths:
        relative = path.relative_to(root)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"{relative}: invalid JSON: {error}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{relative}: root must be an object")
            continue
        if path.name not in _CANONICAL_SCHEMA_FILES:
            continue
        documents[path.name] = value
    for name, value in sorted(documents.items()):
        relative = Path("schemas") / name
        if value.get("$schema") != SCHEMA_DIALECT:
            errors.append(f"{relative}: wrong JSON Schema dialect")
        if value.get("type") != "object":
            errors.append(f"{relative}: root type must be object")
        if value.get("additionalProperties") is not False:
            errors.append(f"{relative}: additionalProperties must be false")
        identifier = value.get("$id")
        if not isinstance(identifier, str) or not identifier:
            errors.append(f"{relative}: $id must be a non-empty string")
        elif identifier in identifiers:
            errors.append(f"schemas: duplicate $id: {identifier}")
        else:
            identifiers.add(identifier)
        properties = value.get("properties")
        version = properties.get("schema_version") if isinstance(properties, dict) else None
        if not isinstance(version, dict) or version.get("const") != SCHEMA_VERSION:
            errors.append(f"{relative}: schema_version must be const {SCHEMA_VERSION}")
        errors.extend(_validate_schema_node(value, relative, documents, value))
    return errors


def _validate_schema_node(
    value: object,
    relative: Path,
    documents: dict[str, dict[str, Any]],
    current_document: dict[str, Any],
    pointer: str = "",
) -> list[str]:
    location = f"{relative}{pointer}"
    if isinstance(value, bool):
        return []
    if not isinstance(value, dict):
        return [f"{location}: schema value must be an object or boolean"]
    errors: list[str] = []
    for key in value:
        if key not in _SCHEMA_KEYWORDS:
            errors.append(f"{location}: unsupported JSON Schema keyword: {key}")
    schema_type = value.get("type")
    if schema_type is not None and not _valid_schema_type(schema_type):
        errors.append(f"{location}: type must be a JSON Schema type")
    properties = value.get("properties")
    if properties is not None and not isinstance(properties, dict):
        errors.append(f"{location}: properties must be an object")
    required = value.get("required")
    if required is not None:
        if not isinstance(required, list) or any(not isinstance(item, str) or not item for item in required):
            errors.append(f"{location}: required must contain non-empty strings")
        elif len(required) != len(set(required)):
            errors.append(f"{location}: required fields must be unique")
        elif not isinstance(properties, dict) or any(item not in properties for item in required):
            errors.append(f"{location}: required fields must be declared properties")
    enum = value.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        errors.append(f"{location}: enum must be a non-empty array")
    pattern = value.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            errors.append(f"{location}: pattern must be a string")
        else:
            try:
                re.compile(pattern)
            except re.error:
                errors.append(f"{location}: pattern must compile")
    for key in _CARDINALITY_KEYWORDS:
        if key in value and (isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 0):
            errors.append(f"{location}: {key} must be a non-negative integer")
    for key in _NUMERIC_KEYWORDS:
        if key in value and (isinstance(value[key], bool) or not isinstance(value[key], (int, float))):
            errors.append(f"{location}: {key} must be a number")
    if _ordered_numbers_invalid(value, "minimum", "maximum"):
        errors.append(f"{location}: minimum cannot exceed maximum")
    if _ordered_numbers_invalid(value, "minLength", "maxLength"):
        errors.append(f"{location}: minLength cannot exceed maxLength")
    if _ordered_numbers_invalid(value, "minItems", "maxItems"):
        errors.append(f"{location}: minItems cannot exceed maxItems")
    if _ordered_numbers_invalid(value, "minProperties", "maxProperties"):
        errors.append(f"{location}: minProperties cannot exceed maxProperties")
    if "uniqueItems" in value and not isinstance(value["uniqueItems"], bool):
        errors.append(f"{location}: uniqueItems must be a boolean")
    if "format" in value and not isinstance(value["format"], str):
        errors.append(f"{location}: format must be a string")
    if "$ref" in value:
        errors.extend(
            _validate_reference(value["$ref"], relative, documents, current_document, pointer)
        )
    if isinstance(properties, dict):
        for name, child in properties.items():
            errors.extend(
                _validate_schema_node(child, relative, documents, current_document, f"{pointer}/properties/{name}")
            )
    for key in ("additionalProperties", "items", "if", "then", "else"):
        if key in value:
            child = value[key]
            if not isinstance(child, (bool, dict)):
                errors.append(f"{location}: {key} must be a schema")
            else:
                errors.extend(
                    _validate_schema_node(child, relative, documents, current_document, f"{pointer}/{key}")
                )
    for key in ("allOf", "oneOf"):
        if key in value:
            children = value[key]
            if not isinstance(children, list) or not children:
                errors.append(f"{location}: {key} must be a non-empty array of schemas")
            else:
                for index, child in enumerate(children):
                    errors.extend(
                        _validate_schema_node(
                            child, relative, documents, current_document, f"{pointer}/{key}/{index}"
                        )
                    )
    return errors


def _valid_schema_type(value: object) -> bool:
    if isinstance(value, str):
        return value in _SCHEMA_TYPES
    return (
        isinstance(value, list)
        and bool(value)
        and len(value) == len(set(value))
        and all(isinstance(item, str) and item in _SCHEMA_TYPES for item in value)
    )


def _ordered_numbers_invalid(value: dict[str, Any], minimum: str, maximum: str) -> bool:
    return (
        minimum in value
        and maximum in value
        and isinstance(value[minimum], (int, float))
        and not isinstance(value[minimum], bool)
        and isinstance(value[maximum], (int, float))
        and not isinstance(value[maximum], bool)
        and value[minimum] > value[maximum]
    )


def _validate_reference(
    reference: object,
    relative: Path,
    documents: dict[str, dict[str, Any]],
    current_document: dict[str, Any],
    pointer: str,
) -> list[str]:
    location = f"{relative}{pointer}"
    if not isinstance(reference, str) or not reference:
        return [f"{location}: $ref must be a non-empty local reference"]
    document_name, separator, fragment = reference.partition("#")
    if "://" in reference:
        return [f"{location}: unresolved local reference: {reference}"]
    if document_name:
        document = documents.get(document_name)
    else:
        document = current_document
    if document is None:
        return [f"{location}: unresolved local reference: {reference}"]
    if separator and fragment and not fragment.startswith("/"):
        return [f"{location}: unresolved local reference: {reference}"]
    if separator and _resolve_json_pointer(document, fragment) is _MISSING_POINTER:
        return [f"{location}: unresolved local reference: {reference}"]
    return []


_MISSING_POINTER = object()


def _resolve_json_pointer(document: object, fragment: str) -> object:
    current = document
    if not fragment:
        return current
    for raw_token in fragment[1:].split("/"):
        token = _unescape_json_pointer_token(raw_token)
        if token is None:
            return _MISSING_POINTER
        if isinstance(current, dict):
            if token not in current:
                return _MISSING_POINTER
            current = current[token]
            continue
        if isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                return _MISSING_POINTER
            index = int(token)
            if index >= len(current):
                return _MISSING_POINTER
            current = current[index]
            continue
        return _MISSING_POINTER
    return current


def _unescape_json_pointer_token(value: str) -> str | None:
    result: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "~":
            result.append(character)
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] not in {"0", "1"}:
            return None
        result.append("~" if value[index + 1] == "0" else "/")
        index += 2
    return "".join(result)


def _validate_source_manifest(root: Path) -> list[str]:
    manifest = root / "docs" / "source-manifest.md"
    if not manifest.is_file():
        return ["docs/source-manifest.md: required source manifest is missing"]
    content = manifest.read_text(encoding="utf-8")
    errors: list[str] = []
    for label, document_name in _SOURCE_DOCUMENTS.items():
        match = re.search(
            rf"^\|\s*{re.escape(label)}\s*\|.*?\|\s*`([0-9a-f]{{64}})`\s*\|",
            content,
            re.MULTILINE,
        )
        if match is None:
            errors.append(f"docs/source-manifest.md: missing SHA-256 for {label}")
            continue
        document = root / document_name
        if not document.is_file():
            errors.append(f"{document_name}: required by source manifest but missing")
            continue
        actual = _checksum(document)
        if actual != match.group(1):
            errors.append(f"{document_name}: checksum differs from docs/source-manifest.md")
    return errors


def _validate_public_authority(root: Path) -> list[str]:
    package_dir = root / "src" / "car_job_search"
    if not package_dir.is_dir():
        return ["src/car_job_search: package directory is missing"]
    errors: list[str] = []
    for path in sorted(package_dir.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as error:
            errors.append(f"{path.relative_to(root)}: cannot inspect public API: {error}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
                if _FORBIDDEN_PUBLIC_FUNCTION.match(node.name):
                    errors.append(
                        f"{path.relative_to(root)}: prohibited public authority API: {node.name}"
                    )
    return errors


def _lint_extracted_contracts(root: Path) -> list[str]:
    tool_path = root / "tools" / "lint_contracts.py"
    if not tool_path.is_file():
        return ["tools/lint_contracts.py: required contract linter is missing"]
    pack_path = root / "execution-pack-car-ai-job-search-integration.md"
    if not pack_path.is_file():
        return ["execution-pack-car-ai-job-search-integration.md: required extraction source is missing"]
    try:
        pack = pack_path.read_text(encoding="utf-8")
        expected = {
            root / "CLAUDE.md": _extract(pack, "# CLAUDE.md\n", '\n---\n\nextract_to: "./SPEC.md"'),
            root / "SPEC.md": _extract(pack, "# SPEC.md\n", '\n---\n\nextract_to: "./docs/RUNBOOK.md"'),
            root / "docs" / "RUNBOOK.md": _extract(pack, "# RUNBOOK.md\n", None),
        }
    except ValueError:
        return ["execution-pack-car-ai-job-search-integration.md: required extraction boundary is missing"]
    errors: list[str] = []
    for path, content in expected.items():
        if not path.is_file():
            errors.append(f"{path.relative_to(root)}: required extraction document is missing")
        elif path.read_text(encoding="utf-8") != content:
            errors.append(f"{path.relative_to(root)}: differs from execution-pack extraction")
    for path in (root / "src" / "car_job_search").rglob("*.py"):
        if path.name != "models.py" and re.search(r"class\s+\w+\([^)]*Enum", path.read_text(encoding="utf-8")):
            errors.append(f"{path.relative_to(root)}: shared enum authority belongs in contracts/models.py")
    return errors


def _extract(pack: str, heading: str, next_header: str | None) -> str:
    start = pack.index(heading)
    end = pack.index(next_header, start) if next_header else len(pack)
    return pack[start:end].rstrip("\n-") + "\n"


def _require_clean_repository(root: Path) -> None:
    status = _git(root, "status", "--porcelain")
    if status:
        raise ReleaseDirtyTree("repository has uncommitted changes")


def _release_manifest(root: Path) -> dict[str, Any]:
    schema_versions = {
        path.name: _schema_version(path)
        for path in sorted((root / "schemas").glob("*.schema.json"))
    }
    source_checksums = _source_checksums(root)
    return {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "commit_sha": _git(root, "rev-parse", "HEAD"),
        "contract_versions": {"car_job_search": __version__},
        "schema_versions": schema_versions,
        "test_summary": {
            "command": "python3 -m unittest discover -s tests -t . -v",
            "evidence": "not recorded in deterministic release metadata",
            "status": "unverified",
        },
        "projection_contract_version": _schema_version(
            root / "schemas" / "runtime-projection.schema.json"
        ),
        "known_limitations": [
            "external sends are not implemented",
            "personal runtime release remains blocked pending private repository verification",
            "real CAR exports are not admitted to this repository",
        ],
        "source_checksums": source_checksums,
    }


def _source_checksums(root: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for _label, name in _SOURCE_DOCUMENTS.items():
        path = root / name
        if path.is_file():
            checksums[name] = _checksum(path)
    manifest = root / "docs" / "source-manifest.md"
    if manifest.is_file():
        checksums["docs/source-manifest.md"] = _checksum(manifest)
    return dict(sorted(checksums.items()))


def _schema_version(path: Path) -> str:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        version = value["properties"]["schema_version"]["const"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ReleaseRepositoryError(f"invalid schema version in {path}") from error
    if not isinstance(version, str):
        raise ReleaseRepositoryError(f"invalid schema version in {path}")
    return version


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_exclusive(destination: Path, manifest: dict[str, Any]) -> None:
    try:
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
        )
    except OSError as error:
        raise ReleaseOutputError(f"could not write output: {destination}") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, destination)
    except OSError as error:
        _remove_temporary(temporary)
        raise ReleaseOutputError(f"could not write output: {destination}") from error
    try:
        os.unlink(temporary)
    except OSError as error:
        _remove_temporary(temporary)
        _remove_temporary(destination)
        raise ReleaseOutputError(f"could not write output: {destination}") from error


def _remove_temporary(path: str | Path) -> None:
    try:
        if os.path.lexists(path):
            os.unlink(path)
    except OSError:
        pass


def _git(root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise ReleaseRepositoryError("git is unavailable for release metadata") from error
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise ReleaseRepositoryError(f"git metadata unavailable: {message}")
    return result.stdout.strip()
