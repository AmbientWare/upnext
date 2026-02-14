"""Dead-letter queue management routes."""

import logging

from fastapi import APIRouter, HTTPException, Query
from shared.contracts import (
    DeadLetterEntryResponse,
    DeadLetterListResponse,
    DeadLetterPurgeResponse,
    ErrorResponse,
)

from server.services.dlq import (
    delete_dead_letter,
    get_dead_letter_entry,
    get_dlq_count,
    list_dead_letters,
    purge_dead_letters,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/functions/{function}/dead-letters", tags=["dead-letters"])


@router.get(
    "",
    response_model=DeadLetterListResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Redis not available."},
    },
)
async def list_function_dead_letters(
    function: str,
    limit: int = Query(100, ge=1, le=1000, description="Maximum entries to return"),
) -> DeadLetterListResponse:
    """List dead-letter entries for a function."""
    try:
        entries = await list_dead_letters(function, limit=limit)
        total = await get_dlq_count(function)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return DeadLetterListResponse(
        entries=[DeadLetterEntryResponse(**e) for e in entries],
        total=total,
        function=function,
    )


@router.delete(
    "/{entry_id}",
    response_model=DeadLetterEntryResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Entry not found."},
        503: {"model": ErrorResponse, "description": "Redis not available."},
    },
)
async def delete_function_dead_letter(
    function: str,
    entry_id: str,
) -> DeadLetterEntryResponse:
    """Delete a single dead-letter entry."""
    try:
        entry = await get_dead_letter_entry(function, entry_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="Dead-letter entry not found")
        deleted = await delete_dead_letter(function, entry_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if not deleted:
        raise HTTPException(status_code=404, detail="Dead-letter entry not found")

    return DeadLetterEntryResponse(**entry)


@router.delete(
    "",
    response_model=DeadLetterPurgeResponse,
    responses={
        503: {"model": ErrorResponse, "description": "Redis not available."},
    },
)
async def purge_function_dead_letters(function: str) -> DeadLetterPurgeResponse:
    """Purge all dead-letter entries for a function."""
    try:
        deleted = await purge_dead_letters(function)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return DeadLetterPurgeResponse(
        purged=True,
        function=function,
        deleted=deleted,
    )
