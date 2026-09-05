# Installation and Operations Guide

## 1. Audience

This guide is for Odoo administrators, Tally administrators, implementation consultants, and the
support team responsible for deployment and daily operation.

## 2. Prerequisites

### Odoo

- Odoo 19 Community or Enterprise on Odoo.sh or on-premise.
- Administrative access to install a custom addon.
- PostgreSQL/database backup capability.
- Installed dependencies: Accounting/Invoicing, Discuss, Product, UoM, Inventory and Analytic.
- A test/staging database for first installation.

### Tally

- TallyPrime with the target company open.
- XML/HTTP gateway enabled, normally on port 9000.
- A backed-up test copy or an explicitly disposable test company for UAT.
- Permission to import/export the intended masters and vouchers.
- Exact company name, financial period, inventory mode and relevant GST ledger configuration.

### Network

Choose one topology:

- **Direct:** Odoo can reach a secured Tally gateway URL.
- **Agent:** a Windows/Linux process beside Tally can reach Tally locally and Odoo over HTTPS.

Do not publicly expose raw Tally port 9000.

## 3. Pre-deployment discovery

Record these decisions before installation:

| Question | Required answer |
|---|---|
| Which system owns customer/vendor identity? | Tally, Odoo, or controlled bidirectional |
| Which system owns product identity and price? | Per business policy |
| Which system is the accounting book of record? | Normally Tally or Odoo, explicitly declared |
| Does Tally maintain inventory? | Accounts only or accounts with inventory |
| Is Odoo Community operational-only? | If yes, inbound vouchers remain disabled |
| Are custom voucher types/TDL used? | List and include in UAT |
| What historical period must be imported? | Start/end dates and locked periods |
| Which ledgers represent CGST/SGST/IGST, bank, cash and rounding? | Named mapping sheet |
| What volumes are expected? | Masters/day and vouchers/day/history |
| What is the support/cutover window? | Owners, times and rollback authority |

## 4. Install the addon

1. Copy `tally_integration` into an Odoo custom addons directory.
2. Restart Odoo.
3. Enable developer mode.
4. Update the Apps list.
5. Install **Tally Prime Integration**.
6. Confirm **Tally Prime** appears in the application menu.

For command-line installation:

```bash
odoo-bin -d TARGET_DATABASE -i tally_integration --stop-after-init
```

Always use the target Odoo 19 executable/configuration and back up before an upgrade:

```bash
odoo-bin -d TARGET_DATABASE -u tally_integration --stop-after-init
```

## 5. Configure TallyPrime

1. Open TallyPrime and the intended company.
2. Open connectivity settings.
3. Configure TallyPrime as **Server** or **Both**.
4. Enable the HTTP/XML service on the selected port, normally 9000.
5. Save and restart TallyPrime if required.
6. From the connector host, test that a native XML company export receives a valid envelope.

Tally's exact menus vary by release. Use the current Tally help for that release if labels differ.

## 6. Configure an Odoo instance

Create **Tally Prime → Dashboard & Instances → New**.

### Identity

- Name: an operational label such as `Head Office Tally`.
- Odoo Company: the matching legal entity.
- Tally Company: exact open-company name.

### Connection

- Mode: direct or agent.
- Direct: protocol, host/port or base URL, TLS verification and optional proxy authentication.
- Agent: generate a strong pairing token and store it securely on the agent host.

### Business mode

- Odoo role `full`: accounting vouchers can synchronize both ways as configured.
- Odoo role `operational`: Odoo is a front office and inbound accounting vouchers are refused.
- Tally mode `with_inventory` or `accounts_only`: must match the Tally company.
- Educational mode: enable only for an unlicensed disposable test environment with restricted dates.

### Safety and operations

- Keep automated-valuation stock adjustment off unless the accounting/valuation design explicitly
  proves it will not double count opening value.
- Keep direct auto-pull off during mapping/UAT.
- Choose log verbosity and retention.
- Keep the inbound quarantine threshold at three unless a documented support policy requires another
  positive value.

## 7. Configure entities

Click **Load Default Entities** and review all 20 rows.

For each entity decide:

- Enabled or disabled.
- Direction: Tally→Odoo, Odoo→Tally, or both.
- Source of truth: Tally, Odoo, Tally master, or bidirectional.

Recommended conservative starting point:

- Tally owns account groups, tax ledgers, currencies, opening balances and historical accounting.
- Parties/products/UoMs/categories/godowns may be bidirectional only if both teams follow a clear
  change process.
- Select one owner for high-conflict master fields.
- Enable transaction outbound only after all required master mappings pass.

## 8. Direct mode

1. Configure a protected route from Odoo to Tally.
2. Enter the URL/authentication settings.
3. Click **Test Connection**.
4. Load/review entities.
5. Start with a manual master pull or push.
6. Inspect Sync Logs, Outbound Queue and Identity Mappings.
7. Run the UAT sequence before enabling scheduled direct pull.

## 9. Agent mode

