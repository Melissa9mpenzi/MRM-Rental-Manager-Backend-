# How to get payment API keys (Uganda)

Pick **one** provider in `.env` — do not enable both at the same time.

| If tenants pay with… | Use | Keys you need |
|---------------------|-----|----------------|
| **MTN only** | `PAYMENT_GATEWAY_PROVIDER=mtn_momo` | MTN MoMo Developer (4 values) |
| **MTN + Airtel + card** | `PAYMENT_GATEWAY_PROVIDER=pesapal` | Pesapal (3 values) |

---

## Option A — MTN MoMo keys (`mtn_momo`)

### 1. Create a developer account

1. Open [https://momodeveloper.mtn.com](https://momodeveloper.mtn.com)
2. Sign up / log in
3. Accept terms

### 2. Create a product & subscribe to **Collection**

1. In the portal, go to **Products** (or **My Apps**)
2. Create a new product / application
3. Subscribe to **Collection** (sometimes labeled *Collections* or *Request to Pay*)
4. Copy the **Primary Key** (Subscription Key) → this is:

```env
MTN_MOMO_SUBSCRIPTION_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

(There may also be a Secondary Key — use **Primary** for collections.)

### 3. Create API User + API Key (sandbox)

MTN does **not** give you the API User/Key on the dashboard alone — you **provision** them once:

**In the developer portal (easiest):**

- Look for **Sandbox Users**, **Provisioning**, or **Manage APIs** under your Collection subscription
- Follow **“Create API User”** / **“Provision sandbox user”**
- You receive:
  - **API User** (UUID) → `MTN_MOMO_API_USER`
  - **API Key** (secret string) → `MTN_MOMO_API_KEY`  
  Copy the API Key immediately — it is often shown only once.

**Or via API (if the portal points you here):**

```http
POST https://sandbox.momodeveloper.mtn.com/v1_0/apiuser
Headers:
  X-Reference-Id: {new-uuid}
  Ocp-Apim-Subscription-Key: {MTN_MOMO_SUBSCRIPTION_KEY}
Body:
  { "providerCallbackHost": "your-public-hostname.com" }
```

Then:

```http
POST https://sandbox.momodeveloper.mtn.com/v1_0/apiuser/{same-uuid}/apikey
Headers:
  Ocp-Apim-Subscription-Key: {MTN_MOMO_SUBSCRIPTION_KEY}
```

Response body contains the **API Key**.

### 4. Target environment & base URL

**Sandbox (testing):**

```env
MTN_MOMO_TARGET_ENVIRONMENT=sandbox
MTN_MOMO_BASE_URL=https://sandbox.momodeveloper.mtn.com
```

**Production Uganda** (after MTN approves you for live):

```env
MTN_MOMO_TARGET_ENVIRONMENT=mtnuganda
MTN_MOMO_BASE_URL=https://proxy.momoapi.mtn.com
```

Confirm the exact production `X-Target-Environment` value in the MTN portal for **Uganda** — it must match what MTN assigns.

### 5. Callback URL (webhook)

Your API must be reachable from the internet (use [ngrok](https://ngrok.com) on localhost).

```env
MTN_MOMO_CALLBACK_URL=https://YOUR-PUBLIC-HOST/api/v1/payments/webhooks/mtn-momo
```

Register the same URL in the MTN developer portal under **Callback Host** / **Provider Callback**.

Example with ngrok:

```env
MTN_MOMO_CALLBACK_URL=https://abc123.ngrok-free.app/api/v1/payments/webhooks/mtn-momo
API_PUBLIC_BASE_URL=https://abc123.ngrok-free.app
```

### 6. Full MTN `.env` example

```env
PAYMENT_GATEWAY_PROVIDER=mtn_momo
PAYMENT_ALLOW_MOCK=false

MTN_MOMO_SUBSCRIPTION_KEY=your-primary-subscription-key
MTN_MOMO_API_USER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MTN_MOMO_API_KEY=your-secret-api-key
MTN_MOMO_TARGET_ENVIRONMENT=sandbox
MTN_MOMO_BASE_URL=https://sandbox.momodeveloper.mtn.com
MTN_MOMO_CALLBACK_URL=https://your-public-url/api/v1/payments/webhooks/mtn-momo
```

Restart the backend after saving `.env`.

### 7. Sandbox test phone

MTN sandbox uses **test MSISDNs** listed in their docs/portal (not real money). Use those when paying in the app.

---

## Option B — Pesapal keys (`pesapal`)

### 1. Merchant account

1. Go to [https://www.pesapal.com/ug/business/online/](https://www.pesapal.com/ug/business/online/)
2. Register your business (RentDirect / landlord company details)
3. Complete Pesapal **KYC** and merchant approval

### 2. Developer credentials

1. Open [https://developer.pesapal.com](https://developer.pesapal.com) (log in with merchant account)
2. Go to **API keys** / **Applications**
3. Create an app (or use default test app)
4. Copy:
   - **Consumer Key** → `PESAPAL_CONSUMER_KEY`
   - **Consumer Secret** → `PESAPAL_CONSUMER_SECRET`

### 3. Sandbox vs live

```env
PESAPAL_ENV=sandbox
```

For real UGX after approval:

```env
PESAPAL_ENV=live
```

### 4. IPN (webhook) — `PESAPAL_IPN_ID`

1. In Pesapal dashboard → **IPN** / **Instant Payment Notification**
2. Register URL:

   `https://YOUR-PUBLIC-HOST/api/v1/payments/webhooks/pesapal`

3. Pesapal gives you a **Notification ID** (or IPN ID) →

```env
PESAPAL_IPN_ID=that-id-from-dashboard
```

### 5. Full Pesapal `.env` example

```env
PAYMENT_GATEWAY_PROVIDER=pesapal
PAYMENT_ALLOW_MOCK=false

PESAPAL_CONSUMER_KEY=your-consumer-key
PESAPAL_CONSUMER_SECRET=your-consumer-secret
PESAPAL_ENV=sandbox
PESAPAL_IPN_ID=your-ipn-notification-id

FRONTEND_BASE_URL=http://localhost:5173
API_PUBLIC_BASE_URL=https://your-public-url
```

Restart the backend.

---

## Verify configuration

```http
GET http://localhost:8000/api/v1/payments/gateway/status
```

You want `"configured": true` and the correct `"provider"`.

---

## Common mistakes

1. **Mixing two providers in one line** — each variable on its own line; only one `PAYMENT_GATEWAY_PROVIDER=...`
2. **No public URL** — MTN/Pesapal webhooks cannot reach `localhost` without ngrok or a deployed API
3. **Using Pesapal for MTN-only** — unnecessary; use MTN MoMo API directly
4. **Using MTN MoMo for Airtel** — MTN API is MTN-only; use Pesapal for Airtel

## Which should you choose?

- **Most landlords, MTN tenants only** → start with **MTN MoMo** (fewer fees/partners, direct USSD)
- **Need Airtel + Visa/Mastercard on same checkout** → **Pesapal**
