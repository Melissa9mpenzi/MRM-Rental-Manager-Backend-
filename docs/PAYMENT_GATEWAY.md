# Uganda rent payments (MTN MoMo & Pesapal)

Flutterwave is **not** the default for RentDirect UG — many Uganda businesses cannot onboard there. Use:

| Provider | Best for | Sign up |
|----------|----------|---------|
| **mtn_momo** (default) | **MTN Mobile Money** — USSD prompt on tenant phone | [momodeveloper.mtn.com](https://momodeveloper.mtn.com) |
| **pesapal** | **MTN + Airtel + card** on one hosted page | [pesapal.com/ug](https://www.pesapal.com/ug/business/online/) |

## Option A — MTN MoMo only (recommended for MTN rent)

1. Register at **MTN MoMo Developer** → create app → subscribe to **Collection**.
2. Provision **API User** + **API Key** (sandbox, then production).
3. Set `.env`:

```env
PAYMENT_GATEWAY_PROVIDER=mtn_momo
PAYMENT_ALLOW_MOCK=false

MTN_MOMO_SUBSCRIPTION_KEY=your-primary-subscription-key
MTN_MOMO_API_USER=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
MTN_MOMO_API_KEY=your-api-key
MTN_MOMO_TARGET_ENVIRONMENT=sandbox
# Production Uganda: mtnuganda (confirm in MTN portal for your market)
# MTN_MOMO_TARGET_ENVIRONMENT=mtnuganda

# Sandbox base URL (default):
# MTN_MOMO_BASE_URL=https://sandbox.momodeveloper.mtn.com
# Production:
# MTN_MOMO_BASE_URL=https://proxy.momoapi.mtn.com

MTN_MOMO_CALLBACK_URL=https://api.your-app.com/api/v1/payments/webhooks/mtn-momo
```

4. Register callback URL in MTN developer portal.

**Flow:** `RequestToPay` → tenant approves on phone → webhook or poll → invoice marked paid.

## Option B — Pesapal (MTN + Airtel + card)

```env
PAYMENT_GATEWAY_PROVIDER=pesapal
PESAPAL_CONSUMER_KEY=...
PESAPAL_CONSUMER_SECRET=...
PESAPAL_ENV=sandbox
# PESAPAL_ENV=live
PESAPAL_IPN_ID=your-registered-ipn-id

FRONTEND_BASE_URL=https://your-app.com
API_PUBLIC_BASE_URL=https://api.your-app.com
```

Webhook / IPN: `https://api.your-app.com/api/v1/payments/webhooks/pesapal`

Tenant opens Pesapal page → chooses MTN, Airtel, or card → auto-settlement on IPN.

## Check status

`GET /api/v1/payments/gateway/status`

```json
{
  "provider": "mtn_momo",
  "configured": true,
  "mode": "sandbox",
  "country": "UG",
  "supports": { "mtn_momo": true, "airtel": false, "card": false }
}
```

Use `supports` in the app to show/hide Airtel or card options.

## Local dev mock (fake money only)

```env
PAYMENT_GATEWAY_PROVIDER=mock
PAYMENT_ALLOW_MOCK=true
ENVIRONMENT=development
```

Never enable mock in production.
