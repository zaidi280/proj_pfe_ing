import os
import hmac
import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
import jwt
from jwt import ExpiredSignatureError, InvalidTokenError
from pymongo.errors import DuplicateKeyError

from controllers.db_controller import DBController


class AuthUser(BaseModel):
	user_id: str
	username: str
	role: str
	display_name: str
	permissions: list[str] = []


ALLOWED_PERMISSIONS = {
	"save_invoice",
	"ask_chat",
	"modify_invoice",
}


def _utcnow() -> datetime:
	return datetime.now(timezone.utc)


def _int_env(name: str, default: int) -> int:
	value = os.getenv(name, str(default)).strip()
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


_JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change_this_secret_in_production")
_JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
_ACCESS_TOKEN_EXPIRE_MINUTES = _int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30)
_REFRESH_TOKEN_EXPIRE_DAYS = _int_env("REFRESH_TOKEN_EXPIRE_DAYS", 7)
_PBKDF2_ITERATIONS = _int_env("PASSWORD_HASH_ITERATIONS", 390000)

_http_bearer = HTTPBearer(auto_error=False)


def _db() -> DBController:
	return DBController()


def _to_auth_user(user_doc: dict) -> AuthUser:
	raw_permissions = user_doc.get("permissions", [])
	permissions = _normalize_permissions(raw_permissions)
	role = str(user_doc.get("role", "")).strip().lower()
	if role == "admin" and not permissions:
		permissions = sorted(ALLOWED_PERMISSIONS)
	if role == "comptable" and not permissions:
		# Backward compatibility for existing comptable accounts created before permissions.
		permissions = sorted(ALLOWED_PERMISSIONS)

	return AuthUser(
		user_id=str(user_doc.get("_id")),
		username=str(user_doc.get("username", "")).strip(),
		role=str(user_doc.get("role", "")).strip(),
		display_name=str(user_doc.get("display_name", "")).strip(),
		permissions=permissions,
	)


def _normalize_permissions(values: Any) -> list[str]:
	if not isinstance(values, list):
		return []
	for value in values:
		if isinstance(value, str) and value.strip().lower() in {"all", "all_permissions", "*"}:
			return sorted(ALLOWED_PERMISSIONS)
	seen: set[str] = set()
	out: list[str] = []
	for value in values:
		if not isinstance(value, str):
			continue
		v = value.strip().lower()
		if v in ALLOWED_PERMISSIONS and v not in seen:
			seen.add(v)
			out.append(v)
	return out


def _hash_password(password: str, salt_hex: str | None = None, iterations: int | None = None) -> str:
	salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
	rounds = iterations if isinstance(iterations, int) and iterations > 0 else _PBKDF2_ITERATIONS
	digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
	return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, hashed: str) -> bool:
	try:
		algo, iterations, salt_hex, digest_hex = hashed.split("$", 3)
		if algo != "pbkdf2_sha256":
			return False
		recomputed = _hash_password(password, salt_hex=salt_hex, iterations=int(iterations))
		return hmac.compare_digest(recomputed, f"pbkdf2_sha256${iterations}${salt_hex}${digest_hex}")
	except Exception:
		return False


def _hash_token(raw_token: str) -> str:
	return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _bootstrap_users() -> None:
	db = _db()
	users = db.collection("users")
	refresh_tokens = db.collection("auth_refresh_tokens")
	users.create_index("username", unique=True)
	refresh_tokens.create_index("jti", unique=True)
	refresh_tokens.create_index("expires_at")

	bootstrap_defs = [
		{
			"username": os.getenv("AUTH_BOOTSTRAP_ADMIN_USERNAME", "admin").strip() or "admin",
			"password": os.getenv("AUTH_BOOTSTRAP_ADMIN_PASSWORD", "admin123"),
			"role": "admin",
			"display_name": os.getenv("AUTH_BOOTSTRAP_ADMIN_DISPLAY_NAME", "Administrator"),
		},
		{
			"username": os.getenv("AUTH_BOOTSTRAP_COMPTABLE_USERNAME", "comptable").strip() or "comptable",
			"password": os.getenv("AUTH_BOOTSTRAP_COMPTABLE_PASSWORD", "comptable123"),
			"role": "comptable",
			"display_name": os.getenv("AUTH_BOOTSTRAP_COMPTABLE_DISPLAY_NAME", "Comptable"),
		},
	]

	now = _utcnow().isoformat()
	for item in bootstrap_defs:
		try:
			users.update_one(
				{"username": item["username"]},
				{
					"$setOnInsert": {
						"username": item["username"],
						"password_hash": _hash_password(item["password"]),
						"role": item["role"],
						"display_name": item["display_name"],
						"is_active": True,
						"created_at": now,
						"updated_at": now,
					}
				},
				upsert=True,
			)
		except DuplicateKeyError:
			# Uvicorn reload can run startup concurrently; safe to ignore duplicate inserts.
			continue


