# Hackathon blockchain setup — step by step

Use this before presenting RentDirect UG. Target: **Sui testnet** + **production Vercel** (not localhost).

---

## Part 1 — Vercel backend environment variables

1. Open [Vercel](https://vercel.com) → project **mrm-rental-manager-backend** → **Settings** → **Environment Variables**.
2. Set variables for **Production** (and Preview if you use preview URLs).
3. Click **Save**, then **Deployments** → latest deployment → **⋯** → **Redeploy** (required after any env change).

### A. Security and URLs (fixes QR → localhost)

| Variable | Value |
|----------|--------|
| `ENVIRONMENT` | `production` |
| `SECRET_KEY` | Long random string (see below) — **never** `change-me-in-production-use-long-random-string` |
| `FRONTEND_BASE_URL` | `https://mrm-rental-manager-frontend-pink.vercel.app` |
| `API_PUBLIC_BASE_URL` | `https://mrm-rental-manager-backend.vercel.app` |
| `ALLOWED_ORIGINS` | `https://mrm-rental-manager-frontend-pink.vercel.app,https://mrm-rental-manager-mobile.vercel.app` |
| `DATABASE_URL` | `postgresql+psycopg2://...@...neon.tech/neondb?sslmode=require` |
| `SKIP_STARTUP_MIGRATIONS` | `true` |

**Generate `SECRET_KEY` (PowerShell):**

```powershell
[Convert]::ToBase64String((1..48 | ForEach-Object { Get-Random -Maximum 256 }))
```

Copy the output into `SECRET_KEY`.

**Why this matters:** Receipt and lease QR codes use `FRONTEND_BASE_URL`. If it is missing, the API defaults to `http://localhost:5173` and phones cannot open the link.

---

### B. Sui testnet (on-chain rent)

| Variable | Value |
|----------|--------|
| `SUI_NETWORK` | `testnet` |
| `SUI_RPC_URL` | `https://fullnode.testnet.sui.io:443` |
| `SUI_TREASURY_ADDRESS` | Your testnet wallet address (starts with `0x`) |
| `SUI_UGX_PER_SUI` | `6000000` (optional, default) |
| `SUI_ANCHOR_FIAT_RECEIPTS` | `true` (optional — fiat pays also get blockchain receipt rows) |

**Optional (stronger demo):**

| Variable | Value |
|----------|--------|
| `SUI_PACKAGE_ID` | `0x...` after publishing Move package |
| `WALRUS_PUBLISHER_URL` | Walrus publisher URL |
| `WALRUS_AGGREGATOR_URL` | Walrus aggregator URL |

Without `SUI_PACKAGE_ID`: escrow metadata still works in the database; on-chain Move escrow is not linked.

Without Walrus publisher: proofs use **SHA-256 content hashes** (still verifiable; UI labels this honestly).

---

### C. Payments (fiat — keep sandbox or go live)

For hackathon **without real UGX**, sandbox is fine:

```env
PAYMENT_GATEWAY_PROVIDER=pesapal
PAYMENT_ALLOW_MOCK=false
PESAPAL_CONSUMER_KEY=...
PESAPAL_CONSUMER_SECRET=...
PESAPAL_ENV=sandbox
```

For **real money**, use Pesapal **live** keys and `PESAPAL_ENV=live`.

---

## Part 2 — Get testnet SUI for treasury

### Option A — Sui CLI (recommended)

1. Install Sui CLI: https://docs.sui.io/guides/developer/getting-started/sui-install  
2. In a terminal:

```bash
sui client
# If prompted, create wallet and choose testnet

sui client active-address
# Copy the 0x... address → paste into Vercel as SUI_TREASURY_ADDRESS

sui client faucet
# Repeat if balance is low
```

3. Confirm balance:

```bash
sui client gas
```

### Option B — Sui Wallet browser extension

1. Install [Sui Wallet](https://sui.io/) / Slush.  
2. Switch network to **Testnet**.  
3. Use **Request testnet SUI** from the wallet.  
4. Copy your address → `SUI_TREASURY_ADDRESS` on Vercel.

---

## Part 3 — Redeploy and verify API

After saving env vars, **redeploy the backend**.

### 3.1 Blockchain status

Open in a browser:

```
https://mrm-rental-manager-backend.vercel.app/api/v1/blockchain/status
```

Expect JSON like:

```json
{
  "success": true,
  "data": {
    "enabled": true,
    "network": "testnet",
    "treasury_configured": true,
    ...
  }
}
```

If `enabled` is `false`, `SUI_TREASURY_ADDRESS` is missing or empty on Vercel.

### 3.2 Production readiness

```
https://mrm-rental-manager-backend.vercel.app/api/v1/platform/readiness
```

| Field | Goal for hackathon |
|-------|---------------------|
| `issues` | **[]** (empty) — fix `SECRET_KEY`, `DATABASE_URL`, payments if listed |
| `warnings` | OK: sandbox payments, no Walrus publisher, no `SUI_PACKAGE_ID` |
| `ready_for_global_demo` | `true` when payments + DB + secret are OK |

### 3.3 Database health

```
https://mrm-rental-manager-backend.vercel.app/health/db
```

Expect `"database":"connected"`.

---

## Part 4 — Frontend (optional env)

Vercel project **mrm-rental-manager-frontend-pink**:

```env
VITE_API_URL=https://mrm-rental-manager-backend.vercel.app
VITE_GOV_API_URL=https://mrm-rental-manager-backend.vercel.app
VITE_SUI_NETWORK=testnet
```

Redeploy frontend after changes.

---

## Part 5 — Run one real testnet payment + QR scan

### 5.1 Prepare users

You need:

- A **tenant** with an active lease and an **unpaid invoice** (or use pay flow).
- Tenant logged in on: https://mrm-rental-manager-frontend-pink.vercel.app

On first login, the API provisions a **platform Sui wallet** (`sui_address` on profile / pay page).

### 5.2 Pay with Sui

1. Go to **Pay rent** (`/tenant/pay`).  
2. Confirm the banner says **Sui blockchain active on testnet**.  
3. Choose payment method **Sui**.  
4. Either:
   - **Platform wallet** — Pay now (server signs from auto wallet; treasury must have gas), or  
   - **External wallet** — Connect Slush/Suiet → approve transfer → confirm digest on API.  
5. Wait for success toast and receipt.

If pay fails:

- Treasury has no SUI → run `sui client faucet` for treasury address.  
- `blockchain/status` shows `enabled: false` → fix `SUI_TREASURY_ADDRESS` and redeploy.

### 5.3 Scan QR (must NOT be localhost)

1. Open the new **receipt** (tenant receipts or payment confirmation).  
2. Find **Scan to Verify Receipt** QR.  
3. Scan with your phone.

The URL must look like:

```
https://mrm-rental-manager-frontend-pink.vercel.app/verify/<long-token>
```

**Not** `http://localhost:5173/...`

4. Page should animate checks and show **Authenticated** (or explain which check failed).

**Old receipts** created before fixing `FRONTEND_BASE_URL` still have localhost in the QR. Issue a **new payment** after redeploy to get a correct QR.

### 5.4 Manual verify (if QR broken)

```
https://mrm-rental-manager-frontend-pink.vercel.app/verify/<token-from-receipt>
```

Or API only:

```
https://mrm-rental-manager-backend.vercel.app/api/v1/verify/<token>
```

---

## Part 6 — Judge demo script (5 minutes)

| Step | What to show |
|------|----------------|
| 1 | Login → tenant has **RentDirect Sui wallet** (no extension required) |
| 2 | Pay rent with **Sui** on testnet → success |
| 3 | Receipt PDF + **QR** → scan → verify page green |
| 4 | Show `blockchain/status` and `platform/readiness` in browser |
| 5 | (Optional) KCCA property verify or gov **Walrus audit export** |

**Talking point:** *Postgres runs operations; Sui settles trust; Walrus (or content hashes) stores dispute-grade proofs.*

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| QR opens localhost | Set `FRONTEND_BASE_URL` on backend Vercel, redeploy, **new** receipt after pay |
| Sui pay disabled | Set `SUI_TREASURY_ADDRESS`, redeploy, check `/blockchain/status` |
| `issues` includes SECRET_KEY | Set strong `SECRET_KEY`, not default placeholder |
| Verify page red, no tx | Paid with MoMo only — no `tx_hash`; Sui pay adds chain check |
| Platform wallet pay fails | Fund **treasury** with testnet SUI; tenant wallet may need faucet too |
| PDF download 500 | Redeploy backend with latest `feature-fix` (in-memory PDF on Vercel) |

---

## Related docs

- [HACKATHON_SUI_WALRUS.md](./HACKATHON_SUI_WALRUS.md) — positioning for judges  
- [SUI_PAYMENTS.md](./SUI_PAYMENTS.md) — API routes and Move deploy  
- [PRODUCTION_DEPLOY.md](./PRODUCTION_DEPLOY.md) — full production checklist  
- [VERCEL.md](./VERCEL.md) — Vercel deploy notes  
