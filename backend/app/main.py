import base64
import binascii
import hashlib
import logging
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from firebase_admin import auth, firestore, storage
from firebase_admin.exceptions import FirebaseError
from google.api_core.exceptions import AlreadyExists, GoogleAPICallError, NotFound
from starlette.concurrency import run_in_threadpool

from backend.app.config import get_settings
from backend.app.firebase import get_firebase_app, get_firestore
from backend.app.schemas import (
    AdminLogin,
    AdminProjectRead,
    AuthVerify,
    ContactCreate,
    ContactCreated,
    ContactPage,
    ContactRead,
    MessageStatusUpdate,
    ProjectCreate,
    ProjectPage,
    ProjectRead,
    ProjectUpdate,
    UploadRead,
)
from backend.app.security import (
    client_ip_hash,
    enforce_rate_limit,
    ensure_same_origin,
    log_admin_activity,
    require_admin,
    verify_admin_identity,
)

logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="2.0.0",
    description="Firebase-backed portfolio API with verified administrator access.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(settings.origin_set),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.url.path == "/api/admin/uploads" and request.method == "POST":
        content_length = request.headers.get("content-length")
        try:
            body_too_large = bool(
                content_length and int(content_length) > settings.upload_max_bytes + 1024 * 1024
            )
        except ValueError:
            response = JSONResponse(status_code=400, content={"detail": "Invalid Content-Length"})
        else:
            response = (
                JSONResponse(status_code=413, content={"detail": "Upload exceeds the 4 MB limit"})
                if body_too_large else await call_next(request)
            )
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"detail": [
            {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]},
    )


@app.exception_handler(FirebaseError)
@app.exception_handler(GoogleAPICallError)
async def firebase_error_handler(request: Request, exc: Exception):
    logger.exception("Firebase service request failed")
    return JSONResponse(status_code=503, content={"detail": "Firebase service is unavailable"})


def _encode_cursor(document_id: str) -> str:
    return base64.urlsafe_b64encode(document_id.encode()).decode().rstrip("=")


def _cursor_snapshot(collection, cursor: str | None):
    if not cursor:
        return None
    try:
        document_id = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc
    if not document_id or "/" in document_id:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor")
    snapshot = collection.document(document_id).get()
    if not snapshot.exists:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor")
    return snapshot


def _page(query, collection, limit: int, cursor: str | None, model):
    last = _cursor_snapshot(collection, cursor)
    if last:
        query = query.start_after(last)
    snapshots = list(query.limit(limit + 1).stream())
    has_more = len(snapshots) > limit
    snapshots = snapshots[:limit]
    items = []
    for snapshot in snapshots:
        item = snapshot.to_dict() or {}
        item["id"] = snapshot.id
        items.append(model.model_validate(item))
    return items, _encode_cursor(snapshots[-1].id) if has_more and snapshots else None


def _filtered_page(query, collection, limit: int, cursor: str | None, terms: set[str]):
    last = _cursor_snapshot(collection, cursor)
    if last:
        query = query.start_after(last)
    matching = []
    while len(matching) <= limit:
        batch = list(query.limit(50).stream())
        if not batch:
            break
        for snapshot in batch:
            data = snapshot.to_dict() or {}
            if terms.issubset(set(data.get("search_terms", []))):
                data["id"] = snapshot.id
                matching.append(ProjectRead.model_validate(data))
            query = query.start_after(snapshot)
            if len(matching) > limit:
                break
        if len(batch) < 50 or len(matching) > limit:
            break
    has_more = len(matching) > limit
    items = matching[:limit]
    return items, _encode_cursor(items[-1].id) if has_more and items else None


def _project_query(collection, *, published: bool, category: str | None,
                   featured: bool | None, search: str | None):
    query = collection
    if published:
        query = query.where("published", "==", True)
    if category:
        query = query.where("category", "==", category)
    if featured is not None:
        query = query.where("featured", "==", featured)
    terms = re.findall(r"[a-z0-9]+", (search or "").casefold())
    if terms:
        query = query.where("search_terms", "array_contains", terms[0])
    return query.order_by("featured", direction=firestore.Query.DESCENDING).order_by(
        "updated_at", direction=firestore.Query.DESCENDING
    ), set(terms)


