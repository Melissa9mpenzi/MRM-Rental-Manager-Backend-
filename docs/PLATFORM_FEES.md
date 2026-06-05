# Platform fees & landlord balance

RentDirect UG earns when landlords use the platform to **collect rent online** and **manage occupied units**.

## Fee table (default — override via env)

| Item | Rate | Who pays | When |
|------|------|----------|------|
| **Online rent collection** | **1.5%** of gross rent (min **UGX 500**) | Landlord (deducted from payout) | Each MoMo / Pesapal / Sui payment |
| **Per active unit** | **UGX 8,000 / month** | Landlord | Monthly per **occupied** unit |
| **Manual bank recording** | **0%** | — | Landlord records offline payment in app |
| **Tenant browse / search** | **Free** | — | — |

### Example — Lydia pays UGX 3,000,000 rent online

| Line | Amount |
|------|--------|
| Tenant pays (gross) | UGX 3,000,000 |
| Platform fee (1.5%) | UGX 45,000 |
| **Landlord balance credit** | **UGX 2,955,000** |

Landlord with **5 occupied units** also accrues **UGX 40,000/month** unit subscription (5 × 8,000).

## Environment variables

```env
PLATFORM_RENT_FEE_PERCENT=1.5
PLATFORM_RENT_FEE_FLAT_UGX=0
PLATFORM_RENT_FEE_MIN_UGX=500
PLATFORM_UNIT_FEE_MONTHLY_UGX=8000
```

## API

| Method | Path | Role |
|--------|------|------|
| GET | `/api/v1/payments/platform-fees` | Public fee table |
| GET | `/api/v1/payments/landlord-balance` | Landlord — balance + ledger preview |
| GET | `/api/v1/payments/landlord-ledger` | Landlord — full ledger |
| POST | `/api/v1/payments/accrue-unit-fees` | Landlord — bill this month's unit fees |
| GET | `/api/v1/payments/platform-revenue` | System admin — platform totals |

## Data model

- **`payments`**: `gross_amount`, `platform_fee`, `net_to_landlord` on online settlements
- **`landlord_ledger_entries`**: credits, fees, unit subscriptions, future payouts

## Payouts (next phase)

Landlord `available_balance_ugx` is the ledger sum. Automatic MoMo/bank **payout to landlord** is not implemented yet — use ledger for reporting until disbursement is wired.
