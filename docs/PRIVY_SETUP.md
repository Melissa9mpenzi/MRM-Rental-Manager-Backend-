# Privy social auth + embedded Sui wallet

RentDirect uses **[Privy](https://www.privy.io/)** (recommended) for Gmail, Apple, and email login with an embedded **Sui** wallet — no separate “connect wallet” step.

**Alternative:** [Enoki](https://enoki.mystenlabs.com/) (Mysten) for zkLogin-style Sui auth — not wired in this repo yet; Privy covers social + embedded wallets in one SDK.

---

## 1. Privy Dashboard

1. Create an app at [dashboard.privy.io](https://dashboard.privy.io/).
2. **Login methods:** enable Google, Apple, Email.
3. **Embedded wallets → Extended chains:** enable **Sui** (testnet for hackathon).
4. **Allowed domains:** `http://localhost:5173`, your Vercel frontend URL.
5. Copy **App ID** and **App Secret**.

---

## 2. Environment variables

**Frontend** (`.env` / Vercel):

```env
VITE_PRIVY_APP_ID=your-privy-app-id
VITE_SUI_NETWORK=testnet
```

**Backend** (`.env` / Vercel):

```env
PRIVY_APP_ID=your-privy-app-id
PRIVY_APP_SECRET=your-privy-app-secret
```

Install API dependency:

```bash
pip install privy-client
```

---

## 3. Flow

1. User taps **Google** or **Apple** on login/register.
2. Privy authenticates and creates an embedded Sui wallet (`chainType: sui`).
3. Frontend sends Privy **access token** → `POST /api/v1/auth/privy`.
4. API verifies token, creates/links RentDirect user, stores `privy_did`, links Sui address (`wallet_source=privy`).
5. API returns RentDirect JWT — same session as email/password.

First-time social users are **auto-registered** (no “register first” step). Role on register page is passed as `role` (default `tenant`).

---

## 4. Firebase fallback

If `VITE_PRIVY_APP_ID` is unset, the UI falls back to **Firebase** (`VITE_FIREBASE_*` + `FIREBASE_CREDENTIALS_PATH`). Firebase still requires an existing email account.

Prefer Privy for hackathon demos: one tap → account + Sui address.

---

## 5. API

```
POST /api/v1/auth/privy
{
  "access_token": "<privy-access-token>",
  "sui_address": "0x…",   // optional; API also reads from Privy user profile
  "role": "tenant"        // optional on first sign-up
}
```

---

See also: `docs/HACKATHON_SUI_WALRUS.md`, `docs/SUI_PAYMENTS.md`.
