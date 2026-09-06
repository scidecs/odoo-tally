# Odoo Tally Integration — Verified Implementation Status

Last updated: 2026-09-05

This file is the release-scope ledger. A feature is marked verified only when executable code
and an applicable automated or live test exist. Marketing checklists must not expand the product
boundary without adding the required Odoo dependency, implementation, and tests.

## Supported product boundary

| Capability | Direction | Status | Verification |
|---|---|---|---|
| Account groups and general ledgers | Tally → Odoo; accounts Odoo → Tally | Implemented | Fresh Odoo 19 install; XML tests |
| Party ledgers and GST identity | Both | Implemented | XML round-trip; Odoo engine tests |
| Units, stock groups, items, godowns, cost centres | Both where configured | Implemented | Parser/build tests; fresh install; live products/transfer |
| Products and stock items | Both | Implemented | XML round-trip; Odoo engine tests |
| Opening balances | Tally → Odoo | Implemented | Balanced journal implementation; Odoo transactional test |
| Sales, purchases, credit/debit notes | Both where configured | Implemented | Invoice total regression; live Tally round trip |
| Receipts and payments | Both where configured | Implemented | Odoo outbound queue test; bill allocation paths |
| Journal and contra vouchers | Both / inbound as configured | Implemented | Balanced-entry logic; Odoo load validation |
| Stock Journal internal transfers | Both where configured | Implemented | Odoo 19 transactional test; native live Tally import/export |
| GST ledger and per-item rate mapping | Tally → Odoo | Implemented | Parser tests; mixed-rate allocation logic |
| Direct gateway transport | Both | Implemented | Existing live connection plus isolated install |
| On-premise agent fallback | Both | Implemented | Entity-specific polling, voucher routing, leased queue recovery |
| Multi-company isolation | Both | Implemented | Company fields, ACLs, record rules, per-instance identity |
| Monitoring, retries, deletion reconciliation | Both | Implemented | Native views, crons, queue state machine |
| Inbound poison-record quarantine and targeted retry | Tally → Odoo | Implemented | Dedicated dead-letter model; threshold/retry/echo-resolution tests |

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
4. Twenty Odoo post-install test methods (22 framework counts), with zero failures and zero errors,
   covering failed-watermark safety, quarantine and targeted retry, echo suppression, stable identity,
   ownership policy, inventory-invoice fidelity, opening balances, stock idempotency, product queue
   deduplication, dated rates and Stock Journal transfer creation.
5. Real TallyPrime round trip covering 15 products, purchases, sales, both returns, CGST/SGST,
   receipt, payment, journal and internal transfer.
6. Fresh-database recovery, repeat-pull idempotency, and verified/restored price edits in both
   directions.
7. A 1080p live demonstration that creates a synthetic product in Odoo, shows the split-screen
   handoff, and verifies its exact name and SKU/part number in TallyPrime.

A customer deployment is complete only after UAT against that customer's TallyPrime release,
voucher configurations, GST ledgers, security proxy, fiscal periods, and representative data.
No responsible integration can promise universal zero-error operation without this deployment UAT.
