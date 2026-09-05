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

* Supported master data: groups, general accounts, parties, units of measure, stock groups,
  stock items, godowns/locations, cost centres, taxes, and currencies.
* Supported transactions: sales invoices, credit notes, purchase bills, debit notes,
  receipts, payments, journal/contra vouchers, and internal stock transfers.
* Configurable source of truth: Tally-first, Odoo-first, or bidirectional with serialized
  processing and SHA-256 echo/loop suppression.
* Outbound queue and token-authenticated controllers for the optional on-prem sync agent.
* Native Odoo list, pivot, and graph views for synchronization monitoring.
""",
    "version": "19.0.1.1.0",
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
        "views/tally_inbound_dead_letter_views.xml",
        "views/tally_account_type_map_views.xml",
        "views/tally_discovered_company_views.xml",
        "views/res_config_settings_views.xml",
        "wizard/tally_onboarding_views.xml",
        "views/tally_menus.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
