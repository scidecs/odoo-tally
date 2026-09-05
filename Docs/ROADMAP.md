# Odoo ⇄ TallyPrime Integration — Roadmap & Architecture

Single native Odoo 19 module (`tally_integration`) for near-real-time, two-way sync
between **TallyPrime** and **Odoo 19** (Enterprise or Community). Built around
configuration over customization, native Odoo operations, recoverability and security by design.
See `ARCHITECTURE.md` and `IMPLEMENTATION_STATUS.md` for the authoritative product boundary.

---

## 1. The bottom line

- **Two-way sync with Tally as the default (configurable) source of truth is achievable.**
- **"Real-time from Tally" = short-interval polling** of Tally's AlterID counter — Tally has
  no push. Honest latency: 1–2 min via `ir.cron`.
- **Direct and outbound-only agent topologies share one Odoo business engine.**

---

## 2. Deployment topology — cloud-Tally first (plug & play)

| Scenario | How it connects | Extra process? |
|---|---|---|
| **Routable/protected Tally** | `connection_mode = direct`; Odoo cron → secured gateway URL | No connector process |
| **Private-LAN Tally** | `connection_mode = agent`; local relay uses outbound HTTPS | Local agent |

### ⚠ Security — mandatory (Tally `:9000` is UNAUTHENTICATED, plain HTTP)
Never expose it raw. Use at least one of:
1. **IP allow-list** — only Odoo's egress IP(s) may reach `:9000` (Odoo.sh has stable egress IPs).
2. **Reverse proxy** (nginx/Caddy) adding **HTTPS + Basic-Auth or a secret header**.
3. **Authenticated tunnel** — cloudflared + Access token, or `ngrok --basic-auth`. Never a raw public URL.

Module support: `tally_protocol`, `tally_base_url`, `tls_verify`, `auth_type` (none/basic/header)
+ credentials, all via `_tally_endpoint()` → `services/tally_transport.post_xml(...)`.

---

## 3. Architecture

**Brain = the Odoo module** (config, identity mapping, transform, queue, logs, dashboards — all
native UI). Transport is pluggable:

- **`direct`** (default): Odoo's `ir.cron` (`_cron_direct_sync`, every 2 min) POSTs export/import
  XML to Tally with stdlib `urllib` (no `requests` dep). Outbound queue drain is complete;
  master/voucher pulls run on the configured schedule and can also be started manually.
- **`agent`**: `/tally/agent/*` controllers + a thin on-prem relay, only for the isolated case.

The agent never held business logic — it only ever bridged a network gap.

---

## 4. Editions — Enterprise vs Community

Auto-detected via `tally.instance.odoo_role`:
- **`full`** (Enterprise Accounting present): Odoo keeps the books; two-way; Tally SoT default.
- **`operational`** (Community default): Odoo is the front office; **Tally keeps the books**;
  data pushed **Odoo → Tally**; the engine refuses to import vouchers into Odoo.

`tally_inventory` (accounts_only / with_inventory) tolerates any Tally company setup.

---

## 5. Module map (single add-on)

| Model | Role |
|---|---|
| `tally.instance` | Connection, endpoint+auth, source-of-truth, mode, agent token, entities, crons |
| `tally.entity.config` | Per entity: enable, direction, source of truth, AlterID watermark |
| `tally.mapping` | Identity map (Tally GUID ⇄ Odoo record) + content hash + last-origin |
| `tally.sync.log` | Every operation; list/pivot/graph dashboards |
| `tally.sync.queue` | Outbound Odoo→Tally items + retry/dead-letter |
| `tally.inbound.dead.letter` | Inbound revision failures, payload audit, quarantine and targeted retry |
| `tally.account.type.map` | Tally group → Odoo `account_type` (seeded, editable) |
| `tally.discovered.company` | Multi-company onboarding (agent-reported companies) |
| `tally.onboarding` (wizard) | Initial full-sync / migration |
| services | `tally_transport`, `tally_xml_builder`, `tally_xml_parser`, `sync_engine` |

Standard-model hooks (`res.partner`, `product.template`, `product.product`, `uom.uom`,
`product.category`, `stock.location`, `account.analytic.account`, `account.tax`,
`account.account/move/payment`, and `stock.picking`) are
loop-guarded (`tally_no_sync`) and wrapped in try/except — non-invasive to other modules.

---

## 6. Build roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Scaffold + engine + native UI + security | ✅ Done |
| 1.5 | Onboarding/migration (CoA import wizard, group→type map, opening balances, multi-company) | Implemented; client UAT required |
| 2 | Masters delta sync with ledger classification and safe AlterID watermark | Implemented and regression-tested |
| 3 | Core vouchers + GST mapping and total reconciliation | Implemented; client tax/voucher UAT required |
| 4 | Direct queue + recoverable agent fallback + loop guard | Implemented and regression-tested |
| 5 | Source policy, GUID echo closure, mapping dedup, balancing | Implemented and regression-tested |
| 6 | Documentation and release validation | Live round trip validated; controlled customer UAT next |

---

## 7. Quality & Hardening Verification

- **[RESOLVED] Two-Way Echo Closure**: `tally.mapping.register_outbound()` records `last_origin="odoo"` and content hash on every outbound enqueue, dropping re-imports.
- **[RESOLVED] Manual Post-Back Guard**: Outbound hooks verify if `mapping.last_origin == "tally"` to skip re-pushing unmodified imported vouchers upon user posting.
- **[RESOLVED] Invoice GST Tax Mapping**: Inbound engine automatically extracts CGST, SGST, IGST ledgers and links `tax_ids` directly to invoice lines; extra charges/discounts/roundoffs are preserved as individual lines.
- **[RESOLVED] Journal & Contra Balancing**: Double-entry balance check ($\Sigma \text{Debit} = \Sigma \text{Credit}$) with automatic rounding/suspense adjustment line.
- **[RESOLVED] Multi-Tier Master Lookups**: GUID $\rightarrow$ GSTIN / PAN / Internal Code $\rightarrow$ Company Scoped Name.
- **[RESOLVED] Direct Connection Live Test**: `action_test_connection()` performs live HTTP XML test in direct mode and provides status notifications.
- **[VERIFIED] Isolated Odoo 19 install and transactional tests**: fresh database installation plus engine regressions pass.
- **[VERIFIED] Live bidirectional round trip**: clean recovery, repeat-pull idempotency, price edits
  in both directions, GST vouchers, payments, journal and Stock Journal transfer pass.
- **[RESOLVED] Poison-record stall**: a dedicated inbound dead-letter model quarantines a repeatedly
  failing revision without losing later records; retry rewinds only the affected entity watermark.
- **[DEPLOYMENT GATE] Client Tally UAT**: required for each Tally release, company configuration, voucher type, and tax setup. See `IMPLEMENTATION_STATUS.md`.

---
_Roadmap maintained in Markdown. Last updated 2026-09-05 by Scidecs._