def _project_data(payload: ProjectCreate | ProjectUpdate, *, creating: bool = False) -> dict:
    data = payload.model_dump(mode="json", exclude_unset=not creating)
    if "repository_url" in data and data["repository_url"] is not None:
        data["repository_url"] = str(data["repository_url"])
    if "demo_url" in data and data["demo_url"] is not None:
        data["demo_url"] = str(data["demo_url"])
    if creating:
        words = re.findall(
            r"[a-z0-9]+",
            " ".join(str(data.get(field, "")) for field in ("title", "category", "summary", "tech_stack")).casefold(),
        )
        data["search_terms"] = sorted(set(words))
        data["view_count"] = 0
    return data


def _admin_document(uid: str, email: str) -> None:
    reference = get_firestore().collection("admins").document(uid)
    if not reference.get().exists:
        reference.set({"created_at": firestore.SERVER_TIMESTAMP})
    reference.set(
        {"email": email, "updated_at": firestore.SERVER_TIMESTAMP},
        merge=True,
    )


def _set_session_cookies(response: Response, id_token: str, refresh_token: str, expires_in: int) -> None:
    common = {
        "secure": settings.cookie_secure,
        "httponly": True,
        "samesite": "strict",
        "path": "/api",
    }
    if settings.cookie_domain:
        common["domain"] = settings.cookie_domain
    response.set_cookie(settings.access_cookie_name, id_token, max_age=expires_in, **common)
    response.set_cookie(settings.refresh_cookie_name, refresh_token, max_age=30 * 24 * 60 * 60, **common)


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(settings.access_cookie_name, path="/api", domain=settings.cookie_domain or None)
    response.delete_cookie(settings.refresh_cookie_name, path="/api", domain=settings.cookie_domain or None)


def _session_error(status_code: int, detail: str) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    _clear_session_cookies(response)
    return response


def _firebase_api_url() -> str:
    if not settings.firebase_web_api_key:
        raise HTTPException(status_code=503, detail="Firebase Authentication is not configured")
    return "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + quote(
        settings.firebase_web_api_key, safe=""
    )


def _auth_result(tokens: dict, response: Response) -> dict:
    identity = verify_admin_identity(tokens["idToken"])
    _admin_document(identity["sub"], identity["email"])
    expires_in = max(1, min(int(identity["expires_at"] - datetime.now(timezone.utc).timestamp()), 3600))
    _set_session_cookies(response, tokens["idToken"], tokens["refreshToken"], expires_in)
    return {"authenticated": True, "email": identity["email"], "expires_in": expires_in}


@app.get("/api/health", tags=["health"])
def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/ready", tags=["health"])
def readiness():
    if not all((
        settings.firebase_project_id,
        settings.firebase_client_email,
        settings.firebase_private_key,
        settings.firebase_storage_bucket,
        settings.firebase_web_api_key,
    )):
        raise HTTPException(status_code=503, detail="Firebase services are not fully configured")
    db = get_firestore()
    db.collection("site_settings").limit(1).get()
    if not storage.bucket(app=get_firebase_app()).exists():
        raise HTTPException(status_code=503, detail="Firebase Storage bucket is not accessible")
    next(auth.list_users(max_results=1, app=get_firebase_app()), None)
    return {"status": "ready", "database": "connected", "storage": "accessible", "auth": "configured"}


@app.post("/api/contact", response_model=ContactCreated, status_code=201, tags=["contact"])
def create_contact(payload: ContactCreate, request: Request):
    if payload.website:
        return Response(status_code=202)
    ip_hash = client_ip_hash(request)
    enforce_rate_limit(
        f"contact_{ip_hash}", settings.contact_rate_limit_per_hour, 60 * 60
    )
    now = datetime.now(timezone.utc)
    data = {
        "name": payload.name,
        "email": str(payload.email).lower(),
        "subject": payload.subject,
        "message": payload.message,
        "status": "new",
        "ip_hash": ip_hash,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP,
    }
    reference = get_firestore().collection("contact_messages").document()
    reference.set(data)
    return ContactCreated(id=reference.id, status="new", created_at=now)


@app.get("/api/projects", response_model=ProjectPage, tags=["projects"])
def list_projects(
    category: str | None = Query(default=None, pattern=r"^(semiconductor|software|embedded|wireless|ai|cloud)$"),
    featured: bool | None = None,
    search: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
):
    collection = get_firestore().collection("projects")
    query, terms = _project_query(
        collection, published=True, category=category, featured=featured, search=search
    )
    if len(terms) > 1:
        items, next_cursor = _filtered_page(query, collection, limit, cursor, terms)
    else:
        items, next_cursor = _page(query, collection, limit, cursor, ProjectRead)
    return {"items": items, "next_cursor": next_cursor}


