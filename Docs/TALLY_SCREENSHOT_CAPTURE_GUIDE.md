# TallyPrime Screenshot Capture Guide

This checklist creates defensible Tally-side evidence for the Odoo Apps listing. Use the disposable
test company only. Do not expose customer names, license serials, email addresses, GST credentials,
Windows usernames, network addresses or unrelated companies.

## Access method

Use a user-authorized, temporary browser remote-desktop session. The user enters the one-time PIN;
the credential is never posted in chat or stored in the repository. Disable remote access after the
capture. The Tally XML port must remain private.

## Evidence inventory

Status as of 2026-09-06: 15 real, sanitized TallyPrime screenshots are published. Items marked
optional below were deliberately not captured because the required behavior is already evidenced or
the screen would expose unrelated test data/infrastructure. Missing optional images are not release
blockers.

Save clean 16:9 PNG or high-quality JPEG images with these names:

1. **Captured** `tally_01_gateway_company.jpg` — Gateway of Tally with the disposable company loaded.
2. **Optional / excluded** `tally_02_xml_server_enabled.jpg` — omit when sanitizing the connectivity screen would remove its evidentiary value.
3. **Captured** `tally_03_account_groups.jpg` — account-group hierarchy.
4. **Captured** `tally_04_ledgers.jpg` — synthetic party ledger.
5. **Captured** `tally_05_stock_groups.jpg` — synchronized category hierarchy.
6. **Captured** `tally_06_stock_items.jpg` — synchronized stock-item catalog.
7. **Captured** `tally_07_stock_item_detail.jpg` — UoM, group and GST applicability for a test item.
8. **Captured** `tally_08_godown_summary.jpg` — source/destination godown masters.
9. **Captured** `tally_09_sales_gst_voucher.jpg` — inventory sales voucher with CGST/SGST.
10. **Captured** `tally_10_purchase_gst_voucher.jpg` — inventory purchase voucher with GST.
11. **Captured** `tally_11_credit_note.jpg` — customer return.
12. **Captured** `tally_12_debit_note.jpg` — vendor return.
13. **Captured** `tally_13_receipt.jpg` — customer receipt.
14. **Captured** `tally_14_payment.jpg` — vendor payment.
15. **Captured** `tally_15_journal.jpg` — balanced general journal.
16. **Optional** `tally_16_contra.jpg` — cash/bank transfer voucher; code support remains covered by tests and the feature catalog.
17. **Captured** `tally_17_stock_journal.jpg` — source and destination godown transfer.
18. **Excluded for privacy** `tally_18_day_book.jpg` — the unfiltered test date contained unrelated companies; individual RT vouchers provide stronger proof.
19. **Optional** `tally_19_cost_centres.jpg` — synchronized cost-centre hierarchy when enabled.
20. **Optional** `tally_20_round_trip_edit.jpg` — item rate changed by Odoo and visible in Tally; machine-readable round-trip evidence remains documented separately.

## Capture standard

- Set TallyPrime to a readable 100%–125% display scale and maximize the window.
- Keep the Tally title bar visible so the application is identifiable.
- Use the same disposable scenario references shown in the Odoo screenshots.
- Open each voucher; a list row alone does not prove tax, ledger or inventory allocations.
- Capture before and after only for the one explicitly demonstrated round-trip edit.
- Do not crop away important context or add claims to the screenshot itself.
- Review every image at full size before committing it.

## Publication check

After capture, confirm that all images are sanitized, add captions and alt text to
`static/description/index.html`, update `Docs/SCREENSHOT_CATALOG.md`, run the stage checks, and have
a second reviewer compare the visible voucher values with the saved round-trip evidence. The
2026-09-06 publication set passed a full-size contact-sheet review and OCR screening for unrelated
names, personal details, private IP addresses and legacy project names.
