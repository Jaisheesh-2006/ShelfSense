"""Event ingestion endpoint — `POST /events/ingest` (acceptance-gate critical).

Design points (API_SPEC.md, ADR-0013):
- **≤500 events** per batch (enforced by the request model).
- **Partial success:** the body is accepted as raw dicts and each event is validated individually,
  so one malformed event is reported in `errors` instead of 422-ing the whole batch.
- **Idempotent by `event_id`:** re-POSTing the same events counts them as `duplicates`, never
  inserting twice (see `repository.insert_events_dedup`).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field, ValidationError
from shelfsense_common.contracts import BehaviorEvent

from shelfsense_api.db import get_session
from shelfsense_api.repository import insert_events_dedup

router = APIRouter(tags=["events"])

MAX_BATCH = 500


class IngestError(BaseModel):
    index: int
    error: str


class IngestRequest(BaseModel):
    events: list[dict[str, Any]] = Field(max_length=MAX_BATCH)


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    rejected: int
    errors: list[IngestError]


def _first_error(exc: ValidationError) -> str:
    err = exc.errors()[0]
    loc = ".".join(str(part) for part in err.get("loc", ()))
    msg = err.get("msg", "invalid event")
    return f"{loc}: {msg}" if loc else msg


@router.post("/events/ingest", response_model=IngestResponse)
def ingest_events(payload: IngestRequest) -> IngestResponse:
    valid: list[BehaviorEvent] = []
    errors: list[IngestError] = []
    for index, raw in enumerate(payload.events):
        try:
            valid.append(BehaviorEvent.model_validate(raw))
        except ValidationError as exc:
            errors.append(IngestError(index=index, error=_first_error(exc)))

    accepted = duplicates = 0
    if valid:
        with get_session() as session:
            accepted, duplicates = insert_events_dedup(session, valid)

    return IngestResponse(
        accepted=accepted,
        duplicates=duplicates,
        rejected=len(errors),
        errors=errors,
    )
