# Technical Reference

## 1. Module metadata

| Item | Value |
|---|---|
| Technical name | `tally_integration` |
| Odoo version | 19.0 |
| License | LGPL-3 |
| Maintainer | Scidecs |
| Python dependencies | Odoo and Python standard library only |
| Odoo dependencies | `base`, `mail`, `account`, `uom`, `product`, `stock`, `analytic` |
| Transport | Tally XML over HTTP/HTTPS; JSON-RPC between optional agent and Odoo |

The manifest description is reStructuredText because that is Odoo's manifest contract. The Odoo
Apps product page is `tally_integration/static/description/index.html`; repository guidance is in
Markdown under `Docs/`.

## 2. Source layout

```text
tally_integration/
  controllers/       agent-facing JSON-RPC endpoints
  data/              cron and seeded account-type mappings
  models/            configuration, queue, mapping, log, quarantine and Odoo hooks
  security/          groups, ACLs and multi-company record rules
  services/          transport, XML build/parse and synchronization engine
  static/description Odoo Apps listing assets
  tests/              Odoo TransactionCase regressions
  views/              native Odoo list/form/search/graph/pivot views
  wizard/             onboarding workflow
agent/                optional standard-library local relay
scripts/              stage checks and controlled live test utilities
tests/                standalone XML transformation tests
Docs/                 architecture, operations, marketing and support documentation
```

## 3. Entity registry

| Key | Odoo model | Typical Tally object/voucher | Default authority |
|---|---|---|---|
| `group` | `account.group` | Group | Tally |
| `account_ledger` | `account.account` | Ledger | Tally |
| `ledger` | `res.partner` | Party ledger | Bidirectional |
| `uom` | `uom.uom` | Unit | Bidirectional |
| `stock_group` | `product.category` | Stock Group | Bidirectional |
| `stock_item` | `product.product` | Stock Item | Bidirectional |
| `godown` | `stock.location` | Godown | Bidirectional |
| `cost_centre` | `account.analytic.account` | Cost Centre | Bidirectional |
| `tax` | `account.tax` | Duties & Taxes ledger | Tally |
| `currency` | `res.currency` | Currency | Tally |
| `opening_balance` | `account.move` | Ledger opening balance | Tally |
| `sales` | `account.move` | Sales | Tally |
| `credit_note` | `account.move` | Credit Note | Tally |
| `purchase` | `account.move` | Purchase | Tally |
| `debit_note` | `account.move` | Debit Note | Tally |
| `receipt` | `account.payment` | Receipt | Tally |
| `payment` | `account.payment` | Payment | Tally |
| `journal` | `account.move` | Journal | Tally |
| `contra` | `account.move` | Contra | Tally |
| `stock_journal` | `stock.picking` | Stock Journal | Tally |

Defaults are starting points. Direction and authority must be reviewed during implementation.

## 4. Core models

### `tally.instance`

One integration endpoint and Tally company binding for one Odoo company. Important groups of fields:

- Connection: mode, protocol, host, port/base URL, TLS verification, authentication and company.
- Behavior: Odoo role, Tally inventory mode, default source, polling interval, direct pull, auto-post,
  delta mode, lookback/history dates and educational-mode dates.
- Safety: active state, company uniqueness, database UUID and agent token.
- Operations: log retention, verbose logging, automated-valuation stock guard and quarantine threshold.
- KPIs: mappings, logs, pending/failed queue, orphans, quarantined records and today's activity.

Only one active instance is permitted per Odoo company to avoid ambiguous outbound routing.

### `tally.entity.config`

Stores one row per instance/entity with:

- `enabled`
- `direction`: `tally_to_odoo`, `odoo_to_tally`, `both`
- `source_of_truth`: `tally`, `odoo`, `tally_master`, `bidirectional`
- `last_alterid` and `last_sync`
- processing `sequence`

The unique constraint is `(instance_id, entity)`.

### `tally.mapping`

Maps `(instance, entity, tally_guid)` to an Odoo model/id. `content_hash`, `last_origin`, and
`last_sync` implement echo/repeat suppression. Orphan fields support deletion reconciliation.

### `tally.sync.queue`

Stores outbound XML and delivery state:

- Identity: instance, company, entity, Odoo model/id, idempotency key.
- Payload: complete Tally import envelope.
- State: `pending`, `sent`, `acked`, `failed`.
- Operations: attempts, last error, agent lease timestamp and retry action.

### `tally.inbound.dead.letter`

Stores a failed inbound record revision:

- Identity: instance/company, entity, stable record key, GUID and AlterID.
- Evidence: normalized JSON payload, SHA-256 payload hash and last error.
- Lifecycle: attempts, `pending`/`quarantined`/`resolved`, first/last failure and resolution time.
- Actions: retry, quarantine and resolve.

The revision uniqueness key is `(instance_id, entity, record_key, tally_alterid)`.

### `tally.sync.log`

Provides direction/entity/status/message/detail, related Odoo record, Tally GUID, and movement count.
Verbose mode writes per-record movements; compact mode writes batch summaries. Retention is
configurable on the instance.

### Supporting models

- `tally.account.type.map`: editable Tally group to Odoo account-type mapping.
- `tally.discovered.company`: companies observed by the optional agent.
- `tally.onboarding`: initial import/mapping workflow.

## 5. Standard Odoo hooks

