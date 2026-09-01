# Tally Prime ⇄ Odoo 19 Integration (`tally_integration`)

A native Odoo 19 module providing near-real-time, two-way synchronization between **TallyPrime** and **Odoo 19** (Enterprise / Odoo.sh / On-Premise).

## Key Features
- **Configurable Source of Truth**: Global and per-entity configuration (`tally`, `odoo`, `tally_master`, `bidirectional`).
- **Echo & Loop Suppression**: SHA-256 content hashing and origin tracking prevents ping-pong loops.
- **Master Data Synchronization**:
  - Account Groups (`account.group` ⇄ Tally Group)
  - General Accounts (`account.account` ⇄ Tally Ledger)
  - Party Ledgers (`res.partner` ⇄ Tally Debtors/Creditors with Indian GSTIN, PAN, State)
  - Units of Measure (`uom.uom` ⇄ Tally Unit)
  - Stock Groups & Items (`product.category`, `product.product` ⇄ Tally Stock Item & HSN)
  - Cost Centres (`account.analytic.account` ⇄ Tally Cost Centre)
  - Taxes (`account.tax` ⇄ Tally Duty/Tax Ledgers)
  - Godowns / Locations (`stock.location` ⇄ Tally Godown)
- **Transaction & Voucher Synchronization**:
  - Sales Invoices (`account.move` out_invoice) & Credit Notes (`account.move` out_refund)
  - Purchase Bills (`account.move` in_invoice) & Debit Notes (`account.move` in_refund)
  - Customer Receipts & Vendor Payments (`account.payment` with `<BILLALLOCATIONS>`)
  - Journal Vouchers & Contra Entries (`account.move` entry)
- **Queue & Agent Controllers**: Token-authenticated `/tally/agent/*` endpoints consumed by on-premise Sync Agent.
- **Native Dashboards**: Standard Odoo list, form, search, pivot, and graph views with multi-company security.

## Installation
Place `tally_integration` in your Odoo `addons_path`, update the Apps list, and install **Tally Prime Integration**.
