# Prajwal Mhetre — Engineering Portfolio

A responsive, dependency-free portfolio spanning semiconductor design, embedded systems, AI/ML and software engineering.

## Features
- Premium dark UI with cyan / blue / violet accents
- Space Grotesk, Manrope and DM Mono typography
- Responsive navigation and mobile layout
- Education, engineering focus, selected repositories and contact sections
- Searchable catalogue of 50 semiconductor + 50 software project concepts
- Focus-music links (no autoplay)
- SEO / Open Graph metadata and reduced-motion support

## Run locally
Open `index.html` or run `python3 -m http.server 8080` and visit `http://localhost:8080`.

## Project status
The 100-item index is a curated roadmap, not a claim that all projects are complete. Repository cards link to public repositories; verify implementation status before representing work as finished.

## Deployment
Static hosting: Vercel, Cloudflare Pages or GitHub Pages. Build command: none. Output directory: `.`.


## Full-stack backend (added)
The FastAPI backend is exposed under `/api/*` on the same Vercel origin. Existing static portfolio pages remain served normally.

### Stack
FastAPI · PostgreSQL (Supabase) · SQLAlchemy 2 · Alembic · Supabase Auth JWT sessions · OpenAPI/Swagger · Vercel Functions · GitHub Actions.

### Admin allowlist
- work.mhetreprajwal@gmail.com
- mhprajwal601@gmail.com

Only these pre-created Supabase Auth users can authenticate as admins. Keep public sign-up disabled and enable MFA for both accounts.

### Local backend setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Set DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY in .env
alembic upgrade head
uvicorn backend.app.main:app --reload
```

### Production environment
Configure these in Vercel Project Settings > Environment Variables (Production, Preview and Development):
- `DATABASE_URL`: Supabase Postgres connection string using the Supabase pooler for serverless.
- `SUPABASE_URL`: Supabase project URL.
- `SUPABASE_ANON_KEY`: Supabase publishable key or legacy anon key.
- `ADMIN_EMAILS`: `work.mhetreprajwal@gmail.com,mhprajwal601@gmail.com`
- `ALLOWED_ORIGINS`: the exact production portfolio origin.
- `COOKIE_SECURE`: `true`

Do not commit real credentials, service-role keys or database passwords. Do not expose database credentials in browser code. The backend validates access tokens through Supabase Auth and stores them only in HttpOnly cookies.

### Endpoints
- `GET /api/health`, `GET /api/ready`
- `POST /api/contact`
- `GET /api/projects`, `GET /api/projects/{slug}`
- `POST /api/projects/{slug}/view`
- `POST /api/auth/login`, `POST /api/auth/refresh`, `POST /api/auth/logout`
- `GET /api/admin/me`, `GET /api/admin/messages`
- `PATCH /api/admin/messages/{id}`
- `POST /api/admin/projects`, `PATCH /api/admin/projects/{id}`, `DELETE /api/admin/projects/{id}`
- `GET /api/admin/analytics`
- Swagger: `/api/docs`

The database migration enables RLS and revokes direct Data API access for `anon` and `authenticated`; the backend uses a server-side PostgreSQL connection.