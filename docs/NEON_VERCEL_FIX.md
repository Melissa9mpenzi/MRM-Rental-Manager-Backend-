# Fix: "Could not reach the database" (Neon + Vercel)

## 1. Set `DATABASE_URL` on Vercel (backend project)

1. Open [Neon Console](https://console.neon.tech) → your project → **Connection details**.
2. Choose **Pooled connection** (host contains `-pooler`).
3. Copy the URI and adapt for this API:

```env
DATABASE_URL=postgresql+psycopg2://USER:PASSWORD@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require
DATABASE_SCHEMA=rental_mgr
```

**Do not** include `channel_binding=require` — the API strips it automatically, but Neon’s raw string often breaks login on Vercel.

4. Vercel → **Settings → Environment Variables** → add for **Production** (and Preview if needed).
5. **Deployments → Redeploy** (env vars apply only after redeploy).

## 2. Create tables on Neon (one-time)

From your PC, in `MRM-Rental-Manager-Backend-`, put the **same** `DATABASE_URL` in `.env`, then:

```bash
pip install -r requirements.txt
python -m app.utils.init_db
```

You should see tables under schema `rental_mgr` in Neon SQL editor.

Optional on Vercel (slower cold starts):

```env
SKIP_STARTUP_MIGRATIONS=false
```

The API will run lightweight migrations on boot. For first-time DB, still run `init_db` locally once.

## 3. Verify

Open:

`https://mrm-rental-manager-backend.vercel.app/health/db`

**Good:**

```json
{"status":"ok","database":"connected","schema":"rental_mgr","app_tables":"ready"}
```

**Tables missing:**

```json
{"app_tables":"missing_run_init_db", ...}
```

→ Run step 2.

## 4. Other Vercel variables

| Variable | Value |
|----------|--------|
| `SECRET_KEY` | long random string |
| `ENVIRONMENT` | `production` |
| `ALLOWED_ORIGINS` | your frontend + mobile Vercel URLs |

## 5. Neon checklist

- Project is **not suspended** (free tier idle suspend).
- IP allow list: **allow all** (or Vercel has no fixed IPs — use pooler + SSL).
- Password special characters are **URL-encoded** in the connection string.
