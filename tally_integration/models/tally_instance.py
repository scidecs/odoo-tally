# -*- coding: utf-8 -*-
import logging
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

from .constants import DEFAULT_ENTITIES, direction_for_source
from .compat import config_param, sql_constraints


class TallyInstance(models.Model):
    _name = "tally.instance"
    _description = "Tally Connection / Instance"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    company_id = fields.Many2one(
        "res.company", required=True, index=True,
        default=lambda self: self.env.company,
    )
    active = fields.Boolean(default=True)

    # --- Tally endpoint (reached by the on-prem agent, not by Odoo directly) ---
    tally_host = fields.Char(
        string="Tally Host / IP", default="127.0.0.1",
        help="IP or hostname of the Tally XML gateway. For cloud-hosted Tally this is its "
             "public/routable address; for a local Tally, use the tunnel/proxy host.",
    )
    tally_port = fields.Integer(string="Tally Port", default=9000)
    connection_mode = fields.Selection(
        [("direct", "Direct — Odoo connects to Tally (no agent)"),
         ("agent", "On-prem agent relays")],
        string="Connection Mode", default="direct", required=True, tracking=True,
        help="Direct: Odoo's scheduled job opens an HTTP connection to Tally's gateway "
             "(use when Odoo can reach Tally over LAN / VPN / tunnel) — no extra process. "
             "Agent: a thin on-prem process relays over outbound HTTPS (use on Odoo.sh when "
             "the Tally LAN is otherwise unreachable).")
    tally_protocol = fields.Selection(
        [("http", "HTTP"), ("https", "HTTPS")], default="http", required=True,
        string="Protocol",
        help="Use HTTPS when Tally is fronted by a reverse proxy / tunnel that terminates TLS.")
    tally_base_url = fields.Char(
        string="Tally Base URL",
        help="Optional. Full URL of the gateway (e.g. https://acme-tally.example.com, or an "
             "ngrok / cloudflared URL). Overrides Host / Port / Protocol when set.")
    tls_verify = fields.Boolean(string="Verify TLS", default=True)
    auth_type = fields.Selection(
        [("none", "None"), ("basic", "Basic Auth"), ("header", "Custom Header")],
        string="Endpoint Auth", default="none", required=True,
        help="Tally's gateway is unauthenticated. Put it behind a reverse proxy / tunnel that "
             "requires Basic Auth or a secret header, and set the matching credential here.")
    auth_username = fields.Char(string="Auth Username")
    auth_password = fields.Char(
        string="Auth Password", groups="tally_integration.group_tally_manager")
    auth_header_name = fields.Char(string="Auth Header Name")
    auth_header_value = fields.Char(
        string="Auth Header Value", groups="tally_integration.group_tally_manager")

    # --- Import behaviour ---
    auto_post = fields.Boolean(
        string="Auto-post Imported Vouchers", default=True,
        help="Post imported invoices / payments / journals automatically. Any that do not "
             "balance are left in draft for review.")
    verbose_logging = fields.Boolean(
        string="Full (per-record) Logging", default=True,
        help="Log every individual record moving in or out. Turn off for a lighter, "
             "batch-summary-only log at very high volume.")
    log_retention_days = fields.Integer(
        string="Log Retention (days)", default=90,
        help="Sync logs older than this are pruned automatically. 0 disables pruning.")
    direct_auto_pull = fields.Boolean(
        string="Auto-pull on Schedule", default=True,
        help="In direct mode, the scheduled job also pulls masters and vouchers FROM Tally, "
             "not just pushing Odoo changes to Tally.")
    pull_lookback_days = fields.Integer(
        string="Voucher Pull Window (days)", default=30,
        help="How far back to pull vouchers on each scheduled/manual pull (from History From "
             "if set, otherwise this many days back).")
    pull_interval = fields.Integer(
        string="Pull Interval (min)", default=15,
        help="How often the scheduled job pulls FROM Tally (decoupled from the faster push "
             "cadence). A full pull is heavier than a push, so this is less frequent.")
    last_pull = fields.Datetime(string="Last Pull", readonly=True)
    tally_books_from = fields.Date(string="Tally Books From", readonly=True)
    tally_ledger_index = fields.Text(
        readonly=True, copy=False,
        help="Ledger name -> party/tax/group-chain classification read from Tally.")
    tally_group_tree = fields.Text(readonly=True, copy=False)
    tally_voucher_type_parents = fields.Text(
        readonly=True, copy=False,
        help="User-defined Tally voucher type -> parent type, used to route custom types.")
    use_tdl_delta = fields.Boolean(
        string="Server-side AlterID Delta (TDL)", default=False,
        help="Send an inline TDL filter so Tally returns only masters changed since the last "
             "watermark (minimal transfer). Leave off until validated against your Tally build; "
             "client-side delta skipping applies either way.")
    tally_company = fields.Char(
        string="Tally Company",
        help="Exact name of the company open in TallyPrime.",
    )

    # --- Source of truth ---
    default_source = fields.Selection(
        [("tally", "Tally (accounting system)"), ("odoo", "Odoo")],
        string="Default Source of Truth", default="tally", required=True, tracking=True,
        help="Default winner on conflict for this instance. Override per entity below.",
    )
    poll_interval = fields.Integer(
        string="Poll Interval (s)", default=60,
        help="How often the on-prem agent polls Tally for AlterID changes.",
    )

    # --- Odoo edition / deployment mode ---
    odoo_edition = fields.Char(string="Odoo Edition", compute="_compute_odoo_edition")
    odoo_role = fields.Selection(
        [("full", "Odoo keeps the books (two-way)"),
         ("operational", "Tally keeps the books (Odoo → Tally)")],
        string="Odoo Role", required=True, tracking=True,
        default=lambda self: self._default_odoo_role(),
        help="Full: Odoo has accounting; two-way sync. Operational: Odoo is the front "
             "office (sales/inventory) and Tally is the accounting system, so financial "
             "data is pushed Odoo → Tally. Defaults to Operational on Odoo Community.")
    tally_inventory = fields.Selection(
        [("with_inventory", "Accounts with Inventory"),
         ("accounts_only", "Accounts only")],
        string="Tally Mode", default="with_inventory", required=True,
        help="Match your Tally company. 'Accounts only' companies receive ledger-only "
             "vouchers (no inventory entries).")
    tally_educational_mode = fields.Boolean(
        string="Tally Educational Mode",
        help="Use educational-mode voucher dates (1st, 2nd, or 31st). Enable only for an "
             "unlicensed Tally test environment; licensed production companies keep the real date.")
    sync_automated_valuation_stock = fields.Boolean(
        string="Adjust Automated-Valuation Stock",
        default=False,
        help="Allow Tally quantities to create Odoo inventory valuation entries for automated-"
             "valuation product categories. Keep disabled when financial opening balances are "
             "also migrated, otherwise stock value can be counted twice.")
    inbound_quarantine_threshold = fields.Integer(
        string="Inbound Quarantine Attempts", default=3,
        help="After this many failures of the same Tally record revision, quarantine it and "
             "allow the entity watermark to continue. Operators can retry it from Operations.")

    # --- Onboarding / initial migration ---
    coa_mode = fields.Selection(
        [("import", "Import CoA from Tally"),
         ("map", "Map to existing Odoo CoA")],
        string="Chart of Accounts Mode", default="import",
        help="On initial onboarding: import Tally's chart of accounts wholesale "
             "(greenfield Odoo), or map Tally ledgers onto an existing Odoo CoA.",
    )
    onboarding_done = fields.Boolean(string="Onboarding Done", readonly=True)
    history_from = fields.Date(
        string="History From",
        help="Earliest voucher date to pull on the initial full sync.")

    # --- Agent pairing / health ---
    agent_token = fields.Char(
        string="Agent Token", copy=False, readonly=True, index=True,
        groups="tally_integration.group_tally_manager",
        help="Bearer token the on-prem Sync Agent uses to authenticate. Keep secret.",
    )
    agent_last_seen = fields.Datetime(string="Agent Last Seen", readonly=True)
    db_uuid = fields.Char(string="Bound DB UUID", readonly=True, copy=False,
        help="Database this instance was activated in. If the DB is copied (staging/restore), "
             "the sync auto-disables to prevent pushing test data to the live Tally.")
    state = fields.Selection(
        [("draft", "Draft"), ("online", "Online"), ("offline", "Offline")],
        default="draft", readonly=True, tracking=True,
    )

    entity_config_ids = fields.One2many(
        "tally.entity.config", "instance_id", string="Entities",
    )
    mapping_count = fields.Integer(compute="_compute_counts")
    log_count = fields.Integer(compute="_compute_counts")
    queue_pending = fields.Integer(compute="_compute_counts")
    queue_failed = fields.Integer(compute="_compute_counts")
    orphan_count = fields.Integer(compute="_compute_counts")
    quarantine_count = fields.Integer(compute="_compute_counts")
    synced_today = fields.Integer(string="Synced Today", compute="_compute_counts")

    sql_constraints(
        locals(),
        ("name_company_uniq", "UNIQUE(name, company_id)",
         "Instance name must be unique per company."),
        ("positive_quarantine_threshold",
         "CHECK(inbound_quarantine_threshold >= 1)",
         "Inbound quarantine attempts must be at least 1."),
    )

    @api.constrains("active", "company_id")
    def _check_single_active_instance_per_company(self):
        """Prevent an outbound event being routed to an arbitrary Tally company."""
        for instance in self.filtered("active"):
            duplicate = self.search_count([
                ("company_id", "=", instance.company_id.id),
                ("active", "=", True),
                ("id", "!=", instance.id),
            ])
            if duplicate:
                raise ValidationError(_(
                    "Only one active Tally instance is allowed per Odoo company. "
                    "Archive the current instance before activating another one."))

    def _compute_counts(self):
        mapping = self.env["tally.mapping"]
        log = self.env["tally.sync.log"]
        queue = self.env["tally.sync.queue"]
        dead_letter = self.env["tally.inbound.dead.letter"]
        for rec in self:
            rec.mapping_count = mapping.search_count([("instance_id", "=", rec.id)])
            rec.log_count = log.search_count([("instance_id", "=", rec.id)])
            rec.queue_pending = queue.search_count(
                [("instance_id", "=", rec.id), ("state", "in", ("pending", "sent"))])
            rec.queue_failed = queue.search_count(
                [("instance_id", "=", rec.id), ("state", "=", "failed")])
            rec.orphan_count = mapping.search_count(
                [("instance_id", "=", rec.id), ("is_orphan", "=", True)])
            rec.quarantine_count = dead_letter.search_count(
                [("instance_id", "=", rec.id), ("state", "=", "quarantined")])
            rec.synced_today = log.search_count([
                ("instance_id", "=", rec.id),
                ("create_date", ">=", fields.Datetime.to_string(
                    fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))),
                ("status", "!=", "error")])

    # ------------------------------------------------------------------ edition
    @api.model
    def _is_enterprise(self):
        return bool(self.env["ir.module.module"].sudo().search_count(
            [("name", "=", "account_accountant"), ("state", "=", "installed")]))

    @api.model
    def _default_odoo_role(self):
        return "full" if self._is_enterprise() else "operational"

    def _compute_odoo_edition(self):
        edition = "Enterprise" if self._is_enterprise() else "Community"
        for rec in self:
            rec.odoo_edition = edition

    # ------------------------------------------------------------------ actions
    def action_generate_token(self):
        for rec in self:
            rec.agent_token = secrets.token_urlsafe(32)
        return True

    # Entities Odoo pushes to Tally when it is operational-only (books in Tally).
    OPERATIONAL_PUSH = {
        "ledger", "stock_item", "uom", "stock_group", "godown", "cost_centre",
        "sales", "credit_note", "purchase", "debit_note", "receipt", "payment",
    }

    def action_load_default_entities(self):
        """Seed the standard entity set (idempotent), honouring the Odoo role.

        In 'operational' mode (Odoo has no books, Tally is the accounting system)
        the entities Odoo originates are pushed Odoo -> Tally, and pure accounting
        entities (CoA, journals, opening balances) are seeded disabled.
        """
        self.ensure_one()
        operational = self.odoo_role == "operational"
        existing = set(self.entity_config_ids.mapped("entity"))
        commands = []
        for entity, model, sot, seq in DEFAULT_ENTITIES:
            if entity in existing:
                continue
            enabled = True
            if operational:
                if entity in self.OPERATIONAL_PUSH:
                    sot, direction = "odoo", "odoo_to_tally"
                else:
                    direction, enabled = direction_for_source(sot), False
            else:
                direction = direction_for_source(sot)
            commands.append((0, 0, {
                "entity": entity,
                "odoo_model_name": model,
                "source_of_truth": sot,
                "direction": direction,
                "enabled": enabled,
                "sequence": seq,
            }))
        if commands:
            self.write({"entity_config_ids": commands})
        return True

    def action_test_connection(self):
        self.ensure_one()
        if self.connection_mode == "direct":
            from ..services import tally_transport, tally_xml_builder, tally_xml_parser
            try:
                ep = self._tally_endpoint()
                xml = tally_xml_builder.build_collection_export("Company", company_name=self.tally_company)
                resp = tally_transport.post_xml(ep["url"], xml, auth=ep["auth"], extra_headers=ep["headers"], verify=ep["verify"], timeout=5)
                root = tally_xml_parser.parse_tally_xml_root(resp)
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Connection Successful"),
                        "message": _("Successfully connected directly to Tally gateway at %s.", ep["url"]),
                        "type": "success",
                        "sticky": False,
                    },
                }
            except Exception as e:
                return {
                    "type": "ir.actions.client",
                    "tag": "display_notification",
                    "params": {
                        "title": _("Connection Failed"),
                        "message": _("Could not reach Tally at %s: %s", self._tally_endpoint()["url"], str(e)),
                        "type": "danger",
                        "sticky": True,
                    },
                }
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Agent-mediated connection"),
                "message": _(
                    "The live TCP test to Tally is performed by the on-prem Sync Agent. "
                    "Ensure the agent is installed near Tally, paired with this instance's "
                    "token, and that Tally's XML gateway is enabled on port %s.",
                    self.tally_port or 9000),
                "type": "info",
                "sticky": False,
            },
        }

    def action_view_mappings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Mappings"),
            "res_model": "tally.mapping",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id)],
            "context": {"default_instance_id": self.id},
        }

    def action_view_queue(self, state=None):
        self.ensure_one()
        domain = [("instance_id", "=", self.id)]
        if state == "failed":
            domain.append(("state", "=", "failed"))
        elif state == "pending":
            domain += [("state", "in", ("pending", "sent"))]
        return {
            "type": "ir.actions.act_window",
            "name": _("Outbound Queue"),
            "res_model": "tally.sync.queue",
            "view_mode": "list,form",
            "domain": domain,
            "context": {"default_instance_id": self.id},
        }

    def action_view_queue_pending(self):
        return self.action_view_queue(state="pending")

    def action_view_queue_failed(self):
        return self.action_view_queue(state="failed")

    def action_view_quarantine(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Quarantined Records"),
            "res_model": "tally.inbound.dead.letter",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id), ("state", "=", "quarantined")],
        }

    def action_retry_quarantined(self):
        """Clear quarantine flags and force a re-pull of the affected entities so the
        (now hopefully fixed) records are retried."""
        self.ensure_one()
        q = self.env["tally.inbound.dead.letter"].search(
            [("instance_id", "=", self.id), ("state", "=", "quarantined")])
        q.action_retry()
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Quarantine cleared"),
                       "message": _("%s record(s) released; affected watermarks were safely rewound.") % len(q),
                       "type": "success", "sticky": False},
        }

    def action_view_orphans(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Orphans (Deleted in Tally)"),
            "res_model": "tally.mapping",
            "view_mode": "list,form",
            "domain": [("instance_id", "=", self.id), ("is_orphan", "=", True)],
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Sync Logs"),
            "res_model": "tally.sync.log",
            "view_mode": "list,pivot,graph,form",
            "domain": [("instance_id", "=", self.id)],
        }

    def action_open_onboarding(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Tally Onboarding"),
            "res_model": "tally.onboarding",
            "view_mode": "form",
            "target": "new",
            "context": {"default_instance_id": self.id},
        }

    def _tally_endpoint(self):
        """Resolve the Tally endpoint URL + auth + TLS options for this instance."""
        self.ensure_one()
        base = (self.tally_base_url or "").strip()
        if base:
            url = base.rstrip("/")
        else:
            proto = self.tally_protocol or "http"
            url = "%s://%s:%s" % (proto, self.tally_host or "127.0.0.1", self.tally_port or 9000)
        auth = None
        headers = {}
        if self.auth_type == "basic" and self.auth_username:
            auth = (self.auth_username, self.auth_password or "")
        elif self.auth_type == "header" and self.auth_header_name:
            headers[self.auth_header_name] = self.auth_header_value or ""
        return {"url": url, "auth": auth, "headers": headers, "verify": bool(self.tls_verify)}

    # --------------------------------------------------------------- direct mode
    MAX_QUEUE_ATTEMPTS = 5

    def _set_status(self, ok):
        """Reflect live reachability on the instance for the dashboard."""
        vals = {"state": "online" if ok else "offline"}
        if ok:
            vals["agent_last_seen"] = fields.Datetime.now()
        self.write(vals)

    def _log_outbound(self, item, ok, error=None):
        """Per-record log of an Odoo -> Tally send (gated by verbose_logging)."""
        if not self.verbose_logging:
            return
        name = item.idempotency_key or (item.odoo_model_name or "record")
        try:
            if item.odoo_model_name and item.odoo_res_id:
                rec = self.env[item.odoo_model_name].browse(item.odoo_res_id)
                if rec.exists():
                    name = rec.display_name
        except Exception:
            pass
        self.env["tally.sync.log"].log(
            self, "odoo_to_tally", item.entity,
            "success" if ok else "error",
            (_("Sent %s to Tally") % name) if ok else (_("Failed sending %s to Tally") % name),
            record_name=name, odoo_model_name=item.odoo_model_name,
            odoo_res_id=item.odoo_res_id, detail=error, record_count=1)

    # Masters must exist in Tally before any voucher that references them.
    MASTER_PUSH_ORDER = ["currency", "group", "uom", "stock_group", "godown", "cost_centre",
                         "tax", "account_ledger", "ledger", "stock_item"]
    COLLECTION_FOR_ENTITY = {
        "currency": "Currency", "group": "Group", "uom": "Unit", "stock_group": "StockGroup",
        "godown": "Godown", "cost_centre": "CostCentre", "tax": "Ledger",
        "account_ledger": "Ledger", "ledger": "Ledger", "stock_item": "StockItem",
    }

    def _tally_post(self, xml, timeout=30):
        from ..services import tally_transport
        ep = self._tally_endpoint()
        return tally_transport.post_xml(ep["url"], xml, auth=ep["auth"], extra_headers=ep["headers"],
                                        verify=ep["verify"], timeout=timeout)

    def _tally_export(self, xml, timeout=60):
        from ..services import tally_xml_parser
        return tally_xml_parser.parse_tally_xml_root(self._tally_post(xml, timeout=timeout))

    @staticmethod
    def _payload_remote_ids(payload):
        import re
        return re.findall(r"<GUID>(.*?)</GUID>", payload or "")

    def _identity_pairs(self, items):
        """Group queue items by Tally collection with their identity mappings."""
        Mapping = self.env["tally.mapping"]
        by_collection = {}
        for item in items:
            if not (item.odoo_model_name and item.odoo_res_id):
                continue
            mapping = Mapping.for_record(self, item.entity, item.odoo_model_name, item.odoo_res_id)
            if not mapping:
                continue
            coll = "Voucher" if "<VOUCHER" in (item.payload or "") else self.COLLECTION_FOR_ENTITY.get(item.entity)
            if coll:
                by_collection.setdefault(coll, []).append((item, mapping))
        return by_collection

    def _identity_request(self, coll, pairs, last_vch_id=None):
        """Export request that returns Tally's identity for pushed records."""
        from ..services import tally_xml_builder
        remote_ids = [m.remote_id for _i, m in pairs if m.remote_id]
        master_ids = [m.tally_masterid for _i, m in pairs if m.tally_masterid]
        if coll == "Voucher" and last_vch_id and len(pairs) == 1:
            master_ids.append(last_vch_id)
        if not (remote_ids or master_ids):
            return None
        return tally_xml_builder.build_identity_lookup(
            coll, remote_alt_guids=remote_ids, master_ids=master_ids, company_name=self.tally_company)

    def _apply_identity_response(self, coll, pairs, raw, last_vch_id=None):
        from ..services import tally_xml_parser
        root = tally_xml_parser.parse_tally_xml_root(raw)
        if root is None:
            return
        if coll == "Voucher":
            found = tally_xml_parser.parse_vouchers_from_xml(root)
        else:
            found = []
            for el in root.iter(coll.upper()):
                guid = (el.findtext("GUID") or "").strip()
                if guid:
                    found.append({
                        "name": el.get("NAME") or (el.findtext("NAME") or "").strip(),
                        "guid": guid,
                        "alterid": (el.findtext("ALTERID") or "").strip(),
                        "master_id": (el.findtext("MASTERID") or "").strip(),
                        "remote_alt_guid": (el.findtext("REMOTEALTGUID") or "").strip(),
                    })
        for _item, mapping in pairs:
            candidates = [f for f in found if mapping.remote_id and f.get("remote_alt_guid") == mapping.remote_id]
            if len(candidates) > 1 and mapping.tally_name:
                candidates = [f for f in candidates if f.get("name") == mapping.tally_name] or candidates
            if not candidates and mapping.tally_masterid:
                candidates = [f for f in found if f.get("master_id") == mapping.tally_masterid]
            if not candidates and coll == "Voucher" and last_vch_id and len(pairs) == 1:
                candidates = [f for f in found if f.get("master_id") == str(last_vch_id)]
            if candidates:
                mapping.bind_identity(candidates[0])

    def _bind_identities(self, items, result=None):
        """After Tally accepted ``items``, read back Tally's own identity (GUID,
        MasterID, AlterID, voucher number) and store it on the identity map, so
        the next pull recognises these objects instead of importing them again."""
        last_vch_id = (result or {}).get("last_vch_id")
        for coll, pairs in self._identity_pairs(items).items():
            xml = self._identity_request(coll, pairs, last_vch_id)
            if not xml:
                continue
            try:
                raw = self._tally_post(xml)
            except Exception as e:
                _logger.warning("Identity read-back failed for %s on instance %s: %s", coll, self.id, e)
                continue
            self._apply_identity_response(coll, pairs, raw, last_vch_id)

    def _voucher_address_check(self, item):
        """For a payload addressing a Tally-typed voucher by date + number, return
        ``(verify_request_xml, expected_guid)``; ``(None, None)`` otherwise.

        Tally matches date + number across voucher types, so an Alter/Cancel is
        only safe when exactly one voucher in Tally has that pair and it is the
        linked one.
        """
        import datetime
        import re
        from ..services import tally_xml_builder
        payload = item.payload or ""
        m = re.search(r'<VOUCHER DATE="([^"]+)" TAGNAME="Voucher Number" TAGVALUE="([^"]*)"', payload)
        if not m:
            return None, None
        mapping = self.env["tally.mapping"].for_record(self, item.entity, item.odoo_model_name, item.odoo_res_id)
        day = datetime.datetime.strptime(m.group(1), "%d-%b-%Y").date()
        number = m.group(2).replace("&amp;", "&").replace("&quot;", '"')
        xml = tally_xml_builder.build_voucher_collection_export(
            company_name=self.tally_company, from_date=day, to_date=day,
            formula="$VoucherNumber = %s" % tally_xml_builder.tdl_string(number),
            fetch_fields="GUID,VoucherNumber,VoucherTypeName")
        return xml, mapping.tally_guid

    @staticmethod
    def _voucher_address_ok(raw, expected_guid):
        import re
        guids = re.findall(r"<GUID[^>]*>([^<]+)</GUID>", raw or "")
        return bool(expected_guid) and guids == [expected_guid]

    def _direct_dispatch_queue(self, limit=200, batch_size=25):
        """Push pending outbound (Odoo -> Tally) queue items straight to Tally.

        Masters go first (batched), then vouchers one per request so each result
        can be tied to exactly one Tally voucher. Every accepted item is bound to
        Tally's identity immediately after the import.
        """
        self.ensure_one()
        self._guard_environment()
        if not self.active:
            raise UserError(_("Synchronization is disabled because this database appears to be a copy."))
        import re
        from ..services import tally_transport, tally_xml_builder
        from ..services.tally_transport import TallyTransportError
        Queue = self.env["tally.sync.queue"]
        items = Queue.search([
            ("instance_id", "=", self.id),
            "|", ("state", "=", "pending"),
            "&", ("state", "=", "failed"), ("attempts", "<", self.MAX_QUEUE_ATTEMPTS),
        ], order="create_date, id", limit=limit)
        if not items:
            return True
        contacted = None

        def _messages(xml_text):
            return re.findall(r"(<TALLYMESSAGE[\s\S]*?</TALLYMESSAGE>)", xml_text or "")

        def _fail(item, error):
            if tally_transport.is_educational_date_error(error):
                error = _("%s — TallyPrime Educational only accepts the 1st, 2nd and 31st of a month; "
                          "enable 'Tally Educational Mode' on the instance for test companies.") % error
            item.write({"state": "failed", "attempts": item.attempts + 1, "error": error})
            self._log_outbound(item, False, error=error)

        def _ok(batch, result):
            for it in batch:
                it.write({"state": "acked", "attempts": it.attempts + 1, "error": False})
                self._log_outbound(it, True)
            try:
                self._bind_identities(batch, result)
            except Exception as e:
                _logger.warning("Identity binding failed on instance %s: %s", self.id, e)

        def _post(payload):
            nonlocal contacted
            resp = self._tally_post(payload)
            contacted = True
            return tally_transport.parse_import_response(resp)

        def _single(item):
            payload = item.payload or ""
            if "<VOUCHER" in payload and "<ID>All Masters</ID>" in payload:
                payload = payload.replace("<ID>All Masters</ID>", "<ID>Vouchers</ID>")
            verify_xml, expected = self._voucher_address_check(item)
            if verify_xml:
                try:
                    ok = self._voucher_address_ok(self._tally_post(verify_xml), expected)
                except TallyTransportError:
                    raise
                if not ok:
                    _fail(item, _("Tally has more than one voucher with this date and number (voucher "
                                  "numbers repeat across voucher types), or the linked voucher is gone. "
                                  "Sending would change the wrong voucher, so this edit must be made "
                                  "in Tally."))
                    return
            try:
                result = _post(payload)
            except TallyTransportError as e:
                item.write({"state": "failed", "attempts": item.attempts + 1, "error": str(e)})
                raise
            except Exception as e:
                _fail(item, str(e))
                return
            changed = sum(result.get(k, 0) for k in ("created", "altered", "deleted", "combined", "ignored"))
            if result.get("errors") or result.get("line_error") or not changed:
                _fail(item, result.get("line_error") or _("Ambiguous Tally response: no object count returned"))
            else:
                _ok(item, result)

        masters = items.filtered(lambda i: "<VOUCHER" not in (i.payload or ""))
        order = {e: n for n, e in enumerate(self.MASTER_PUSH_ORDER)}
        masters = masters.sorted(lambda i: (order.get(i.entity, 99), i.create_date or fields.Datetime.now(), i.id))
        vouchers = items - masters

        def _master_key(item):
            m = re.search(r'<(\w+) NAME="([^"]*)"', item.payload or "")
            return (m.group(1), m.group(2).strip().lower()) if m else (item.entity, str(item.id))

        # Tally aborts with an internal error (and stops serving XML until the
        # dialog is closed) when one import creates the same master twice, so a
        # batch never carries two messages for the same Tally name.
        batches, current, seen = [], [], set()
        for item in masters:
            key = _master_key(item)
            if key in seen or len(current) >= batch_size:
                batches.append(current)
                current, seen = [], set()
            current.append(item)
            seen.add(key)
        if current:
            batches.append(current)
        try:
            for batch in batches:
                batch = self.env["tally.sync.queue"].browse([b.id for b in batch])
                messages = [m for it in batch for m in _messages(it.payload)]
                if len(batch) == 1 or not messages:
                    for it in batch:
                        _single(it)
                    continue
                try:
                    result = _post(tally_xml_builder.wrap_import_envelope(
                        messages, company_name=self.tally_company, report_type="All Masters"))
                except TallyTransportError:
                    raise
                except Exception:
                    result = {"errors": 1}
                changed = sum(result.get(k, 0) for k in ("created", "altered", "combined", "ignored"))
                if not result.get("errors") and not result.get("line_error") and changed >= len(messages):
                    _ok(batch, result)
                else:
                    for it in batch:
                        _single(it)
            for item in vouchers:
                _single(item)
        except TallyTransportError:
            contacted = False
        if contacted is not None:
            self._set_status(contacted)
        return True

    def _direct_ping(self):
        """Cheap liveness probe so the dashboard shows true online/offline in direct mode."""
        self.ensure_one()
        from ..services import tally_xml_builder
        try:
            self._tally_post(tally_xml_builder.build_collection_export(
                "Company", company_name=self.tally_company), timeout=8)
            self._set_status(True)
            return True
        except Exception:
            self._set_status(False)
            return False

    # ------------------------------------------------------- Tally structure
    def _get_ledger_index(self):
        import json
        try:
            return json.loads(self.tally_ledger_index or "{}")
        except ValueError:
            return {}

    def _get_voucher_type_parents(self):
        import json
        try:
            return json.loads(self.tally_voucher_type_parents or "{}")
        except ValueError:
            return {}

    def _opening_balance_date(self):
        """Opening balances belong on the first day of the Tally books."""
        return (self.tally_books_from or self.history_from
                or fields.Date.context_today(self))

    STRUCTURE_REQUESTS = ("groups", "ledgers", "voucher_types", "company")

    def _structure_requests(self):
        """Export requests needed to understand the Tally company's structure
        (also sent to the on-prem agent, which relays the raw responses)."""
        from ..services import tally_xml_builder
        company = self.tally_company
        return {
            "groups": tally_xml_builder.build_collection_export("Group", company_name=company),
            "ledgers": tally_xml_builder.build_collection_export("Ledger", company_name=company),
            "voucher_types": tally_xml_builder.build_collection_export(
                "VoucherType", company_name=company, fetch_fields="Name,Parent,GUID"),
            "company": tally_xml_builder.build_collection_export(
                "Company", company_name=company, fetch_fields="Name,BooksFrom,StartingFrom",
                formula=("$Name = %s" % tally_xml_builder.tdl_string(company)) if company else None),
        }

    def _apply_tally_structure(self, responses):
        """Store the ledger classification index, voucher-type hierarchy and
        books-from date. ``responses`` maps request key -> raw Tally XML.
        Returns ``(groups, ledgers, group_tree)``."""
        import json
        from ..services import tally_xml_parser
        parse = tally_xml_parser.parse_tally_xml_root
        groups = tally_xml_parser.parse_groups_from_xml(parse(responses["groups"]))
        tree = tally_xml_parser.build_group_tree(groups)
        ledgers = tally_xml_parser.parse_ledgers_from_xml(parse(responses["ledgers"]))
        index = {}
        for led in ledgers:
            party, tax, chain = tally_xml_parser.classify_ledger(led, tree)
            led["group_chain"] = chain
            index[led["name"].strip().lower()] = {
                "party": party, "tax": tax, "chain": chain, "parent": led.get("parent") or "",
                "reserved": led.get("reserved_name") or ""}
        parents = {}
        if responses.get("voucher_types"):
            for vt in parse(responses["voucher_types"]).iter("VOUCHERTYPE"):
                name = (vt.get("NAME") or vt.findtext("NAME") or "").strip().lower()
                parent = (vt.findtext("PARENT") or "").strip().lower()
                if name and parent and parent != name:
                    parents[name] = parent
        vals = {"tally_ledger_index": json.dumps(index), "tally_voucher_type_parents": json.dumps(parents),
                "tally_group_tree": json.dumps(tree)}
        if responses.get("company"):
            for c in parse(responses["company"]).iter("COMPANY"):
                raw = (c.findtext("BOOKSFROM") or c.findtext("STARTINGFROM") or "").strip()
                parsed = tally_xml_parser._parse_tally_date(raw)
                if parsed and len(parsed) == 10:
                    vals["tally_books_from"] = parsed
                break
        self.write(vals)
        return groups, ledgers, tree

    def _refresh_tally_structure(self):
        """Direct mode: read the company structure from Tally and apply it."""
        responses = {}
        for key, xml in self._structure_requests().items():
            try:
                responses[key] = self._tally_post(xml, timeout=120)
            except Exception as e:
                if key in ("groups", "ledgers"):
                    raise
                _logger.info("Optional Tally structure request %s failed: %s", key, e)
        return self._apply_tally_structure(responses)

    PULL_ORDER = ["currency", "group", "uom", "stock_group", "godown", "cost_centre",
                  "tax", "account_ledger", "ledger", "stock_item", "opening_balance"]
    LEDGER_ENTITIES = ("ledger", "account_ledger", "tax", "opening_balance")
    PULL_VOUCHER_ENTITIES = ("sales", "credit_note", "purchase", "debit_note",
                             "receipt", "payment", "journal", "contra", "stock_journal")

    def _pull_plan(self, include_vouchers=True):
        """Ordered ``[(key, export_xml_or_None)]`` for one pull.

        Group and ledger entities reuse the structure export (``None``); other
        masters need their own collection; vouchers come last from a Voucher
        collection filtered by AlterID (or by date on the first sync).
        """
        from datetime import date, timedelta
        from ..services import tally_xml_builder
        company = self.tally_company
        enabled = {c.entity: c for c in self.entity_config_ids
                   if c.enabled and c.direction in ("tally_to_odoo", "both")}
        plan = []
        for entity in self.PULL_ORDER:
            cfg = enabled.get(entity)
            if not cfg:
                continue
            if entity == "group" or entity in self.LEDGER_ENTITIES:
                plan.append((entity, None))
            else:
                from_aid = cfg.last_alterid if self.use_tdl_delta else None
                plan.append((entity, tally_xml_builder.build_collection_export(
                    tally_xml_builder.COLLECTION_MAP[entity], company_name=company,
                    from_alterid=from_aid)))
        if include_vouchers and self.odoo_role != "operational":
            enabled_v = [c for e, c in enabled.items() if e in self.PULL_VOUCHER_ENTITIES]
            if enabled_v:
                watermark = min(c.last_alterid or 0 for c in enabled_v)
                if watermark:
                    xml = tally_xml_builder.build_voucher_collection_export(
                        company_name=company, from_alterid=watermark)
                else:
                    start = self.history_from or (date.today() - timedelta(days=self.pull_lookback_days or 30))
                    xml = tally_xml_builder.build_voucher_collection_export(
                        company_name=company, from_date=start)
                plan.append(("vouchers", xml))
        return plan

    def _process_pull_step(self, engine, key, raw, groups, ledgers, tree):
        """Parse one export response and feed it to the sync engine."""
        from ..services import tally_xml_parser
        parser_map = {
            "currency": tally_xml_parser.parse_currencies_from_xml,
            "uom": tally_xml_parser.parse_units_from_xml,
            "stock_group": tally_xml_parser.parse_stock_groups_from_xml,
            "stock_item": tally_xml_parser.parse_stock_items_from_xml,
            "cost_centre": tally_xml_parser.parse_cost_centres_from_xml,
            "godown": tally_xml_parser.parse_godowns_from_xml,
        }
        if key == "vouchers":
            vouchers = tally_xml_parser.parse_vouchers_from_xml(
                tally_xml_parser.parse_tally_xml_root(raw))
            # Oldest revision first so Tally's own order of edits is replayed.
            vouchers.sort(key=lambda v: int(v.get("alterid") or 0))
            res = engine.process_vouchers(vouchers) if vouchers else {}
            return sum((r or {}).get("processed", 0) for r in res.values())
        if key == "group":
            records = [dict(g) for g in groups]
        elif key in self.LEDGER_ENTITIES:
            records = tally_xml_parser.filter_ledgers_for_entity([dict(l) for l in ledgers], key, tree)
        else:
            records = parser_map[key](tally_xml_parser.parse_tally_xml_root(raw))
        if not records:
            return 0
        return (engine.process_inbound_batch(key, records) or {}).get("processed", 0)

    def _direct_pull(self, include_vouchers=True):
        """Pull masters and vouchers from Tally (direct mode, no agent)."""
        self.ensure_one()
        self._guard_environment()
        if not self.active:
            raise UserError(_("Synchronization is disabled because this database appears to be a copy."))
        from ..services.sync_engine import SyncEngine
        groups, ledgers, tree = self._refresh_tally_structure()
        engine = SyncEngine(self.env, self)
        pulled = 0
        for key, xml in self._pull_plan(include_vouchers):
            try:
                raw = self._tally_post(xml, timeout=300) if xml else None
                pulled += self._process_pull_step(engine, key, raw, groups, ledgers, tree)
            except Exception as e:
                self.env["tally.sync.log"].log(
                    self, "tally_to_odoo", key if key != "vouchers" else "journal", "error",
                    "Pull failed for %s: %s" % (key, e))
        return pulled

    def _outbound_entities(self):
        return {c.entity for c in self.entity_config_ids
                if c.enabled and c.direction in ("odoo_to_tally", "both")}

    def action_push_existing_odoo_data(self):
        """Queue every existing Odoo master and posted document for Tally.

        For a company that already runs Odoo and is starting (or joining) a
        Tally company. Masters are queued before documents; documents start at
        *History From* when set. Identical re-pushes are skipped, so running it
        twice is harmless.
        """
        self.ensure_one()
        entities = self._outbound_entities()
        env = self.env
        company = self.company_id
        shared = ["|", ("company_id", "=", False), ("company_id", "=", company.id)]
        queued_before = env["tally.sync.queue"].search_count([("instance_id", "=", self.id)])
        if "uom" in entities:
            # Only units products actually use; Odoo ships dozens of unused units.
            env["product.template"].search(shared).uom_id._enqueue_tally_uom()
        if "stock_group" in entities:
            env["product.category"].search([])._enqueue_tally_stock_group()
        if "godown" in entities:
            env["stock.location"].search([("usage", "=", "internal"), ("company_id", "=", company.id)])._enqueue_tally_godown()
        if "cost_centre" in entities:
            env["account.analytic.account"].search(shared)._enqueue_tally_cost_centre()
        if "tax" in entities:
            env["account.tax"].search([("company_id", "=", company.id)])._enqueue_tally_tax()
        if "account_ledger" in entities:
            Account = env["account.account"]
            domain = ([("company_ids", "in", company.ids)] if "company_ids" in Account._fields
                      else [("company_id", "=", company.id)])
            for account in Account.search(domain):
                account._enqueue_tally_account()
        if "ledger" in entities:
            partners = env["res.partner"].search(shared + [
                ("parent_id", "=", False), "|", ("customer_rank", ">", 0), ("supplier_rank", ">", 0)])
            for partner in partners:
                partner._enqueue_tally_party()
        if "stock_item" in entities:
            for template in env["product.template"].search(shared + [("type", "!=", "service")]):
                template._enqueue_tally_product()
        date_domain = [("date", ">=", self.history_from)] if self.history_from else []
        move_types = {"sales": "out_invoice", "credit_note": "out_refund", "purchase": "in_invoice",
                      "debit_note": "in_refund", "journal": "entry"}
        wanted = [mt for ent, mt in move_types.items() if ent in entities]
        if wanted:
            moves = env["account.move"].search([
                ("company_id", "=", company.id), ("state", "=", "posted"),
                ("move_type", "in", wanted)] + date_domain, order="date, id")
            for move in moves:
                move._enqueue_tally_voucher()
        pay_types = [t for ent, t in (("receipt", "inbound"), ("payment", "outbound")) if ent in entities]
        if pay_types:
            payments = env["account.payment"].search([
                ("company_id", "=", company.id), ("state", "not in", ("draft", "cancel")),
                ("payment_type", "in", pay_types)] + date_domain, order="date, id")
            for payment in payments:
                payment._enqueue_tally_payment()
        if "stock_journal" in entities:
            pickings = env["stock.picking"].search([
                ("company_id", "=", company.id), ("state", "=", "done"),
                ("picking_type_id.code", "=", "internal")])
            pickings._enqueue_tally_stock_journal()
        queued = env["tally.sync.queue"].search_count([("instance_id", "=", self.id)]) - queued_before
        msg = _("%s record(s) queued for Tally. They are sent on the next sync (masters first).") % queued
        self.message_post(body=msg)
        return {"type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Odoo data queued"), "message": msg,
                           "type": "success", "sticky": False}}

    def _pull_notification(self, pulled):
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"title": _("Direct pull complete"),
                       "message": _("Pulled / updated %s record(s) from Tally.") % pulled,
                       "type": "success", "sticky": False},
        }

    def action_pull_masters(self):
        """Manual: pull master data from Tally now (direct mode)."""
        self.ensure_one()
        return self._pull_notification(self._direct_pull(include_vouchers=False))

    def action_pull_now(self):
        """Manual: pull masters AND vouchers from Tally now (direct mode)."""
        self.ensure_one()
        return self._pull_notification(self._direct_pull(include_vouchers=True))

    def action_sync_now(self):
        """Manual: push queued changes AND pull from Tally now (direct mode)."""
        self.ensure_one()
        self._direct_dispatch_queue()
        pulled = self._direct_pull(include_vouchers=True)
        self.last_pull = fields.Datetime.now()
        return self._pull_notification(pulled)

    def action_setup_indian_localization(self):
        """Install and configure Indian Localization (l10n_in) and INR currency for this company."""
        self.ensure_one()
        company = self.company_id or self.env.company
        country_in = self.env["res.country"].search([("code", "=", "IN")], limit=1)

        # 1. Activate INR Currency
        Currency = self.env["res.currency"].with_context(active_test=False)
        inr_currency = Currency.search([("name", "=", "INR")], limit=1)
        if inr_currency:
            inr_currency.write({
                "active": True,
                "symbol": "₹",
                "currency_unit_label": "Rupees",
                "currency_subunit_label": "Paise",
                "rounding": 0.01,
                "decimal_places": 2,
            })
        else:
            inr_currency = Currency.create({
                "name": "INR",
                "symbol": "₹",
                "currency_unit_label": "Rupees",
                "currency_subunit_label": "Paise",
                "rounding": 0.01,
                "decimal_places": 2,
                "active": True,
            })

        # 2. Update company country & currency
        comp_vals = {}
        if country_in and company.country_id != country_in:
            comp_vals["country_id"] = country_in.id
        if company.currency_id != inr_currency:
            has_moves = self.env["account.move"].search_count([("company_id", "=", company.id), ("state", "=", "posted")])
            if not has_moves:
                comp_vals["currency_id"] = inr_currency.id

        if comp_vals:
            company.write(comp_vals)

        # 3. Check / Install l10n_in module
        l10n_in_mod = self.env["ir.module.module"].search([("name", "=", "l10n_in")], limit=1)
        installed_l10n = False
        if l10n_in_mod and l10n_in_mod.state != "installed":
            try:
                l10n_in_mod.button_immediate_install()
                installed_l10n = True
            except Exception as e:
                self.env["tally.sync.log"].log(
                    self, False, False, "warning",
                    _("Could not auto-install l10n_in module: %s") % e)

        msg = _("Indian Localization configured · Company: %s · Currency: INR (₹) · Country: India%s") % (
            company.name, " · l10n_in module installed" if installed_l10n else ""
        )
        self.env["tally.sync.log"].log(self, False, False, "success", msg)
        self.message_post(body=msg)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Indian Localization Configured"),
                "message": msg,
                "type": "success",
                "sticky": False,
            },
        }

    def _reconcile_tally_deletions(self, entities=None):
        """Flag Odoo records whose Tally object no longer exists.

        AlterID deltas never report deletions, so the full GUID set of each
        collection is compared with the identity map. Only mappings bound to a
        real Tally GUID are judged; records are flagged (never deleted) for an
        accountant to review.
        """
        self.ensure_one()
        from ..services import tally_xml_builder
        from ..services.sync_engine import SyncEngine
        voucher_entities = sorted(SyncEngine.DOCUMENT_ENTITIES)
        if not entities:
            entities = ["currency", "group", "ledger", "account_ledger", "tax", "stock_item", "uom",
                        "stock_group", "godown", "cost_centre"] + voucher_entities
        collections = {}
        for ent in entities:
            coll = "Voucher" if ent in voucher_entities else self.COLLECTION_FOR_ENTITY.get(ent)
            if coll:
                collections.setdefault(coll, []).append(ent)
        orphan_summary = {}
        for coll, ents in collections.items():
            try:
                root = self._tally_export(tally_xml_builder.build_collection_export(
                    coll, company_name=self.tally_company, fetch_fields="GUID"), timeout=300)
                live = {(el.findtext("GUID") or "").strip() for el in root.iter(coll.upper())}
                live.discard("")
                if not live:
                    self.env["tally.sync.log"].log(
                        self, "tally_to_odoo", False, "warning",
                        _("Deletion reconcile skipped for %s: Tally returned no records (export failed?).") % coll)
                    continue
                mappings = self.env["tally.mapping"].search([
                    ("instance_id", "=", self.id), ("entity", "in", ents),
                    ("tally_guid", "!=", False), ("state", "!=", "orphan"),
                ])
                gone = mappings.filtered(lambda m: m.tally_guid not in live)
                if gone:
                    gone.write({"is_orphan": True, "state": "orphan", "orphan_date": fields.Datetime.now()})
                    for ent in set(gone.mapped("entity")):
                        count = len(gone.filtered(lambda m: m.entity == ent))
                        orphan_summary[ent] = count
                        self.env["tally.sync.log"].log(
                            self, "tally_to_odoo", ent, "warning",
                            _("Deletion Reconcile: %s record(s) no longer exist in Tally.") % count)
                # A record deleted earlier and restored in Tally is active again.
                back = self.env["tally.mapping"].search([
                    ("instance_id", "=", self.id), ("entity", "in", ents),
                    ("state", "=", "orphan"), ("tally_guid", "in", list(live)),
                ])
                back.write({"is_orphan": False, "state": "active", "orphan_date": False})
            except Exception as e:
                _logger.warning("Deletion reconcile failed for %s on instance %s: %s", coll, self.id, e)
        return orphan_summary

    def action_reconcile_deletions(self):
        """Manual trigger for Deletion Reconciliation."""
        self.ensure_one()
        summary = self._reconcile_tally_deletions()
        total_orphans = sum(summary.values())
        if total_orphans > 0:
            return {
                "name": _("Orphaned Records (Deleted in Tally)"),
                "type": "ir.actions.act_window",
                "res_model": "tally.mapping",
                "view_mode": "list,form",
                "domain": [("instance_id", "=", self.id), ("is_orphan", "=", True)],
            }
        else:
            return {
                "type": "ir.actions.client", "tag": "display_notification",
                "params": {"title": _("Reconciliation Complete"),
                           "message": _("All mappings are consistent with Tally. Zero orphan records found."),
                           "type": "success", "sticky": False},
            }

    # ------------------------------------------------------------------ cron
    @api.model
    def _cron_health_check(self):
        """Flag instances offline when the agent heartbeat goes stale."""
        threshold = fields.Datetime.subtract(fields.Datetime.now(), minutes=5)
        stale = self.search([
            ("state", "=", "online"),
            ("agent_last_seen", "<", threshold),
        ])
        stale.write({"state": "offline"})
        return True

    def _guard_environment(self):
        """Staging/DB-copy bleed guard: disable sync if the database was cloned."""
        current = config_param(self.env, "database.uuid")
        for inst in self:
            if not inst.db_uuid:
                inst.db_uuid = current
            elif current and inst.db_uuid != current:
                inst.write({"active": False, "state": "offline"})
                try:
                    inst.message_post(body=_(
                        "Sync auto-disabled: this database appears to be a COPY (uuid changed). "
                        "Re-enable manually only on the intended environment."))
                except Exception:
                    pass
                _logger.warning("Tally instance %s auto-disabled (staging bleed guard: db uuid mismatch).", inst.id)
        return True

    @api.model
    def _cron_direct_sync(self):
        """For every direct-mode instance: push queued changes AND pull from Tally."""
        self.search([("connection_mode", "=", "direct")])._guard_environment()
        instances = self.search([("active", "=", True), ("connection_mode", "=", "direct")])
        now = fields.Datetime.now()
        for inst in instances:
            # Push runs every cron tick (responsive); pull is decoupled + less frequent.
            try:
                inst._direct_ping()
            except Exception as e:
                _logger.warning("Direct ping failed for instance %s: %s", inst.id, e)
            try:
                inst._direct_dispatch_queue()
            except Exception as e:
                _logger.warning("Direct push failed for instance %s: %s", inst.id, e)
            if inst.direct_auto_pull:
                due = (not inst.last_pull) or (
                    (now - inst.last_pull).total_seconds() >= (inst.pull_interval or 15) * 60)
                if due:
                    try:
                        inst._direct_pull(include_vouchers=True)
                        inst.last_pull = now
                    except Exception as e:
                        _logger.warning("Direct pull failed for instance %s: %s", inst.id, e)
        return True

    @api.model
    def _cron_reconcile_deletions(self):
        """Daily cron to reconcile and audit deletions across all direct Tally instances."""
        instances = self.search([("active", "=", True), ("connection_mode", "=", "direct")])
        for inst in instances:
            try:
                inst._reconcile_tally_deletions()
            except Exception as e:
                _logger.warning("Scheduled deletion reconcile failed for instance %s: %s", inst.id, e)
        return True

    @api.model
    def _cron_prune_logs(self):
        """Delete sync logs older than each instance's retention window."""
        Log = self.env["tally.sync.log"]
        for inst in self.search([]):
            days = inst.log_retention_days or 0
            if days <= 0:
                continue
            cutoff = fields.Datetime.subtract(fields.Datetime.now(), days=days)
            old = Log.search([("instance_id", "=", inst.id), ("create_date", "<", cutoff)])
            if old:
                old.unlink()
        return True
