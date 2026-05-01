"""
Entry Point: main.py
Responsibility: Create the FastAPI app and register all routes.
Nothing else lives here.
"""

import os
from fastapi import FastAPI
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

# Load environment variables before importing modules that read env at import time.
load_dotenv()

from routes.invoice_routes import router as invoice_router
from routes.chat_routes import router as chat_router
from routes.auth_routes import router as auth_router
from routes.audit_routes import router as audit_router
from services.auth_service import init_auth_storage
from services.audit_service import init_audit_storage, log_audit_event, user_from_bearer_token

app = FastAPI(
    title="Invoice AI API",
    description="Upload invoices, extract data with Kimi, query with Llama3.",
    version="1.0.0",
)

# ── CORS (Angular dev server) ────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4200"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ──────────────────────────────────────────────────────
app.include_router(invoice_router)
app.include_router(chat_router)
app.include_router(auth_router)
app.include_router(audit_router)


@app.middleware("http")
async def audit_comptable_requests(request: Request, call_next):
    response = await call_next(request)

    path = request.url.path
    if path.startswith("/auth") or path in {"/", "/health"}:
        return response

    auth_header = request.headers.get("authorization", "")
    bearer_token = ""
    if auth_header.lower().startswith("bearer "):
        bearer_token = auth_header[7:].strip()

    actor = user_from_bearer_token(bearer_token)
    if actor is not None and actor.role.lower() == "comptable":
        try:
            log_audit_event(
                actor=actor,
                action="platform_access",
                request_method=request.method,
                request_path=path,
                client_ip=request.client.host if request.client else None,
                summary=f"{request.method} {path} : statut {response.status_code}",
                metadata={"status_code": response.status_code},
            )
        except Exception:
            pass

    return response


@app.on_event("startup")
def startup_event() -> None:
    # Ensure auth collections and bootstrap users exist before serving requests.
    init_auth_storage()
    init_audit_storage()

@app.get("/")
def root():
    return {"message": "API is running"}
@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}
