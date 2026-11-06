import hashlib
from typing import Any
import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, Request
from backend.app.config import get_settings

settings = get_settings()
_jwks_client: PyJWKClient | None = None

def verify_access_token(token: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "HS256":
            if not settings.supabase_jwt_secret:
                raise ValueError("SUPABASE_JWT_SECRET is required for legacy HS256 tokens")
            return jwt.decode(token, settings.supabase_jwt_secret, algorithms=["HS256"], audience="authenticated")
        global _jwks_client
        if _jwks_client is None:
            _jwks_client = PyJWKClient(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")
        key = _jwks_client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated",
                          issuer=f"{settings.supabase_url.rstrip('/')}/auth/v1",
                          options={"require": ["exp", "sub", "iat"]})
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc

def require_admin(request: Request) -> dict[str, Any]:
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    claims = verify_access_token(token)
    email = str(claims.get("email", "")).lower()
    if email not in settings.admin_email_set:
        raise HTTPException(status_code=403, detail="Admin access required")
    return claims

def client_ip_hash(request: Request) -> str:
    # Vercel injects x-vercel-forwarded-for at its trusted edge.
    ip = request.headers.get("x-vercel-forwarded-for", "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return hashlib.sha256((ip or "unknown").encode()).hexdigest()

def ensure_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.origin_set:
        raise HTTPException(status_code=403, detail="Origin not allowed")