@app.get("/api/projects/{slug}", response_model=ProjectRead, tags=["projects"])
def get_project(slug: str):
    snapshot = get_firestore().collection("projects").document(slug).get()
    data = snapshot.to_dict() if snapshot.exists else None
    if not data or not data.get("published"):
        raise HTTPException(status_code=404, detail="Project not found")
    data["id"] = snapshot.id
    return data


@app.get("/api/projects/{slug}/image", tags=["projects"])
def get_project_image(slug: str):
    snapshot = get_firestore().collection("projects").document(slug).get()
    project = snapshot.to_dict() if snapshot.exists else None
    if not project or not project.get("published"):
        raise HTTPException(status_code=404, detail="Project image not found")
    image_path = project.get("image_path")
    if not image_path or not re.fullmatch(
        r"projects/[A-Za-z0-9_-]+/[0-9a-f]{32}\.(jpg|png|webp)", image_path
    ):
        raise HTTPException(status_code=404, detail="Project image not found")
    try:
        content = storage.bucket(app=get_firebase_app()).blob(image_path).download_as_bytes()
    except NotFound as exc:
        raise HTTPException(status_code=404, detail="Project image not found") from exc
    content_type = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}[image_path.rsplit(".", 1)[1]]
    return Response(content, media_type=content_type, headers={"X-Content-Type-Options": "nosniff"})


@app.post("/api/projects/{slug}/view", status_code=202, tags=["analytics"])
def record_project_view(slug: str, request: Request):
    db = get_firestore()
    project = db.collection("projects").document(slug)
    snapshot = project.get()
    if not snapshot.exists or not (snapshot.to_dict() or {}).get("published"):
        raise HTTPException(status_code=404, detail="Project not found")
    enforce_rate_limit(f"view_{client_ip_hash(request)}", 60, 60)
    referrer = request.headers.get("referer")
    if referrer:
        from urllib.parse import urlparse

        parsed = urlparse(referrer)
        referrer = f"{parsed.scheme}://{parsed.netloc}"[:500]
    batch = db.batch()
    batch.update(project, {"view_count": firestore.Increment(1)})
    batch.set(db.collection("project_views").document(), {
        "project_slug": slug,
        "referrer": referrer,
        "ip_hash": client_ip_hash(request),
        "created_at": firestore.SERVER_TIMESTAMP,
    })
    batch.commit()
    return {"accepted": True}


@app.post("/api/auth/login", tags=["authentication"])
async def login(payload: AdminLogin, request: Request, response: Response):
    ensure_same_origin(request, require_origin=True)
    email = str(payload.email).strip().lower()
    if email not in settings.admin_email_set:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    ip_hash = client_ip_hash(request)
    await run_in_threadpool(
        enforce_rate_limit,
        f"login_{ip_hash}",
        settings.login_rate_limit_per_window,
        settings.login_rate_limit_window_seconds,
    )
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            result = await client.post(
                _firebase_api_url(),
                json={"email": email, "password": payload.password, "returnSecureToken": True},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="Authentication service unavailable") from exc
    if result.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    try:
        tokens = result.json()
    except ValueError as exc:
        logger.error("Firebase Authentication returned an invalid response")
        raise HTTPException(status_code=503, detail="Authentication service unavailable") from exc
    if not isinstance(tokens, dict) or not tokens.get("idToken") or not tokens.get("refreshToken"):
        raise HTTPException(status_code=503, detail="Authentication service returned an invalid response")
    return await run_in_threadpool(_auth_result, tokens, response)


@app.post("/api/auth/verify", tags=["authentication"])
def verify_session(payload: AuthVerify, request: Request, response: Response):
    ensure_same_origin(request, require_origin=True)
    identity = verify_admin_identity(payload.id_token)
    _admin_document(identity["sub"], identity["email"])
    expires_in = max(1, min(int(identity["expires_at"] - datetime.now(timezone.utc).timestamp()), 3600))
    _set_session_cookies(response, payload.id_token, payload.refresh_token, expires_in)
    return {"authenticated": True, "email": identity["email"]}


