# Scidecs Odoo–TallyPrime Integration

[![Odoo 19](https://img.shields.io/badge/Odoo-19.0-875A7B.svg)](https://www.odoo.com/)
[![License LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](LICENSE)
[![Free](https://img.shields.io/badge/Module-Free-16A34A.svg)](#free-software-paid-expertise)

A free, open-source Odoo 19 connector that keeps supported accounting and inventory data aligned
between Odoo and TallyPrime. It supports direct XML/HTTP connectivity and an outbound-only agent
for private networks, with durable queues, stable identities, per-entity ownership rules,
monitoring, and poison-record quarantine.

The code is free under LGPL-3. Scidecs charges only when an organization chooses professional
discovery, configuration, migration, training, support, or customization.

> Release position: live-Tally round trip validated and ready for controlled customer UAT.
> Customer-specific UAT remains mandatory before unattended production operation.

## Why this exists — AIDA summary

### Attention

Running sales and operations in Odoo while finance maintains Tally often creates duplicate entry,
delayed books, spreadsheet handoffs, mismatched stock, and uncertain responsibility for corrections.

### Interest

This module connects the systems through TallyPrime's native XML gateway. Each data domain can be
Tally-owned, Odoo-owned, one-way, or bidirectional. It synchronizes the supported masters and
vouchers automatically while retaining an auditable operational trail.

### Desire

Teams gain fewer manual handoffs, recoverable synchronization, controlled conflict behavior,
multi-company separation, clean fresh-database recovery, and a choice between direct and private-LAN
deployment. The connector is transparent: its supported boundary, test evidence, and exclusions are
documented rather than hidden behind a generic “complete integration” claim.

### Action

Install the module in a test Odoo 19 database, connect a backed-up Tally test company, run the
[deployment checklist](Docs/INSTALLATION_AND_OPERATIONS.md), and complete the
[UAT matrix](Docs/TESTING_AND_VALIDATION.md) before production activation.

## What it solves

- Re-keying customers, vendors, products, invoices, bills, payments, and journals.
- Inconsistent ledger, GST, product, UoM, price, and warehouse identities.
- One-way export files with no durable acknowledgement or retry trail.
- Duplicate creation caused by unstable external identifiers.
- Feedback loops where an imported record is immediately exported back.
- A single malformed inbound record permanently blocking every newer record.
- Accidental production pushes from copied or restored Odoo databases.
- Private Tally installations that cannot accept inbound internet traffic.

## Supported scope

| Domain | Tally → Odoo | Odoo → Tally | Notes |
|---|:---:|:---:|---|
| Account groups | Yes | Limited | Groups are normally Tally-owned |
| General ledgers/accounts | Yes | Yes | Configurable account-group mapping |
| Customers and vendors | Yes | Yes | GSTIN, PAN, address and contact identity |
| Currency | Yes | No | Tally normally remains authoritative |
| UoMs | Yes | Yes | Tally-compatible unit normalization |
| Stock groups/categories | Yes | Yes | Parent hierarchy retained |
| Products/stock items | Yes | Yes | SKU, GUID, HSN, rates, quantity and category |
| Godowns/locations | Yes | Yes | Internal stock locations |
| Cost centres/analytics | Yes | Yes | Analytic account mapping |
| Percentage GST/tax ledgers | Yes | Yes | CGST, SGST and IGST recognition |
| Opening balances | Yes | No | Imported through balanced entries |
| Sales and credit notes | Yes | Yes | Inventory or accounts-only vouchers |
| Purchases and debit notes | Yes | Yes | Inventory or accounts-only vouchers |
| Receipts and payments | Yes | Yes | Bank/cash and bill allocation paths |
| Journal and contra vouchers | Yes | Yes | Balanced accounting entries |
| Internal transfers | Yes | Yes | Tally Stock Journal ↔ Odoo transfer |

“Yes” means implemented for the standard structures exercised by the included tests. Tally is
highly configurable; non-standard voucher definitions, custom TDL, unusual GST ledgers, and legacy
data must be covered by customer UAT.

## Explicit exclusions

This release does not implement manufacturing orders/BOMs, landed costs, fixed-asset depreciation,
procurement or replenishment rules, sales/purchase orders, delivery/receipt notes, Tally payroll,
government IRN generation, E-Way Bill submission, GSTR filing, or portal reconciliation. Tally
references may be retained when matching Odoo fields exist, but reference retention is not filing.

## Architecture at a glance

```text
Odoo business event
  -> guarded model hook
  -> XML builder + stable GUID
  -> durable outbound queue
  -> direct dispatcher OR outbound-only agent
  -> TallyPrime XML gateway
  -> acknowledgement, retry and audit log

TallyPrime AlterID delta
  -> direct poller OR outbound-only agent
  -> XML parser
  -> direction/source policy + echo suppression
  -> transactional Odoo upsert + identity mapping
  -> watermark advance
  -> repeated failure -> inbound quarantine -> surgical retry
```

See [Architecture](Docs/ARCHITECTURE.md) for components, sequences, trust boundaries, failure
modes, and deployment topologies. See [Technical Reference](Docs/TECHNICAL_REFERENCE.md) for
models, fields, routes, entities, XML contracts, and extension guidance.

## Deployment choices

| Topology | Use when | Network behavior |
|---|---|---|
| Direct | Odoo can securely reach the Tally host | Odoo calls the protected Tally gateway |
| Agent | Tally is on a private LAN | Agent calls Tally locally and Odoo over outbound HTTPS |

Never expose Tally's unauthenticated HTTP port directly to the public internet. Use a VPN,
allow-listed private network, authenticated tunnel, or HTTPS reverse proxy.

## Quick start

1. Back up the Odoo database and Tally company.
2. Put `tally_integration` on the Odoo 19 addons path.
3. Update the Apps list and install **Tally Prime Integration**.
4. In TallyPrime, enable the XML server and open the target company.
5. Create one Tally instance in Odoo and select direct or agent mode.
6. Load default entities, then review every entity's direction and source of truth.
7. Test connection, synchronize masters, and run a small voucher UAT.
8. Re-run the same pull and confirm that counts and balances remain stable.
9. Activate scheduled synchronization only after signed UAT.

Detailed procedures, rollback, Windows service setup, firewall guidance, and incident handling are
in [Installation and Operations](Docs/INSTALLATION_AND_OPERATIONS.md).

## Reliability controls

- RFC-4122-compatible stable GUIDs and dedicated identity mappings.
- SHA-256 content hashes and origin tracking for echo suppression.
- Per-entity direction, source-of-truth policy, and AlterID watermark.
- Durable outbound queue with idempotency keys, retry, acknowledgement, and expired-lease recovery.
- Inbound dead-letter records with payload hash, error history, threshold, quarantine, and targeted
  `AlterID - 1` retry.
- Savepoints around individual inbound records.
- Multi-company ACLs and record rules.
- One-active-instance-per-company constraint.
- Database UUID clone guard.
- Configurable log retention and optional per-record audit logging.

## Validation status

The release was validated using:

- Python compilation and XML/manifest checks.
- Eight standalone XML transformation tests.
- Fresh Odoo 19 module installation.
- Twenty post-install test methods / 22 Odoo framework counts with zero failures and zero errors.
- A real TallyPrime round trip covering 15 products, purchases, sales, both returns, CGST/SGST,
  receipts, payments, a journal, and an internal Stock Journal transfer.
- Fresh-database recovery, repeated-pull idempotency, and price edits in both directions.

Read [Testing and Validation](Docs/TESTING_AND_VALIDATION.md) and the
[release evidence summary](tally_integration/FINAL_VALIDATION_REPORT.md).

## How this differs from common alternatives

Public Odoo Apps listings include manual XML-export tools, paid connectors focused on customer
invoices, direct auto-sync connectors, and assisted one-time migration middleware. This project is
positioned differently: free LGPL source, direct and private-LAN agent topologies, configurable
ownership for 20 entity types, disaster-recovery testing, and separate outbound retry plus inbound
poison-record quarantine.

The comparison is capability-based, sourced from public listings, and does not imply that other
products are inferior. Review the dated analysis in [Product and Marketing](Docs/PRODUCT_AND_MARKETING.md).

## Free software, paid expertise

The module, source code, documentation, and community updates are free. There is no license fee and
no mandatory paid activation. Organizations may engage Scidecs for optional:

- Readiness assessment and solution design.
- Secure network and agent deployment.
- Chart-of-accounts and GST mapping.
- Historical migration and reconciliation.
- Customer-specific UAT and cutover.
- Training, operational support, upgrades, and custom extensions.

The free module is provided under LGPL-3 without a promise that every customized Tally company will
work without configuration. Paid consulting purchases expertise and accountable delivery, not a
different hidden edition of the connector. See [Support and Consulting](Docs/SUPPORT_AND_CONSULTING.md).

## Documentation map

| Document | Audience | Purpose |
|---|---|---|
| [Architecture](Docs/ARCHITECTURE.md) | Architects, technical leads | End-to-end components, flows and failure design |
| [Technical Reference](Docs/TECHNICAL_REFERENCE.md) | Developers, reviewers | Models, APIs, entities, XML, hooks and extension rules |
| [Installation and Operations](Docs/INSTALLATION_AND_OPERATIONS.md) | Implementers, administrators | Installation, configuration, runbooks and recovery |
| [Testing and Validation](Docs/TESTING_AND_VALIDATION.md) | QA, customer UAT | Automated tests, live scenario and acceptance criteria |
| [Security](Docs/SECURITY.md) | Security and infrastructure | Threat model, secrets, network and access controls |
| [Product and Marketing](Docs/PRODUCT_AND_MARKETING.md) | Sales, marketing, partners | AIDA copy, personas, value, differentiation and claims |
| [FAQ](Docs/FAQ.md) | Sales, support, customers | Client-ready functional and technical answers |
| [Support and Consulting](Docs/SUPPORT_AND_CONSULTING.md) | Customers, delivery teams | Free/paid boundary and engagement model |
| [Odoo Apps Publishing](Docs/ODOO_APPS_PUBLISHING.md) | Release manager | Store assets, manifest, branch and submission checklist |
| [Implementation Status](Docs/IMPLEMENTATION_STATUS.md) | All reviewers | Honest supported boundary and release gates |
| [Roadmap](Docs/ROADMAP.md) | Product and engineering | Completed capabilities and future hardening |
| [Changelog](CHANGELOG.md) | All users | Versioned public feature and correction history |
| [Contributing](CONTRIBUTING.md) | Contributors | Change design, validation, documentation and security reporting |

## Compatibility and license

- Odoo: 19.0 Community and Enterprise code paths.
- Hosting: Odoo.sh or on-premise; direct connectivity depends on network reachability.
- Tally: TallyPrime native XML gateway; validate the customer's exact release and configuration.
- Python agent: Python 3.10+ standard library only.
- License: LGPL-3.
- Maintainer: Scidecs.
- Questions and optional services: [hello@scidecs.com](mailto:hello@scidecs.com).
- Issues and contributions: [GitHub repository](https://github.com/scidecs/odoo-tally).

Tally and TallyPrime are trademarks of their respective owner. Odoo is a trademark of Odoo S.A.
This community connector is independently developed by Scidecs.
