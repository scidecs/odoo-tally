# Odoo 19 and TallyPrime Integration — Final Implementation and Validation Report

Date: 2026-09-05  
Release status: **Ready for controlled client UAT / supervised pilot**

This report records the implemented product boundary, defect corrections, automated checks,
and live bidirectional round-trip evidence. It is intended to be safe to share with Gemini or a
release reviewer. It deliberately does not describe unimplemented ERP or statutory features as
complete.

## 1. Supported product boundary

The module supports configurable one-way or bidirectional synchronization for:

- Masters: account groups, general ledgers, party ledgers, currencies, UoMs, stock groups,
  stock items/products, godowns/locations, cost centres, and percentage tax ledgers.
- Transactions: sales invoices, purchase bills, credit notes, debit notes, receipts, payments,
  journal vouchers, contra vouchers, opening balances, and internal stock transfers through
  Tally Stock Journal vouchers.
- Inventory identity and values: SKU/part number, GUID, category, UoM, HSN, barcode where
  available, standard cost, standard selling price, and closing quantity.
- Operations: direct gateway and on-premise agent modes, per-entity direction/source policy,
  stable identity mappings, queue leasing/retry, echo suppression, logs, multi-company rules,
  deletion reconciliation, and inbound dead-letter quarantine.

Explicitly outside this release: MRP/BOM/work centres, landed costs, fixed-asset depreciation,
Odoo replenishment/procurement, government IRN generation/signing, E-Way Bill submission,
GSTR filing, and portal reconciliation. References received from Tally are not equivalent to
performing statutory filing.

## 2. Correctness and architecture work completed

### Safety, identity, and lifecycle

- Added database-clone UUID protection so a copied/restored Odoo database cannot silently push
  test data to a live Tally company.
- Enforced one active Tally instance per Odoo company and company-scoped access rules.
- Replaced unstable product-template identity with stable `product.product` identity and GUID
  mapping; confirmed product creation creates exactly one outbound queue item.
- Retained SHA-256 payload hashing and origin tracking to prevent echo loops while still allowing
  genuine edits from either side under bidirectional policy.
- Preserved outbound work through a durable queue with idempotency keys and leased retries.

### Master synchronization

- Added outbound create/write hooks for accounts, products, UoMs, stock groups, godowns, cost
  centres, and tax ledgers.
- Normalized Odoo unit names to Tally-compatible units.
- Preserved product SKU through Tally `MAILINGNAME`, plus GUID, category, cost, price, quantity,
  HSN, barcode where available, and effective-dated standard rates.
- Added the required `DATE` value to Tally standard-cost and standard-price lists; educational
  test mode uses a valid first-of-month date without changing licensed-production dates.
- Corrected zero closing-stock parsing so zero is not replaced by opening stock.
- Corrected total-closing-stock application so repeated pulls remain idempotent and do not add
  the main-warehouse quantity on top of recovered secondary-godown stock.

### Voucher and inventory synchronization

- Corrected inventory invoice XML to use Tally invoice-view ledger structures, party flags,
  inventory accounting allocations, destination godowns, and balanced GST signs.
- Corrected Sales, Purchase, Credit Note, Debit Note, Receipt, Payment, Journal, and Contra
  parsing/building paths and retained business references.
- Implemented internal Odoo transfers as balanced Tally Stock Journal IN/OUT entries and parsed
  the same structure back into Odoo internal transfers.
- Adapted transfer completion to Odoo 19 by setting moved quantities as picked before validation.
- Added a guard against automatically changing automated-valuation stock when financial opening
  balances could otherwise double-count value.
- Escaped XML attribute values correctly, including quotation marks.

### Poison-record isolation (Claude implementation reconciled)

- Kept the dedicated `tally.inbound.dead.letter` design; removed the competing mapping-based
  quarantine concept so identity mappings retain a single responsibility.
- Stores instance/company, entity, stable record key, GUID, AlterID, payload and SHA-256 hash,
  last error, attempts, state, and timestamps for an exact operational audit trail.
- A failed revision blocks the entity watermark while retryable. At the configured threshold
  (default 3, database-constrained to at least 1), that revision is quarantined and later valid
  records can progress.
- Operators can inspect payload/error details, quarantine, resolve, or retry. Retry rewinds only
  the affected entity watermark to `AlterID - 1`, rather than triggering a full historical pull.
- A later successful import or an accepted Odoo-origin acknowledgement resolves stale failure
  records automatically.
- Added manager-only mutation, user read access, multi-company isolation, instance KPI/button,
  and **Tally Prime → Operations → Inbound Quarantine** views.