def init_auth_storage() -> None:
	_bootstrap_users()


def _get_user_by_username(username: str) -> dict | None:
	if not username:
		return None
	return _db().collection("users").find_one({"username": username.strip(), "is_active": True})


def _get_user_by_id(user_id: str) -> dict | None:
	if not user_id:
		return None
	from bson import ObjectId
	from bson.errors import InvalidId

	try:
		obj_id = ObjectId(user_id)
	except (InvalidId, TypeError):
		return None
	return _db().collection("users").find_one({"_id": obj_id, "is_active": True})


def authenticate_user(username: str, password: str) -> AuthUser | None:
	if not username or not password:
		return None

	_bootstrap_users()
	user_doc = _get_user_by_username(username)
	if user_doc is None:
		return None

	hashed = str(user_doc.get("password_hash", ""))
	if not _verify_password(password, hashed):
		return None

	return _to_auth_user(user_doc)


def authenticate_user_detailed(username: str, password: str) -> tuple[AuthUser | None, str]:
	"""Authenticate and return detailed error reason if authentication fails.
	
	Returns:
		(user, error_message) where user is None if authentication failed
		- "User not found" if username doesn't exist
		- "Account deactivated" if account exists but is_active=False
		- "Invalid password" if password is wrong
		- "" (empty string) if authentication successful
	"""
	if not username or not password:
		return (None, "username and password are required")

	_bootstrap_users()
	
	# First check if user exists at all (including deactivated)
	user_doc_any = _db().collection("users").find_one({"username": username.strip()})
	
	# Then check if user exists AND is active
	user_doc = _get_user_by_username(username)
	
	# User doesn't exist
	if user_doc_any is None:
		return (None, "Nom d'utilisateur incorrect")
	
	# User exists but is deactivated
	if user_doc is None and user_doc_any is not None:
		return (None, "Compte désactivé")
	
	# Check password
	hashed = str(user_doc.get("password_hash", ""))
	if not _verify_password(password, hashed):
		return (None, "Mot de passe incorrect")
	
	return (_to_auth_user(user_doc), "")


def register_user(username: str, password: str, display_name: str | None = None) -> AuthUser:
	clean_username = (username or "").strip()
	clean_password = password or ""
	clean_display_name = (display_name or "").strip() or clean_username

	if len(clean_username) < 3:
		raise HTTPException(status_code=400, detail="username must contain at least 3 characters")
	if len(clean_password) < 6:
		raise HTTPException(status_code=400, detail="password must contain at least 6 characters")

	_bootstrap_users()
	users = _db().collection("users")
	now = _utcnow().isoformat()
	try:
		result = users.insert_one(
			{
				"username": clean_username,
				"password_hash": _hash_password(clean_password),
				"role": "comptable",
				"display_name": clean_display_name,
				"permissions": sorted(ALLOWED_PERMISSIONS),
				"is_active": True,
				"created_at": now,
				"updated_at": now,
			}
		)
	except DuplicateKeyError:
		raise HTTPException(status_code=409, detail="username already exists")

	created = users.find_one({"_id": result.inserted_id})
	if created is None:
		raise HTTPException(status_code=500, detail="user creation failed")
	return _to_auth_user(created)


def list_comptable_users(limit: int = 200) -> list[dict[str, str | bool | list[str]]]:
	if limit < 1 or limit > 1000:
		raise HTTPException(status_code=400, detail="limit must be between 1 and 1000")

	_bootstrap_users()
	docs = list(
		_db()
		.collection("users")
		.find({"role": "comptable"}, {"password_hash": 0})
		.sort("created_at", -1)
		.limit(limit)
	)

	items: list[dict[str, str | bool | list[str]]] = []
	for doc in docs:
		permissions = _normalize_permissions(doc.get("permissions", []))
		if not permissions:
			permissions = sorted(ALLOWED_PERMISSIONS)
		items.append(
			{
				"user_id": str(doc.get("_id")),
				"username": str(doc.get("username", "")),
				"role": str(doc.get("role", "comptable")),
				"display_name": str(doc.get("display_name", "")),
				"permissions": permissions,
				"is_active": bool(doc.get("is_active", True)),
				"created_at": str(doc.get("created_at", "")),
				"updated_at": str(doc.get("updated_at", "")),
			}
		)

	return items


