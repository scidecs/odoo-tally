# Product and Marketing Guide

## 1. Product identity

**Product name:** Tally Prime Integration

**Publisher:** Scidecs

**Technical name:** `tally_integration`

**License and price:** Free, LGPL-3

**Commercial model:** Optional paid consultation, implementation, migration, training, support and
custom development

**Release:** Odoo 19

### One-line positioning

A free, transparent and recoverable Odoo 19–TallyPrime synchronization foundation for organizations
that want to keep their existing finance workflow while reducing duplicate entry.

### Short description

Connect supported Odoo accounting and inventory records with TallyPrime using its native XML gateway.
Choose direct or private-LAN agent deployment, define ownership per entity, and operate through a
durable queue, stable mappings, audit logs, and inbound quarantine.

## 2. AIDA messaging framework

### Attention — lead with the operational pain

Your sales, purchase and inventory teams work in Odoo. Your accountants close books in Tally.
Between them sits manual re-entry: slow, hard to audit and easy to mismatch.

Alternative headlines:

- Stop entering the same transaction twice.
- Keep Odoo operations and Tally books connected—with evidence, not guesswork.
- One operational flow. Two trusted systems. Fewer spreadsheet handoffs.

### Interest — explain the mechanism

Scidecs Tally Prime Integration connects Odoo 19 to the native TallyPrime XML gateway. It can move
supported masters, invoices, bills, notes, payments, journals and internal transfers. Each domain
has its own direction and source-of-truth policy, so the connector adapts to the organization's
actual operating model instead of assuming one system always wins.

Two deployment choices cover cloud/routable Tally and private office networks. Stable GUIDs,
content hashes and durable work queues make synchronization inspectable and recoverable.

### Desire — make outcomes concrete

- Reduce duplicate master and voucher entry.
- Keep product, party, GST, rate and warehouse identity aligned.
- Recover supported data into a clean Odoo database from Tally.
- See pending, acknowledged, failed and quarantined work in native Odoo screens.
- Retry a single poison record without replaying all history.
- Protect production Tally from accidental writes by an Odoo database clone.
- Adopt without license cost, source lock-in or a mandatory paid activation.

### Action — responsible conversion

Download the free LGPL module, install it in a test Odoo 19 database and complete the documented UAT
against a backed-up Tally company. Organizations that want accountable mapping, migration, security,
training or cutover support can contact [hello@scidecs.com](mailto:hello@scidecs.com).

## 3. Problems and business impact

| Problem | Operational effect | Connector response |
|---|---|---|
| Duplicate transaction entry | Delay and typing errors | Supported voucher synchronization |
| Separate master maintenance | Wrong GSTIN, ledger, SKU or price | Stable mappings and master synchronization |
| Manual XML export/import | No continuous status or recovery trail | Direct/agent dispatch with queue and logs |
| Sync loops | Repeated or bounced records | Origin/hash echo suppression |
| Duplicate external records | Reconciliation effort | Deterministic GUIDs and idempotency keys |
| One bad source record | Newer data stops indefinitely | Durable inbound quarantine and targeted retry |
| Unclear ownership | Users overwrite one another | Direction and authority per entity |
| Private Tally network | Unsafe public exposure pressure | Outbound-only local agent option |
| Staging restored from production | Test data reaches live books | Database UUID clone guard |
| Proprietary connector lock-in | Cost and dependency | Free LGPL source and documentation |

## 4. Ideal users

- Indian distributors and traders operating in Odoo while accountants retain TallyPrime.
- Odoo Community deployments using Odoo as an operational front office and Tally as the accounting
  book of record.
- Odoo Enterprise deployments needing controlled parallel or transitional accounting data.
- Odoo partners and internal IT teams performing Tally-to-Odoo migration/UAT.
- Multi-company groups with one explicitly bound Tally instance per Odoo company.

Poor fit without additional implementation:

- Companies expecting Odoo MRP/BOM/work orders to synchronize as Tally manufacturing journals.
- Organizations needing statutory IRN/E-Way/GSTR submission from this connector.
- Environments with heavily customized TDL/voucher structures and no budget/time for UAT.
- Users expecting a cloud service to reach an unprotected desktop Tally port directly.

## 5. Evidence-led value proposition

The product story must use evidence already available:

- Clean Odoo 19 install and transactional test result.
- Real TallyPrime import/export rather than only mocked XML.
- 15-product scenario spanning purchase, sale, returns, taxes, payments, journal and godown transfer.
- Fresh-database recovery and repeat-pull idempotency.
- Verified changes in both directions and restoration.
- Dedicated retry/quarantine and operational UI.

Avoid these claims:

- “Works with every Tally database without configuration.”
- “Real-time push from Tally.” Tally inbound is scheduled polling.
- “Complete ERP/MRP synchronization.”
- “Generates or files IRN, E-Way Bill or GSTR.”
- “No duplicates under every custom TDL.”
- “Production proven at 100,000 vouchers” until a published benchmark exists.
- “Official Tally connector” or an affiliation not established by Scidecs.

Approved release statement:

> Live-Tally round trip validated for the documented accounting and inventory scenario; ready for
> controlled customer UAT. Customer configuration, data and volume remain deployment gates.

## 6. Differentiation from publicly listed alternatives

Research date: 2026-09-05. Capabilities below are based only on public Odoo Apps descriptions and
may change. Buyers should verify each current listing and vendor documentation. This is not a claim
about undocumented capabilities or product quality.

