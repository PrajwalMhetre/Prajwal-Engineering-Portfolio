from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from backend.app.config import get_settings
from backend.app.db import get_db
from backend.app.models import ContactMessage, PortfolioProject, ProjectView
from backend.app.schemas import ContactCreate, ContactCreated, ContactRead, MessageStatusUpdate, ProjectCreate, ProjectRead, ProjectUpdate
from backend.app.security import client_ip_hash, ensure_same_origin, require_admin

settings = get_settings()
app = FastAPI(title=settings.app_name, version="1.0.0",
              description="Portfolio API: projects, contact submissions, protected admin and analytics.",
              docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
app.add_middleware(CORSMiddleware, allow_origins=sorted(settings.origin_set), allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                   allow_headers=["Content-Type", "Authorization"])

def auth_url(path: str) -> str:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status_code=503, detail="Supabase Auth configuration is missing")
    return f"{settings.supabase_url.rstrip('/')}/auth/v1/{path}"

def set_cookies(response: Response, session: dict) -> None:
    common = {"secure": settings.cookie_secure, "httponly": True, "samesite": "lax", "path": "/api"}
    if settings.cookie_domain:
        common["domain"] = settings.cookie_domain
    response.set_cookie(settings.access_cookie_name, session["access_token"],
                        max_age=int(session.get("expires_in", 3600)), **common)
    response.set_cookie(settings.refresh_cookie_name, session["refresh_token"],
                        max_age=60 * 60 * 24 * 30, **common)

def clear_cookies(response: Response) -> None:
    response.delete_cookie(settings.access_cookie_name, path="/api", domain=settings.cookie_domain or None)
    response.delete_cookie(settings.refresh_cookie_name, path="/api", domain=settings.cookie_domain or None)

@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok", "service": settings.app_name, "time": datetime.now(timezone.utc).isoformat()}

@app.get("/api/ready", tags=["health"])
def readiness(db: Session = Depends(get_db)):
    db.execute(select(1))
    return {"status": "ready", "database": "connected"}

@app.post("/api/contact", response_model=ContactCreated, status_code=201, tags=["contact"])
def create_contact(payload: ContactCreate, request: Request, db: Session = Depends(get_db)):
    if payload.website:
        return Response(status_code=202)
    ip_hash = client_ip_hash(request)
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    count = db.scalar(select(func.count(ContactMessage.id)).where(
        ContactMessage.ip_hash == ip_hash, ContactMessage.created_at >= since)) or 0
    if count >= settings.contact_rate_limit_per_hour:
        raise HTTPException(status_code=429, detail="Too many messages. Try again later.")
    row = ContactMessage(name=payload.name, email=str(payload.email).lower(),
                         subject=payload.subject, message=payload.message, ip_hash=ip_hash)
    db.add(row); db.commit(); db.refresh(row)
    return ContactCreated(id=row.id, status=row.status, created_at=row.created_at)

@app.get("/api/projects", response_model=list[ProjectRead], tags=["projects"])
def list_projects(category: str | None = None, featured: bool | None = None,
                  limit: int = 100, offset: int = 0, db: Session = Depends(get_db)):
    query = select(PortfolioProject).where(PortfolioProject.published.is_(True))
    if category: query = query.where(PortfolioProject.category == category)
    if featured is not None: query = query.where(PortfolioProject.featured.is_(featured))
    return list(db.scalars(query.order_by(PortfolioProject.featured.desc(), PortfolioProject.updated_at.desc())
                           .offset(max(offset, 0)).limit(min(max(limit, 1), 100))))

@app.get("/api/projects/{slug}", response_model=ProjectRead, tags=["projects"])
def get_project(slug: str, db: Session = Depends(get_db)):
    row = db.scalar(select(PortfolioProject).where(PortfolioProject.slug == slug,
                                                   PortfolioProject.published.is_(True)))
    if not row: raise HTTPException(status_code=404, detail="Project not found")
    return row

@app.post("/api/projects/{slug}/view", status_code=202, tags=["analytics"])
def record_project_view(slug: str, request: Request, db: Session = Depends(get_db)):
    exists = db.scalar(select(PortfolioProject.id).where(PortfolioProject.slug == slug,
                                                         PortfolioProject.published.is_(True)))
    if not exists: raise HTTPException(status_code=404, detail="Project not found")
    ref = request.headers.get("referer")
    if ref:
        parsed = urlparse(ref); ref = f"{parsed.scheme}://{parsed.netloc}"[:500]
    db.add(ProjectView(project_slug=slug, referrer=ref, ip_hash=client_ip_hash(request))); db.commit()
    return {"accepted": True}