def create_comptable_user(
	username: str,
	password: str,
	display_name: str | None = None,
	permissions: list[str] | None = None,
) -> AuthUser:
	clean_username = (username or "").strip()
	clean_password = password or ""
	clean_display_name = (display_name or "").strip() or clean_username

	if len(clean_username) < 3:
		raise HTTPException(status_code=400, detail="username must contain at least 3 characters")
	if len(clean_password) < 6:
		raise HTTPException(status_code=400, detail="password must contain at least 6 characters")

	clean_permissions = _normalize_permissions(
		permissions if permissions is not None else sorted(ALLOWED_PERMISSIONS)
	)
	if not clean_permissions:
		raise HTTPException(status_code=400, detail="At least one permission is required")

	_bootstrap_users()
	users = _db().collection("users")
	now = _utcnow().isoformat()
	try:
		result = users.insert_one(
			{
				"username": clean_username,
				"password_hash": _hash_password(clean_password),
				"role": "comptable",
				"display_name": clean_display_name,
				"permissions": clean_permissions,
				"is_active": True,
				"created_at": now,
				"updated_at": now,
			}
		)
	except DuplicateKeyError:
		raise HTTPException(status_code=409, detail="username already exists")

	created = users.find_one({"_id": result.inserted_id})
	if created is None:
		raise HTTPException(status_code=500, detail="user creation failed")
	return _to_auth_user(created)


def update_comptable_user(
	user_id: str,
	display_name: str | None = None,
	password: str | None = None,
	is_active: bool | None = None,
	permissions: list[str] | None = None,
) -> dict[str, str | bool | list[str]]:
	from bson import ObjectId
	from bson.errors import InvalidId

	clean_user_id = (user_id or "").strip()
	if not clean_user_id:
		raise HTTPException(status_code=400, detail="user_id is required")

	try:
		obj_id = ObjectId(clean_user_id)
	except (InvalidId, TypeError):
		raise HTTPException(status_code=400, detail="invalid user_id")

	set_fields: dict[str, str | bool] = {"updated_at": _utcnow().isoformat()}

	if display_name is not None:
		clean_display = display_name.strip()
		if not clean_display:
			raise HTTPException(status_code=400, detail="display_name cannot be empty")
		set_fields["display_name"] = clean_display

	if password is not None:
		clean_password = password.strip()
		if len(clean_password) < 6:
			raise HTTPException(status_code=400, detail="password must contain at least 6 characters")
		set_fields["password_hash"] = _hash_password(clean_password)

	if is_active is not None:
		set_fields["is_active"] = bool(is_active)

	if permissions is not None:
		clean_permissions = _normalize_permissions(permissions)
		if not clean_permissions:
			raise HTTPException(status_code=400, detail="At least one permission is required")
		set_fields["permissions"] = clean_permissions

	if len(set_fields) == 1:
		raise HTTPException(status_code=400, detail="No fields to update")

	users = _db().collection("users")
	result = users.update_one({"_id": obj_id, "role": "comptable"}, {"$set": set_fields})
	if result.matched_count == 0:
		raise HTTPException(status_code=404, detail="comptable user not found")

	doc = users.find_one({"_id": obj_id}, {"password_hash": 0})
	if doc is None:
		raise HTTPException(status_code=500, detail="failed to fetch updated user")

	return {
		"user_id": str(doc.get("_id")),
		"username": str(doc.get("username", "")),
		"role": str(doc.get("role", "comptable")),
		"display_name": str(doc.get("display_name", "")),
		"permissions": _normalize_permissions(doc.get("permissions", [])) or sorted(ALLOWED_PERMISSIONS),
		"is_active": bool(doc.get("is_active", True)),
		"created_at": str(doc.get("created_at", "")),
		"updated_at": str(doc.get("updated_at", "")),
	}


def deactivate_comptable_user(user_id: str) -> dict[str, str]:
	updated = update_comptable_user(user_id=user_id, is_active=False)
	return {"status": "deactivated", "user_id": str(updated.get("user_id", ""))}


def _build_token_payload(user: AuthUser, token_type: str, expires_delta: timedelta) -> dict[str, str | int]:
	now = _utcnow()
	expires_at = now + expires_delta
	return {
		"uid": user.user_id,
		"sub": user.username,
		"role": user.role,
		"name": user.display_name,
		"type": token_type,
		"iat": int(now.timestamp()),
		"exp": int(expires_at.timestamp()),
	}


def create_access_token(user: AuthUser) -> str:
	payload = _build_token_payload(user, "access", timedelta(minutes=_ACCESS_TOKEN_EXPIRE_MINUTES))
	return jwt.encode(payload, _JWT_SECRET_KEY, algorithm=_JWT_ALGORITHM)


