# Odoo 18 Enterprise Validation Report

Validation date: 2026-09-09  
Release branch: `18.0`  
Scenario identifier: `RT180909A`

## Runtime under test

- Odoo Community 18.0 source commit: `68dcb950df83d70ff2aea0e05c96cc9b57c1a8a9`.
- Odoo Enterprise 18.0 source commit: `40b53e99de1d534987bd331d25685df2dd56b30d`.
- Installed applications: `web_enterprise`, `account_accountant`, `l10n_in`, and
  `tally_integration` plus their dependencies.
- Topology: Odoo on macOS/PostgreSQL; TallyPrime on a separate Windows EliteBook over a private
  LAN. The private host address is deliberately excluded from the public repository.
- Tally company: disposable demonstration company opened in educational mode.

## Automated and runtime gates

- Clean Enterprise database installation completed successfully.
- 23 post-install test methods / 27 Odoo framework counts completed with zero failures and zero
  errors.
- Real HTTP agent-route coverage passed for authorization, heartbeat, company discovery, raw XML
  inbound processing, queue leasing, and acknowledgement.
- Enterprise web client rendered the dashboard, instance configuration, entity policies, queue,
  logs, account-type mappings, and navigation without browser-console errors.

## Live round trip

The source database created 15 stock items across three categories, four GST taxes, two purchase
bills, two sales invoices, a purchase return, a sales return, a customer receipt, a vendor payment,
a balanced journal, and an internal transfer of five items between godowns.

Outbound result:

- 39 queue records acknowledged by TallyPrime.
- Zero failed queue records.
- Native Tally re-export returned 15/15 products with matching part number, category, cost, and
  selling price.

Fresh-database recovery result:

- A separate blank Odoo 18 Enterprise database was installed from scratch.
- 262 records were processed and 247 durable mappings created.
- All 15 products recovered with exact SKU, category, cost, selling price, and total quantity.
- All six invoice/refund documents recovered with matching untaxed, GST, and total amounts.
- Both payments, the journal entry, and the completed internal transfer recovered.
- Zero synchronization errors were recorded.
- A repeat pull preserved all expected counts and values.

Bidirectional result:

- A TallyPrime selling-price alteration was pulled into Odoo and verified.
- An Odoo selling-price alteration was pushed to TallyPrime and verified by native re-export.
- A defect found during this test was corrected: updates to an already mapped stock item now use
  Tally `ACTION="Alter"` rather than resending an existing GUID as `Create`. A dedicated regression
  test protects this behavior.

## Acceptance boundary

This evidence establishes Odoo 18 Enterprise compatibility and the tested functional round trip.
It does not replace customer UAT for custom TDL, non-standard voucher definitions, closed fiscal
periods, security infrastructure, or production-scale volumes. The next separate gate is a hosted
Odoo deployment communicating with the private-LAN Tally machine through the outbound agent over
HTTPS; Tally port 9000 must never be exposed directly to the public internet.
