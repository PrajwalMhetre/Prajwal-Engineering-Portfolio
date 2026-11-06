from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from firebase_admin import firestore
from google.api_core.exceptions import AlreadyExists

from backend.app import main, security
from backend.app.main import app
from backend.app.security import require_admin


class Snapshot:
    def __init__(self, document_id, data):
        self.id = document_id
        self._data = deepcopy(data)
        self.exists = data is not None

    def to_dict(self):
        return deepcopy(self._data)


class Document:
    def __init__(self, collection, document_id):
        self.collection = collection
        self.id = document_id

    def get(self, transaction=None):
        return Snapshot(self.id, self.collection.documents.get(self.id))

    def create(self, data):
        if self.id in self.collection.documents:
            raise AlreadyExists("already exists")
        self.set(data)

    def set(self, data, merge=False):
        current = self.collection.documents.get(self.id, {}) if merge else {}
        self.collection.documents[self.id] = _resolve({**current, **data})

    def update(self, data):
        if self.id not in self.collection.documents:
            raise KeyError(self.id)
        self.collection.documents[self.id].update(_resolve(data))

    def delete(self):
        self.collection.documents.pop(self.id, None)


def _resolve(data):
    now = datetime.now(timezone.utc)
    result = {}
    for key, value in data.items():
        if value is firestore.SERVER_TIMESTAMP:
            result[key] = now
        elif isinstance(value, firestore.Increment):
            result[key] = value.value
        else:
            result[key] = deepcopy(value)
    return result


class Query:
    def __init__(self, collection, filters=(), orders=(), limit_value=None, cursor=None):
        self.collection = collection
        self.filters = list(filters)
        self.orders = list(orders)
        self.limit_value = limit_value
        self.cursor = cursor

    def where(self, field, operator, value):
        return Query(self.collection, [*self.filters, (field, operator, value)], self.orders, self.limit_value, self.cursor)

    def order_by(self, field, direction="ASCENDING"):
        return Query(self.collection, self.filters, [*self.orders, (field, direction)], self.limit_value, self.cursor)

    def limit(self, value):
        return Query(self.collection, self.filters, self.orders, value, self.cursor)

    def start_after(self, snapshot):
        return Query(self.collection, self.filters, self.orders, self.limit_value, snapshot.id)

    def stream(self):
        rows = list(self.collection.documents.items())
        for field, operator, value in self.filters:
            if operator == "==":
                rows = [(key, data) for key, data in rows if data.get(field) == value]
            elif operator == "array_contains":
                rows = [(key, data) for key, data in rows if value in data.get(field, [])]
        for field, direction in reversed(self.orders):
            rows.sort(
                key=lambda row: row[1].get(field, datetime.min.replace(tzinfo=timezone.utc)),
                reverse=direction == "DESCENDING",
            )
        if self.cursor:
            ids = [key for key, _ in rows]
            if self.cursor in ids:
                rows = rows[ids.index(self.cursor) + 1:]
        if self.limit_value is not None:
            rows = rows[:self.limit_value]
        return [Snapshot(key, data) for key, data in rows]

    def count(self):
        return Aggregate(self)


class Aggregate:
    def __init__(self, query):
        self.query = query

    def get(self):
        return [[SimpleNamespace(value=len(self.query.stream()))]]


class Collection(Query):
    def __init__(self, name):
        self.name = name
        self.documents = {}
        super().__init__(self)

    def document(self, document_id=None):
        return Document(self, document_id or uuid.uuid4().hex)


class FakeFirestore:
    def __init__(self):
        self.collections = {}

    def collection(self, name):
        if name not in self.collections:
            self.collections[name] = Collection(name)
        return self.collections[name]


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def fake_firestore(monkeypatch):
    db = FakeFirestore()
    monkeypatch.setattr(main, "get_firestore", lambda: db)
    monkeypatch.setattr(main, "enforce_rate_limit", lambda *args: None)
    monkeypatch.setattr(main, "log_admin_activity", lambda *args: None)
    return db


@pytest.fixture
def admin_client(monkeypatch):
    app.dependency_overrides[require_admin] = lambda: {
        "sub": "admin-uid",
        "email": "work.mhetreprajwal@gmail.com",
        "role": "admin",
    }
    monkeypatch.setattr(main, "enforce_rate_limit", lambda *args: None)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def project_payload(slug="test-project", **overrides):
    return {
        "slug": slug,
        "title": "Test project",
        "category": "software",
        "summary": "A sufficiently descriptive project summary.",
        "description": "Detailed project description.",
        "tech_stack": "Python, FastAPI",
        "repository_url": "https://github.com/example/project",
        "featured": False,
        "published": True,
        **overrides,
    }


