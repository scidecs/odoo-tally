# Odoo Tally Integration (Tally Prime connector for Odoo 18, 19 and 20)

This is the installable Odoo addon from the
[Scidecs Odoo–TallyPrime Integration](https://github.com/scidecs/odoo-tally) repository.

It provides configurable, two-way synchronization of accounting and inventory masters and
vouchers between Odoo and TallyPrime through the Tally XML gateway (port 9000). Direct and
outbound-only agent deployments are supported. The addon includes durable outbound work, stable
identity mappings, source-of-truth policy, echo suppression, audit logs, and inbound poison-record
quarantine.

The software is free under LGPL-3. Optional implementation, migration, training, support, and
customization services are available from Scidecs; no paid activation is required.

| Odoo | Module version | Branch |
|---|---|---|
| 18.0 Community / Enterprise | 18.0.1.2.0 | [`18.0`](https://github.com/scidecs/odoo-tally/tree/18.0) |
| 19.0 Community / Enterprise | 19.0.1.2.0 | [`19.0`](https://github.com/scidecs/odoo-tally/tree/19.0) |
| 20.0 Community / Enterprise | 20.0.1.2.0 | [`20.0`](https://github.com/scidecs/odoo-tally/tree/20.0) (PostgreSQL 16+) |

Releases are validated against TallyPrime. Tally.ERP 9 exposes the same XML gateway; validate
Tally.ERP 9 companies in UAT before go-live.

## What's new in 1.2.0 (29 September 2026)

A data-integrity release. Every fix was reproduced against a live TallyPrime gateway first.

**New**

- Odoo 20 support, alongside Odoo 18 and 19 from one code base.
- Tally's own identity (GUID, voucher number, revision) is read back after every push, so
  documents are never imported twice.
- Vouchers are pulled by Tally revision and date instead of the Day Book, so back-dated entries
  are no longer missed.
- Reset to draft, cancel and delete in Odoo become a cancellation in Tally; posting again restores
  the voucher.
- **Push Existing Odoo Data** for companies that already run Odoo before connecting Tally.
- Payments are re-sent after reconciliation so Tally bill-wise references match Odoo.
- Automatic upgrade of mappings created by earlier releases.

**Fixed**

- Duplicate invoices and bills in Odoo after pushing them to Tally.
- Editing or cancelling a voucher by number could change a different voucher type with the same
  number.
- Opening balances imported on the wrong side (debit/credit).
- Party, tax and journal lines counted twice when Tally returned both ledger lists.
- SGST mapped onto the CGST tax, and imported GST posted to Sales/Purchases instead of the tax
  accounts.
- Parties under custom Sundry Debtors/Creditors sub-groups imported as general ledger accounts.
- Orders and delivery/receipt notes imported as invoices; custom voucher types misrouted.
- Cash sales and direct expense payments assigned to contacts named "Cash" or after the expense.
- Renames in either system creating a second master instead of renaming it.
- Tally edits and cancellations not applied to posted Odoo documents.
- Multi-company imports using another company's accounts.
- Unique safeguards missing on Odoo 19, and duplicate master names stopping the Tally XML server.

**Validation:** 48 automated tests pass on each of Odoo 18, 19 and 20. A live matrix of four
onboarding scenarios (both systems new, Tally already in use, Odoo already in use, two companies)
on all three versions ran 12 times with 45 ledger-balance audits and zero differences.

The full history is in [CHANGELOG.md](CHANGELOG.md).

## Upgrading from an earlier release

1. Back up the Odoo database and the Tally company.
2. Replace the module and upgrade **Odoo Tally Integration** from Apps (or run Odoo with
   `-u tally_integration`). Existing mappings are converted automatically.
3. If you use the on-premise agent, replace it with `agent/tally_agent.py` from this release.
   Older agents still connect but do not receive the voucher-pull and identity fixes.
4. Run **Sync Now** once and review the sync log before re-enabling scheduled sync.

## Installation

1. Add `tally_integration` to the addons path of your Odoo 18, 19 or 20 server.
2. Update the Apps list and install **Odoo Tally Integration**.
3. Create a Tally instance, run **Test Connection**, load the default entities and review the
   direction and source of truth for each entity.
4. Choose the onboarding path: **Pull Masters from Tally** / **Pull Now** when Tally is already in
   use, **Push Existing Odoo Data** when Odoo is already in use.
5. Use a backed-up test company for UAT and enable scheduled sync only after reconciliation passes.

## Supported entities

Account groups, general ledgers, customers/vendors, currencies, UoMs, stock groups, products,
godowns, cost centres, GST tax ledgers, opening balances, sales, purchases, credit notes, debit
notes, receipts, payments, journals, contras, and internal Stock Journal transfers.

The exact direction and authority are configured per entity. Customer-specific Tally voucher
definitions and custom TDL require UAT.

## Not included

MRP/BOM, landed costs, assets, procurement, sales/purchase orders, delivery/receipt notes, payroll,
IRN generation, E-Way Bill submission, GSTR filing, government-portal reconciliation, and
replication of bank-statement matching entries are not part of this release.

## Documentation

- [Sync integrity rules](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/SYNC_INTEGRITY_RULES.md) — the verified TallyPrime behaviours the sync relies on
- [Implementation status](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/IMPLEMENTATION_STATUS.md)
- [Installation and operations](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/INSTALLATION_AND_OPERATIONS.md)
- [Architecture](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/ARCHITECTURE.md)
- [Technical reference](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/TECHNICAL_REFERENCE.md)
- [FAQ](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/FAQ.md)
- [Support model](https://github.com/scidecs/odoo-tally/blob/20.0/Docs/SUPPORT_AND_CONSULTING.md)

Contact: [hello@scidecs.com](mailto:hello@scidecs.com)<br>
License: LGPL-3