| Public listing/category | Publicly described focus | Scidecs positioning difference |
|---|---|---|
| [Webkul Odoo Tally Connector](https://apps.odoo.com/apps/modules/19.0/odoo_tally_connector) | Paid import/export connector; public page highlights XLS export, manual mapping, bill allocation and customer invoices | Free LGPL source; broader explicitly tested voucher/entity boundary; direct plus agent architecture; inbound poison quarantine and disaster-recovery evidence |
| [ProcessDrive Tally→Odoo Sync Middleware](https://apps.odoo.com/apps/modules/19.0/tally_to_odoo_middleware) | Paid assisted migration/middleware with broad one-time migration packages; public page says it is not delivered standalone | Standalone open-source addon; continuous configurable synchronization; service is optional rather than required to obtain code |
| [NEXERP Direct XML Connector](https://apps.odoo.com/apps/modules/19.0/tally_connector_direct) | Paid direct XML auto-sync with contacts, products, invoices/payments, mapping, batch and duplicate handling | Adds private-LAN outbound agent option, explicit per-entity authority, clean-recovery test harness and dedicated inbound quarantine; distributed free |
| Manual XML exporter category | Generates files for a user to import into Tally | Durable delivery status, automatic direct/agent transport and inbound synchronization |
| Tally-style reporting modules | Makes Odoo reports resemble Tally | This project exchanges business data; it does not replace Odoo financial report layouts |

Do not use competitor names in the Odoo Apps `static/description/index.html`; keep this dated market
analysis in repository documentation. Store copy should describe this module on its own merits and
follow Odoo's rule against harming another publisher's reputation.

## 7. Why free

Free distribution is a Scidecs brand and ecosystem strategy:

- Lower the adoption barrier for Odoo/Tally users.
- Make implementation quality auditable.
- Encourage community testing and contributions.
- Demonstrate Scidecs integration capability through working software.
- Build long-term relationships based on expertise and outcomes rather than license lock-in.

The module does not hide essential features behind a paid edition. Revenue comes from optional
professional effort required by real deployments: discovery, mapping, security, migration,
reconciliation, training, support, upgrades and client-specific extensions.

## 8. Buyer journey and calls to action

| Stage | Question | Asset | CTA |
|---|---|---|---|
| Awareness | Why are Odoo and Tally totals drifting? | Problem-led store/GitHub copy | Review supported scope |
| Evaluation | Will it fit our workflow? | Architecture, entity matrix, FAQ | Run readiness checklist |
| Technical validation | Is it safe/recoverable? | Security and test evidence | Install in staging |
| UAT | Does it fit our exact Tally data? | UAT matrix and operations guide | Execute controlled pilot |
| Adoption | Who will map/train/cut over? | Support model | Self-implement or request Scidecs consultation |
| Expansion | What custom workflows are needed? | Technical extension guide | Scope a separate extension |

## 9. Sales qualification questions

1. Which Odoo edition/version and hosting model are used?
2. Which TallyPrime release and company features/custom TDL are used?
3. Which system is the legal accounting book of record?
4. Which records must move in each direction?
5. Is the need continuous synchronization, one-time migration, or both?
6. How many masters/vouchers and how many daily changes?
7. Does Tally maintain inventory and multiple godowns?
8. Which GST, rounding, bank and bill-allocation patterns exist?
9. Can Odoo reach Tally securely, or is an outbound-only agent required?
10. Who owns reconciliation, UAT approval and cutover rollback?

If the answer includes MRP, orders, delivery notes, statutory filing or custom TDL, flag a scope
assessment rather than promising standard support.

## 10. Reusable marketing copy

### 50-word version

Connect Odoo 19 and TallyPrime with a free LGPL connector built for controlled, recoverable data
exchange. Synchronize supported masters, accounting vouchers, GST, payments and internal transfers
through direct or private-LAN agent deployment—with stable identity, audit logs, retries and inbound
quarantine. Customer UAT is required before production.

### 100-word version

Scidecs Tally Prime Integration helps businesses keep Odoo operations and TallyPrime accounting
aligned without paying a connector license. The free Odoo 19 addon supports configurable one-way or
bidirectional synchronization for core masters, invoices, bills, returns, payments, journals,
opening balances and internal transfers. It communicates through Tally's native XML gateway either
directly or through an outbound-only local agent. Stable GUIDs, content hashes, durable queues,
multi-company rules, audit logs and poison-record quarantine make failures visible and recoverable.
The documented release has completed a real Tally round trip and is ready for controlled customer
UAT; optional Scidecs implementation and support are available.

### Elevator pitch

We give the Odoo community the connector code for free. Companies pay Scidecs only when they want
specialists to make their specific Tally data, accounting policy, security and cutover work safely.

## 11. Objection handling

**“If it is free, is it unsupported?”**

The source and community documentation are free. Organizations can self-support or purchase a
defined Scidecs engagement for accountable response, mapping, migration and production assistance.

**“Can you guarantee our customized Tally will work immediately?”**

No responsible connector vendor should promise that without examining the company. The standard
scope is tested; custom TDL, ledgers, fiscal rules and volumes require UAT.

**“Why keep both systems?”**

Some organizations transition gradually or intentionally keep Tally as the finance book while Odoo
runs operations. This connector reduces the handoff cost; it does not prescribe permanent dual use.

**“Is bidirectional always best?”**

No. One owner per high-conflict domain is safer. Bidirectional mode is useful when the organization
has disciplined change ownership and accepts serialized arrival-order behavior.

**“Does this file GST returns?”**

No. It transports supported GST-related master/voucher data. Government submission belongs to the
relevant Odoo localization/provider workflow or Tally process.

## 12. Brand voice

- Confident but evidence-led.
- Technical enough to earn trust; clear enough for finance leaders.
- Transparent about scope and customer responsibilities.
- Never attack competitors or claim undocumented superiority.
- Use “free module; optional paid expertise,” not “free until activation.”
- Use “near-real-time polling,” not “instant Tally events.”
- Use Scidecs consistently as publisher and service provider.
