# Role Surface Matrix (Web vs Mobile)

This project intentionally separates **mobile execution flows** from **web management workflows**.

Do not mirror every feature on both surfaces. This matrix is the source of truth.

---

## Design principles

- **Usage behavior:** mobile for quick, frequent actions; web for deep operations.
- **Device capability:** complex tables/audits/analytics stay on desktop web.
- **Role fit:** government + system admin are web-only.
- **Workflow complexity:** approvals, monitoring, exports, and moderation belong on web.

---

## Primary role distribution

| Role | Mobile | Web |
|------|--------|-----|
| Tenant | **Primary** | Secondary |
| Landlord | Shared | **Primary for management** |
| Agent | **Primary** | Secondary |
| Government (NIRA/KCCA/URA) | No | **Primary (web-only)** |
| System admin | No | **Primary (web-only)** |

---

## Tenant

### Mobile (primary)
- Home / dashboard
- Search and saved properties
- Applications
- Payments and wallet
- Messages / notifications
- Profile / settings
- Quick receipt access and share

### Web (secondary)
- Applications, contracts, payments, documents, messages, profile
- Verification pages and printable views

---

## Landlord

### Web (primary)
- Portfolio management (multi-property)
- Tenants, approvals, contracts
- Payments, escrow, analytics
- Reporting and exports
- Moderation/governance integrations

### Mobile (support)
- Quick stats and alerts
- Property updates/photos
- Approve/reject actions
- Messaging and payment follow-up

---

## Agent

### Mobile (primary)
- Leads in the field
- Inspection notes and communication
- Quick property capture/update
- Tasks and appointments

### Web (secondary)
- Client/property reports
- Commission and operational analytics

---

## Government and System Admin

### Web only (mandatory)
- Verification queues and approvals
- Audit trails and compliance analytics
- Fraud monitoring and escalations
- Officer/admin controls and system health

Mobile apps should redirect these users to web.

---

## Blockchain / Sui split

### Mobile
- Quick wallet visibility
- Receipt visibility/share
- Lightweight blockchain status views

### Web
- Wallet connect/signing flows
- Escrow management
- Verification explorer and analytics
- Walrus proof and audit workflows

---

## Implementation notes

- Keep APIs shared, but tailor UI/flows by surface.
- Add clear “Use web portal” prompts for web-only workflows on mobile.
- Prioritize speed/minimal UI on mobile and depth/controls on web.
