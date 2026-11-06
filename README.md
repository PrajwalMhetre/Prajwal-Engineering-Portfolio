# Prajwal Mhetre — Engineering Portfolio

A responsive, dependency-free HTML/CSS/JavaScript portfolio with a Firebase-backed FastAPI API. The existing public pages, project concept catalogue, navigation, animations and music player remain static and retain their current UI.

## Run the portfolio locally

Open `index.html`, or run `python3 -m http.server 8080` and visit `http://localhost:8080`.

The portfolio can still be browsed without a configured backend. Contact submissions and the admin console require the API described below.

## Backend architecture

- Python 3.12+, FastAPI, Pydantic v2 and Firebase Admin SDK
- Cloud Firestore collections: `admins`, `projects`, `contact_messages`, `project_views`, `site_settings`, and `activity_logs`
- Firebase Authentication email/password identity provider; backend verifies ID tokens, checks revocation, reloads the user record and applies the verified-email administrator allowlist on every protected request
- Firebase Storage for validated, private project image uploads
- HttpOnly, SameSite=Strict access and refresh cookies; logout revokes Firebase refresh tokens
- Cursor-paginated project and contact APIs; Firestore indexes are in `firestore.indexes.json`
- API health, readiness, Swagger (`/api/docs`) and OpenAPI (`/api/openapi.json`)

Firestore and Storage client rules deny direct client access. The server uses the Firebase Admin SDK, which bypasses those rules; grant the Vercel service account only the Firestore and Storage IAM roles the API needs.

## Local API setup

1. In Firebase Console, create a project and enable **Authentication / Email and password**, **Cloud Firestore**, and **Cloud Storage**.
2. Create and verify these users in Firebase Authentication; public administrator registration is not implemented:
   - `work.mhetreprajwal@gmail.com`
   - `mhprajwal601@gmail.com`
3. Configure Auth authorized domains and the Firebase web API key. Keep account creation restricted to trusted operators; the API does not expose a sign-up route.
4. Deploy `firestore.rules`, `storage.rules`, and `firestore.indexes.json` with the Firebase CLI (`firebase deploy --only firestore,storage`).
5. Create a service account with least-privilege Firestore and Storage IAM permissions. Do not download or commit its JSON key.
6. Configure a local environment:

   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   ```

   Fill the Firebase values in `.env`, use `COOKIE_SECURE=false` only for local HTTP, and add your local origin (for example `http://localhost:8080`) to `ALLOWED_ORIGINS`.

7. Start the API:

   ```bash
   uvicorn backend.app.main:app --reload
   ```

The Firebase Admin SDK service-account key is supplied as environment variables. `FIREBASE_PRIVATE_KEY` accepts either literal newlines or `\n` sequences. No credential file is required.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `FIREBASE_PROJECT_ID` | Firebase project ID |
| `FIREBASE_CLIENT_EMAIL` | Service-account email |
| `FIREBASE_PRIVATE_KEY` | Service-account private key; store only as a secret |
| `FIREBASE_STORAGE_BUCKET` | Firebase Storage bucket name |
| `FIREBASE_WEB_API_KEY` | Firebase Identity Toolkit / Secure Token REST API key |
| `ALLOWED_ADMIN_EMAILS` | Comma-separated server-side admin allowlist |
| `ALLOWED_ORIGINS` | Exact comma-separated browser origins, with scheme |
| `COOKIE_SECURE` | Set `true` for HTTPS deployments |
| `COOKIE_DOMAIN` | Optional cookie domain; normally leave empty |

See [.env.example](./.env.example). Never expose service-account credentials or private keys in browser code.

## API

- `GET /api/health`, `GET /api/ready`
- `GET /api/projects?limit=20&cursor=...&search=...`
- `GET /api/projects/{slug}`
- `GET /api/projects/{slug}/image` (public only for published projects)
- `POST /api/projects/{slug}/view`
- `POST /api/contact`
- `POST /api/auth/login`, `POST /api/auth/verify`, `POST /api/auth/refresh`, `POST /api/auth/logout`
- `GET /api/admin/me`
- `GET /api/admin/projects`, `POST /api/admin/projects`, `PUT /api/admin/projects/{project_id}`, `DELETE /api/admin/projects/{project_id}`
- `GET /api/admin/messages`, `PATCH /api/admin/messages/{message_id}`
- `GET /api/admin/analytics`
- `POST /api/admin/uploads` (JPEG, PNG or WebP; maximum 4 MB; objects remain private)
- Swagger: `/api/docs`

The existing contact form continues to post to `/api/contact`. The existing admin login exchanges credentials with Firebase Authentication server-side and receives only HttpOnly cookies; public JavaScript never handles Firebase tokens.

## Deploy to Vercel

1. Connect the `feature/firebase-backend` branch to a Vercel Preview deployment. The existing static site remains the frontend and `api/index.py` exposes FastAPI under `/api/*`.
2. Set all Firebase variables and `ALLOWED_ORIGINS` in Vercel Project Settings. Add the exact deployed origin; keep `COOKIE_SECURE=true`.
3. Deploy Firestore/Storage rules and indexes to the same Firebase project. Create both verified administrator accounts in Firebase Console.
4. Keep Vercel Production deployments attached to `main`; require the `Backend CI / test` check in GitHub branch protection. Deploy to Preview and verify `/api/health`, `/api/ready`, `/api/docs`, contact submissions, and an authorized admin session before promoting.
5. Configure GitHub Actions; CI runs imports, OpenAPI generation, and tests on the feature branch and pull requests before merge.

No Firebase credentials are present in this repository, so live Firebase readiness, Storage IAM permissions, Vercel deployment, and production health cannot be verified from a local checkout. Existing PostgreSQL/Supabase data is not automatically migrated; export and validate it before switching any live deployment to Firestore.

## Tests

```bash
pip install -r requirements.txt pytest
pytest -q
```

Tests use isolated Firebase mocks and do not require credentials. Firebase Emulator Suite integration was not run here; configure the Firestore, Authentication and Storage emulator host variables and add emulator-backed integration tests before relying on live-service behavior.

## Project catalogue

The 100-item index is a curated roadmap, not a claim that every concept is complete. Public repository cards link to their source repositories; verify implementation status before representing work as finished.
