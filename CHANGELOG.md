# Changelog

All notable public changes to the Scidecs Odoo–TallyPrime integration are documented here.

## Unreleased

### Corrected

- Replaced affected punctuation in the Odoo Apps description with safe HTML entities after the live
  page exposed character-encoding corruption.
- Coalesced unsent stock-item changes by canonical variant. Product creation through both the normal
  Odoo `product.template` UI and the `product.product` API now produces one current queue row while
  preserving variant-level SKU and barcode events.

### Documentation

- Rebuilt the store and video hero on a strict editorial grid with the Scidecs brand mark and the
  official standard Odoo and combined TallyPrime wordmarks; corrected panel padding, alignment,
  content density and proof-strip spacing while preserving editable SVG source and asset provenance.
- Added a live-listing benchmark, visual redesign sequence, Odoo-compliant promotion boundary,
  Scidecs domain-authority strategy and phased growth measurement plan.
- Added the canonical 20-entity feature catalog, screenshot provenance catalog and a secure
  TallyPrime desktop capture checklist.
- Rebuilt the Odoo Apps description as a complete visual product tour using 28 sanitized Odoo 19
  screenshots, a landscape cover, exhaustive capability matrix and honest product boundary.
- Added 15 real, sanitized TallyPrime screenshots covering the disposable company, master data, GST
  sales and purchase, returns, receipts, payments, journal and a five-item Stock Journal transfer.
- Documented Tally screenshot provenance and privacy exclusions; unfiltered Day Book and connection
  settings were intentionally not published.
- Added a reproducible two-minute narrated explainer built around a live Odoo product creation and
  live TallyPrime arrival/detail verification, with editable narration, English subtitles and cover.
- Extended release checks to reject broken store images, missing alt text, scripts, external image
  assets, private filesystem paths and legacy project references.

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