## 3. Automated verification

Final clean Odoo 19 install on database `odootally_test_final`:

- Python compilation: passed.
- All addon XML files: well formed.
- Git whitespace/error check: passed.
- Eight standalone XML/parser tests: passed.
- Odoo module install and registry load: passed.
- 20 post-install test methods / 22 Odoo framework test counts: **0 failed, 0 errors**.

The regression suite covers failed-watermark safety, three-attempt quarantine, surgical retry,
echo acknowledgement resolution, product single-enqueue behavior through both the normal template UI
and direct variant API, workflow echo suppression,
stable identity, ownership policy, invoice amount balancing, dated standard prices, opening
balance integrity, stock-group retention, zero closing stock, repeated stock idempotency, and
internal transfer creation.

Expected exception traces for intentionally malformed test records appear in the test log; they
are the exercised failure path, not test failures.

## 4. Live Tally round-trip evidence

Live endpoint: private LAN test endpoint (redacted from the public report)<br>

A post-fix live capture created synthetic SKU `VID260906-BEARING` through the standard Odoo product
form. The database contained one acknowledged stock-item queue row, and TallyPrime displayed the
matching `VID260906 Live Demo Bearing` master and part number. The two-minute video and reproducible
source are documented in `Docs/video/README.md`.
Tally company: `Scidecs Demo Pvt Ltd`<br>
Scenario namespace: `RT260904F`

The scenario created 15 industrial products across three categories, then exercised two
purchases, two sales, purchase return, sales return, CGST and SGST at 9% each, inbound receipt,
outbound payment, balanced journal entry, and a secondary-godown internal transfer involving
five products.

Observed results:

- Initial outbound run: 39 records acknowledged, 0 failed.
- Tally: exactly 15 scenario products and 10 scenario transaction vouchers.
- Fresh Odoo recovery: 220 records processed, 205 identity mappings, 0 sync errors.
- Repeated pull: stable product quantities and financial totals, with no duplicates.
- Recovered Odoo result: 15/15 products, 6 invoices/notes, 2 payments, 1 journal, and 1 transfer.
- Tally → Odoo edit: product selling price 1380 → 1399 was pulled and verified, then restored.
- Odoo → Tally edit: product selling price 1050 → 1077 was pushed and verified, then restored.
- Final current-state verifier: `ok: true`; no missing/unexpected invoices, invoice mismatches,
  product quantity/value/identity mismatches, or sync-log errors.
- Final live Tally product verifier: 15 expected, 15 actual, 0 mismatches, `ok: true`.
- Final native Stock Journal diagnostic: live Tally created the voucher with 0 errors and exported
  the source as `INVENTORYENTRIESIN.LIST` / -7200 and destination as
  `INVENTORYENTRIESOUT.LIST` / +7200, matching the builder and parser contract.

Primary machine-readable evidence:

- `artifacts/roundtrip_final_release_verification.json`
- `artifacts/roundtrip_final_release_tally_products.json`
- `artifacts/roundtrip_absolute_final_clean_recovery.json`
- `artifacts/roundtrip_absolute_final_repeat_pull.json`
- `artifacts/roundtrip_tally_to_odoo_1399_verified.json`
- `artifacts/roundtrip_odoo_to_tally_1077_verified.json`
- `artifacts/tally_roundtrip_items.xml`
- `artifacts/tally_roundtrip_vouchers.xml`

Recovery dumps were taken before destructive database validation:

- `backups/odootally_local_pre_roundtrip_20260904.dump`
- `backups/odootally_local_recovered_before_final_clean_20260905.dump`
- `backups/odootally_local_final_bidirectional_20260905.dump`

## 5. Release assessment

The implementation is suitable for a controlled UAT/pilot and the validated scenario is a real
end-to-end milestone. The evidence does not justify claiming universal production hardening for
arbitrary client datasets. Before an unsupervised broad rollout, run:

1. Client UAT against the customer's real Tally release, ledgers, fiscal periods, GST setup, and
   representative messy history.
2. Scale tests with at least 10,000 vouchers and realistic master volumes.
3. Multi-day soak testing with process restarts and intermittent network failure.
4. Simultaneous-edit/conflict testing under realistic accountant activity.

These are deployment-hardening gates, not failures in the validated functional scenario.

## 6. Publish checklist

- Review the working-tree diff and this report.
- Commit the module, scenario runner, tests, and this report together.
- Tag/version according to the release policy after client UAT sign-off.
- Do not publish test credentials, database dumps, or client accounting XML in a public release.
- Keep the release statement precise: **live-Tally round trip validated; ready for controlled UAT**.
