# Frequently Asked Questions

## Product and commercial model

### What is this module?

It is a free Odoo 19 addon that synchronizes a documented set of accounting and inventory masters
and vouchers with TallyPrime through the native XML gateway.

### Is the module really free?

Yes. The source is distributed under LGPL-3 with no license fee or mandatory activation service.
Scidecs charges only for optional professional services such as assessment, installation, mapping,
migration, training, support and customization.

### Is there a paid edition with essential features hidden?

No. The repository contains the connector, agent, operations UI, tests and documentation. A paid
engagement provides people, responsibility and customer-specific delivery—not a secret code unlock.

### Why does Scidecs provide it free?

To reduce adoption friction, build community trust through visible engineering, and demonstrate
Scidecs integration capability. Organizations with complex deployments can then choose Scidecs for
expert services.

### Is Scidecs or this connector officially affiliated with Tally or Odoo?

It is an independently developed third-party/community connector unless Scidecs separately states a
current verified partnership. Tally/TallyPrime and Odoo trademarks belong to their owners.

## Compatibility and scope

### Which Odoo version is supported?

This release targets Odoo 19. Community and Enterprise code paths are supported. Always run a clean
install and customer regression against the exact Odoo build and other custom modules.

### Does it work on Odoo.sh and on-premise?

Yes, subject to custom-addon installation and network access. Direct mode requires Odoo to reach a
secured Tally gateway. Agent mode is designed for a private Tally LAN.

### Does it work on Odoo Online/SaaS?

Treat Odoo Online eligibility as dependent on Odoo Apps installation policy and the required network
topology. Confirm on a trial database before promising it. Odoo.sh or on-premise provides the most
predictable custom-addon and connectivity control.

### Which Tally versions are supported?

The implementation targets the native TallyPrime XML gateway. Tally configurations vary; validate
the customer's exact release, enabled features and custom TDL during UAT. Tally ERP 9 is not claimed
as a tested release by this Odoo 19 package.

### What master data is supported?

Account groups, general ledgers, parties, currencies, UoMs, stock groups, products/stock items,
godowns, cost centres and percentage tax/GST ledgers within the documented standard structures.

### What transactions are supported?

Opening balances, sales, purchases, credit notes, debit notes, receipts, payments, journals, contras
and internal transfers represented as Tally Stock Journals.

### Are sales orders, purchase orders, deliveries and receipts synchronized?

No. The current standard scope is accounting vouchers and internal Stock Journal transfers, not
Odoo order/procurement logistics documents.

### Does it support MRP or BOMs?

No. Manufacturing orders, BOMs, work centres and manufacturing valuation need a separate feature
module and dedicated mapping/UAT.

### Does it generate IRNs, E-Way Bills or file GSTR returns?

No. It can carry supported accounting/GST data and retain a reference where matching fields exist,
but it does not call government portals or an authorized compliance provider.

### Does it support fixed assets or landed costs?

No. Those are separate Odoo application domains and are not claimed by this connector.

## Direction and business ownership

### Is the synchronization bidirectional?

It can be, per entity. Each entity also supports one-way direction. Bidirectional mode should be
chosen only with an agreed ownership and conflict process.

### What does source of truth mean?

It defines which system's mapped record is allowed to overwrite the other when a change is observed:
Tally, Odoo, Tally-master/read-only, or bidirectional serialized arrival order.

### Does bidirectional mode merge simultaneous edits field by field?

No. The systems do not provide a distributed merge transaction. Changes are serialized by delivery
order and echo suppression. Declare one business owner for records likely to be edited concurrently.

### Can Odoo Community import accounting vouchers?

The module defaults Community to an operational role where Tally keeps the books and inbound
financial vouchers are skipped. A deployment must not pretend Community has Enterprise accounting
features that are not installed.

## Connectivity

### Does Tally push changes instantly to Odoo?

No. Tally's standard XML gateway is polled using AlterID/date windows. “Near real time” means the
configured polling interval, commonly one or two minutes.

### What is direct mode?

Odoo sends XML to and requests XML from a secured reachable Tally gateway. Use it when private
routing, VPN or an authenticated/allow-listed proxy is available.

### What is agent mode?

A small Python process runs near Tally. It accesses Tally locally and makes outbound HTTPS calls to
Odoo for work, deltas and acknowledgements. No inbound public port is required at the customer site.

### Does the agent contain business logic?

No. Transformation and policy remain in the Odoo module. The agent is a network relay and scheduler,
which prevents mapping logic from drifting across installations.

### Can we expose Tally port 9000 directly to the internet?

Do not do that. Use VPN/private routing or an HTTPS authenticated proxy/tunnel with access controls.

### Why does connection testing say company not found?

