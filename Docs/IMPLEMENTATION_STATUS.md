# Odoo Tally Integration — Verified Implementation Status

Last updated: 2026-09-04

This file is the release-scope ledger. A feature is marked verified only when executable code
and an applicable automated or live test exist. Marketing checklists must not expand the product
boundary without adding the required Odoo dependency, implementation, and tests.

## Supported product boundary

| Capability | Direction | Status | Verification |
|---|---|---|---|
| Account groups and general ledgers | Tally → Odoo; accounts Odoo → Tally | Implemented | Fresh Odoo 19 install; XML tests |
| Party ledgers and GST identity | Both | Implemented | XML round-trip; Odoo engine tests |
| Units, stock groups, items, godowns, cost centres | Tally → Odoo | Implemented | Parser/build tests; fresh install |
| Products and stock items | Both | Implemented | XML round-trip; Odoo engine tests |
| Opening balances | Tally → Odoo | Implemented | Balanced journal implementation; Odoo transactional test |
| Sales, purchases, credit/debit notes | Both where configured | Implemented | Invoice total regression; live Tally evidence remains deployment-specific |
| Receipts and payments | Both where configured | Implemented | Odoo outbound queue test; bill allocation paths |
| Journal and contra vouchers | Both / inbound as configured | Implemented | Balanced-entry logic; Odoo load validation |
| Stock Journal internal transfers | Tally → Odoo | Implemented | Odoo 19 transactional test; requires client UAT |
| GST ledger and per-item rate mapping | Tally → Odoo | Implemented | Parser tests; mixed-rate allocation logic |
| Direct gateway transport | Both | Implemented | Existing live connection plus isolated install |
| On-premise agent fallback | Both | Implemented | Entity-specific polling, voucher routing, leased queue recovery |
| Multi-company isolation | Both | Implemented | Company fields, ACLs, record rules, per-instance identity |
| Monitoring, retries, deletion reconciliation | Both | Implemented | Native views, crons, queue state machine |

## Explicitly outside this addon's scope

These are not Tally transport features and are not claimed as implemented:

- Manufacturing orders, BOMs, work centres, or MRP valuation (`mrp`).
- Landed-cost calculation (`stock_landed_costs`).
- Fixed-asset depreciation (`account_asset`).
- Government IRN generation/signing, E-Way Bill submission, or cancellation services
  (`l10n_in_edi` and an authorized provider).
- GSTR return preparation, filing, or portal reconciliation.
- Odoo procurement rules, replenishment, dropshipping, or pricelist synchronization.

Tally-origin IRN/E-Way identifiers may be retained as reference metadata when corresponding Odoo
fields exist; that is not equivalent to generating or filing statutory documents.

## Release gates

The repository currently passes:

1. Python compilation, XML well-formedness, and manifest validation.
2. Eight standalone XML/parser regression tests.
3. Fresh Odoo 19 installation on an isolated database.
4. Thirteen Odoo transactional engine tests covering failed-watermark safety, workflow echo
   suppression, stable identity, ownership policy, inventory-invoice amount fidelity, opening
   balance integrity, and stock-journal transfer creation.

A customer deployment is complete only after UAT against that customer's TallyPrime release,
voucher configurations, GST ledgers, security proxy, fiscal periods, and representative data.
No responsible integration can promise universal zero-error operation without this deployment UAT.
