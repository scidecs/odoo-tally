# -*- coding: utf-8 -*-
import logging
import secrets

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

from .constants import DEFAULT_ENTITIES, direction_for_source


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
        string="Agent Token", copy=False, readonly=True,
        groups="tally_integration.group_tally_manager",
        help="Bearer token the on-prem Sync Agent uses to authenticate. Keep secret.",
    )
    agent_last_seen = fields.Datetime(string="Agent Last Seen", readonly=True)
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
    synced_today = fields.Integer(string="Synced Today", compute="_compute_counts")

    _name_company_uniq = models.Constraint(
        "UNIQUE(name, company_id)",
        "Instance name must be unique per company.",
    )

    def _compute_counts(self):
        mapping = self.env["tally.mapping"]
        log = self.env["tally.sync.log"]
        queue = self.env["tally.sync.queue"]
        for rec in self:
            rec.mapping_count = mapping.search_count([("instance_id", "=", rec.id)])
            rec.log_count = log.search_count([("instance_id", "=", rec.id)])
            rec.queue_pending = queue.search_count(
                [("instance_id", "=", rec.id), ("state", "in", ("pending", "sent"))])
            rec.queue_failed = queue.search_count(
                [("instance_id", "=", rec.id), ("state", "=", "failed")])
            rec.orphan_count = mapping.search_count(
                [("instance_id", "=", rec.id), ("is_orphan", "=", True)])
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

    def _direct_dispatch_queue(self, limit=100, batch_size=25):
        """POST pending/failed outbound (Odoo -> Tally) queue items straight to Tally.

        High throughput batching: Bundles up to `batch_size` TALLYMESSAGE items inside
        a single XML envelope. If the batch succeeds, all items are acknowledged together.
        If a batch fails, it falls back to item-by-item dispatch to isolate individual errors.
        """
        self.ensure_one()
        import re
        from ..services import tally_transport, tally_xml_builder
        from ..services.tally_transport import TallyTransportError
        Queue = self.env["tally.sync.queue"]
        items = Queue.search([
            ("instance_id", "=", self.id),
            "|", ("state", "=", "pending"),
            "&", ("state", "=", "failed"), ("attempts", "<", self.MAX_QUEUE_ATTEMPTS),
        ], order="create_date", limit=limit)
        if not items:
            return True

        ep = self._tally_endpoint()
        contacted = None

        def _extract_messages(xml_text):
            return re.findall(r"(<TALLYMESSAGE[\s\S]*?</TALLYMESSAGE>)", xml_text or "")

        def _detect_report_type(xml_text):
            if "<VOUCHER" in (xml_text or ""):
                return "Vouchers"
            m = re.search(r"<ID>(.*?)</ID>", xml_text or "")
            return m.group(1) if m else "All Masters"

        def _dispatch_single_item(item):
            nonlocal contacted
            try:
                payload = item.payload or ""
                if "<VOUCHER" in payload and "<ID>All Masters</ID>" in payload:
                    payload = payload.replace("<ID>All Masters</ID>", "<ID>Vouchers</ID>")
                resp = tally_transport.post_xml(
                    ep["url"], payload, auth=ep["auth"],
                    extra_headers=ep["headers"], verify=ep["verify"])
                contacted = True
                result = tally_transport.parse_import_response(resp)
                if result["errors"]:
                    item.write({"state": "failed", "attempts": item.attempts + 1,
                                "error": result.get("line_error") or (resp or "")[:2000]})
                    self._log_outbound(item, False, error=result.get("line_error"))
                else:
                    item.write({"state": "acked", "attempts": item.attempts + 1, "error": False})
                    self._log_outbound(item, True)
            except TallyTransportError as e:
                contacted = False
                item.write({"state": "failed", "attempts": item.attempts + 1, "error": str(e)})
                raise
            except Exception as e:
                item.write({"state": "failed", "attempts": item.attempts + 1, "error": str(e)})
                self._log_outbound(item, False, error=str(e))

        # Group items by report_type for batch packaging
        by_report_type = {}
        for item in items:
            rtype = _detect_report_type(item.payload)
            by_report_type.setdefault(rtype, []).append(item)

        for rtype, ritems in by_report_type.items():
            # Chunk items into batches
            for i in range(0, len(ritems), batch_size):
                batch = ritems[i:i + batch_size]
                if len(batch) == 1:
                    try:
                        _dispatch_single_item(batch[0])
                    except TallyTransportError:
                        break
                    continue

                # Batch dispatch (multi-message envelope)
                try:
                    all_messages = []
                    for item in batch:
                        all_messages.extend(_extract_messages(item.payload))

                    if not all_messages:
                        for it in batch:
                            _dispatch_single_item(it)
                        continue

                    batched_xml = tally_xml_builder.wrap_import_envelope(
                        all_messages, company_name=self.tally_company, report_type=rtype)

                    resp = tally_transport.post_xml(
                        ep["url"], batched_xml, auth=ep["auth"],
                        extra_headers=ep["headers"], verify=ep["verify"])
                    contacted = True
                    result = tally_transport.parse_import_response(resp)

                    if result["errors"] == 0 and (result["created"] > 0 or result["altered"] > 0):
                        # Whole batch succeeded!
                        for it in batch:
                            it.write({"state": "acked", "attempts": it.attempts + 1, "error": False})
                            self._log_outbound(it, True)
                    else:
                        # Fallback to single item dispatch to isolate which one had errors
                        for it in batch:
                            _dispatch_single_item(it)
                except TallyTransportError as e:
                    contacted = False
                    for it in batch:
                        it.write({"state": "failed", "attempts": it.attempts + 1, "error": str(e)})
                    break
                except Exception as e:
                    # Fallback on unexpected error
                    for it in batch:
                        try:
                            _dispatch_single_item(it)
                        except Exception:
                            pass

        if contacted is not None:
            self._set_status(contacted)
        return True

    def _direct_ping(self):
        """Cheap liveness probe so the dashboard shows true online/offline in direct mode."""
        self.ensure_one()
        from ..services import tally_transport, tally_xml_builder
        try:
            ep = self._tally_endpoint()
            tally_transport.post_xml(
                ep["url"],
                tally_xml_builder.build_collection_export("Company", company_name=self.tally_company),
                auth=ep["auth"], extra_headers=ep["headers"], verify=ep["verify"], timeout=8)
            self._set_status(True)
            return True
        except Exception:
            self._set_status(False)
            return False

    def _direct_pull(self, include_vouchers=True):
        """Pull masters (and optionally Day Book vouchers) from Tally directly — no agent.

        Idempotent: re-pulling updates existing records via the identity map and is
        echo-suppressed, so a scheduled full pull is safe.
        """
        self.ensure_one()
        from datetime import date, timedelta
        from ..services import tally_transport, tally_xml_builder, tally_xml_parser
        from ..services.sync_engine import SyncEngine
        parser_map = {
            "currency": tally_xml_parser.parse_currencies_from_xml,
            "group": tally_xml_parser.parse_groups_from_xml,
            "account_ledger": tally_xml_parser.parse_ledgers_from_xml,
            "ledger": tally_xml_parser.parse_ledgers_from_xml,
            "uom": tally_xml_parser.parse_units_from_xml,
            "stock_item": tally_xml_parser.parse_stock_items_from_xml,
            "cost_centre": tally_xml_parser.parse_cost_centres_from_xml,
            "godown": tally_xml_parser.parse_godowns_from_xml,
        }
        engine = SyncEngine(self.env, self)
        ep = self._tally_endpoint()
        pulled = 0

        # --- Masters (native collections) ---
        for cfg in self.entity_config_ids.filtered(
                lambda c: c.enabled and c.direction in ("tally_to_odoo", "both")):
            ctype = tally_xml_builder.COLLECTION_MAP.get(cfg.entity)
            pfn = parser_map.get(cfg.entity)
            if not ctype or not pfn:
                continue
            try:
                from_aid = cfg.last_alterid if self.use_tdl_delta else None
                xml = tally_xml_builder.build_collection_export(
                    ctype, company_name=self.tally_company, from_alterid=from_aid)
                resp = tally_transport.post_xml(ep["url"], xml, auth=ep["auth"],
                                                extra_headers=ep["headers"], verify=ep["verify"])
                root = tally_xml_parser.parse_tally_xml_root(resp)
                records = pfn(root) if root is not None else []
                if records:
                    res = engine.process_inbound_batch(cfg.entity, records)
                    pulled += (res or {}).get("processed", 0)
            except Exception as e:
                self.env["tally.sync.log"].log(
                    self, "tally_to_odoo", cfg.entity, "error", "Master pull failed: %s" % e)

        # --- Vouchers (Day Book, date range) ---
        if include_vouchers and self.odoo_role != "operational":
            voucher_codes = {"sales", "credit_note", "purchase", "debit_note",
                             "receipt", "payment", "journal", "contra"}
            enabled_v = self.entity_config_ids.filtered(
                lambda c: c.enabled and c.entity in voucher_codes
                and c.direction in ("tally_to_odoo", "both"))
            if enabled_v:
                to_d = date.today()
                from_d = self.history_from or (to_d - timedelta(days=self.pull_lookback_days or 30))
                try:
                    xml = tally_xml_builder.build_voucher_export(from_d, to_d, company_name=self.tally_company)
                    resp = tally_transport.post_xml(ep["url"], xml, auth=ep["auth"],
                                                    extra_headers=ep["headers"], verify=ep["verify"])
                    root = tally_xml_parser.parse_tally_xml_root(resp)
                    vouchers = tally_xml_parser.parse_vouchers_from_xml(root) if root is not None else []
                    if vouchers:
                        res = engine.process_vouchers(vouchers)
                        pulled += sum((r or {}).get("processed", 0) for r in res.values())
                except Exception as e:
                    self.env["tally.sync.log"].log(
                        self, "tally_to_odoo", "journal", "error", "Voucher pull failed: %s" % e)
        return pulled

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
        """Reconciliation: Identify and flag records deleted directly in Tally.

        Tally's AlterID tracks additions and edits, but never reports deletions.
        This method queries Tally's live collection manifests for mapped masters,
        identifies mappings missing from Tally, and marks them as `is_orphan = True`
        and `state = 'orphan'` without deleting any financial records in Odoo.
        """
        self.ensure_one()
        import xml.etree.ElementTree as ET
        from ..services import tally_transport, tally_xml_builder, tally_xml_parser

        if not entities:
            entities = ["currency", "ledger", "group", "stock_item", "uom", "cost_centre"]

        type_collection_map = {
            "currency": ("Currency", "NAME,GUID,MASTERID,MAILINGNAME"),
            "ledger": ("Ledger", "NAME,GUID,MASTERID"),
            "group": ("Group", "NAME,GUID,MASTERID"),
            "stock_item": ("StockItem", "NAME,GUID,MASTERID"),
            "uom": ("Unit", "NAME,GUID,MASTERID,ORIGINALNAME"),
            "cost_centre": ("CostCentre", "NAME,GUID,MASTERID"),
        }

        ep = self._tally_endpoint()
        orphan_summary = {}

        for ent in entities:
            if ent not in type_collection_map:
                continue
            col_type, fetch_fields = type_collection_map[ent]
            try:
                col_xml = tally_xml_builder.build_collection_export(
                    col_type, company_name=self.tally_company, fetch_fields=fetch_fields)
                resp = tally_transport.post_xml(
                    ep["url"], col_xml, auth=ep["auth"],
                    extra_headers=ep["headers"], verify=ep["verify"])
                root = tally_xml_parser.parse_tally_xml_root(resp)

                # Collect all live identifiers and GUIDs from Tally
                live_ids = set()
                for el in root.iter():
                    if el.tag in ("LEDGER", "GROUP", "STOCKITEM", "UNIT", "COSTCENTRE"):
                        name = el.get("NAME") or (el.findtext("NAME") or "").strip()
                        guid = (el.findtext("GUID") or "").strip()
                        mid = (el.findtext("MASTERID") or "").strip()
                        if name:
                            live_ids.add(name.lower())
                        if guid:
                            live_ids.add(guid.lower())
                        if mid:
                            live_ids.add(mid)

                # Safety: an empty result means the export failed or returned nothing.
                # Never flag orphans on an empty manifest (would delete-flag the whole book).
                if not live_ids:
                    self.env["tally.sync.log"].log(
                        self, "tally_to_odoo", ent, "warning",
                        _("Deletion reconcile skipped for %s: Tally returned no records (export failed?).") % ent)
                    continue

                # Find all active mappings for this entity
                # Only reconcile records that originated in Tally: they carry a real GUID.
                # Odoo-origin mappings use a synthetic "odoo_*" guid and must never be
                # treated as "deleted in Tally".
                mappings = self.env["tally.mapping"].search([
                    ("instance_id", "=", self.id),
                    ("entity", "=", ent),
                    ("state", "!=", "orphan"),
                    ("last_origin", "=", "tally"),
                ])

                orphaned_mappings = []
                for m in mappings:
                    guid = (m.tally_guid or "").lower()
                    mid = str(m.tally_masterid or "")
                    if not guid or guid.startswith("odoo_"):
                        continue  # synthetic id — cannot judge deletion
                    if guid not in live_ids and mid not in live_ids:
                        orphaned_mappings.append(m)

                if orphaned_mappings:
                    orphaned_records = self.env["tally.mapping"].browse([m.id for m in orphaned_mappings])
                    orphaned_records.write({
                        "is_orphan": True,
                        "state": "orphan",
                        "orphan_date": fields.Datetime.now(),
                    })
                    orphan_summary[ent] = len(orphaned_mappings)
                    self.env["tally.sync.log"].log(
                        self, "tally_to_odoo", ent, "warning",
                        _("Deletion Reconcile: Found %s orphaned record(s) deleted in Tally.") % len(orphaned_mappings)
                    )
            except Exception as e:
                _logger.warning("Deletion reconcile failed for entity %s on instance %s: %s", ent, self.id, e)

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

    @api.model
    def _cron_direct_sync(self):
        """For every direct-mode instance: push queued changes AND pull from Tally."""
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
