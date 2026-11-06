import hashlib
import httpx
from fastapi import HTTPException, Request
from backend.app.config import get_settings

settings = get_settings()

def client_ip_hash(request: Request) -> str:
    ip = request.headers.get("x-vercel-forwarded-for", "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return hashlib.sha256((ip or "unknown").encode()).hexdigest()

def ensure_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.origin_set:
        raise HTTPException(status_code=403, detail="Origin not allowed")

async def require_admin(request: Request) -> dict:
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth is not configured")
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            result = await client.get(
                f"{settings.supabase_url.rstrip('/')}/auth/v1/user",
                headers={"apikey": settings.supabase_anon_key, "Authorization": f"Bearer {token}"},
            )
        if result.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        user = result.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from exc
    email = str(user.get("email", "")).lower()
    if email not in settings.admin_email_set:
        raise HTTPException(status_code=403, detail="Admin access required")
    if request.cookies.get(settings.access_cookie_name):
        ensure_same_origin(request)
    return {"sub": user.get("id"), "email": email, "role": "admin"}
