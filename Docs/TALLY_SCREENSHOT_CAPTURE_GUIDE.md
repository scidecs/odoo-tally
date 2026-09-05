# TallyPrime Screenshot Capture Guide

This checklist creates defensible Tally-side evidence for the Odoo Apps listing. Use the disposable
test company only. Do not expose customer names, license serials, email addresses, GST credentials,
Windows usernames, network addresses or unrelated companies.

## Access method

Use a user-authorized, temporary browser remote-desktop session. The user enters the one-time PIN;
the credential is never posted in chat or stored in the repository. Disable remote access after the
capture. The Tally XML port must remain private.

## Required images

Save clean 16:9 PNG or high-quality JPEG images with these names:

1. `tally_01_gateway_company.jpg` — Gateway of Tally with the disposable company loaded.
2. `tally_02_xml_server_enabled.jpg` — server connectivity setting, with addresses sanitized.
3. `tally_03_account_groups.jpg` — synchronized account-group hierarchy.
4. `tally_04_ledgers.jpg` — synchronized party and tax ledgers.
5. `tally_05_stock_groups.jpg` — synchronized category hierarchy.
6. `tally_06_stock_items.jpg` — 10–15 synchronized stock items.
7. `tally_07_stock_item_detail.jpg` — SKU, UoM, HSN and rates for one test item.
8. `tally_08_godown_summary.jpg` — source/destination godown quantities.
9. `tally_09_sales_gst_voucher.jpg` — inventory sales voucher with CGST/SGST or IGST.
10. `tally_10_purchase_gst_voucher.jpg` — inventory purchase voucher with GST.
11. `tally_11_credit_note.jpg` — customer return.
12. `tally_12_debit_note.jpg` — vendor return.
13. `tally_13_receipt.jpg` — customer receipt and bill allocation.
14. `tally_14_payment.jpg` — vendor payment and bill allocation.
15. `tally_15_journal.jpg` — balanced general journal.
16. `tally_16_contra.jpg` — cash/bank transfer voucher.
17. `tally_17_stock_journal.jpg` — source and destination godown transfer.
18. `tally_18_day_book.jpg` — complete test date Day Book showing the voucher mix.
19. `tally_19_cost_centres.jpg` — synchronized cost-centre hierarchy, when enabled.
20. `tally_20_round_trip_edit.jpg` — item rate changed by Odoo and visible in Tally.

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
a second reviewer compare the visible voucher values with the saved round-trip evidence.
