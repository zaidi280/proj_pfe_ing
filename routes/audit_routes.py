from typing import Any
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from services.auth_service import AuthUser, require_roles
from services.audit_service import count_audit_events, list_audit_events


router = APIRouter(
    prefix="/audit",
    tags=["Audit"],
)


@router.get("/comptable")
async def get_comptable_audit_trail(
    limit: int = 200,
    offset: int = 0,
    username: str | None = None,
    action: str | None = None,
    action_kind: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    _: AuthUser = Depends(require_roles("admin")),
) -> dict[str, Any]:
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be >= 0")

    normalized_action_kind = (action_kind or "").strip().lower()
    if normalized_action_kind and normalized_action_kind not in {"read", "write"}:
        raise HTTPException(status_code=400, detail="action_kind must be read or write")

    if from_date and from_date.strip():
        try:
            datetime.strptime(from_date.strip(), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="from_date must be in YYYY-MM-DD format")

    if to_date and to_date.strip():
        try:
            datetime.strptime(to_date.strip(), "%Y-%m-%d")
        except ValueError:
            raise HTTPException(status_code=400, detail="to_date must be in YYYY-MM-DD format")

    if from_date and from_date.strip() and to_date and to_date.strip():
        if from_date.strip() > to_date.strip():
            raise HTTPException(status_code=400, detail="from_date must be <= to_date")

    items = list_audit_events(
        limit=limit,
        offset=offset,
        username=username,
        action=action,
        action_kind=normalized_action_kind or None,
        from_date=(from_date or "").strip() or None,
        to_date=(to_date or "").strip() or None,
    )
    total = count_audit_events(
        username=username,
        action=action,
        action_kind=normalized_action_kind or None,
        from_date=(from_date or "").strip() or None,
        to_date=(to_date or "").strip() or None,
    )
    return {
        "count": len(items),
        "total": total,
        "offset": offset,
        "limit": limit,
        "items": items,
    }
