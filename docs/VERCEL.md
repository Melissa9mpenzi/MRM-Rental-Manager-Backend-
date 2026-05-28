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
| `FIREBASE_CREDENTIALS_JSON_BASE64` | base64-encoded Firebase service-account JSON (recommended on Vercel) |
| `FIREBASE_CREDENTIALS_PATH` | absolute path to service-account JSON (non-serverless hosts) |
| `FIREBASE_STORAGE_BUCKET` | `your-project-id.appspot.com` (optional, for persistent property images/videos) |

Use the **`postgresql+psycopg2://`** prefix (not plain `postgresql://`) so SQLAlchemy uses the installed driver.

## Limitations

- Local `/uploads` on Vercel are under `/tmp` and are **not persistent** across invocations.
- For persistent media on Vercel, set `FIREBASE_CREDENTIALS_JSON_BASE64` + `FIREBASE_STORAGE_BUCKET`; uploads then use Firebase Storage URLs.
- Cold starts can take several seconds; the first request after idle may be slow.
- Run database migrations manually against Neon; do not rely on API boot migrations on Vercel.

## Migrate old media to Firebase

After enabling Firebase Storage, migrate already-uploaded local media paths (`/uploads/...`) in the database:

1. Dry run (reports what can be migrated):
   - `python -m app.utils.migrate_media_to_firebase`
2. Apply migration:
   - `python -m app.utils.migrate_media_to_firebase --apply`
3. Optional smoke test on a few items first:
   - `python -m app.utils.migrate_media_to_firebase --apply --limit 10`

The migration updates media fields in properties, tenants, maintenance requests, message attachments, payment proofs, and receipt PDF paths to Firebase URLs.  
If a local file is missing, that row is reported and skipped.

## Health check

After deploy, open `https://<your-project>.vercel.app/health` — expect `{"status":"ok"}`.