Confirm Tally is open, the gateway is enabled, and the Odoo `Tally Company` value exactly matches
the open company name.

## Reliability and duplicates

### How are duplicates prevented?

The connector uses stable GUIDs, an identity mapping table, SHA-256 content hashes, origin tracking,
outbound idempotency keys and Tally Create/Alter behavior. Customer UAT must still test custom TDL and
legacy duplicate data.

### What happens when Tally is offline?

Outbound work remains in the Odoo queue as pending/failed rather than blocking the user's Odoo
transaction. Inbound watermarks remain unchanged. Restore connectivity and retry.

### What happens if the agent crashes after downloading work?

Agent-leased work is marked `sent`. A later pull returns leases older than ten minutes to `pending`.

### Can one malformed Tally record stop synchronization forever?

No. It blocks the relevant entity while it is still retryable, protecting against data loss. At the
configured threshold it enters the dedicated inbound quarantine so newer records can progress.

### How do we retry a quarantined record?

Correct the source/mapping, open **Tally Prime → Operations → Inbound Quarantine**, and choose
**Retry on Next Pull**. Only that entity watermark is rewound to `AlterID - 1`.

### Why not always skip the first failure?

That could silently lose a temporary or fixable accounting record. The connector first blocks safe
progress, records repeated evidence, then makes quarantine visible when the threshold is reached.

### Is repeated pull safe?

The design is idempotent and the reference live test repeated the pull without count/quantity drift.
Customer-specific data must repeat the same check before production.

### What protects against a restored staging database writing to production Tally?

The instance binds to Odoo's database UUID. A clone mismatch disables/blocks the integration until
the environment is intentionally configured.

## Accounting and inventory

### Are CGST, SGST and IGST supported?

Standard percentage ledger recognition and invoice tax paths are implemented. Exact ledger names,
mixed rates, place-of-supply behavior and custom structures require customer UAT.

### Are invoices inventory-based or ledger-only?

Both modes are available through the Tally company mode setting. Match it to the target company.

### Are receipts and payments linked to invoices/bills?

Bill-allocation structures are supported for standard references. Validate the customer's allocation
method and legacy outstanding data.

### How are internal warehouse transfers represented?

As a Tally Stock Journal with negative source/consumption IN rows and positive
destination/production OUT rows. Inbound Stock Journals create Odoo internal transfers.

### Why is automated-valuation stock adjustment disabled by default?

Changing physical stock can create valuation entries while opening financial balances may also
carry stock value. The guard prevents accidental double counting until the implementation design
explicitly approves it.

### How are product prices transferred?

Standard cost and selling price use effective-dated Tally lists. SKU is preserved through the
observed compatible mailing-name field; HSN, category, UoM, barcode where available and quantity are
also mapped.

## Installation and operation

### What should synchronize first?

Currency/groups, accounts, parties, UoMs/categories, products, godowns/cost centres/taxes, opening
balances, then chronological transactions.

### Do we need backups?

Yes. Back up both Odoo database/filestore and the Tally company before installation, historical pull,
bulk push, upgrade, source-policy change and cutover.

### Where are errors visible?

Use Outbound Queue, Sync Logs, Identity Mappings and Inbound Quarantine under the Tally Prime menus.

### Can synchronization run automatically?

Yes, after UAT. Direct mode uses Odoo scheduled work; agent mode runs at its configured interval.

### How should we monitor it?

Alert on lost connection/heartbeat, failed or old pending queue items, quarantined records, and an
unexpected absence of successful movements.

## Validation and support

### Has it been tested with live Tally?

Yes. The documented reference scenario covered 15 products, purchases, sales, returns, CGST/SGST,
payments, a journal, internal transfer, clean recovery, repeated pull and edits in both directions.

### Is it production ready?

It is ready for controlled customer UAT/pilot within the documented scope. Production approval
depends on the customer's Tally version/configuration, data, volume, network, security and signed
reconciliation.

### What remains a hardening gate?

Customer real-data UAT, 10,000+ voucher or customer-peak scale testing, multi-day soak, network fault
testing and realistic simultaneous-edit testing.

### What support is included for free?

Public documentation, source, tests and community issue discussion are free. There is no guaranteed
response SLA unless a support engagement is purchased.

### What can Scidecs provide commercially?

Readiness assessment, secure deployment, account/GST mapping, data migration, reconciliation, UAT,
cutover, training, incident support, upgrades and scoped custom features.

### How do we contact Scidecs?

Email [hello@scidecs.com](mailto:hello@scidecs.com) with Odoo/Tally versions, topology, required
entities/directions, volumes, error evidence and the desired outcome. Redact sensitive accounting
data unless a secure exchange channel has been agreed.
