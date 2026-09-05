# Screenshot and Visual Evidence Catalog

The Odoo Apps product tour uses screenshots captured from a running Odoo 19 installation on
2026-09-05. Interface images use synthetic Scidecs demo labels or the disposable live-round-trip
test scenario; private infrastructure values and credentials are excluded. Empty monitoring views
were temporarily populated with clearly marked synthetic `[Store Demo]` records, then the records
were removed from the test database after capture.

## Module control centre

| Asset | What it proves |
|---|---|
| `01_dashboard_kanban.jpg` | Instance health dashboard and primary actions |
| `02_instances_list.jpg` | Multi-instance list, company separation and connection mode |
| `03_instance_control_center.jpg` | Configuration, live status and operational KPIs |
| `04_private_lan_agent.jpg` | Agent topology and authenticated token workflow |
| `05_onboarding_wizard.jpg` | Guided first-run setup |

## Operations, recovery and auditability

| Asset | What it proves |
|---|---|
| `06_outbound_queue.jpg` | Durable outbound work queue and states |
| `07_outbound_item_detail.jpg` | Idempotency, attempts, payload and acknowledgement detail |
| `08_sync_logs_list.jpg` | Searchable per-operation audit trail |
| `09_sync_log_detail.jpg` | Request/result/error diagnostic detail |
| `10_sync_analytics_pivot.jpg` | Pivot analysis of synchronization activity |
| `11_sync_analytics_graph.jpg` | Graph analysis of synchronization activity |
| `12_inbound_quarantine.jpg` | Poison-record dead-letter queue |
| `13_quarantine_record_detail.jpg` | Failure history and targeted retry controls |
| `14_identity_mappings.jpg` | Stable Odoo/Tally identity registry |
| `15_identity_mapping_detail.jpg` | GUID, AlterID, source and local-record mapping detail |

## Configuration and discovery

| Asset | What it proves |
|---|---|
| `16_integration_settings.jpg` | Global connector settings and retention controls |
| `17_entity_configuration.jpg` | Per-entity direction and ownership policy |
| `18_account_type_mapping.jpg` | Tally group to Odoo account-type mapping |
| `19_discovered_tally_companies.jpg` | LAN-agent Tally company discovery |
| `20_discovered_company_detail.jpg` | Discovered company metadata and selection workflow |

## Recovered and synchronized business data

| Asset | What it proves |
|---|---|
| `21_recovered_product_catalog.jpg` | Products recovered with SKU, price and stock context |
| `22_synchronized_sales_invoices.jpg` | Tally-linked customer invoices |
| `23_gst_sales_invoice_detail.jpg` | Sales lines and GST on a synchronized invoice |
| `24_synchronized_purchase_bills.jpg` | Tally-linked vendor bills |
| `25_gst_purchase_bill_detail.jpg` | Purchase lines and GST on a synchronized bill |
| `26_synchronized_receipts_payments.jpg` | Payment synchronization results |
| `27_stock_journal_warehouse_transfer.jpg` | Stock Journal represented as an internal transfer |
| `28_synchronized_journal_entry.jpg` | Balanced synchronized general journal entry |

All files are under `tally_integration/static/description/screenshots/` and are intentionally part of
the distributable module so the Odoo Apps renderer uses only local assets.

## TallyPrime desktop evidence

TallyPrime runs on the separate Windows test host. Its XML gateway and remote-desktop ports were not
reachable from the publishing workstation at the time of this capture. No Tally UI screenshot is
fabricated or inferred from XML. Follow [Tally Screenshot Capture Guide](TALLY_SCREENSHOT_CAPTURE_GUIDE.md)
once a user-authorized browser remote session is available; then place the sanitized files in
`tally_integration/static/description/screenshots/tally/` and add them to the product tour.
