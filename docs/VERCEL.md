# Deploying the API on Vercel

## Required environment variables

Set these in the Vercel project **Settings → Environment Variables** (then **Redeploy**):

| Variable | Example |
|----------|---------|
| `DATABASE_URL` | `postgresql+psycopg2://user:pass@ep-xxx-pooler.neon.tech/neondb?sslmode=require` |
| `DATABASE_SCHEMA` | `public` (must match where Neon tables live) |

**Without `DATABASE_URL`, `/health` works but login returns 503.**

After deploy, open `/health/db` — you want `"app_tables":"ready"`.  
If you see `"missing_run_init_db"`, run `python -m app.utils.init_db` locally against Neon (see `docs/NEON_VERCEL_FIX.md`).

**Do not** use `channel_binding=require` in the URL on Vercel.
| `SECRET_KEY` | long random string |
| `ENVIRONMENT` | `production` |
| `ALLOWED_ORIGINS` | `https://mrm-rental-manager-frontend-pink.vercel.app,https://mrm-rental-manager-mobile.vercel.app` |
| `FRONTEND_BASE_URL` | `https://mrm-rental-manager-frontend-pink.vercel.app` |
| `API_PUBLIC_BASE_URL` | `https://mrm-rental-manager-backend.vercel.app` |
| `SKIP_STARTUP_MIGRATIONS` | `false` (or omit — migrations run on cold start) |

Use the **`postgresql+psycopg2://`** prefix (not plain `postgresql://`) so SQLAlchemy uses the installed driver.

## Limitations

- Uploads are stored under `/tmp` and are **not persistent** across invocations. Use object storage for production file hosting.
- Cold starts can take several seconds; the first request after idle may be slow.
- Run database migrations manually against Neon; do not rely on API boot migrations on Vercel.

## Health check

After deploy, open `https://<your-project>.vercel.app/health` — expect `{"status":"ok"}`.
