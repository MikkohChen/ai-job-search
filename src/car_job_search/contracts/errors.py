"""Typed contract and runtime errors."""


class ContractError(ValueError):
    """Base error for rejected runtime contract data."""


class SchemaViolation(ContractError):
    """A payload violates a declared contract."""


class UnknownEnum(SchemaViolation):
    """A payload contains an enum value not known to this version."""


class UnsupportedVersion(SchemaViolation):
    """A payload declares an unsupported contract version."""


class DuplicateIdentifier(SchemaViolation):
    """A stable identifier occurs more than once in one scope."""
