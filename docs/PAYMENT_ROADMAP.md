# Payment roadmap (RentDirect Uganda)

## Strategy

| Phase | Channel | Purpose |
|-------|---------|---------|
| **1 — MTN MoMo** | Direct MTN Collection API | Fast USSD prompt on the tenant’s MTN line (MTN-only) |
| **2 — Pesapal** | Hosted checkout | MTN, Airtel, and card on one secure page |
| **3 — Blockchain** | TBD (e.g. Sui) | On-chain settlement — **not implemented yet** |

Landlord **manual** payments (cash, bank transfer recorded in the office) stay separate and do not use the gateway.

## How the app works today

- The API runs **one** online provider at a time (`PAYMENT_GATEWAY_PROVIDER` in `.env`).
- **Current setup:** `pesapal` (sandbox) — tenants open Pesapal and can pay with **MTN MoMo, Airtel, or card** there.
- **Direct MTN MoMo** is built (`mtn_momo` provider) but needs valid keys from [momodeveloper.mtn.com](https://momodeveloper.mtn.com). See `docs/GETTING_PAYMENT_KEYS.md` and `scripts/provision_mtn_sandbox.py`.

### Recommended rollout

1. **Now:** Keep **Pesapal** for all online tenant checkout (covers MoMo + Airtel + card).
2. **When MTN keys are ready:** Either:
   - Switch `.env` to `mtn_momo` for MTN-only USSD (Airtel/card need Pesapal again), or
   - Add dual-routing (future): MTN → direct API, Airtel/card → Pesapal.
3. **Later:** Blockchain provider + wallet connect UI (Sui is preview-only in clients today).

## Tenant vs landlord flows

| Who | Flow | Gateway |
|-----|------|---------|
| Tenant | Pay rent online | Pesapal or MTN MoMo (per `.env`) |
| Landlord | Record cash/bank | No gateway — `POST /payments` |

## Go live checklist

- [ ] Pesapal: `PESAPAL_ENV=live`, live consumer key/secret, live IPN on HTTPS
- [ ] MTN (optional): production subscription + `MTN_MOMO_TARGET_ENVIRONMENT=mtnuganda`
- [ ] `API_PUBLIC_BASE_URL` and `FRONTEND_BASE_URL` set to production HTTPS URLs
- [ ] One end-to-end payment per method (MTN, Airtel, card)

## Blockchain (phase 3)

Not wired to any provider. UI may show “Coming soon” until a gateway module and env vars exist.
