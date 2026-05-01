from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import jwt
from jwt import ExpiredSignatureError, InvalidTokenError

from controllers.db_controller import DBController
from services.auth_service import AuthUser


_AUDIT_COLLECTION = os.getenv("AUDIT_COLLECTION", "audit_trail")
_JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change_this_secret_in_production")
_JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db() -> DBController:
    return DBController()


def init_audit_storage() -> None:
    coll = _db().collection(_AUDIT_COLLECTION)
    coll.create_index("occurred_at")
    coll.create_index("action_kind")
    coll.create_index("actor.user_id")
    coll.create_index("actor.role")
    coll.create_index("entity.type")
    coll.create_index("entity.id")


def _action_kind_from_method(method: str | None) -> str:
    normalized = (method or "").strip().upper()
    if normalized in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    return "write"


def _parse_date_start_utc(date_str: str) -> datetime:
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc, hour=0, minute=0, second=0, microsecond=0)


def _parse_date_end_utc(date_str: str) -> datetime:
    parsed = datetime.strptime(date_str, "%Y-%m-%d")
    return parsed.replace(tzinfo=timezone.utc, hour=23, minute=59, second=59, microsecond=999999)


def user_from_bearer_token(raw_token: str | None) -> AuthUser | None:
    token = (raw_token or "").strip()
    if not token:
        return None
    try:
        payload = jwt.decode(token, _JWT_SECRET_KEY, algorithms=[_JWT_ALGORITHM])
    except (ExpiredSignatureError, InvalidTokenError):
        return None

    if str(payload.get("type", "")).strip() != "access":
        return None

    user_id = str(payload.get("uid", "")).strip()
    username = str(payload.get("sub", "")).strip()
    role = str(payload.get("role", "")).strip()
    display_name = str(payload.get("name", "")).strip()
    if not user_id or not username:
        return None

    return AuthUser(
        user_id=user_id,
        username=username,
        role=role,
        display_name=display_name,
    )


def _normalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_normalize_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _normalize_value(v) for k, v in value.items()}
    return str(value)


def compute_changes(old_value: Any, new_value: Any, path: str = "") -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    if isinstance(old_value, dict) and isinstance(new_value, dict):
        keys = sorted(set(old_value.keys()) | set(new_value.keys()))
        for key in keys:
            child_path = f"{path}.{key}" if path else str(key)
            if key not in old_value:
                changes.append({"field": child_path, "old": None, "new": _normalize_value(new_value[key])})
                continue
            if key not in new_value:
                changes.append({"field": child_path, "old": _normalize_value(old_value[key]), "new": None})
                continue
            changes.extend(compute_changes(old_value[key], new_value[key], child_path))
        return changes

    if isinstance(old_value, list) and isinstance(new_value, list):
        if old_value != new_value:
            changes.append({
                "field": path or "value",
                "old": _normalize_value(old_value),
                "new": _normalize_value(new_value),
            })
        return changes

    if old_value != new_value:
        changes.append({"field": path or "value", "old": _normalize_value(old_value), "new": _normalize_value(new_value)})

    return changes


def log_audit_event(
    *,
    actor: AuthUser,
    action: str,
    request_method: str,
    request_path: str,
    client_ip: str | None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    summary: str | None = None,
    changes: list[dict[str, Any]] | None = None,
    metadata: dict[str, Any] | None = None,
    action_kind: str | None = None,
) -> None:
    if actor.role.lower() != "comptable":
        return

    doc = {
        "actor": {
            "user_id": actor.user_id,
            "username": actor.username,
            "role": actor.role,
            "display_name": actor.display_name,
        },
        "action": action,
        "action_kind": (action_kind or _action_kind_from_method(request_method)).strip().lower(),
        "occurred_at": _utcnow_iso(),
        "request": {
            "method": request_method,
            "path": request_path,
            "client_ip": client_ip or "",
        },
        "entity": {
            "type": entity_type or "",
            "id": entity_id or "",
        },
        "summary": summary or "",
        "changes": _normalize_value(changes or []),
        "metadata": _normalize_value(metadata or {}),
    }

    _db().collection(_AUDIT_COLLECTION).insert_one(doc)


def list_audit_events(
    *,
    limit: int = 200,
    offset: int = 0,
    username: str | None = None,
    action: str | None = None,
    action_kind: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 1000))
    safe_offset = max(0, offset)

    query = _build_audit_query(
        username=username,
        action=action,
        action_kind=action_kind,
        from_date=from_date,
        to_date=to_date,
    )

    docs = list(
        _db()
        .collection(_AUDIT_COLLECTION)
        .find(query)
        .sort("occurred_at", -1)
        .skip(safe_offset)
        .limit(safe_limit)
    )

    items: list[dict[str, Any]] = []
    for doc in docs:
        items.append(
            {
                "id": str(doc.get("_id")),
                "actor": doc.get("actor", {}),
                "action": doc.get("action", ""),
                "action_kind": doc.get("action_kind") or _action_kind_from_method(doc.get("request", {}).get("method", "")),
                "occurred_at": doc.get("occurred_at", ""),
                "request": doc.get("request", {}),
                "entity": doc.get("entity", {}),
                "summary": doc.get("summary", ""),
                "changes": doc.get("changes", []),
                "metadata": doc.get("metadata", {}),
            }
        )

    return items


def count_audit_events(
    *,
    username: str | None = None,
    action: str | None = None,
    action_kind: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
) -> int:
    query = _build_audit_query(
        username=username,
        action=action,
        action_kind=action_kind,
        from_date=from_date,
        to_date=to_date,
    )
    return int(_db().collection(_AUDIT_COLLECTION).count_documents(query))


def _build_audit_query(
    *,
    username: str | None,
    action: str | None,
    action_kind: str | None,
    from_date: str | None,
    to_date: str | None,
) -> dict[str, Any]:
    query: dict[str, Any] = {"actor.role": "comptable"}
    if username and username.strip():
        query["actor.username"] = username.strip()
    if action and action.strip():
        query["action"] = action.strip()

    normalized_action_kind = (action_kind or "").strip().lower()
    if normalized_action_kind in {"read", "write"}:
        method_set = ["GET", "HEAD", "OPTIONS"] if normalized_action_kind == "read" else ["POST", "PUT", "PATCH", "DELETE"]
        query["$or"] = [
            {"action_kind": normalized_action_kind},
            {"action_kind": {"$exists": False}, "request.method": {"$in": method_set}},
        ]

    occurred_at_filter: dict[str, str] = {}
    if from_date and from_date.strip():
        occurred_at_filter["$gte"] = _parse_date_start_utc(from_date.strip()).isoformat()
    if to_date and to_date.strip():
        occurred_at_filter["$lte"] = _parse_date_end_utc(to_date.strip()).isoformat()
    if occurred_at_filter:
        query["occurred_at"] = occurred_at_filter
    return query
