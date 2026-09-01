"""Pure, append-only outcome events and delivery bookkeeping."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import json
from typing import Final
from uuid import NAMESPACE_URL, uuid5

from car_job_search.approval import verify_approval
from car_job_search.contracts import (
    ApplicationPackage,
    ApprovalAction,
    ApprovalRecord,
    OutcomeEvent,
    OutcomeType,
)


class DuplicateEvent(ValueError):
    """Raised when an idempotency key is reused with different event data."""


class InvalidTransition(ValueError):
    """Raised when an outcome does not follow the package lifecycle."""


class UnknownPackage(ValueError):
    """Raised when no approved package is registered for an event."""


class UnknownEvent(ValueError):
    """Raised when delivery bookkeeping names no accepted event."""


class OutboxWriteFailure(RuntimeError):
    """Reserved for an outbox persistence adapter; the in-memory ledger never raises it."""


@dataclass(frozen=True)
class OutboxRecord:
    """A minimal, secret-free record eligible for replay by a delivery adapter."""

    event_id: str
    package_id: str
    payload_version: str
    delivered: bool = False


@dataclass(frozen=True)
class DeliveryAttempt:
    """An immutable delivery result; failed attempts leave the record replayable."""

    event_id: str
    succeeded: bool
    error: str | None = None


@dataclass(frozen=True)
class QuarantineRecord:
    """A visible, non-mutating record of a rejected event request."""

    reason: str
    package_id: str
    event_type: OutcomeType | str
    idempotency_key: str


_TRANSITIONS: Final[dict[OutcomeType | None, frozenset[OutcomeType]]] = {
    None: frozenset({OutcomeType.APPROVED}),
    OutcomeType.APPROVED: frozenset({OutcomeType.SUBMITTED, OutcomeType.WITHDRAWN}),
    OutcomeType.SUBMITTED: frozenset(
        {OutcomeType.INTERVIEW, OutcomeType.REJECTED, OutcomeType.WITHDRAWN}
    ),
    OutcomeType.INTERVIEW: frozenset(
        {OutcomeType.INTERVIEW, OutcomeType.OFFER, OutcomeType.REJECTED, OutcomeType.WITHDRAWN}
    ),
    OutcomeType.OFFER: frozenset(),
    OutcomeType.REJECTED: frozenset(),
    OutcomeType.WITHDRAWN: frozenset(),
}


class OutcomeLedger:
    """In-memory, append-only outcome state for explicitly approved packages only."""

    def __init__(self) -> None:
        self._packages: dict[str, ApplicationPackage] = {}
        self._events: list[OutcomeEvent] = []
        self._outbox: list[OutboxRecord] = []
        self._events_by_key: dict[str, tuple[str, OutcomeEvent, OutboxRecord]] = {}
        self._event_ids: set[str] = set()
        self._states: dict[str, OutcomeType | None] = {}
        self._approved_at: dict[str, datetime] = {}
        self._last_occurred_at: dict[str, datetime] = {}
        self._quarantine: list[QuarantineRecord] = []
        self._attempts: list[DeliveryAttempt] = []
        self._successful_attempts: dict[str, DeliveryAttempt] = {}

    @property
    def packages(self) -> tuple[ApplicationPackage, ...]:
        """Registered packages in registration order."""
        return tuple(self._packages.values())

    @property
    def events(self) -> tuple[OutcomeEvent, ...]:
        """Accepted events in append order."""
        return tuple(self._events)

    @property
    def outbox(self) -> tuple[OutboxRecord, ...]:
        """Outbox records in append order; delivered records remain present."""
        return tuple(self._outbox)

    @property
    def quarantine(self) -> tuple[QuarantineRecord, ...]:
        """Rejected event requests in append order."""
        return tuple(self._quarantine)

    @property
    def attempts(self) -> tuple[DeliveryAttempt, ...]:
        """Delivery results in append order."""
        return tuple(self._attempts)

    def register_package(
        self,
        package: ApplicationPackage,
        approval: ApprovalRecord | None,
        verified_at: str,
    ) -> ApplicationPackage:
        """Register a package only after its EMIT_OUTCOME approval verifies at ``verified_at``."""
        verified_approval = verify_approval(
            package, ApprovalAction.EMIT_OUTCOME, approval, verified_at
        )
        existing = self._packages.get(package.package_id)
        if existing is not None:
            if existing != package:
                raise DuplicateEvent("package ID is already registered with different contents")
            return existing
        self._packages[package.package_id] = package
        self._states[package.package_id] = None
        self._approved_at[package.package_id] = _aware_datetime(verified_approval.approved_at)
        return package

    def append_outcome(
        self,
        package_id: str,
        event_type: OutcomeType | str,
        occurred_at: str,
        source: str,
        idempotency_key: str,
        evidence_ref: str | None = None,
        correction_of: str | None = None,
        corrected_event_type: OutcomeType | str | None = None,
    ) -> tuple[OutcomeEvent, OutboxRecord]:
        """Append one validated event and its replayable outbox record, or return its replay."""
        _require_text("package_id", package_id)
        occurred_instant = _aware_datetime(occurred_at)
        _require_text("source", source)
        _require_text("idempotency_key", idempotency_key)
        if evidence_ref is not None:
            _require_text("evidence_ref", evidence_ref)
        try:
            outcome_type = _outcome_type(event_type)
        except InvalidTransition:
            self._quarantine.append(
                QuarantineRecord(
                    "unknown_outcome_type",
                    package_id,
                    event_type if isinstance(event_type, str) else str(event_type),
                    idempotency_key,
                )
            )
            raise

        try:
            corrected_type = _optional_outcome_type(corrected_event_type)
        except InvalidTransition:
            self._quarantine.append(
                QuarantineRecord("invalid_transition", package_id, outcome_type, idempotency_key)
            )
            raise

        canonical = _canonical_payload(
            package_id,
            outcome_type,
            occurred_at,
            source,
            idempotency_key,
            evidence_ref,
            correction_of,
            corrected_type,
        )
        prior = self._events_by_key.get(idempotency_key)
        if prior is not None:
            prior_canonical, prior_event, prior_record = prior
            if prior_canonical == canonical:
                return prior_event, prior_record
            self._quarantine.append(
                QuarantineRecord("duplicate_event", package_id, outcome_type, idempotency_key)
            )
            raise DuplicateEvent("idempotency key is already bound to different event data")

        if package_id not in self._packages:
            raise UnknownPackage(f"unknown package: {package_id}")
        if occurred_instant < self._approved_at[package_id]:
            self._reject_transition(package_id, outcome_type, idempotency_key)
        last_occurred_at = self._last_occurred_at.get(package_id)
        if last_occurred_at is not None and occurred_instant < last_occurred_at:
            self._reject_transition(package_id, outcome_type, idempotency_key)
        next_state = self._next_state(
            package_id,
            outcome_type,
            evidence_ref,
            correction_of,
            corrected_type,
            idempotency_key,
        )

        event_id = str(uuid5(NAMESPACE_URL, canonical))
        if event_id in self._event_ids:
            raise DuplicateEvent("canonical event ID already exists")
        event = OutcomeEvent(
            event_id=event_id,
            package_id=package_id,
            event_type=outcome_type,
            occurred_at=occurred_at,
            source=source,
            idempotency_key=idempotency_key,
            evidence_ref=evidence_ref,
            correction_of=correction_of,
            corrected_event_type=corrected_type,
        )
        record = OutboxRecord(event.event_id, event.package_id, event.payload_version)
        self._events.append(event)
        self._outbox.append(record)
        self._events_by_key[idempotency_key] = (canonical, event, record)
        self._event_ids.add(event_id)
        self._states[package_id] = next_state
        self._last_occurred_at[package_id] = occurred_instant
        return event, record

    def lifecycle_state(self, package_id: str) -> OutcomeType | None:
        """Return the current lifecycle state, ignoring corrections."""
        if package_id not in self._packages:
            raise UnknownPackage(f"unknown package: {package_id}")
        return self._states[package_id]

    def record_delivery(
        self,
        event_id: str,
        succeeded: bool,
        error: str | None = None,
    ) -> DeliveryAttempt:
        """Append a delivery attempt and logically mark a successful record as delivered."""
        _require_text("event_id", event_id)
        if event_id not in self._event_ids:
            raise UnknownEvent(f"unknown event: {event_id}")
        if not isinstance(succeeded, bool):
            raise ValueError("succeeded must be a boolean")
        if error is not None:
            _require_text("error", error)
        if succeeded and error is not None:
            raise ValueError("successful delivery cannot include an error")
        existing_success = self._successful_attempts.get(event_id)
        if existing_success is not None:
            if succeeded:
                return existing_success
            raise InvalidTransition("delivery is already recorded as successful")

        attempt = DeliveryAttempt(event_id, succeeded, error)
        self._attempts.append(attempt)
        if succeeded:
            for index, record in enumerate(self._outbox):
                if record.event_id == event_id:
                    self._outbox[index] = replace(record, delivered=True)
                    event = self._events[index]
                    canonical, _, _ = self._events_by_key[event.idempotency_key]
                    self._events_by_key[event.idempotency_key] = (
                        canonical,
                        event,
                        self._outbox[index],
                    )
                    self._successful_attempts[event_id] = attempt
                    break
        return attempt

    def _next_state(
        self,
        package_id: str,
        outcome_type: OutcomeType,
        evidence_ref: str | None,
        correction_of: str | None,
        corrected_event_type: OutcomeType | None,
        idempotency_key: str,
    ) -> OutcomeType:
        if outcome_type is OutcomeType.CORRECTION:
            if evidence_ref is None or correction_of is None or corrected_event_type is None:
                self._reject_transition(package_id, outcome_type, idempotency_key)
            target = self._latest_lifecycle_event(package_id)
            if target is None or target.event_id != correction_of:
                self._reject_transition(package_id, outcome_type, idempotency_key)
            state_before_target = self._state_before_event(package_id, target.event_id)
            if corrected_event_type not in _TRANSITIONS[state_before_target]:
                self._reject_transition(package_id, outcome_type, idempotency_key)
            return corrected_event_type
        if correction_of is not None or corrected_event_type is not None:
            self._reject_transition(package_id, outcome_type, idempotency_key)
        if outcome_type not in _TRANSITIONS[self._states[package_id]]:
            self._reject_transition(package_id, outcome_type, idempotency_key)
        return outcome_type

    def _latest_lifecycle_event(self, package_id: str) -> OutcomeEvent | None:
        for event in reversed(self._events):
            if event.package_id == package_id and event.event_type is not OutcomeType.CORRECTION:
                return event
        return None

    def _state_before_event(self, package_id: str, event_id: str) -> OutcomeType | None:
        state: OutcomeType | None = None
        for event in self._events:
            if event.package_id != package_id:
                continue
            if event.event_id == event_id:
                return state
            if event.event_type is OutcomeType.CORRECTION:
                state = event.corrected_event_type
            else:
                state = event.event_type
        raise UnknownEvent(f"unknown event: {event_id}")

    def _reject_transition(
        self,
        package_id: str,
        event_type: OutcomeType,
        idempotency_key: str,
    ) -> None:
        self._quarantine.append(
            QuarantineRecord("invalid_transition", package_id, event_type, idempotency_key)
        )
        raise InvalidTransition("outcome does not follow the package lifecycle")


def _canonical_payload(
    package_id: str,
    event_type: OutcomeType,
    occurred_at: str,
    source: str,
    idempotency_key: str,
    evidence_ref: str | None,
    correction_of: str | None,
    corrected_event_type: OutcomeType | None,
) -> str:
    return json.dumps(
        {
            "evidence_ref": evidence_ref,
            "corrected_event_type": (
                corrected_event_type.value if corrected_event_type is not None else None
            ),
            "correction_of": correction_of,
            "event_type": event_type.value,
            "idempotency_key": idempotency_key,
            "occurred_at": occurred_at,
            "package_id": package_id,
            "source": source,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _outcome_type(value: OutcomeType | str) -> OutcomeType:
    if isinstance(value, OutcomeType):
        return value
    try:
        return OutcomeType(value)
    except (TypeError, ValueError) as error:
        raise InvalidTransition("outcome type is not a known OutcomeType") from error


def _optional_outcome_type(value: OutcomeType | str | None) -> OutcomeType | None:
    if value is None:
        return None
    return _outcome_type(value)


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _aware_datetime(value: str) -> datetime:
    _require_text("occurred_at", value)
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError("occurred_at must be a timezone-aware ISO-8601 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("occurred_at must be a timezone-aware ISO-8601 timestamp")
    return parsed.astimezone(timezone.utc)
