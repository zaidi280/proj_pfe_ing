from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from services.auth_service import (
	AuthUser,
	authenticate_user,
	authenticate_user_detailed,
	create_comptable_user,
	deactivate_comptable_user,
	get_current_user,
	issue_tokens,
	list_comptable_users,
	require_roles,
	register_user,
	refresh_tokens,
	update_comptable_user,
)


router = APIRouter(prefix="/auth", tags=["Auth"])


class LoginRequest(BaseModel):
	username: str
	password: str


class RefreshTokenRequest(BaseModel):
	refresh_token: str


class RegisterRequest(BaseModel):
	username: str
	password: str
	display_name: str | None = None


class CreateComptableRequest(BaseModel):
	username: str
	password: str
	display_name: str | None = None
	permissions: list[str] | None = None


class UpdateComptableRequest(BaseModel):
	display_name: str | None = None
	password: str | None = None
	is_active: bool | None = None
	permissions: list[str] | None = None


@router.post("/login")
async def login(payload: LoginRequest):
	username = (payload.username or "").strip()
	password = payload.password or ""
	if not username or not password:
		raise HTTPException(status_code=400, detail="username and password are required")

	user, error_detail = authenticate_user_detailed(username, password)
	if user is None:
		raise HTTPException(status_code=401, detail=error_detail)

	return issue_tokens(user)


@router.post("/refresh")
async def refresh(payload: RefreshTokenRequest):
	if not payload.refresh_token or not payload.refresh_token.strip():
		raise HTTPException(status_code=400, detail="refresh_token is required")

	return refresh_tokens(payload.refresh_token.strip())


@router.post("/register")
async def register(payload: RegisterRequest):
	username = (payload.username or "").strip()
	password = payload.password or ""
	if not username or not password:
		raise HTTPException(status_code=400, detail="username and password are required")

	user = register_user(username=username, password=password, display_name=payload.display_name)
	return issue_tokens(user)


@router.get("/me")
async def me(current_user: AuthUser = Depends(get_current_user)):
	return {"user": current_user}


@router.get("/comptables")
async def get_comptable_accounts(
	limit: int = 200,
	_: AuthUser = Depends(require_roles("admin")),
):
	items = list_comptable_users(limit=limit)
	return {"count": len(items), "items": items}


@router.post("/comptables")
async def create_comptable_account(
	payload: CreateComptableRequest,
	_: AuthUser = Depends(require_roles("admin")),
):
	created = create_comptable_user(
		username=payload.username,
		password=payload.password,
		display_name=payload.display_name,
		permissions=payload.permissions,
	)
	return {"user": created}


@router.patch("/comptables/{user_id}")
async def patch_comptable_account(
	user_id: str,
	payload: UpdateComptableRequest,
	_: AuthUser = Depends(require_roles("admin")),
):
	updated = update_comptable_user(
		user_id=user_id,
		display_name=payload.display_name,
		password=payload.password,
		is_active=payload.is_active,
		permissions=payload.permissions,
	)
	return {"user": updated}


@router.delete("/comptables/{user_id}")
async def delete_comptable_account(
	user_id: str,
	_: AuthUser = Depends(require_roles("admin")),
):
	return deactivate_comptable_user(user_id)
