# Payment roadmap (RentDirect Uganda)

## Hybrid strategy (MoMo + Pesapal + Sui)

| Layer | Channel | Role |
|-------|---------|------|
| **Fiat** | MTN MoMo, Airtel, Visa | Primary rent collection (Pesapal or MTN API) |
| **Web3** | Sui wallet | On-chain settlement + receipts |
| **Web3** | Move escrow | Deposits, release after tenancy |
| **Storage** | Walrus | Lease docs, KYC hashes, receipt blobs |

**Sui does not replace MoMo/Pesapal** — it adds settlement, escrow, and immutable proof.

## Implemented (phase 3 foundation)

- Backend: `app/services/blockchain/`, `app/routers/blockchain.py`
- Sui wallet checkout: `payment_method=sui` + `confirm-sui` endpoint
- Fiat payments auto-anchor receipt records when `SUI_ANCHOR_FIAT_RECEIPTS=true`
- Move contracts: `contracts/rentdirect/` (escrow + receipt)
- Frontend: `@mysten/dapp-kit`, Pay rent Sui option, Wallet blockchain receipts
- Docs: [SUI_PAYMENTS.md](./SUI_PAYMENTS.md)

## Setup

1. Keep `PAYMENT_GATEWAY_PROVIDER=pesapal` (or `mtn_momo`)
2. Set `SUI_TREASURY_ADDRESS` (devnet wallet with faucet SUI)
3. Optional: deploy Move package → `SUI_PACKAGE_ID`
4. Frontend: `VITE_SUI_NETWORK=devnet`

## Go live

| Stage | Network |
|-------|---------|
| Dev | devnet |
| Hackathon | testnet |
| Production | mainnet |
