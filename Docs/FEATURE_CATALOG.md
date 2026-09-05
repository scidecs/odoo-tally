# Complete Feature Catalog

This is the canonical public inventory of the Odoo 19 TallyPrime Integration. It is derived from
the shipped models, services, views, access rules, scheduled jobs and test suite. A check in this
catalog means the standard structure is implemented; customer-specific TDL, voucher classes,
ledger conventions and historical data still require UAT.

## Synchronization coverage

| # | Entity | Tally to Odoo | Odoo to Tally | Standard Odoo destination/source |
|---:|---|:---:|:---:|---|
| 1 | Account Group | Yes | Policy-limited | Account type/group mapping |
| 2 | Ledger | Yes | Yes | `account.account` |
| 3 | Party Ledger | Yes | Yes | Customer/vendor and receivable/payable account |
| 4 | Unit of Measure | Yes | Yes | `uom.uom` |
| 5 | Stock Group | Yes | Yes | Product category hierarchy |
| 6 | Stock Item | Yes | Yes | Product template/variant |
| 7 | Godown | Yes | Yes | Internal stock location |
| 8 | Cost Centre | Yes | Yes | Analytic account |
| 9 | Percentage Tax Ledger | Yes | Yes | Sales/purchase tax |
| 10 | Currency | Yes | No | Currency master |
| 11 | Opening Balance | Yes | No | Balanced opening journal entry |
| 12 | Sales | Yes | Yes | Customer invoice |
| 13 | Credit Note | Yes | Yes | Customer credit note |
| 14 | Purchase | Yes | Yes | Vendor bill |
| 15 | Debit Note | Yes | Yes | Vendor refund/debit note |
| 16 | Receipt | Yes | Yes | Inbound payment |
| 17 | Payment | Yes | Yes | Outbound payment |
| 18 | Journal | Yes | Yes | General journal entry |
| 19 | Contra | Yes | Yes | Bank/cash transfer entry |
| 20 | Stock Journal | Yes | Yes | Internal warehouse transfer |

Each entity can be enabled independently with direction (`Tally to Odoo`, `Odoo to Tally`, or
`Both`), source-of-truth policy, polling window, watermark and synchronization sequence. In
bidirectional mode work is serialized in arrival order; teams must still define operational
ownership to avoid intentional edits racing one another.

## Data fidelity

- Stable cross-system GUID and AlterID identity mapping.
- Party GSTIN, PAN, address, email, phone and customer/vendor role.
- Product SKU, barcode, HSN/SAC, UoM, category, standard cost, sale price and opening/closing stock.
- Parent stock groups, godowns/warehouse locations and analytic cost centres.
- CGST, SGST and IGST percentage-ledger recognition and invoice/bill tax lines.
- Inventory and accounts-only sales/purchase voucher paths.
- Bill allocations for receipts and payments.
- Balanced journal/contra entries and native Stock Journal source/destination allocations.
- Business reference, date, narration and mapped external identity where the target supports them.

## Operator experience

- Instance dashboard in kanban, list and control-centre form views.
- Guided onboarding wizard and default entity-policy loader.
- Direct gateway and private-LAN agent connection modes.
- Connection test, master pull, complete master/voucher pull and immediate synchronization actions.
- Deletion reconciliation and Indian localization assistance.
- Token generation and agent heartbeat/company discovery.
- KPI buttons for mappings, logs, pending work, failures, orphans, quarantine and today's success.
- Entity configuration, account-type mapping and discovered-company review screens.
- Searchable outbound queue with retry state and payload detail.
- Searchable logs plus form, pivot and graph analytics.
- Searchable inbound quarantine with error history and targeted retry.
- Searchable identity mappings with Odoo and Tally identifiers.

## Reliability and recovery

- Durable outbound queue with idempotency keys, acknowledgement, retry and expired-lease recovery.
- SHA-256 payload/content hashes, origin markers and echo acknowledgement to prevent feedback loops.
- Per-entity AlterID watermarks and repeat-pull idempotency.
- Per-record database savepoints so one bad inbound record does not roll back a healthy batch.
- Failure counters, configurable threshold, dead-letter quarantine and surgical `AlterID - 1` retry.
- Database-clone UUID guard, one-active-instance-per-company constraint and multi-company rules.
- Scheduled health checks, direct synchronization, deletion reconciliation and log retention.
- Full pull and clean-database recovery workflow for supported masters and vouchers.

## Private-LAN agent

The optional standard-library Python agent runs near Tally, calls the local XML gateway, and makes
outbound HTTPS calls to Odoo. Its authenticated JSON-RPC workflow covers heartbeat, company
discovery, pull requests, queued push delivery and acknowledgement. Transformation and business
rules remain centralized in Odoo.

## Security controls

- Odoo user groups, access rights, company record rules and protected operator actions.
- Hashed agent tokens, token rotation workflow and constant-time authentication comparison.
- Outbound-only HTTPS option for private networks.
- Sanitized logs and explicit guidance never to expose unauthenticated Tally port 9000 publicly.
- Clone/environment protection to prevent a restored production database from pushing unexpectedly.

## Deliberate product boundary

The current release does not claim manufacturing/BOM synchronization, landed costs, fixed assets,
procurement/replenishment, sales or purchase orders, delivery/receipt notes, payroll, government
IRN generation, E-Way Bill submission, GSTR filing or portal reconciliation. These are roadmap or
customer-specific extension areas, not hidden features.

## Architecture map

```text
Odoo model hooks -> XML builders -> durable outbound queue
                                     |-> protected direct Tally XML gateway
                                     `-> authenticated outbound-only LAN agent -> local Tally gateway

Tally AlterID deltas -> XML parser -> policy and echo guard -> transactional upsert
                                                   |-> identity mapping + audit log
                                                   `-> failure history -> quarantine -> targeted retry
```

Implementation detail is in [Architecture](ARCHITECTURE.md), [Technical Reference](TECHNICAL_REFERENCE.md),
[Operations](INSTALLATION_AND_OPERATIONS.md), [Security](SECURITY.md) and
[Testing and Validation](TESTING_AND_VALIDATION.md).