@app.post("/api/auth/refresh", tags=["authentication"])
async def refresh(request: Request, response: Response):
    ensure_same_origin(request, require_origin=True)
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        return _session_error(401, "Session expired")
    if not settings.firebase_web_api_key:
        return _session_error(503, "Firebase Authentication is not configured")
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            result = await client.post(
                "https://securetoken.googleapis.com/v1/token",
                params={"key": settings.firebase_web_api_key},
                data={"grant_type": "refresh_token", "refresh_token": token},
            )
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=503, detail="Authentication service unavailable") from exc
    if result.status_code != 200:
        return _session_error(401, "Session expired")
    try:
        session = result.json()
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Authentication service returned an invalid response") from exc
    if not isinstance(session, dict) or not session.get("id_token") or not session.get("refresh_token"):
        return _session_error(503, "Authentication service returned an invalid response")
    try:
        return await run_in_threadpool(_auth_result, {
            "idToken": session["id_token"],
            "refreshToken": session["refresh_token"],
            "expiresIn": session.get("expires_in", 3600),
        }, response)
    except HTTPException as exc:
        if exc.status_code in {401, 403}:
            return _session_error(exc.status_code, exc.detail)
        raise


@app.post("/api/auth/logout", tags=["authentication"])
async def logout(request: Request, response: Response):
    ensure_same_origin(request, require_origin=True)
    token = request.cookies.get(settings.access_cookie_name)
    uid = None
    if token:
        try:
            claims = await run_in_threadpool(
                auth.verify_id_token, token, app=get_firebase_app(), check_revoked=False
            )
            uid = str(claims["uid"])
        except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError, auth.UserNotFoundError):
            uid = None
    if not uid and request.cookies.get(settings.refresh_cookie_name):
        if not settings.firebase_web_api_key:
            return _session_error(503, "Firebase Authentication is not configured")
        async with httpx.AsyncClient(timeout=12) as client:
            try:
                refreshed = await client.post(
                    "https://securetoken.googleapis.com/v1/token",
                    params={"key": settings.firebase_web_api_key},
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": request.cookies[settings.refresh_cookie_name],
                    },
                )
            except httpx.HTTPError:
                return _session_error(503, "Authentication service unavailable")
        if refreshed.status_code == 200:
            try:
                result = refreshed.json()
                if not isinstance(result, dict):
                    return _session_error(503, "Authentication service returned an invalid response")
                refreshed_token = result.get("id_token")
                if refreshed_token:
                    claims = await run_in_threadpool(
                        auth.verify_id_token, refreshed_token, app=get_firebase_app(), check_revoked=False
                    )
                    uid = str(claims["uid"])
            except (ValueError, auth.InvalidIdTokenError, auth.ExpiredIdTokenError):
                return _session_error(503, "Authentication service returned an invalid response")
    if uid:
        try:
            await run_in_threadpool(auth.revoke_refresh_tokens, uid, app=get_firebase_app())
        except FirebaseError:
            logger.exception("Firebase failed to revoke an administrator session during logout")
            return _session_error(503, "Session could not be revoked; sign out again when Firebase is available")
    _clear_session_cookies(response)
    return {"authenticated": False}


@app.get("/api/admin/me", response_model=AdminProjectRead, tags=["admin"])
def admin_me(claims: dict = Depends(require_admin)):
    return {"authenticated": True, "email": claims["email"]}


@app.get("/api/admin/projects", response_model=ProjectPage, tags=["admin"])
def admin_projects(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    _: dict = Depends(require_admin),
):
    collection = get_firestore().collection("projects")
    query = collection.order_by("updated_at", direction=firestore.Query.DESCENDING)
    items, next_cursor = _page(query, collection, limit, cursor, ProjectRead)
    return {"items": items, "next_cursor": next_cursor}


