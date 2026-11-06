import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from firebase_admin import auth, firestore
from google.cloud.firestore_v1 import transactional

from backend.app.config import get_settings
from backend.app.firebase import get_firebase_app, get_firestore


def client_ip_hash(request: Request) -> str:
    ip = request.headers.get("x-vercel-forwarded-for", "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return hashlib.sha256((ip or "unknown").encode()).hexdigest()


def ensure_same_origin(request: Request, *, require_origin: bool = False) -> None:
    origin = request.headers.get("origin")
    if require_origin and not origin:
        raise HTTPException(status_code=403, detail="Origin header required")
    if origin and origin.rstrip("/") not in get_settings().origin_set:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def enforce_rate_limit(key: str, limit: int, window_seconds: int) -> None:
    db = get_firestore()
    now = datetime.now(timezone.utc)
    ref = db.collection("site_settings").document("rate_limits").collection("requests").document(key)
    transaction = db.transaction()

    @transactional
    def consume(tx):
        snapshot = ref.get(transaction=tx)
        data = snapshot.to_dict() or {}
        reset_at = data.get("reset_at")
        count = data.get("count", 0)
        if reset_at and reset_at > now:
            if count >= limit:
                return max(1, int((reset_at - now).total_seconds()))
            count += 1
        else:
            count = 1
            reset_at = now + timedelta(seconds=window_seconds)
        tx.set(ref, {"count": count, "reset_at": reset_at})
        return 0

    retry_after = consume(transaction)
    if retry_after:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def verify_admin_identity(token: str) -> dict:
    app = get_firebase_app()
    try:
        claims = auth.verify_id_token(token, app=app, check_revoked=True)
        email = str(claims.get("email", "")).strip().lower()
        if not claims.get("email_verified") or email not in get_settings().admin_email_set:
            raise HTTPException(status_code=403, detail="Verified administrator access required")
        user = auth.get_user(str(claims["uid"]), app=app)
        if user.disabled or not user.email_verified or (user.email or "").strip().lower() != email:
            raise HTTPException(status_code=403, detail="Verified administrator access required")
        return {"sub": user.uid, "email": email, "expires_at": int(claims["exp"])}
    except HTTPException:
        raise
    except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError, auth.RevokedIdTokenError) as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc
    except auth.UserNotFoundError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired session") from exc


def verify_admin_token(token: str) -> dict:
    identity = verify_admin_identity(token)
    try:
        admin = get_firestore().collection("admins").document(identity["sub"]).get()
        if not admin.exists or str((admin.to_dict() or {}).get("email", "")).lower() != identity["email"]:
            raise HTTPException(status_code=403, detail="Administrator access required")
        return {**identity, "role": "admin"}
    except HTTPException:
        raise

def require_admin(request: Request) -> dict:
    settings = get_settings()
    token = request.cookies.get(settings.access_cookie_name)
    is_cookie_session = bool(token)
    if not token:
        authorization = request.headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    if is_cookie_session and request.method not in {"GET", "HEAD", "OPTIONS"}:
        ensure_same_origin(request, require_origin=True)
    return verify_admin_token(token)


def log_admin_activity(actor: dict, action: str, resource: str, resource_id: str) -> None:
    get_firestore().collection("activity_logs").add({
        "actor_uid": actor["sub"],
        "actor_email": actor["email"],
        "action": action,
        "resource": resource,
        "resource_id": resource_id,
        "created_at": firestore.SERVER_TIMESTAMP,
    })
