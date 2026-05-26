# Production deploy — global presentation (no mock data)

Use this checklist before presenting RentDirect UG internationally.

## 1. Verify readiness endpoint

After deploy, open:

```
GET https://YOUR-API/api/v1/platform/readiness
```

`ready_for_global_demo` must be **true**. Fix every item in `issues` before the presentation.

## 2. Required Vercel / API environment

```env
ENVIRONMENT=production
DATABASE_URL=postgresql+psycopg2://...
DATABASE_SCHEMA=public
SKIP_STARTUP_MIGRATIONS=false
SECRET_KEY=<long-random>

PAYMENT_GATEWAY_PROVIDER=pesapal
PAYMENT_ALLOW_MOCK=false
PESAPAL_CONSUMER_KEY=...
PESAPAL_CONSUMER_SECRET=...
PESAPAL_ENV=sandbox   # or live for real money

SUI_NETWORK=testnet
SUI_TREASURY_ADDRESS=0x...
SUI_RPC_URL=https://fullnode.testnet.sui.io:443

VITE_PRIVY_APP_ID=...
PRIVY_APP_ID=...
PRIVY_APP_SECRET=...

FRONTEND_BASE_URL=https://your-frontend.vercel.app
API_PUBLIC_BASE_URL=https://your-api.vercel.app
ALLOWED_ORIGINS=https://your-frontend.vercel.app
```

## 3. Strongly recommended

```env
WALRUS_PUBLISHER_URL=https://...
WALRUS_AGGREGATOR_URL=https://...
SUI_PACKAGE_ID=0x...        # after: sui client publish contracts/rentdirect
```

Without Walrus publisher: proofs still work via **SHA-256 content hashes** (labeled honestly in UI — not fake Walrus blobs).

## 4. What is NOT dummy

| Feature | Behavior |
|---------|----------|
| Payments | Real Pesapal/MTN API (mock disabled in production) |
| Sui pay | On-chain verify via RPC + treasury address |
| Receipts | DB + PDF + optional blockchain row |
| Gov fraud | SQL rules on real users/properties |
| Admin KPIs | Live Postgres counts |
| Demo seed | Blocked when `ENVIRONMENT=production` |

## 5. QR verification (signature feature)

Every payment receipt, lease, KCCA-approved property, and NIRA-approved identity gets a **random verification token** (not payment data in the QR).

| QR opens | Example URL |
|----------|-------------|
| Unified (recommended) | `https://your-app.vercel.app/verify/{token}` |
| Typed (optional) | `/verify/receipt/{token}`, `/verify/contract/{token}`, … |

Public API: `GET /api/v1/verify/{token}` — checks hash integrity, payment, optional Sui tx, Walrus proof.

## 6. Pre-demo test script

1. Register a new tenant (email or Privy Google).
2. Landlord creates property + lease → **contract QR** on Contracts page.
3. Tenant pays via MoMo or Sui → receipt PDF + **Scan to Verify Receipt** QR.
4. Scan QR on phone → animated **Verifying on Sui…** → **Receipt Authenticated**.
5. Open `/api/v1/platform/readiness` → green.
6. Government officer login → fraud alerts from DB.

## 6. Do not use for global demo

- `PAYMENT_ALLOW_MOCK=true`
- `python -m app.utils.seed_data` (full demo) on production DB
- Fake KPI deltas on Sui dashboard (removed)
- Pretending `hash:…` blob IDs are Walrus (UI now labels correctly)
