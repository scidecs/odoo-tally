# Tally Prime Integration (`tally_integration`)

Near-real-time, two-way synchronization between **TallyPrime** and **Odoo 19**
(on Odoo.sh). **Tally is the source of truth by default**, configurable per entity.
Native Odoo UI only — no ad-hoc widgets.

## What's here (scaffold)

- **`tally.instance`** — a Tally connection: endpoint, source-of-truth policy, poll
  interval, agent token/heartbeat, and its per-entity configuration.
- **`tally.entity.config`** — per entity (ledgers, groups, stock items, vouchers…):
  enable, direction, source of truth, AlterID watermark.
- **`tally.mapping`** — identity map (Tally GUID ⇄ Odoo record) with content hash +
  last-origin for echo/loop suppression.
- **`tally.sync.log`** — every operation, with pivot/graph dashboards.
- **`tally.sync.queue`** — outbound Odoo→Tally items with retry/dead-letter.
- **Controllers** `/tally/agent/{heartbeat,pull,push,ack}` — token-authenticated,
  consumed by the on-prem Sync Agent.
- Security groups (User / Administrator), ACLs, multi-company record rules, health cron.

## Architecture

Odoo.sh cannot reach a LAN Tally, so a **thin on-prem Sync Agent** (separate deliverable)
runs beside Tally, makes outbound-only HTTPS to the controllers above, polls Tally's
AlterID for deltas, and writes Odoo-owned records back into Tally via XML import.

## Status

Installable skeleton. Transform / XML build+parse logic is intentionally stubbed
(marked `TODO`) — implemented in phases (masters → vouchers). See project `CLAUDE.md`.

## Install

Add `custom-addons/` to the Odoo addons path, update app list, install
**Tally Prime Integration**. Then: Settings → Tally Integration, or the **Tally Sync**
app menu → Instances → create a connection → *Load Default Entities* → *Generate Agent Token*.
