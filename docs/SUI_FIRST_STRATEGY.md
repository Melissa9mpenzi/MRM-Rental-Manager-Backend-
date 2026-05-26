# Sui-first strategy — RentDirect UG

## Positioning (what judges should hear)

> **RentDirect UG is decentralized rental trust infrastructure on Sui** — escrow payments, immutable rental agreements, on-chain receipts, and Walrus-backed proofs for African housing markets.

**Not:** “a property management app with crypto.”

**Yes:** “Africa’s decentralized rental infrastructure powered by Sui.”

---

## Why this could not exist properly without Sui

| Capability | Without Sui | With Sui + Walrus |
|------------|-------------|-------------------|
| Escrow custody | Bank trust / manual holding | Programmable hold + release (Move escrow) |
| Payment proof | PDF anyone can forge | Tx digest + anchored receipt object |
| Lease agreement | DB row | Content hash + Walrus blob + optional Move anchor |
| Gov audit | Export CSV | Tamper-evident audit bundle on Walrus |
| Identity + wallet | Email only | Account-native Sui address (Privy / platform wallet) |

Postgres runs **operations** (listings, chat, CRM). Sui runs **trust** (money + proofs). Walrus runs **durability** (evidence outliving any single server).

---

## Hackathon tracks (do not dilute)

| Priority | Track | Focus |
|----------|--------|--------|
| **Primary** | DeFi & Payments | Escrow, rent settlement, wallets, receipts, payment infra |
| **Secondary** | Walrus | Contracts, receipts, KYC manifests, escrow proofs, gov audit |
| **Optional** | AI prizes | Only **rule-based** fraud (duplicate NIN, flags) — label honestly |
| **Avoid** | Agentic Web | Not an agent economy product |
| **Avoid** | DeepBook | Not a DEX |

---

## Sui-first implementation stack (what exists in repo)

```
contracts/rentdirect/sources/
  escrow.move      → Escrow object + release events
  receipt.move     → PaymentReceipt anchor on-chain

app/services/blockchain/
  blockchain_service.py   → Wallets, receipts, escrow holds
  walrus_anchor_service.py → Receipts, KYC, property, escrow, audit blobs
  wallet_provision.py     → Platform Sui wallet + server-side pay

Frontend /sui/*           → Escrow, receipts, transactions, judge pitch panel
```

**Deploy Move for gold-star demo:** set `SUI_PACKAGE_ID` after `sui client publish`. Until then, DB escrow + tx digests + Walrus proofs still demo the architecture.

---

## Judge demo script (5 minutes)

1. **Login with Google (Privy)** → show Sui address on account (no extension).
2. **Landlord** → create lease → show **agreement hash + Walrus proof** on lease record.
3. **Tenant** → `/tenant/pay` → pay rent via **platform Sui wallet** → open receipt with **tx digest + QR verify**.
4. **Landlord** → `/sui/escrow` → create/release escrow → show Walrus lease/release proofs.
5. **Government** → fraud alerts + audit export Walrus bundle.
6. **One sentence:** “MoMo handles fiat; Sui handles trust; Walrus handles evidence.”

Routes: `/sui`, `/tenant/pay`, `/sui/receipts`, `/sui/escrow`, `/government/fraud`, `/verify/receipt/:token`

---

## Build order (Sui-first only)

### Week 1 — Credibility
- [ ] Privy + testnet treasury funded
- [ ] One successful on-chain rent payment + receipt in UI
- [ ] Move package published OR clear slide: “package ID = testnet deploy”
- [ ] Walrus publisher URL OR demo hashes visible in UI

### Week 2 — Differentiation
- [ ] Escrow create → fund → release with digests on screen
- [ ] Lease agreement anchor on every new lease
- [ ] Receipt verify page public (`/verify/receipt/:token`)
- [ ] Gov fraud = live DB rules only

### Do not build before demo
- NFTs, DAO, tokenomics, LLM “AI”, social feed, voice chat

---

## Revenue (founder layer — post-hackathon)

Platform fee field on checkout, featured listings, gov SaaS **license** (you own IP). See product scope doc — not judge-critical.

---

See also: `HACKATHON_SUI_WALRUS.md`, `SUI_PAYMENTS.md`, `PRIVY_SETUP.md`, frontend `src/config/hackathonPositioning.js`.
