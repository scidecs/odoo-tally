# Tally Prime Integration for Odoo 19

This is the installable Odoo addon from the
[Scidecs Odoo–TallyPrime Integration](https://github.com/scidecs/odoo-tally) repository.

It provides configurable synchronization of supported accounting and inventory masters and
vouchers between Odoo 19 and TallyPrime through the native XML gateway. Direct and outbound-only
agent deployments are supported. The addon includes durable outbound work, stable mappings,
source-of-truth policy, echo suppression, audit logs, and inbound poison-record quarantine.

The software is free under LGPL-3. Optional implementation, migration, training, support, and
customization services are available from Scidecs; no paid activation is required.

## Start here

- [Repository overview](../README.md)
- [Complete feature catalog](../Docs/FEATURE_CATALOG.md)
- [Screenshot catalog](../Docs/SCREENSHOT_CATALOG.md)
- [Architecture](../Docs/ARCHITECTURE.md)
- [Technical reference](../Docs/TECHNICAL_REFERENCE.md)
- [Installation and operations](../Docs/INSTALLATION_AND_OPERATIONS.md)
- [Testing and validation](../Docs/TESTING_AND_VALIDATION.md)
- [FAQ](../Docs/FAQ.md)
- [Support model](../Docs/SUPPORT_AND_CONSULTING.md)
- [Odoo Apps publishing checklist](../Docs/ODOO_APPS_PUBLISHING.md)
- [TallyPrime screenshot capture guide](../Docs/TALLY_SCREENSHOT_CAPTURE_GUIDE.md)
- [Final validation report](FINAL_VALIDATION_REPORT.md)

## Supported entities

Account groups, general ledgers, customers/vendors, currencies, UoMs, stock groups, products,
godowns, cost centres, percentage tax ledgers, opening balances, sales, purchases, credit notes,
debit notes, receipts, payments, journals, contras, and internal Stock Journal transfers.

The exact direction and authority are configured per entity. Customer-specific Tally voucher
definitions and custom TDL require UAT.

## Not included

MRP/BOM, landed costs, assets, procurement, sales/purchase orders, delivery/receipt notes, payroll,
IRN generation, E-Way Bill submission, GSTR filing, and government-portal reconciliation are not
part of this release.

## Minimal installation

1. Add `tally_integration` to an Odoo 19 addons path.
2. Update Apps and install **Tally Prime Integration**.
3. Create a Tally instance, load default entities, and explicitly review direction/source policy.
4. Use a backed-up test company for connection testing and UAT.
5. Enable scheduled sync only after reconciliation passes.

Contact: [hello@scidecs.com](mailto:hello@scidecs.com)<br>
License: LGPL-3
