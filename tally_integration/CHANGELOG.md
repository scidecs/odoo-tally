# Changelog

All notable public changes to the Scidecs Odoo–TallyPrime integration are documented here.

## 1.2.0 (18.0.1.2.0 / 19.0.1.2.0 / 20.0.1.2.0) — 2026-09-29

Data-integrity release. Every item below was reproduced against a live TallyPrime gateway before
it was fixed; the verified TallyPrime behaviours are documented in
[Sync Integrity Rules](Docs/SYNC_INTEGRITY_RULES.md).

### Added

- Odoo 20 support (unified `ir.access` security, API renames, PostgreSQL 16+), alongside 18 and 19
  from one code base.
- Identity binding after every push: Tally's GUID, MasterID, AlterID and voucher number are read
  back and stored, so pulled read-backs are never imported as new documents.
- Voucher collection pull by AlterID (and by date on first sync) replacing the Day Book export.
- Odoo reset-to-draft, cancel and delete mirrored as Tally cancellations; re-posting restores.
- "Push Existing Odoo Data" onboarding for companies that already run Odoo.
- Accounting fingerprint and field gating so Tally-owned records are only written back on real edits.
- Payments re-sent after reconciliation so Tally bill-wise references match.
- Upgrade migration for identity rows created by earlier releases.
- Agent relay protocol: Odoo builds every Tally request; the agent is a single standard-library file.

### Corrected

- Duplicate invoices/bills in Odoo after pushing them to Tally (Tally renumbers vouchers and ignores
  supplied GUIDs).
- Voucher pull only saw Tally's current date (Day Book ignores date ranges).
- Voucher Alter/Cancel by number could change a *different* voucher type with the same number.
- Opening balances imported on the wrong side (Tally negative = debit).
- Party/tax/journal lines double counted when Tally returned both ledger lists.
- Parties under custom Sundry Debtors/Creditors sub-groups imported as general ledger accounts.
- Sales/Purchase Orders and Delivery/Receipt Notes imported as invoices; custom voucher types
  misrouted.
- Ledgers such as "Processing Fees" or "Renovation" treated as CESS/VAT tax ledgers.
- SGST ledgers mapped onto the CGST tax (halving GST); imported GST posted to Sales/Purchases.
- GST on expense ledgers and custom allocations forced into a reconciliation plug (now exact lines).
- Round-off and charge lines with inverted signs; cash sales invoiced to a contact named "Cash";
  expense payments imported as payments to a contact named after the expense.
- Journals/payments with the same narration merged into one Odoo entry.
- Renames in Odoo created a second Tally master; Tally renames created a second Odoo record.
- Tally edits and cancellations not applied to posted Odoo documents.
- Deletion reconcile flagging every Tally-origin master as deleted.
- Unique constraints silently absent on Odoo 19 (`_sql_constraints` ignored).
- Multi-company imports using the first company's account codes and partner accounts.
- Duplicate master names in one import raising a TallyPrime internal error.

### Upgrading

1. Back up the Odoo database and the Tally company.
2. Upgrade the module (`-u tally_integration`); identity rows from earlier releases are migrated
   automatically.
3. Replace the on-premise agent with `agent/tally_agent.py` from this release. Older agents still
   connect but do not receive the voucher-pull and identity fixes.
4. Run **Sync Now** once and review the sync log before re-enabling scheduled sync.

### Validated

- 48 Odoo post-install tests on each of Odoo 18, 19 and 20.
- Live TallyPrime matrix: four scenarios (both new, Tally in use, Odoo in use, two companies) on
  three Odoo versions, 12 runs and 45 ledger-balance audits with zero differences.
- On-premise agent end-to-end run and upgrade migration from 19.0.1.1.0.

## 18.0.1.0.0 — 2026-09-09

### Added

- Odoo 18 Community and Enterprise compatibility branch and target-version documentation.
- Exact-runtime Odoo 18 Enterprise clean-install, post-install, HTTP agent-route, UI, live Tally
  round-trip, fresh-database recovery, repeat-pull and bidirectional-edit validation.
- Odoo 18 compatibility guards in the release checks and an environment-selectable live-scenario
  prefix for collision-free validation runs.

### Corrected

- Replaced Odoo 19-only `models.Constraint` declarations with Odoo 18 SQL constraints.
- Restored Odoo 18 JSON controller route declarations, required stock-move names, required imported
  UoM categories and valid opening-balance equity account types.
- Existing mapped stock-item updates now use Tally `Alter` semantics, protecting hierarchy and
  other structural fields from recreate behavior.

### Validated

- 8 standalone transformation tests and 23 Odoo post-install methods / 27 framework counts passed.
- Live Tally accepted 39 outbound records with zero failures; native export matched 15/15 products.
- A blank Odoo 18 Enterprise database processed 262 inbound records, created 247 mappings and
  recovered the complete reference scenario with zero sync errors.

The Odoo 18 release details are in `Docs/ODOO18_VALIDATION_REPORT.md`.

## Store and packaging updates — September 2026

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