The agent has no third-party Python packages.

```bash
python3 agent/tally_agent.py \
  --odoo-url "https://your-odoo.example.com" \
  --token "YOUR_INSTANCE_TOKEN" \
  --tally-host 127.0.0.1 \
  --tally-port 9000 \
  --interval 30
```

Use environment variables or a protected service configuration where practical. Never commit the
token. Restrict service-file permissions to the operating-system account running the agent.

### Windows service

With Python 3.10+ and NSSM installed:

```powershell
nssm install OdooTallyAgent "C:\Python311\python.exe" "C:\OdooTally\agent\tally_agent.py"
nssm set OdooTallyAgent AppParameters --odoo-url https://your-odoo.example.com --token TOKEN --tally-host 127.0.0.1 --tally-port 9000 --interval 30
nssm start OdooTallyAgent
```

Prefer a protected environment file or service secret manager over exposing the token in process
arguments. Confirm service restart after Windows reboot and after Tally maintenance.

## 10. Initial synchronization order

Use this controlled order:

1. Currency and account groups.
2. General ledgers/accounts.
3. Parties.
4. UoMs and stock groups.
5. Stock items/products.
6. Godowns and cost centres.
7. Tax ledgers.
8. Opening balances.
9. Transactions in chronological batches.

After every phase compare counts, exceptions, balances and sample field values. Do not proceed merely
because transport returned HTTP 200.

## 11. UAT workflow

Minimum functional UAT:

1. Create representative masters in the declared source system.
2. Synchronize and compare identity, tax and hierarchy fields.
3. Create purchase, sale, both returns, receipt, payment, journal, contra and internal transfer.
4. Compare untaxed, tax, total, quantity and godown values.
5. Pull again and confirm counts/totals do not change.
6. Edit one mapped product in Tally and verify Odoo.
7. Edit a different mapped product in Odoo and verify Tally.
8. Simulate gateway downtime; verify outbound durability and recovery.
9. Inject or locate one bad inbound record; verify quarantine and targeted retry.
10. Restore from backup/fresh Odoo database and verify recoverable scope where migration is required.

Use the formal criteria in [Testing and Validation](TESTING_AND_VALIDATION.md).

## 12. Daily operations

### Dashboard

Check:

- Connection/agent health.
- Pending and failed outbound queue.
- Quarantined inbound records.
- Sync errors and last successful movement.
- Unexpected mapping/orphan growth.

### Outbound failure

1. Open the failed queue item.
2. Read Tally's error and inspect the related Odoo record.
3. Correct the dependency, mapping, closed period, date, unit or ledger.
4. Retry the item.
5. Confirm `acked` and validate the business record in Tally.

### Inbound quarantine

1. Open **Operations → Inbound Quarantine**.
2. Inspect entity, GUID, AlterID, payload and error.
3. Correct the Tally record or connector mapping.
4. Click **Retry on Next Pull**.
5. The entity watermark rewinds to `AlterID - 1`.
6. Run pull and confirm resolution before closing the incident.

**Mark Resolved** documents an operator decision; **Quarantine** intentionally skips a revision.
Use these only with an auditable business explanation.

## 13. Backup and rollback

Before initial migration, bulk replay, module upgrade or source-policy change:

- Back up PostgreSQL and the Odoo filestore together.
- Back up the Tally company.
- Record instance/entity configuration and current watermarks.
- Stop scheduled synchronization during restore/cutover.

Rollback procedure:

1. Stop Odoo synchronization/agent service.
2. Preserve current logs/queue evidence.
3. Restore the approved Odoo and Tally backups as a coordinated pair when both were mutated.
4. Verify the restored database UUID guard and active-instance state.
5. Reconcile records created outside the rollback window.
6. Re-enable one direction at a time after approval.

Never reset every watermark to zero in production without estimating replay volume and duplication
risk. Prefer targeted entity/revision recovery.

## 14. Monitoring and alerting recommendations

At minimum alert on:

- Tally/agent unavailable beyond the agreed interval.
- Failed queue count greater than zero.
- Quarantined record count greater than zero.
- No successful movements during an expected business period.
- Pending queue age above SLA.
- Sudden mapping or voucher-count deviation.

The module provides operational records; external notification integration is deployment-specific.

## 15. Upgrade procedure

1. Review changelog/release report and database schema changes.
2. Back up Odoo and Tally.
3. Disable schedules and stop agent.
4. Update code in staging.
5. Run stage checks and clean registry/module upgrade.
6. Run customer regression/UAT.
7. Upgrade production with `-u tally_integration`.
8. Verify instance config, ACLs, queue and quarantine.
9. Resume agent/schedules and monitor the first complete cycle.

## 16. Decommissioning

1. Disable schedules and agent.
2. Archive/deactivate the instance.
3. Export audit evidence required by policy.
4. Uninstall only after confirming what Odoo will remove and retaining backups.
5. Revoke agent token and network access.

Do not delete Tally or Odoo business records merely because the synchronization component is removed.