| Odoo model | Outbound entity/event |
|---|---|
| `res.partner` | Customer/vendor ledger create/write |
| `account.account` | General ledger create/write |
| `product.template` / `product.product` | Stock item create/write with canonical variant identity |
| `uom.uom` | Unit create/write |
| `product.category` | Stock group create/write |
| `stock.location` | Internal godown create/write |
| `account.analytic.account` | Cost centre create/write |
| `account.tax` | Percentage tax ledger create/write |
| `account.move` | Supported invoice/note/journal posting |
| `account.payment` | Receipt/payment posting |
| `stock.picking` | Completed internal transfer |

All hooks check `tally_no_sync`, instance/company eligibility, entity direction and ownership. They
catch connector exceptions so remote availability does not invalidate the original business write.

## 6. Agent API

All routes are public JSON-RPC endpoints authenticated with `X-Tally-Token`. The token maps to one
active instance and the database-environment guard is enforced.

| Route | Direction | Purpose |
|---|---|---|
| `/tally/agent/heartbeat` | Agent → Odoo | Health update; returns interval, company and inbound watermarks |
| `/tally/agent/companies` | Agent → Odoo | Reports up to 200 visible Tally companies |
| `/tally/agent/pull` | Agent ← Odoo | Leases 1–200 pending outbound queue items |
| `/tally/agent/push` | Agent → Odoo | Sends raw XML or up to 5,000 parsed inbound records |
| `/tally/agent/ack` | Agent → Odoo | Marks leased items acknowledged or failed |

Tokens must be treated as secrets and used only over HTTPS outside localhost.

## 7. Tally XML contracts

### Import envelope

Builders wrap one or more `<TALLYMESSAGE>` nodes in an import envelope with
`SVCURRENTCOMPANY`. Masters use `All Masters`; vouchers use `Vouchers`.

### Export requests

Native collections export masters. Voucher history uses a Day Book request bounded by date. When
enabled, AlterID provides incremental master progress. Tally has no native push event, so inbound
“near real time” is polling.

### Product identity and rates

- `GUID` is the stable external identity.
- Odoo SKU is transported through `MAILINGNAME` for compatibility with observed Tally exports.
- HSN uses `HSNCODE`/description fallback.
- Standard cost and price list entries include an effective `DATE` in `YYYYMMDD` format.
- Zero `CLOSINGBALANCE` is a real value, not a signal to reuse opening stock.

### Inventory invoices

Invoice-view vouchers use `LEDGERENTRIES.LIST` and `ALLINVENTORYENTRIES.LIST`, inventory
`ACCOUNTINGALLOCATIONS.LIST`, party/bill allocations, tax ledgers, balanced signs, and destination
godown fields.

### Stock Journal

Tally's native convention is:

- `INVENTORYENTRIESIN.LIST`: source/consumption, negative amount.
- `INVENTORYENTRIESOUT.LIST`: destination/production, positive amount.

The parser converts IN quantities to negative and OUT quantities to positive for the Odoo internal
transfer upsert.

### XML safety

Text and attribute values are escaped. The parser removes invalid control-character numeric
entities sometimes emitted by Tally before XML parsing.

## 8. Inbound processing algorithm

For every record:

1. Reject the batch if the entity is disabled/not inbound eligible.
2. Skip a record at or below the starting watermark.
3. Skip and count an already quarantined revision.
4. Calculate the normalized payload hash and locate the GUID mapping.
5. Consume an Odoo-origin read-back as an acknowledgement, or observe without overwrite when Odoo
   is authoritative.
6. Otherwise run the entity upsert inside a savepoint.
7. Update mapping, optionally post, resolve previous failures, and log success.
8. On exception, record/increment the dead letter. A retryable failure blocks watermark progress;
   a threshold failure is quarantined and no longer blocks it.
9. Advance the entity watermark only when no retryable error remains.

## 9. Outbound dependency ordering

Vouchers proactively enqueue referenced masters so a newly configured Tally company receives
dependencies before the transaction. Invoice dependencies include accounts, party, products and
taxes. Payments include party and bank/cash account. Stock Journals include both godowns and products.

The queue is ordered by creation time. Tally still remains responsible for its own validation; a
failed dependency is visible and retriable.

## 10. Multi-company and security

Groups:

- Tally User: read operational records.
- Tally Manager: configure instances and mutate queue/quarantine operations.

Global record rules restrict company-bound models to `company_ids`. Agent routes use `sudo()` only
after token authentication and instance/environment validation.

See [Security](SECURITY.md) for network and threat controls.

## 11. Developer setup and tests

Set portable paths instead of editing scripts:

```bash
export ODOO_SRC=/path/to/odoo-src
python3 scripts/run_stage_checks.sh
python3 -m pytest -q tests
```

For Odoo transactional tests, use a disposable database and the target Odoo 19 runtime. The exact
reference command and live-test safety rules are in [Testing and Validation](TESTING_AND_VALIDATION.md).

## 12. Adding an entity

1. Add it to `ENTITY_SELECTION` and `DEFAULT_ENTITIES`.
2. Add collection/export support if inbound.
3. Add parser tests using representative native Tally XML.
4. Add XML builder tests if outbound.
5. Register the upsert handler in `SyncEngine.process_inbound_batch()`.
6. Implement matching through `tally.mapping`.
7. Add a guarded Odoo lifecycle hook if outbound.
8. Add access/view changes only for new user-facing models.
9. Add clean-install and live UAT cases.
10. Update every scope table and explicitly state exclusions.

Do not add marketing claims before the test and implementation exist.
