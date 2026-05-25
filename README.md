# MRM Rental Manager — Backend API

FastAPI backend for **RentDirect UG** (MRM Rental Manager): property listings, tenant/landlord workflows, rent payments, leases, government oversight, and system administration.

| Environment | URL |
|-------------|-----|
| **Production API** | https://mrm-rental-manager-backend.vercel.app |
| **API docs (Swagger)** | https://mrm-rental-manager-backend.vercel.app/docs |
| **Health check** | https://mrm-rental-manager-backend.vercel.app/health |
| **Database check** | https://mrm-rental-manager-backend.vercel.app/health/db |

**Related repos**

| App | Repo role | Production URL |
|-----|-----------|----------------|
| Web app | [MRM-Rental-Manager-Frontend-](https://github.com/Melissa9mpenzi/MRM-Rental-Manager-Frontend-) | https://mrm-rental-manager-frontend-pink.vercel.app |
| Mobile / Flutter web | [MRM-Rental-Manager-Mobile-](https://github.com/Melissa9mpenzi/MRM-Rental-Manager-Mobile-) | https://mrm-rental-manager-mobile.vercel.app |

---

## What this service does

The API powers the full rental lifecycle in Uganda:

- **Authentication** — email/password, OTP verification, Firebase social login, role-based access
- **Roles** — tenant, landlord, agent, system admin, government officers (NIRA, KCCA, URA)
- **Properties & marketplace** — listings, search, saved units, applications
- **Tenants & leases** — onboarding, contracts, move-out
- **Payments** — MTN MoMo / Pesapal integration, wallets, invoices, receipts
- **Maintenance & messaging** — work orders and in-app communication
- **Government portal** — compliance dashboards, fraud review, approvals, audit trails
- **System admin** — platform-wide users, properties, payments, announcements

All REST routes are under **`/api/v1`**. Interactive documentation is at `/docs`.

---

## Tech stack

- **Python 3.11+** with **FastAPI** and **Uvicorn**
- **SQLAlchemy** + **Alembic** migrations
- **PostgreSQL** (Neon in production)
- **JWT** sessions, **bcrypt** passwords
- **Vercel serverless** deployment via `api/index.py`

---

## Local development

### 1. Prerequisites

- Python 3.11 or 3.12
- PostgreSQL (Neon cloud DB or local Postgres)
- Git

### 2. Setup

```bash
cd MRM-Rental-Manager-Backend-
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and set at minimum:

```env
DATABASE_URL=postgresql+psycopg2://user:pass@host/neondb?sslmode=require
SECRET_KEY=your-long-random-secret
ENVIRONMENT=development
FRONTEND_BASE_URL=http://localhost:5173
```

> Use the `postgresql+psycopg2://` prefix so SQLAlchemy picks the correct driver.

### 3. Initialize the database

```bash
python -m app.utils.init_db
```

To reset and seed a single system admin only:

```bash
python -m app.utils.reset_db
```

### 4. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open http://localhost:8000/docs to explore endpoints.

---

## Environment variables

Copy `.env.example` for the full list. Key variables:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string (**required**) |
| `SECRET_KEY` | JWT signing key |
| `ENVIRONMENT` | `development` or `production` |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins for frontends |
| `FRONTEND_BASE_URL` | Used in email links and redirects |
| `API_PUBLIC_BASE_URL` | Public API URL for webhooks and callbacks |
| `SKIP_STARTUP_MIGRATIONS` | Set `true` on Vercel (run migrations locally) |
| `PAYMENT_GATEWAY_PROVIDER` | `mtn_momo` or `pesapal` |
| `SMTP_*` | Email for OTP, invites, password reset |

See also:

- [docs/VERCEL.md](docs/VERCEL.md) — production deployment
- [docs/PAYMENT_GATEWAY.md](docs/PAYMENT_GATEWAY.md) — Uganda payment setup
- [docs/GETTING_PAYMENT_KEYS.md](docs/GETTING_PAYMENT_KEYS.md) — obtaining MoMo/Pesapal keys

---

## Deploying to Vercel

1. Connect this repo to a Vercel project.
2. Set environment variables (see [docs/VERCEL.md](docs/VERCEL.md)).
3. **Redeploy** after changing env vars.
4. Verify:
   - `GET /health` → `{"status":"ok"}`
   - `GET /health/db` → `{"status":"ok","database":"connected"}`

**Important:** Without `DATABASE_URL`, the API responds on `/health` but login and data routes fail.

Uploads on Vercel are stored in `/tmp` and are not persistent — use object storage for production file hosting.

---

## Project structure

```
app/
  main.py           # FastAPI app, CORS, routers
  config.py         # Settings from environment
  database.py       # SQLAlchemy engine and session
  models/           # ORM models
  routers/          # HTTP route handlers
  services/         # Business logic
  utils/            # DB init, seed, helpers
api/
  index.py          # Vercel serverless entrypoint
alembic/            # Database migrations
docs/               # Deployment and payment guides
```

---

## API overview

| Prefix | Area |
|--------|------|
| `/api/v1/auth` | Login, register, OTP, logout |
| `/api/v1/users` | Profiles, KYC documents |
| `/api/v1/properties` | Landlord property CRUD |
| `/api/v1/marketplace` | Public listings |
| `/api/v1/tenants` | Tenant management |
| `/api/v1/tenant-portal` | Tenant self-service |
| `/api/v1/payments` | Rent collection, webhooks |
| `/api/v1/government` | Government dashboards |
| `/api/v1/government/auth` | Officer invitations, 2FA |

---

## Testing

```bash
pytest
```

---

## License

Private — MRM Rental Manager / RentDirect UG.
