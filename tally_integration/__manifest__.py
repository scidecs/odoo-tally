# -*- coding: utf-8 -*-
{
    "name": "Tally Prime Integration",
    "summary": "Near-real-time two-way sync between TallyPrime and Odoo — "
               "Tally as source of truth (configurable), native UI, on-prem agent.",
    "description": """
Tally Prime ⇄ Odoo 19 Integration
=================================
A single native module for near-real-time, two-way synchronization between TallyPrime
and Odoo 19 (Odoo.sh / On-Premise). Tally is the default source of truth, configurable per entity.

- Complete Master Data Sync: Groups, General Accounts, Parties (Customers/Vendors with Indian GST),
  Units of Measure, Stock Groups, Stock Items, Godowns/Locations, Cost Centres, Taxes, Currencies.
- Complete Transaction Sync: Sales Invoices, Credit Notes, Purchase Bills, Debit Notes,
  Customer Receipts, Vendor Payments with Bill-by-Bill Allocations, Journal Vouchers, Contra Vouchers.
- Configurable Source of Truth: Tally-first, Odoo-first, or Bidirectional with Last-Write-Wins and
  SHA-256 Echo / Loop Suppression.
- Outbound queue + token-authenticated agent controllers for the on-prem Sync Agent.
- Native Odoo UI dashboards: list / pivot / graph for sync monitoring.
""",
    "version": "19.0.1.0.0",
    "category": "Accounting",
    "author": "Scidecs",
    "website": "https://www.scidecs.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "account", "uom", "product", "stock", "analytic"],
    "data": [
        "security/tally_security.xml",
        "security/ir.model.access.csv",
        "security/ir_rule_data.xml",
        "data/ir_cron_data.xml",
        "data/tally_account_type_map_data.xml",
        "views/tally_instance_views.xml",
        "views/tally_entity_config_views.xml",
        "views/tally_mapping_views.xml",
        "views/tally_sync_log_views.xml",
        "views/tally_sync_queue_views.xml",
        "views/res_config_settings_views.xml",
        "views/tally_account_type_map_views.xml",
        "views/tally_discovered_company_views.xml",
        "wizard/tally_onboarding_views.xml",
        "views/tally_menus.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
