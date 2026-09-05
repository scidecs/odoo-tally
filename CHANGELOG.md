# Changelog

All notable public changes to the Scidecs Odoo–TallyPrime integration are documented here.

## 19.0.1.1.0 — 2026-09-05

### Added

- Dedicated inbound dead-letter/quarantine model, views, ACLs, company rule and instance KPIs.
- Configurable positive failure threshold and targeted AlterID retry.
- Outbound hooks for UoM, stock group, godown, cost centre and percentage tax masters.
- Product SKU/barcode and effective-dated cost/selling-price XML support.
- Educational-mode date normalization for disposable Tally test environments.
- Full live round-trip scenario commands and machine-readable verification output.
- End-to-end architecture, technical reference, installation/operations, validation, security,
  marketing/AIDA, FAQ, support and Odoo Apps publication documentation.
- English Odoo Apps `static/description/index.html` and manifest support metadata.

### Corrected

- Inventory invoice ledger structure, accounting allocations, tax signs and voucher views.
- Stock Journal native IN/source and OUT/destination structure and Odoo 19 transfer completion.
- Zero-closing-stock parsing and repeated total-stock pull idempotency across godowns.
- Product category, SKU, cost, price, quantity and mapping fidelity on recovery.
- Payment/journal/transfer business references.
- XML attribute escaping and automated-valuation stock safety.
- Product create duplicate queue event concern with a regression proving one canonical event.
- Echo acknowledgement now resolves stale inbound failures.

### Validated

- Eight standalone XML tests.
- Fresh Odoo 19 installation and 20 post-install test methods / 22 framework counts with zero test
  failures or errors.
- Live TallyPrime scenario with 15 products, purchases, sales, both returns, CGST/SGST, receipt,
  payment, journal, internal transfer, clean recovery, repeat pull and edits in both directions.

### Release position

Ready for controlled customer UAT/pilot within the documented scope. Customer real-data, scale,
soak, network-fault and simultaneous-edit testing remain deployment gates.

## Earlier 19.0 development

- Initial Odoo 19 module, instance/entity configuration, mappings, queues, logs and onboarding.
- Native Tally XML transport/build/parse services.
- Direct and optional outbound-only agent topologies.
- Core master and voucher upserts, source policy, echo suppression and multi-company isolation.
