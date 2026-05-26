# Sui payments — RentDirect UG (hybrid Web3)

> **Sui-first framing:** [`SUI_FIRST_STRATEGY.md`](./SUI_FIRST_STRATEGY.md) — position as decentralized rental infrastructure, not “CRM + crypto.”

## Hackathon tracks

| Priority | Track | RentDirect angle |
|----------|--------|------------------|
| **Primary** | **DeFi & Payments** | Escrow, on-chain receipts, Sui wallets, Move contracts |
| **Secondary** | **Walrus** | Agreements, receipts, KYC, escrow proofs, gov audit |
| **Optional** | Risk signals | Rule-based fraud only — no fake AI |
| **Avoid** | Agentic Web / DeepBook | Not our story |

---

RentDirect uses a **hybrid** model: MTN MoMo, Airtel, and card stay on **Pesapal/MTN**; Sui adds settlement, escrow, and immutable receipts **without replacing** fiat rails.

## Architecture

```
Tenant pay page
  ├── MTN / Airtel / Card  →  Pesapal or MTN API  →  invoice paid
  │                              └── optional blockchain receipt (Walrus + Sui hash)
  └── Sui Wallet           →  sign transfer  →  API verifies tx  →  invoice paid + on-chain receipt
```

## Backend modules

| Module | Path | Role |
|--------|------|------|
| Sui RPC | `app/services/blockchain/sui_rpc.py` | Verify transfers, UGX→MIST conversion |
| Blockchain service | `app/services/blockchain/blockchain_service.py` | Wallets, receipts, escrow |
| Sui gateway | `app/services/gateway/sui_provider.py` | Checkout for `payment_method=sui` |
| Walrus | `app/services/blockchain/walrus_service.py` | Decentralized receipt/lease doc storage |
| Move contracts | `contracts/rentdirect/` | Escrow + receipt anchor (deploy to devnet/testnet) |

## API endpoints

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/v1/blockchain/status` | Sui/Walrus config for UI |
| GET/POST | `/api/v1/blockchain/wallet/me`, `/link` | Connect Sui address |
| GET | `/api/v1/blockchain/receipts` | On-chain receipt list |
| GET/POST | `/api/v1/blockchain/escrow` | Escrow holds + release |
| POST | `/api/v1/payments/checkout/initiate` | `payment_method=sui` for wallet pay |
| POST | `/api/v1/payments/checkout/{ref}/confirm-sui` | Submit tx digest after wallet sign |

## `.env` (add to API)

```env
# Keep fiat gateway
PAYMENT_GATEWAY_PROVIDER=pesapal

# Sui hybrid layer
SUI_NETWORK=testnet
SUI_RPC_URL=https://fullnode.testnet.sui.io:443
SUI_TREASURY_ADDRESS=0xYOUR_DEVNET_ADDRESS
SUI_PACKAGE_ID=0x...          # after: sui client publish contracts/rentdirect
SUI_ESCROW_MODULE=escrow
SUI_UGX_PER_SUI=6000000
SUI_ANCHOR_FIAT_RECEIPTS=true

# Walrus (optional)
WALRUS_PUBLISHER_URL=
WALRUS_AGGREGATOR_URL=
```

### Get a devnet treasury address

1. Install [Sui CLI](https://docs.sui.io/guides/developer/getting-started/sui-install)
2. `sui client active-address` (or create new wallet)
3. `sui client faucet` (devnet/testnet)
4. Copy address → `SUI_TREASURY_ADDRESS`

## Deploy Move contracts (hackathon / demo)

```bash
cd contracts/rentdirect
sui move build
sui client publish --gas-budget 100000000
```

Set `SUI_PACKAGE_ID` from publish output.

## Frontend

- `@mysten/dapp-kit` + `@mysten/sui` in `src/providers/SuiProvider.jsx`
- Tenant **Pay rent** → choose **Sui Wallet** → Connect → sign → confirm
- **Wallet** page shows blockchain receipts and escrow status

```env
VITE_SUI_NETWORK=testnet
```

## Networks

| Stage | Network |
|-------|---------|
| Hackathon demo (**recommended**) | **testnet** |
| Experiments only | devnet |
| Production | mainnet |

## What impresses judges

- Real Uganda rent + MoMo/Pesapal **plus** Sui receipts
- Escrow smart contracts for deposits
- Government audit trail hooks (`blockchain_receipts` table)
- Walrus for lease/KYC document integrity

See also: [PAYMENT_ROADMAP.md](./PAYMENT_ROADMAP.md)