def create_refresh_token(user: AuthUser) -> str:
	payload = _build_token_payload(user, "refresh", timedelta(days=_REFRESH_TOKEN_EXPIRE_DAYS))
	payload["jti"] = uuid.uuid4().hex
	return jwt.encode(payload, _JWT_SECRET_KEY, algorithm=_JWT_ALGORITHM)


def _decode_token(token: str, expected_type: str) -> dict[str, str | int]:
	credentials_exception = HTTPException(
		status_code=status.HTTP_401_UNAUTHORIZED,
		detail="Invalid or expired token",
		headers={"WWW-Authenticate": "Bearer"},
	)
	try:
		payload = jwt.decode(token, _JWT_SECRET_KEY, algorithms=[_JWT_ALGORITHM])
	except (ExpiredSignatureError, InvalidTokenError):
		raise credentials_exception

	token_type = str(payload.get("type", ""))
	if token_type != expected_type:
		raise credentials_exception
	return payload


def _user_from_payload(payload: dict[str, str | int]) -> AuthUser:
	user_id = str(payload.get("uid", "")).strip()
	if not user_id:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Invalid token payload",
			headers={"WWW-Authenticate": "Bearer"},
		)

	_bootstrap_users()
	user_doc = _get_user_by_id(user_id)
	if user_doc is None:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="User not found",
			headers={"WWW-Authenticate": "Bearer"},
		)

	return _to_auth_user(user_doc)


def _save_refresh_token(user: AuthUser, refresh_token: str) -> None:
	payload = _decode_token(refresh_token, expected_type="refresh")
	jti = str(payload.get("jti", "")).strip()
	if not jti:
		raise HTTPException(status_code=401, detail="Invalid refresh token")
	expires_at = datetime.fromtimestamp(int(payload.get("exp", 0)), tz=timezone.utc).isoformat()

	_db().collection("auth_refresh_tokens").insert_one(
		{
			"jti": jti,
			"user_id": user.user_id,
			"token_hash": _hash_token(refresh_token),
			"issued_at": _utcnow().isoformat(),
			"expires_at": expires_at,
			"revoked": False,
		}
	)


def issue_tokens(user: AuthUser) -> dict[str, str | AuthUser]:
	access_token = create_access_token(user)
	refresh_token = create_refresh_token(user)
	_save_refresh_token(user, refresh_token)
	return {
		"access_token": access_token,
		"refresh_token": refresh_token,
		"token_type": "bearer",
		"user": user,
	}


def refresh_tokens(refresh_token: str) -> dict[str, str | AuthUser]:
	payload = _decode_token(refresh_token, expected_type="refresh")
	jti = str(payload.get("jti", "")).strip()
	if not jti:
		raise HTTPException(status_code=401, detail="Invalid refresh token")

	token_doc = _db().collection("auth_refresh_tokens").find_one(
		{
			"jti": jti,
			"token_hash": _hash_token(refresh_token),
			"revoked": False,
		}
	)
	if token_doc is None:
		raise HTTPException(status_code=401, detail="Refresh token not recognized")

	user = _user_from_payload(payload)

	_db().collection("auth_refresh_tokens").update_one({"_id": token_doc["_id"]}, {"$set": {"revoked": True}})

	return issue_tokens(user)


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer)) -> AuthUser:
	if credentials is None or not credentials.credentials:
		raise HTTPException(
			status_code=status.HTTP_401_UNAUTHORIZED,
			detail="Not authenticated",
			headers={"WWW-Authenticate": "Bearer"},
		)

	payload = _decode_token(credentials.credentials, expected_type="access")
	return _user_from_payload(payload)


def require_roles(*allowed_roles: str) -> Callable[[AuthUser], AuthUser]:
	allowed = {role.strip().lower() for role in allowed_roles if role and role.strip()}

	async def role_dependency(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
		if current_user.role.lower() not in allowed:
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissions insuffisantes")
		return current_user

	return role_dependency


def require_permissions(*required_permissions: str) -> Callable[[AuthUser], AuthUser]:
	required = {p.strip().lower() for p in required_permissions if p and p.strip()}

	async def permission_dependency(current_user: AuthUser = Depends(get_current_user)) -> AuthUser:
		# Admin keeps full access regardless of explicit permission list.
		if current_user.role.lower() == "admin":
			return current_user

		user_permissions = {p.strip().lower() for p in (current_user.permissions or [])}
		if required and required.isdisjoint(user_permissions):
			raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission refusée")
		return current_user

	return permission_dependency
