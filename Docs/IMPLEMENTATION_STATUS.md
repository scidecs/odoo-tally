# Odoo Tally Integration — Verified Implementation Status

Last updated: 2026-09-29 (release 1.2.0: 18.0.1.2.0 / 19.0.1.2.0 / 20.0.1.2.0)

This file is the release-scope ledger. A feature is marked verified only when executable code
and an applicable automated or live test exist. Marketing checklists must not expand the product
boundary without adding the required Odoo dependency, implementation, and tests. The TallyPrime
behaviours the sync relies on are listed in [Sync Integrity Rules](SYNC_INTEGRITY_RULES.md).

## Supported Odoo versions

| Odoo | Branch | Security files | Verified on |
|---|---|---|---|
| 18.0 | `18.0` | `ir.model.access.csv` + `ir_rule_data.xml` | Enterprise 18.0, PostgreSQL 15 |
| 19.0 | `19.0` | `ir.model.access.csv` + `ir_rule_data.xml` | Enterprise 19.0, PostgreSQL 15 |
| 20.0 | `20.0` | `ir.access.csv` (Odoo 20 unified access) | Enterprise 20.0, PostgreSQL 17 (Odoo 20 needs 16+) |

One code base; branches differ only in the manifest (version and security data files).

## Supported product boundary

| Capability | Direction | Status | Verification |
|---|---|---|---|
| Account groups and general ledgers (group-hierarchy typing) | Both | Implemented | Live matrix; unit tests |
| Party ledgers incl. custom Sundry Debtors/Creditors sub-groups, GSTIN, state | Both | Implemented | Live matrix; parser tests |
| Units, stock groups, items, godowns, cost centres | Both where configured | Implemented | Unit tests; live push |
| Opening balances (Tally negative = debit) | Tally → Odoo | Implemented | `$$IsDr` verified live; unit test |
| Sales, purchases, credit/debit notes (Odoo taxes or exact Tally lines) | Both | Implemented | Live matrix; unit tests |
| Receipts and payments (bill references refreshed after reconciliation) | Both | Implemented | Live matrix |
| Journal, contra, cash sales/purchases, direct expense payments | Both | Implemented | Live matrix; unit tests |
| Stock Journal internal transfers | Both where configured | Implemented | Unit tests |
| GST ledgers (per-ledger taxes and accounts) | Both | Implemented | Live matrix (GST vouchers); unit tests |
| Edits, cancellations and renames in either system | Both | Implemented | Live matrix steps 3–7 |
| Onboarding: Tally in use / Odoo in use / both new | Both | Implemented | Live scenarios s1–s3 |
| Multi-company (one Tally company per Odoo company, shared contacts) | Both | Implemented | Live scenario s4; unit test |
| Direct gateway transport | Both | Implemented | Live matrix |
| On-premise agent relay | Both | Implemented | Live agent end-to-end |
| Deletion reconcile (flag only), quarantine, retries, monitoring | Both | Implemented | Unit tests |
| Upgrade from releases before 1.2.0 | — | Implemented | Migration test from 19.0.1.1.0 |

## Explicitly outside this addon's scope

- Manufacturing orders, BOMs, work centres, or MRP valuation (`mrp`).
- Landed-cost calculation (`stock_landed_costs`).
- Fixed-asset depreciation (`account_asset`).
- Government IRN generation/signing, E-Way Bill submission, or cancellation services.
- GSTR return preparation, filing, or portal reconciliation.
- Odoo procurement rules, replenishment, dropshipping, or pricelist synchronization.
- Replicating bank-statement matching entries; reconcile the bank in the system that owns it.

## Known operating constraints

- A voucher typed in Tally can be changed from Odoo only when its date and voucher number are
  unique across voucher types in Tally (checked live before sending); otherwise the edit is
  refused with a clear error and must be made in Tally.
- A TallyPrime internal-error dialog stops its XML server until it is closed on the Tally machine;
  the connector avoids the known triggers and the queue retries afterwards.

## Release gates (all passing)

1. Python compilation, XML well-formedness, manifest and cross-version guards (`scripts/run_stage_checks.sh`).
2. 8 standalone XML/parser tests.
3. 48 Odoo post-install tests with zero failures on **each** of Odoo 18, 19 and 20.
4. Live integrity matrix against TallyPrime: 4 scenarios × 3 Odoo versions = 12 runs, 45 audit
   steps, **0 issues**. Each audit compares every Tally ledger closing balance with Odoo (up to 112
   ledgers and 102 vouchers per run), checks duplicate/unlinked documents and failed queue items,
   and repeats a sync cycle that must change nothing.
5. Live on-premise agent end-to-end: 18 outbound items acknowledged and bound, 165 inbound records,
   two audits at 126 ledgers with 0 issues, idempotent repeat cycle.
6. Upgrade migration from 19.0.1.1.0 verified on a database created with that release.

The harness is in `scripts/integrity/`. A customer deployment is complete only after running it
(and functional UAT) against that customer's TallyPrime release, voucher types, GST ledgers,
security proxy, fiscal periods and representative data.
