# -*- coding: utf-8 -*-
"""Upgrade identity rows written by releases before 1.2.0.

Older releases stored the GUID *Odoo sent* in ``tally_guid`` (Tally ignores it and
keeps it as REMOTEALTGUID), synthetic ``odoo_<entity>_<id>`` / ``tally_<entity>_<id>``
keys for records pulled without a GUID, and the AlterID in ``tally_masterid``.
Left as is, the first pull after upgrading would treat already-synchronised
records as new. This moves every value to its proper column; the next pull binds
Tally's real GUID through REMOTEALTGUID or the Tally name.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    # 1. The AlterID used to be stored in tally_masterid.
    cr.execute("""
        UPDATE tally_mapping
           SET tally_alterid = CAST(tally_masterid AS INTEGER), tally_masterid = NULL
         WHERE tally_masterid ~ '^[0-9]+$' AND COALESCE(tally_alterid, 0) = 0
    """)
    # 2. GUIDs Odoo generated (plain RFC-4122 or odoo_*): they are our remote id.
    cr.execute("""
        UPDATE tally_mapping
           SET remote_id = tally_guid, tally_guid = NULL, tally_alterid = 0
         WHERE remote_id IS NULL AND tally_guid IS NOT NULL
           AND (tally_guid LIKE 'odoo\\_%%'
                OR (tally_guid ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    AND last_origin = 'odoo'))
    """)
    moved = cr.rowcount
    # 3. Synthetic keys for records pulled without a GUID: drop the key, keep the
    #    link; the Tally name lets the next pull bind the real GUID.
    cr.execute("""
        UPDATE tally_mapping SET tally_guid = NULL, tally_alterid = 0
         WHERE tally_guid LIKE 'tally\\_%%'
    """)
    synthetic = cr.rowcount
    # 4. Tally names of linked masters (used for renames and name binding).
    for table, entity_list in (("res_partner", ("ledger",)), ("account_account", ("account_ledger",)),
                               ("uom_uom", ("uom",)), ("product_category", ("stock_group",)),
                               ("stock_location", ("godown",)), ("account_analytic_account", ("cost_centre",)),
                               ("account_tax", ("tax",))):
        cr.execute("""
            SELECT m.id, t.name FROM tally_mapping m JOIN %s t ON t.id = m.odoo_res_id
             WHERE m.entity IN %%s AND m.tally_name IS NULL
        """ % table, [entity_list])
        for mapping_id, name in cr.fetchall():
            if isinstance(name, dict):  # translated jsonb name
                name = name.get("en_US") or next(iter(name.values()), None)
            cr.execute("UPDATE tally_mapping SET tally_name = %s WHERE id = %s", [name, mapping_id])
    _logger.info("tally_integration 1.2.0 migration: %s pushed GUIDs moved to remote_id, "
                 "%s synthetic keys cleared", moved, synthetic)