@app.post("/api/admin/projects", response_model=ProjectRead, status_code=201, tags=["admin"])
def create_project(
    payload: ProjectCreate,
    claims: dict = Depends(require_admin),
):
    collection = get_firestore().collection("projects")
    reference = collection.document(payload.slug)
    try:
        reference.create({
            **_project_data(payload, creating=True),
            "created_at": firestore.SERVER_TIMESTAMP,
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
    except AlreadyExists as exc:
        raise HTTPException(status_code=409, detail="A project with this slug already exists") from exc
    log_admin_activity(claims, "project.create", "projects", reference.id)
    data = reference.get().to_dict() or {}
    data["id"] = reference.id
    return data


@app.put("/api/admin/projects/{project_id}", response_model=ProjectRead, tags=["admin"])
@app.patch("/api/admin/projects/{project_id}", response_model=ProjectRead, tags=["admin"], include_in_schema=False)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    claims: dict = Depends(require_admin),
):
    reference = get_firestore().collection("projects").document(project_id)
    snapshot = reference.get()
    if not snapshot.exists:
        raise HTTPException(status_code=404, detail="Project not found")
    data = _project_data(payload)
    if "title" in data or "category" in data or "summary" in data or "tech_stack" in data:
        current = snapshot.to_dict() or {}
        updated = {**current, **data}
        data["search_terms"] = sorted(set(re.findall(
            r"[a-z0-9]+",
            " ".join(str(updated.get(field, "")) for field in ("title", "category", "summary", "tech_stack")).casefold(),
        )))
    data["updated_at"] = firestore.SERVER_TIMESTAMP
    reference.update(data)
    log_admin_activity(claims, "project.update", "projects", project_id)
    updated = reference.get().to_dict() or {}
    updated["id"] = project_id
    return updated


@app.delete("/api/admin/projects/{project_id}", status_code=204, tags=["admin"])
def delete_project(project_id: str, claims: dict = Depends(require_admin)):
    reference = get_firestore().collection("projects").document(project_id)
    if not reference.get().exists:
        raise HTTPException(status_code=404, detail="Project not found")
    reference.delete()
    log_admin_activity(claims, "project.delete", "projects", project_id)
    return Response(status_code=204)


@app.get("/api/admin/messages", response_model=ContactPage, tags=["admin"])
def admin_messages(
    status: str | None = Query(default=None, pattern=r"^(new|read|replied|archived|spam)$"),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=512),
    _: dict = Depends(require_admin),
):
    collection = get_firestore().collection("contact_messages")
    query = collection
    if status:
        query = query.where("status", "==", status)
    query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
    items, next_cursor = _page(query, collection, limit, cursor, ContactRead)
    return {"items": items, "next_cursor": next_cursor}


@app.patch("/api/admin/messages/{message_id}", response_model=ContactRead, tags=["admin"])
def update_message(
    message_id: str,
    payload: MessageStatusUpdate,
    claims: dict = Depends(require_admin),
):
    reference = get_firestore().collection("contact_messages").document(message_id)
    if not reference.get().exists:
        raise HTTPException(status_code=404, detail="Message not found")
    reference.update({"status": payload.status, "updated_at": firestore.SERVER_TIMESTAMP})
    log_admin_activity(claims, "message.update", "contact_messages", message_id)
    data = reference.get().to_dict() or {}
    data["id"] = message_id
    return data


@app.get("/api/admin/analytics", tags=["admin"])
def analytics(_: dict = Depends(require_admin)):
    db = get_firestore()
    total = db.collection("contact_messages").count().get()[0][0].value
    new = db.collection("contact_messages").where("status", "==", "new").count().get()[0][0].value
    projects = db.collection("projects").stream()
    project_data = [
        {"slug": project.id, "views": int((project.to_dict() or {}).get("view_count", 0))}
        for project in projects
    ]
    return {
        "total_contact_messages": total,
        "new_messages": new,
        "total_projects": db.collection("projects").count().get()[0][0].value,
        "project_views": sorted(
            project_data,
            key=lambda item: (-item["views"], item["slug"]),
        ),
    }


@app.post("/api/admin/uploads", response_model=UploadRead, status_code=201, tags=["admin"])
async def upload_project_image(
    request: Request,
    file: UploadFile = File(...),
    claims: dict = Depends(require_admin),
):
    ensure_same_origin(request, require_origin=True)
    await run_in_threadpool(enforce_rate_limit, f"upload_{claims['sub']}", 20, 60 * 60)
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.upload_max_bytes + 1024 * 1024:
                raise HTTPException(status_code=413, detail="Upload exceeds the 4 MB limit")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from exc
    allowed = {
        "image/jpeg": (b"\xff\xd8\xff", ".jpg"),
        "image/png": (b"\x89PNG\r\n\x1a\n", ".png"),
        "image/webp": (b"RIFF", ".webp"),
    }
    file_type = file.content_type or ""
    if file_type not in allowed:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG, and WebP images are allowed")
    content = await file.read(settings.upload_max_bytes + 1)
    await file.close()
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="Upload exceeds the 4 MB limit")
    signature, extension = allowed[file_type]
    if not content.startswith(signature) or (file_type == "image/webp" and content[8:12] != b"WEBP"):
        raise HTTPException(status_code=415, detail="File content does not match an allowed image type")
    digest = hashlib.sha256(content).hexdigest()
    object_name = f"projects/{claims['sub']}/{uuid.uuid4().hex}{extension}"
    bucket = storage.bucket(app=get_firebase_app())
    blob = bucket.blob(object_name)
    blob.metadata = {"sha256": digest, "uploaded_by": claims["sub"]}
    await run_in_threadpool(blob.upload_from_string, content, content_type=file_type)
    return {"path": object_name, "content_type": file_type}
