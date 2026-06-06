# Privy social auth + embedded Sui wallet

RentDirect uses **[Privy](https://www.privy.io/)** (recommended) for Gmail, Apple, and email login with an embedded **Sui** wallet — no separate “connect wallet” step.

**Alternative:** [Enoki](https://enoki.mystenlabs.com/) (Mysten) for zkLogin-style Sui auth — not wired in this repo yet; Privy covers social + embedded wallets in one SDK.

---

## 1. Privy Dashboard

1. Create an app at [dashboard.privy.io](https://dashboard.privy.io/).
2. **Login methods:** enable Google, Apple, Email.
3. **Embedded wallets → Extended chains:** enable **Sui** (testnet for hackathon).
4. **Allowed domains:** `http://localhost:5173`, your Vercel frontend URL.
5. **Configuration → UI components → Branding** (improves OTP emails + login modal):
   - **Name:** `RentDirect` (shown in emails and Privy UI)
   - **Logo:** hosted PNG, 180×90px recommended — e.g.  
     `https://mrm-rental-manager-frontend-pink.vercel.app/rentdirect-logo.png`
   - **Brand color:** `#00C076` (matches RentDirect green theme)
6. Copy **App ID** and **App Secret**.

Optional frontend override:

```env
VITE_PRIVY_LOGO_URL=https://your-cdn.com/rentdirect-logo.png
```

> **Note:** Privy sends the OTP email. Full custom HTML templates require Privy Enterprise; branding (logo + color + name) is configured in the dashboard above. The app also includes a **whitelabel email OTP form** on login and pay pages so users enter the code inside RentDirect instead of a generic Privy popup.

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
# Optional — policy ID from Dashboard → Policies (auto-attached before pay)
PRIVY_SUI_POLICY_ID=
# Required only if policy/wallet has an owner in Privy Dashboard
PRIVY_AUTHORIZATION_PRIVATE_KEY=
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

---

## 6. Sui wallet policies (required for Pay rent)

Rent payments use Privy **`raw_sign`** on a Sui transaction with **`SplitCoins`** (take rent from gas coin) and **`TransferObjects`** (send to treasury). Privy’s policy engine evaluates every `raw_sign` as method **`signTransactionBytes`**. If no rule allows those commands, signing fails with *“Privy blocked this Sui payment”*.

### Create the policy (Dashboard)

1. [dashboard.privy.io](https://dashboard.privy.io/) → your app → **Controls** → **Policies** → **Create policy**.
2. **Chain type:** `Sui`.
3. Add an **ALLOW** rule:
   - **Method:** `signTransactionBytes`
   - **Field source:** `sui_transaction_command`
   - **Field:** `commandName`
   - **Operator:** `in`
   - **Values:** `SplitCoins`, `TransferObjects`, `MergeCoins`
4. Save and copy the **Policy ID** (24-character string).

Example JSON (if importing via API):

```json
{
  "version": "1.0",
  "name": "RentDirect Sui rent pay",
  "chain_type": "sui",
  "rules": [
    {
      "name": "Allow rent transfer commands",
      "method": "signTransactionBytes",
      "conditions": [
        {
          "field_source": "sui_transaction_command",
          "field": "commandName",
          "operator": "in",
          "value": ["TransferObjects", "SplitCoins", "MergeCoins"]
        }
      ],
      "action": "ALLOW"
    }
  ]
}
```

Docs: [Privy Sui policy examples](https://docs.privy.io/controls/policies/example-policies/sui).

### Attach the policy to wallets

Creating a policy alone is not enough — each **embedded Sui wallet** must have it assigned:

1. **Dashboard → Wallets** → filter **Sui** → open the wallet → **Policies** → attach your policy, **or**
2. **Embedded wallets** settings → set a **default policy** for new Sui wallets (then reconnect so a new wallet is created), **or**
3. Set on the API (optional): `PRIVY_SUI_POLICY_ID=<policy-id>` on Vercel — the backend attaches it before signing.

Wallets created **before** the policy existed will keep failing until you attach the policy or disconnect and create a fresh Sui wallet after a default policy is set.

### Still blocked after creating the policy?

Privy **defaults to DENY** when no rule matches. Common fixes:

1. **Add a catch-all ALLOW rule** (same policy, second rule): method `signTransactionBytes`, action `ALLOW`, **no conditions** — allows any Sui command.
2. **Remove DENY rules** — DENY always wins over ALLOW.
3. **Dashboard → Wallets → your Sui wallet → Policies** — confirm your policy ID appears on **that exact wallet** (not only in env vars).
4. **Embedded wallets → Default policy** — set your ALLOW policy as the default for new Sui embedded wallets.
5. Check Vercel backend env: `PRIVY_SUI_POLICY_ID` must match the 24-character ID from Dashboard → Policies (not the app ID).

### Authorization signature 401 (`privy-authorization-signature`)

If you set an **owner** on your policy or wallet (Privy recommends this for production), server `raw_sign` and policy attach need an **authorization private key**:

**Easiest (hackathon):** Edit your Sui policy in Dashboard → **remove the owner**. Do not set a wallet owner on embedded wallets. App secret alone is then enough.

**Production:** Dashboard → **Authorization keys** → create key → copy private key → Vercel:

```env
PRIVY_AUTHORIZATION_PRIVATE_KEY=wallet-auth:...   # or raw base64 key from Privy
```

Use the **same key** as the policy owner. Without this env var, RentDirect pays via **browser signing** (still works if the policy is attached to the wallet in Dashboard → Wallets).

### Optional: cap transfers to your treasury only

Add a second ALLOW rule with **Field source** `sui_transfer_objects_command`, **Field** `recipient`, **Operator** `eq`, **Value** = your `SUI_TREASURY_ADDRESS` (from Vercel backend env).