@app.post("/api/auth/login", tags=["authentication"])
async def login(payload: dict, request: Request, response: Response):
    ensure_same_origin(request)
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    if email not in settings.admin_email_set or not password or len(password) > 1024:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    async with httpx.AsyncClient(timeout=12) as client:
        result = await client.post(auth_url("token?grant_type=password"),
            json={"email": email, "password": password},
            headers={"apikey": settings.supabase_anon_key})
    if result.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    session = result.json()
    user = session.get("user") or {}
    if str(user.get("email", "")).lower() not in settings.admin_email_set:
        raise HTTPException(status_code=403, detail="Admin access required")
    set_cookies(response, session)
    return {"authenticated": True, "email": email, "expires_in": session.get("expires_in", 3600)}

@app.post("/api/auth/refresh", tags=["authentication"])
async def refresh(request: Request, response: Response):
    ensure_same_origin(request)
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token: raise HTTPException(status_code=401, detail="Session expired")
    async with httpx.AsyncClient(timeout=12) as client:
        result = await client.post(auth_url("token?grant_type=refresh_token"),
            json={"refresh_token": token}, headers={"apikey": settings.supabase_anon_key})
    if result.status_code != 200:
        clear_cookies(response); raise HTTPException(status_code=401, detail="Session expired")
    session = result.json()
    user = session.get("user") or {}
    if str(user.get("email", "")).lower() not in settings.admin_email_set:
        clear_cookies(response); raise HTTPException(status_code=403, detail="Admin access required")
    set_cookies(response, session)
    return {"authenticated": True, "expires_in": session.get("expires_in", 3600)}

@app.post("/api/auth/logout", tags=["authentication"])
async def logout(request: Request, response: Response):
    ensure_same_origin(request)
    token = request.cookies.get(settings.access_cookie_name)
    if token and settings.supabase_url and settings.supabase_anon_key:
        async with httpx.AsyncClient(timeout=8) as client:
            await client.post(auth_url("logout"), headers={"apikey": settings.supabase_anon_key,
                              "Authorization": f"Bearer {token}"})
    clear_cookies(response)
    return {"authenticated": False}

@app.get("/api/admin/me", tags=["admin"])
def admin_me(claims: dict = Depends(require_admin)):
    return {"authenticated": True, "email": claims.get("email")}

@app.get("/api/admin/messages", response_model=list[ContactRead], tags=["admin"])
def admin_messages(status: str | None = None, limit: int = 100, db: Session = Depends(get_db),
                   _: dict = Depends(require_admin)):
    query = select(ContactMessage)
    if status: query = query.where(ContactMessage.status == status)
    return list(db.scalars(query.order_by(ContactMessage.created_at.desc()).limit(min(max(limit, 1), 200))))

@app.patch("/api/admin/messages/{message_id}", response_model=ContactRead, tags=["admin"])
def update_message(message_id: int, payload: MessageStatusUpdate, db: Session = Depends(get_db),
                   _: dict = Depends(require_admin)):
    row = db.get(ContactMessage, message_id)
    if not row: raise HTTPException(status_code=404, detail="Message not found")
    row.status = payload.status; db.commit(); db.refresh(row); return row

@app.post("/api/admin/projects", response_model=ProjectRead, status_code=201, tags=["admin"])
def create_project(payload: ProjectCreate, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    row = PortfolioProject(**payload.model_dump(mode="json"))
    db.add(row)
    try: db.commit()
    except Exception:
        db.rollback(); raise HTTPException(status_code=409, detail="Project slug already exists or data conflicts")
    db.refresh(row); return row

@app.patch("/api/admin/projects/{project_id}", response_model=ProjectRead, tags=["admin"])
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db),
                   _: dict = Depends(require_admin)):
    row = db.get(PortfolioProject, project_id)
    if not row: raise HTTPException(status_code=404, detail="Project not found")
    for key, value in payload.model_dump(exclude_unset=True, mode="json").items():
        setattr(row, key, value)
    db.commit(); db.refresh(row); return row

@app.delete("/api/admin/projects/{project_id}", status_code=204, tags=["admin"])
def delete_project(project_id: int, db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    row = db.get(PortfolioProject, project_id)
    if not row: raise HTTPException(status_code=404, detail="Project not found")
    db.delete(row); db.commit(); return Response(status_code=204)

@app.get("/api/admin/analytics", tags=["admin"])
def analytics(db: Session = Depends(get_db), _: dict = Depends(require_admin)):
    views = db.execute(select(ProjectView.project_slug, func.count(ProjectView.id))
                       .group_by(ProjectView.project_slug)).all()
    total = db.scalar(select(func.count(ContactMessage.id))) or 0
    new = db.scalar(select(func.count(ContactMessage.id)).where(ContactMessage.status == "new")) or 0
    return {"total_contact_messages": total, "new_messages": new,
            "project_views": [{"slug": slug, "views": count} for slug, count in views]}
