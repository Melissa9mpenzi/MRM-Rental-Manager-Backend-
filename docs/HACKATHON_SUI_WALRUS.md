# Hackathon: Sui & Walrus positioning (RentDirect UG)

> **Sui-first strategy:** see [`SUI_FIRST_STRATEGY.md`](./SUI_FIRST_STRATEGY.md) for judge demo script, build order, and positioning.

## The question judges ask

**“How exactly does this benefit from Sui & Walrus?”**

Short answer:

| Layer | Role |
|-------|------|
| **Postgres** | Day-to-day CRM — listings, leases, gov workflows, MoMo/Pesapal webhooks |
| **Sui** | Settlement & trust — rent payments, escrow, verifiable tx digests |
| **Walrus** | Durable proofs — receipt JSON, KYC manifests, property packets, audit exports |

We are **not** putting the whole product on chain. We are **Payments track first**, Walrus **second** (strategic proofs).

---

## Email → Sui address (no “connect wallet” step)

**Recommended:** [Privy](https://www.privy.io/) — Google / Apple / email login creates an embedded **Sui** wallet automatically (`docs/PRIVY_SETUP.md`). Alternative: [Enoki](https://enoki.mystenlabs.com/) (zkLogin) for Mysten-native flows.

1. User registers / logs in with email, **Privy social**, or password.
2. API calls `ensure_platform_wallet()` or links **Privy** Sui address — deterministic platform wallet per `user_id` when Privy wallet is absent.
3. Login/`/auth/me` returns `sui_address` and `sui_wallet_auto: true`.
4. Tenant pays rent via `POST /payments/checkout/{ref}/pay-platform-sui` (server signs with `pysui` on testnet).
5. **Optional:** link Slush/Suiet via `POST /blockchain/wallet/link` for self-custody.

Frontend: `PlatformSuiWallet`, `/tenant/pay` defaults to platform wallet; checkbox for external wallet.

---

## Why Sui (demo script)

1. **On-chain rent settlement** — Treasury receives SUI; digest stored on `blockchain_receipts` and shown in tenant/landlord UI.
2. **Programmable escrow** — Move package on testnet (`SUI_PACKAGE_ID`) for deposit hold/release tied to lease lifecycle.
3. **Low-friction Web3** — Judges see tenants pay without installing a wallet extension.
4. **Hybrid rails** — Same invoice flow supports MTN MoMo, Pesapal, and Sui (real-world Uganda).

Env: `SUI_NETWORK=testnet`, `SUI_TREASURY_ADDRESS`, `SECRET_KEY` (wallet derivation), optional `pysui` on API host.

---

## Why Walrus (strategic, not “all data”)

Walrus is for **evidence**, not the primary database:

| Artifact | When anchored |
|----------|----------------|
| Payment receipt JSON | After Sui or fiat checkout completes |
| KYC manifest hash | On KYC submit / NIRA review |
| Property verification packet | KCCA approval workflow |
| Government audit export | Officer actions |
| Escrow lease / release proof | Escrow create / release |

- **Live:** set `WALRUS_PUBLISHER_URL` (and related env in `SUI_PAYMENTS.md`).
- **Demo without publisher:** content hashes still recorded so UI and gov audit show proof IDs.

Judges should hear: *“Transactional truth on Sui; dispute-grade blobs on Walrus; operations in SQL.”*

---

## Demo paths

| Step | Route / action |
|------|----------------|
| Show auto wallet | Login → profile or `/sui/wallets` |
| Pay on-chain | `/tenant/pay` → Sui → Pay now (platform wallet) |
| Receipt + Walrus | `/sui/receipts` |
| Judge FAQ panel | `/sui` dashboard |
| Gov + proofs | Government portal fraud / audit (live DB) |

---

## API cheat sheet

```
GET  /api/v1/blockchain/status
GET  /api/v1/blockchain/wallet/me
POST /api/v1/blockchain/wallet/ensure
POST /api/v1/payments/checkout/{ref}/pay-platform-sui
POST /api/v1/payments/checkout/{ref}/confirm-sui   # external wallet
```

---

## What we deliberately do **not** claim

- Not a DEX / DeepBook project.
- Not “everything on Walrus” — only proofs and audit artifacts.
- Not mainnet-ready for hackathon — **testnet** + faucet.

See also: `docs/SUI_PAYMENTS.md`, frontend `src/config/hackathonPositioning.js`.
