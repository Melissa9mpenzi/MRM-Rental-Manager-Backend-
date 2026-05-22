# Deploying the API on Vercel

## Required environment variables

Set these in the Vercel project **Settings → Environment Variables**:

| Variable | Example |
|----------|---------|
| `DATABASE_URL` | `postgresql+psycopg2://user:pass@host/neondb?sslmode=require` |
| `SECRET_KEY` | long random string |
| `ENVIRONMENT` | `production` |
| `ALLOWED_ORIGINS` | `https://mrm-rental-manager-frontend-pink.vercel.app,https://mrm-rental-manager-mobile.vercel.app` |
| `FRONTEND_BASE_URL` | `https://mrm-rental-manager-frontend-pink.vercel.app` |
| `API_PUBLIC_BASE_URL` | `https://mrm-rental-manager-backend.vercel.app` |
| `SKIP_STARTUP_MIGRATIONS` | `true` (run `python -m app.utils.init_db` locally against Neon once) |

Use the **`postgresql+psycopg2://`** prefix (not plain `postgresql://`) so SQLAlchemy uses the installed driver.

## Limitations

- Uploads are stored under `/tmp` and are **not persistent** across invocations. Use object storage for production file hosting.
- Cold starts can take several seconds; the first request after idle may be slow.
- Run database migrations manually against Neon; do not rely on API boot migrations on Vercel.

## Health check

After deploy, open `https://<your-project>.vercel.app/health` — expect `{"status":"ok"}`.