def test_health_docs_and_readiness(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert "/api/health" in app.openapi()["paths"]
    assert client.get("/api/docs").status_code == 200
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert "Firebase services" in response.json()["detail"]


def test_admin_routes_reject_missing_authentication(client):
    response = client.get("/api/admin/me")
    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_contact_submission_is_validated_and_persisted(client, fake_firestore):
    response = client.post("/api/contact", json={
        "name": "  Alex Example  ",
        "email": "ALEX@example.com",
        "subject": "  Project collaboration ",
        "message": "  This is a sufficiently long message.  ",
    })
    assert response.status_code == 201
    stored = fake_firestore.collection("contact_messages").documents[response.json()["id"]]
    assert stored["name"] == "Alex Example"
    assert stored["email"] == "alex@example.com"
    assert stored["status"] == "new"
    assert stored["created_at"] is not None


def test_contact_honeypot_short_circuits_without_persisting(client, fake_firestore):
    response = client.post("/api/contact", json={
        "name": "Spam bot",
        "email": "bot@example.com",
        "subject": "Hello there",
        "message": "This is a sufficiently long message.",
        "website": "filled",
    })
    assert response.status_code == 202
    assert not fake_firestore.collection("contact_messages").documents


def test_contact_rate_limit_returns_retryable_error(client, monkeypatch):
    def reject_request(*args):
        raise HTTPException(status_code=429, detail="Too many requests")

    monkeypatch.setattr(main, "enforce_rate_limit", reject_request)
    response = client.post("/api/contact", json={
        "name": "Alex Example",
        "email": "alex@example.com",
        "subject": "A project request",
        "message": "Please contact me about the project.",
    })
    assert response.status_code == 429
    assert response.json()["detail"] == "Too many requests"


def test_validation_error_does_not_echo_submitted_values(client):
    response = client.post("/api/contact", json={
        "name": "   ",
        "email": "bad",
        "subject": " ",
        "message": " ",
        "password": "do-not-echo-this",
    })
    assert response.status_code == 422
    assert "do-not-echo-this" not in response.text


def test_project_crud_and_cursor_pagination(admin_client, fake_firestore):
    first = admin_client.post("/api/admin/projects", json=project_payload("first-project"))
    second = admin_client.post("/api/admin/projects", json=project_payload("second-project", featured=True))
    assert first.status_code == 201
    assert second.status_code == 201
    assert admin_client.post("/api/admin/projects", json=project_payload("first-project")).status_code == 409

    page = admin_client.get("/api/projects?limit=1").json()
    assert len(page["items"]) == 1
    assert page["next_cursor"]
    next_page = admin_client.get("/api/projects", params={"limit": 1, "cursor": page["next_cursor"]}).json()
    assert len(next_page["items"]) == 1
    assert next_page["items"][0]["id"] != page["items"][0]["id"]
    search = admin_client.get("/api/projects?search=test+summary").json()
    assert len(search["items"]) == 2

    slug = first.json()["id"]
    updated = admin_client.put(f"/api/admin/projects/{slug}", json={"title": "Updated project"})
    assert updated.status_code == 200
    assert updated.json()["title"] == "Updated project"
    assert admin_client.get(f"/api/projects/{slug}").json()["title"] == "Updated project"
    assert admin_client.delete(f"/api/admin/projects/{slug}").status_code == 204
    assert admin_client.get(f"/api/projects/{slug}").status_code == 404


def test_project_input_validation_and_unknown_fields(admin_client):
    invalid = project_payload("Invalid Slug")
    assert admin_client.post("/api/admin/projects", json=invalid).status_code == 422
    extra = project_payload("valid-project", is_admin=True)
    assert admin_client.post("/api/admin/projects", json=extra).status_code == 422


def test_published_project_image_is_served_through_private_storage(admin_client, fake_firestore, monkeypatch):
    image_path = "projects/admin-uid/" + "a" * 32 + ".png"
    created = admin_client.post(
        "/api/admin/projects",
        json=project_payload("image-project", image_path=image_path),
    )
    assert created.status_code == 201

    class Blob:
        def download_as_bytes(self):
            return b"\x89PNG\r\n\x1a\nimage"

    class Bucket:
        def blob(self, path):
            assert path == image_path
            return Blob()

    monkeypatch.setattr(main, "get_firebase_app", lambda: object())
    monkeypatch.setattr(main.storage, "bucket", lambda **kwargs: Bucket())
    response = admin_client.get("/api/projects/image-project/image")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")

    admin_client.put(
        "/api/admin/projects/image-project",
        json={"published": False},
    )
    assert admin_client.get("/api/projects/image-project/image").status_code == 404


def test_contact_message_management_and_analytics(admin_client, fake_firestore):
    submitted = admin_client.post("/api/contact", json={
        "name": "Alex Example",
        "email": "alex@example.com",
        "subject": "A project request",
        "message": "Please contact me about the project.",
    })
    message_id = submitted.json()["id"]
    response = admin_client.get("/api/admin/messages")
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == message_id
    changed = admin_client.patch(f"/api/admin/messages/{message_id}", json={"status": "read"})
    assert changed.status_code == 200
    assert changed.json()["status"] == "read"
    analytics = admin_client.get("/api/admin/analytics").json()
    assert analytics["total_contact_messages"] == 1
    assert analytics["new_messages"] == 0
    assert analytics["total_projects"] == 0


def test_firebase_identity_requires_allowlisted_verified_user(monkeypatch):
    settings = SimpleNamespace(admin_email_set={"work.mhetreprajwal@gmail.com"})
    monkeypatch.setattr(security, "get_settings", lambda: settings)
    monkeypatch.setattr(security, "get_firebase_app", lambda: object())
    monkeypatch.setattr(security.auth, "verify_id_token", lambda *args, **kwargs: {
        "uid": "admin-uid",
        "email": "work.mhetreprajwal@gmail.com",
        "email_verified": True,
        "exp": 4_000_000_000,
    })
    monkeypatch.setattr(security.auth, "get_user", lambda *args, **kwargs: SimpleNamespace(
        uid="admin-uid", email="work.mhetreprajwal@gmail.com", email_verified=True, disabled=False
    ))
    db = FakeFirestore()
    db.collection("admins").document("admin-uid").set({"email": "work.mhetreprajwal@gmail.com"})
    monkeypatch.setattr(security, "get_firestore", lambda: db)

    result = security.verify_admin_token("firebase-id-token")
    assert result["role"] == "admin"
    assert result["email"] == "work.mhetreprajwal@gmail.com"

    db.collection("admins").documents.clear()
    with pytest.raises(HTTPException) as error:
        security.verify_admin_token("firebase-id-token")
    assert error.value.status_code == 403

    monkeypatch.setattr(security.auth, "verify_id_token", lambda *args, **kwargs: {
        "uid": "admin-uid", "email": "attacker@example.com", "email_verified": True, "exp": 4_000_000_000
    })
    with pytest.raises(HTTPException) as error:
        security.verify_admin_identity("untrusted-token")
    assert getattr(error.value, "status_code", None) == 403

    monkeypatch.setattr(security.auth, "verify_id_token", lambda *args, **kwargs: {
        "uid": "admin-uid",
        "email": "work.mhetreprajwal@gmail.com",
        "email_verified": False,
        "exp": 4_000_000_000,
    })
    with pytest.raises(HTTPException) as error:
        security.verify_admin_identity("unverified-token")
    assert error.value.status_code == 403


def test_cors_rejects_untrusted_origin(client):
    response = client.options("/api/contact", headers={
        "Origin": "https://untrusted.example",
        "Access-Control-Request-Method": "POST",
    })
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_upload_rejects_unsupported_and_oversized_files(admin_client, monkeypatch):
    origin = {"Origin": "https://prajwal-engineering-portfolio-web.vercel.app"}
    unsupported = admin_client.post("/api/admin/uploads", files={
        "file": ("bad.svg", b"<svg></svg>", "image/svg+xml")
    }, headers=origin)
    assert unsupported.status_code == 415
    spoofed = admin_client.post("/api/admin/uploads", files={
        "file": ("image.jpg", b"not a JPEG", "image/jpeg")
    }, headers=origin)
    assert spoofed.status_code == 415

    monkeypatch.setattr(main.settings, "upload_max_bytes", 3)
    oversized = admin_client.post("/api/admin/uploads", files={
        "file": ("image.png", b"\x89PNG\r\n\x1a\nmore", "image/png")
    }, headers=origin)
    assert oversized.status_code == 413


def test_upload_content_length_is_rejected_before_multipart_parsing(admin_client):
    response = admin_client.post(
        "/api/admin/uploads",
        content=b"",
        headers={
            "Origin": "https://prajwal-engineering-portfolio-web.vercel.app",
            "Content-Type": "multipart/form-data; boundary=unused",
            "Content-Length": str(main.settings.upload_max_bytes + 1024 * 1024 + 1),
        },
    )
    assert response.status_code == 413


def test_upload_stores_valid_images_privately(admin_client, monkeypatch):
    class Blob:
        metadata = None

        def upload_from_string(self, content, content_type):
            self.content = content
            self.content_type = content_type

    class Bucket:
        def blob(self, path):
            self.path = path
            self.object = Blob()
            return self.object

    bucket = Bucket()
    monkeypatch.setattr(main, "get_firebase_app", lambda: object())
    monkeypatch.setattr(main.storage, "bucket", lambda **kwargs: bucket)
    response = admin_client.post("/api/admin/uploads", files={
        "file": ("image.png", b"\x89PNG\r\n\x1a\nimage data", "image/png")
    }, headers={"Origin": "https://prajwal-engineering-portfolio-web.vercel.app"})
    assert response.status_code == 201
    assert response.json()["path"].startswith("projects/admin-uid/")
    assert bucket.object.content_type == "image/png"
    assert bucket.object.metadata["sha256"]


def test_auth_verify_sets_http_only_session_cookies(client, monkeypatch):
    identity = {"sub": "admin-uid", "email": "work.mhetreprajwal@gmail.com", "expires_at": 4_000_000_000}
    monkeypatch.setattr(main, "verify_admin_identity", lambda token: identity)
    monkeypatch.setattr(main, "_admin_document", lambda *args: None)
    response = client.post("/api/auth/verify", json={
        "id_token": "firebase-id-token",
        "refresh_token": "firebase-refresh-token",
    }, headers={"Origin": "https://prajwal-engineering-portfolio-web.vercel.app"})
    assert response.status_code == 200
    cookies = response.headers.get_list("set-cookie")
    assert any("HttpOnly" in cookie and "pm_admin_access" in cookie for cookie in cookies)
    assert any("HttpOnly" in cookie and "pm_admin_refresh" in cookie for cookie in cookies)


def test_admin_login_sets_cookies_without_returning_firebase_tokens(client, monkeypatch):
    class FirebaseResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "idToken": "private-id-token",
                "refreshToken": "private-refresh-token",
                "expiresIn": "3600",
            }

    class FirebaseClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FirebaseResponse()

    monkeypatch.setattr(main, "_firebase_api_url", lambda: "https://firebase.example/login")
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: FirebaseClient())
    monkeypatch.setattr(main, "verify_admin_identity", lambda token: {
        "sub": "admin-uid",
        "email": "work.mhetreprajwal@gmail.com",
        "expires_at": 4_000_000_000,
    })
    monkeypatch.setattr(main, "_admin_document", lambda *args: None)
    monkeypatch.setattr(main, "enforce_rate_limit", lambda *args: None)
    response = client.post(
        "/api/auth/login",
        json={"email": "work.mhetreprajwal@gmail.com", "password": "valid-password"},
        headers={"Origin": "https://prajwal-engineering-portfolio-web.vercel.app"},
    )
    assert response.status_code == 200
    assert "private-id-token" not in response.text
    assert "private-refresh-token" not in response.text
    assert any("HttpOnly" in cookie and "pm_admin_access" in cookie
               for cookie in response.headers.get_list("set-cookie"))


def test_refresh_failure_clears_session_cookies(client, monkeypatch):
    class FirebaseResponse:
        status_code = 400

    class FirebaseClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, *args, **kwargs):
            return FirebaseResponse()

    monkeypatch.setattr(main.settings, "firebase_web_api_key", "test-api-key")
    monkeypatch.setattr(main.httpx, "AsyncClient", lambda **kwargs: FirebaseClient())
    response = client.post(
        "/api/auth/refresh",
        headers={
            "Origin": "https://prajwal-engineering-portfolio-web.vercel.app",
            "Cookie": "pm_admin_refresh=expired-token",
        },
    )
    assert response.status_code == 401
    assert any("pm_admin_refresh" in cookie and "Max-Age=0" in cookie
               for cookie in response.headers.get_list("set-cookie"))
