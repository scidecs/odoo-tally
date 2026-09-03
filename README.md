# Tally Prime ⇄ Odoo 19 Integration (`tally_integration`)

[![Odoo Version](https://img.shields.io/badge/Odoo-19.0-875A7B.svg)](https://www.odoo.com/)
[![License: LGPL-3](https://img.shields.io/badge/License-LGPL--3-blue.svg)](https://www.gnu.org/licenses/lgpl-3.0)
[![Vendor](https://img.shields.io/badge/Vendor-Scidecs-green.svg)](https://www.scidecs.com)

A native Odoo 19 App-Store-grade module for near-real-time, two-way synchronization between **TallyPrime** and **Odoo 19** (Enterprise / Community / Odoo.sh / On-Premise).

Developed and maintained by **[Scidecs](https://www.scidecs.com)**.

---

## Table of Contents
1. [Architecture Overview](#1-architecture-overview)
2. [Step-by-Step Setup Guide](#2-step-by-step-setup-guide)
   - [Step 1: Install Odoo Module](#step-1-install-odoo-module)
   - [Step 2: Configure TallyPrime Gateway & Credentials](#step-2-configure-tallyprime-gateway--credentials)
   - [Step 3: Configure Tally Instance in Odoo UI](#step-3-configure-tally-instance-in-odoo-ui)
   - [Step 4: Run the On-Premise Sync Agent](#step-4-run-the-on-premise-sync-agent)
3. [Deployment Scenarios](#3-deployment-scenarios)
   - [Scenario A: Odoo Enterprise (Full Accounting / Two-Way)](#scenario-a-odoo-enterprise-full-accounting--two-way)
   - [Scenario B: Odoo Community (Operational Front-Office → Tally Books)](#scenario-b-odoo-community-operational-front-office--tally-books)
   - [Scenario C: Greenfield Migration & Initial Onboarding](#scenario-c-greenfield-migration--initial-onboarding)
   - [Scenario D: Map to Existing Odoo Chart of Accounts](#scenario-d-map-to-existing-odoo-chart-of-accounts)
4. [Entity & Table Mapping Reference](#4-entity--table-mapping-reference)
5. [Source of Truth, Conflict Resolution & Echo Suppression](#5-source-of-truth-conflict-resolution--echo-suppression)
6. [Troubleshooting & FAQ](#6-troubleshooting--faq)
7. [Git Branches & Odoo App Store Compatibility](#7-git-branches--odoo-app-store-compatibility)

---

## 1. Architecture Overview

```
+-------------------------------------------------------------------+
|                        CLOUD / ODOO.SH                            |
|                                                                   |
|   +-----------------------------------------------------------+   |
|   |             Odoo 19 (Module: tally_integration)           |   |
|   |  - Controllers: /tally/agent/{heartbeat,companies,push..} |   |
|   |  - Identity Mapping Registry: tally.mapping               |   |
|   |  - Sync Queue & Dashboards: tally.sync.queue / log        |   |
|   |  - Sync Engine & XML Builders/Parsers                     |   |
|   +-----------------------------------------------------------+   |
+---------------------------------^---------------------------------+
                                  |
              Outbound HTTPS Only | (Bearer Token Authentication)
                                  |
+---------------------------------v---------------------------------+
|                    ON-PREMISE LOCAL NETWORK                       |
|                                                                   |
|   +--------------------------+     HTTP XML      +------------+   |
|   |  On-Premise Sync Agent   | ----------------> | TallyPrime |   |
|   |  (Python Service / NSSM) | <---------------- | (Port 9000)|   |
|   +--------------------------+   (Port 9000/TCP) +------------+   |
|                                                                   |
+-------------------------------------------------------------------+
```

### Key Architectural Advantages
1. **Zero Client Disruption & Zero TDL Code**:
   - No custom plugins, third-party software, or TDL (Tally Definition Language) code needed in Tally.
   - Uses TallyPrime's built-in native XML server.
   - Accountants continue working in Tally normally without changing habits.
2. **Offline Resilience & Store-and-Forward Buffering**:
   - **When the desktop is switched off or internet is down**: Sales, purchases, invoices, and payments created in Odoo are safely queued in PostgreSQL (`tally.sync.queue` with status `pending`).
   - **When the computer is powered on**: The on-premise agent connects to Odoo, fetches the backlog in chronological sequence, and pushes it into Tally.
   - **In reverse (Tally → Odoo)**: If vouchers are entered in Tally while offline, Tally's internal `ALTERID` watermark tracks the delta. As soon as the agent reconnects, all new entries are pulled into Odoo automatically.
3. **Zero Firewall & Network Headaches**:
   - Tally stays behind the office router without public IP exposure or port-forwarding. The agent communicates via outbound HTTPS to Odoo.
4. **Non-Invasive to Odoo**:
   - No custom columns or monkey-patching on core Odoo models (`res.partner`, `account.move`, etc.). Identity mappings live in `tally.mapping`. Outbound hooks are wrapped in defensive `try...except` so Tally errors never interrupt other custom modules.

---

## 2. Step-by-Step Setup Guide

### Step 1: Install Odoo Module
1. Place the `tally_integration` directory inside your custom addons path.
2. In Odoo, activate **Developer Mode** (Settings -> Activate developer mode).
3. Go to **Apps** -> Click **Update Apps List**.
4. Search for `Tally Prime Integration` and click **Install**.

---

### Step 2: Configure TallyPrime Gateway & Credentials

TallyPrime acts as an XML Server listening on a local port (default: `9000`).

#### 1. Enable XML Gateway in TallyPrime:
1. Open **TallyPrime** (run as Administrator if needed).
2. Press **`F1: Help`** (top right) -> Select **Settings** -> Select **Connectivity**.
3. In the **Connectivity Settings** screen:
   - **TallyPrime acts as**: Set to `Both` (or `Server`).
   - **Enable ODBC**: Set to `Yes`.
   - **Port**: Set to `9000` (or your preferred port).
4. Press **`Ctrl + A`** to save.
5. **Restart TallyPrime** for connectivity changes to take effect.

#### 2. Open the Company:
- Ensure the company you wish to sync is **open and loaded** in TallyPrime.
- Note the exact company name as shown in the top-left title bar (e.g. `Acme Enterprises Pvt Ltd`).

#### 3. Tally Credentials & Security:
- If Tally Vault / Security is enabled on your company, ensure the user credentials have data export/import permissions.

---

### Step 3: Configure Tally Instance in Odoo UI

1. In Odoo, navigate to **Invoicing** (or **Accounting**) -> **Configuration** -> **Tally Integration** -> **Instances**.
2. Click **New** and fill in the configuration:
   - **Name**: e.g., `Head Office Tally`.
   - **Company**: Select the matching Odoo company.
   - **Tally Host**: `127.0.0.1` (from the local agent's perspective).
   - **Tally Port**: `9000`.
   - **Tally Company**: Enter the exact company name open in TallyPrime.
   - **Default Source of Truth**:
     - `Tally (accounting system)` *(Recommended)*: Tally wins conflicts; changes in Tally update Odoo.
     - `Odoo`: Odoo wins conflicts; changes in Odoo update Tally.
   - **Tally Mode (`tally_inventory`)**:
     - `Accounts with Inventory`: Standard stock items + ledger vouchers.
     - `Accounts only`: Ledger-only vouchers (disables item lines for non-inventory companies).
   - **Odoo Role (`odoo_role`)**:
     - `Full (Two-Way)`: Recommended for Enterprise with full accounting.
     - `Operational (Odoo → Tally)`: Recommended for Community (Odoo handles front-office sales/invoicing and pushes financial data to Tally).
   - **Poll Interval (s)**: `60` (agent checks Tally for changes every 60 seconds).
3. Click **Generate Token** under the **Agent Pairing** tab. Copy this bearer token.
4. Click **Load Default Entities** (top button) to automatically register all master and voucher sync rules.

---

### Step 4: Run the On-Premise Sync Agent

The standalone Python agent runs on the local Windows PC or server where Tally is located.

#### 1. Setup Environment:
```bash
# Clone or copy the agent directory to the local Windows machine
git clone https://github.com/scidecs/odoo-tally.git
cd odoo-tally/agent

# Install dependencies (Python 3.8+)
pip install requests
```

#### 2. Configure Credentials:
Create `agent.conf` or set environment variables:
```ini
[odoo]
url = https://your-odoo-instance.com
token = <PASTE_GENERATED_AGENT_TOKEN_HERE>

[tally]
host = 127.0.0.1
port = 9000
company = Acme Enterprises Pvt Ltd

[sync]
poll_interval = 60
batch_size = 100
```

#### 3. Start Agent:
```bash
python tally_agent.py
```

#### 4. Run as a Windows Service (Production):
To ensure 24/7 continuous synchronization on Windows, use [NSSM (Non-Sucking Service Manager)](https://nssm.cc/):
```powershell
nssm install OdooTallyAgent "C:\Python311\python.exe" "C:\OdooTally\agent\tally_agent.py"
nssm start OdooTallyAgent
```

---

## 3. Deployment Scenarios

### Scenario A: Odoo Enterprise (Full Accounting / Two-Way)
- **Target Audience**: Organizations using Odoo Enterprise with full double-entry accounting where Tally is either the legacy system or parallel audit system.
- **Configuration**:
  - `Odoo Role`: `Full (Two-Way)`
  - `Default Source of Truth`: `Tally` (or `Odoo` depending on workflow preference)
- **Sync Behavior**:
  - Masters created in Tally pull automatically into Odoo.
  - Invoices and Receipts posted in Odoo push to Tally.
  - Vouchers entered in Tally pull into Odoo draft/posted entries.
  - SHA-256 echo suppression prevents loopback re-imports.

### Scenario B: Odoo Community (Operational Front-Office → Tally Books)
- **Target Audience**: Businesses running Odoo Community for CRM, Sales, Inventory, and Purchase, while relying on Tally for statutory accounting, GST return filing, and balance sheets.
- **Configuration**:
  - `Odoo Role`: `Operational (Odoo → Tally)`
- **Sync Behavior**:
  - Sales Invoices, Customer Receipts, Purchase Bills, and Vendor Payments posted in Odoo are automatically queued and pushed to Tally.
  - Inbound voucher import is disabled to avoid cluttering Community with raw journal entries.
  - Party master records stay synchronized across both systems.

### Scenario C: Greenfield Migration & Initial Onboarding
- **Target Audience**: New Odoo installations migrating master records and transaction history from an established Tally instance.
- **Configuration**:
  - Open Instance -> Click **Tally Onboarding** button.
  - Set **Chart of Accounts Mode**: `Import CoA from Tally`.
  - Set **History From**: e.g., `2024-04-01` (start of financial year).
  - Click **Start Initial Sync**. The agent will pull all Groups, Ledgers, Products, UoMs, opening balances, and past vouchers.

### Scenario D: Map to Existing Odoo Chart of Accounts
- **Target Audience**: Odoo databases that already have a standardized Chart of Accounts (e.g. Indian localization `l10n_in`).
- **Configuration**:
  - In Instance, set **Chart of Accounts Mode**: `Map to existing Odoo CoA`.
  - Open **Configuration** -> **Account Type Mappings** (`tally.account.type.map`).
  - Configure how Tally groups (e.g. `Sundry Debtors`, `Bank Accounts`, `Direct Incomes`, `Indirect Expenses`) map to Odoo `account_type` values (`asset_receivable`, `asset_cash`, `income`, `expense`).

---

## 4. Entity & Table Mapping Reference

Every entity can be individually enabled/disabled with independent directional control (**Tally to Odoo**, **Odoo to Tally**, or **Both**).

### Masters Mapping Table

| Entity Key | Odoo Model | Tally Tag / Object | Direction Options | Key Mapped Attributes |
| :--- | :--- | :--- | :--- | :--- |
| `group` | `account.group` | `<GROUP>` | Tally → Odoo | Group Name, Parent Group hierarchy |
| `account_ledger` | `account.account` | `<LEDGER>` (General) | Both / Directional | Name, Code, Account Type, Currency |
| `ledger` | `res.partner` | `<LEDGER>` (Party) | Both / Directional | Name, GSTIN, PAN, Address, State, PIN, Phone, Email, Credit Limit |
| `uom` | `uom.uom` | `<UNIT>` | Tally → Odoo | Unit Name, Symbol, Decimal Places |
| `stock_group` | `product.category` | `<STOCKGROUP>` | Tally → Odoo | Category Name, Parent Category |
| `stock_item` | `product.product` | `<STOCKITEM>` | Both / Directional | Name, Base UoM, Category, HSN Code, Cost Price, Sale Price |
| `cost_centre` | `account.analytic.account` | `<COSTCENTRE>` | Tally → Odoo | Cost Centre Name, Analytic Plan |
| `godown` | `stock.location` | `<GODOWN>` | Tally → Odoo | Location Name, Parent Location |
| `tax` | `account.tax` | `<LEDGER>` (Duties/Taxes) | Tally → Odoo | Tax Name, Rate of Tax (%), Tax Type |

### Vouchers / Transactions Mapping Table

| Entity Key | Odoo Model (`move_type` / `payment_type`) | Tally Voucher Type | Direction Options | Key Mapped Attributes |
| :--- | :--- | :--- | :--- | :--- |
| `sales` | `account.move` (`out_invoice`) | `Sales` | Both / Directional | Voucher No, Date, Customer, Inventory Lines, Tax Lines, Bill Allocation |
| `credit_note` | `account.move` (`out_refund`) | `Credit Note` | Both / Directional | Voucher No, Date, Customer, Return Items, Reference Invoice |
| `purchase` | `account.move` (`in_invoice`) | `Purchase` | Both / Directional | Bill No, Date, Vendor, Inventory Lines, Tax Lines, Bill Allocation |
| `debit_note` | `account.move` (`in_refund`) | `Debit Note` | Both / Directional | Voucher No, Date, Vendor, Return Items, Reference Bill |
| `receipt` | `account.payment` (`inbound`) | `Receipt` | Both / Directional | Customer, Bank/Cash Journal, Amount, Date, `<BILLALLOCATIONS>` (Agst Ref) |
| `payment` | `account.payment` (`outbound`) | `Payment` | Both / Directional | Vendor, Bank/Cash Journal, Amount, Date, `<BILLALLOCATIONS>` (Agst Ref) |
| `journal` | `account.move` (`entry`) | `Journal` | Both / Directional | Voucher No, Date, Multi-line Debit/Credit entries, Narration |
| `contra` | `account.move` (`entry`) | `Contra` | Both / Directional | Bank-to-Cash, Cash-to-Bank, Bank-to-Bank transfers |

---

## 5. Source of Truth, Conflict Resolution & Echo Suppression

### 1. Watermarking & 3-Tier AlterID Delta Optimization
Tally maintains an incremental integer watermark called `ALTERID` across all masters and vouchers. The integration implements a high-performance 3-layer delta strategy:

1. **Decoupled Push & Pull Cadence**:
   - **Outbound Push (Odoo → Tally)**: Runs on every cron execution (default every 2 minutes) for instant responsiveness.
   - **Inbound Pull (Tally → Odoo)**: Decoupled to a configurable interval (`pull_interval`, default 15 minutes), preventing unnecessary network and database load.
2. **Client-Side AlterID Fast Skip (Always Active)**:
   - Because Tally's `ALTERID` is strictly monotonic, `process_inbound_batch` instantly skips any record where `AlterID <= entity_config.last_alterid` before performing any database or ORM operations.
   - Even if an entire master collection is pulled, unchanged records cost zero CPU/write cycles.
3. **Server-Side TDL Delta Filter (Opt-In)**:
   - For high-volume companies (100,000+ masters), enabling **`Server-side AlterID Delta (TDL)`** embeds an inline collection filter (`$AlterID > last_alterid`) directly into the Tally XML export query, transferring only altered objects over the network.
4. **Voucher Lookback Window & Auto-Post**:
   - Vouchers pull across a configurable lookback window (`pull_lookback_days`, default 30 days or `history_from`).
   - Optional **Auto-post (`auto_post`)** flag allows imported draft vouchers to automatically post into Odoo's general ledger.

### 2. SHA-256 Echo & Loop Suppression (Two-Way Closed Loop)
When Odoo pushes a record to Tally or when an accountant posts an imported draft voucher in Odoo:
1. **Outbound Registration**: When any record is enqueued from Odoo, `tally.mapping.register_outbound()` records `last_origin="odoo"` along with the SHA-256 hash of the payload.
2. **Inbound Echo Drop**: When Tally returns the record on the next `ALTERID` poll, the Sync Engine verifies `last_origin == "odoo"` and matching content hash, dropping the echo immediately.
3. **Manual Post-Back Guard**: Inbound invoices and vouchers from Tally enter Odoo as `draft`. When a user reviews and clicks **"Post"** in Odoo, `register_outbound()` checks if `last_origin == "tally"` and suppresses the outbound enqueue so Tally never receives a duplicate voucher.

### 3. GST Tax Resolution & Invoice Matching
- **Automated Tax Ledger Matching**: In Tally, Indian vouchers store GST as ledger entries (`CGST 9%`, `SGST 9%`, `IGST 18%`, `Output CGST`, `Duties & Taxes`).
- **Odoo `account.tax` Mapping**: The engine parses tax rates/names, finds or creates the matching `account.tax` in Odoo, and attaches `tax_ids` directly to the invoice product lines.
- **Supplementary Charges**: Non-tax adjustment ledgers (`Freight Charges`, `Discounts`, `Round Off`) are automatically appended as individual line items, guaranteeing 100% tax and invoice total fidelity with Tally.

### 4. Double-Entry Journal & Contra Balancing
- Tally journals and contras are automatically validated for double-entry balance ($\Sigma \text{Debit} = \Sigma \text{Credit}$).
- If minor rounding discrepancies or adjustments occur, the engine creates a balancing line against `Rounding & Suspense Difference`, preventing Odoo from rejecting the entry upon posting.

### 5. Multi-Tier Prioritized Master Matching
To eliminate duplicate records from name variations or shared companies, master lookups follow a strict 3-tier resolution:
1. **Tier 1 (GUID)**: Match against existing `tally.mapping` by unique Tally GUID.
2. **Tier 2 (Government / Internal Identifier)**: Match by GSTIN / PAN (`res.partner.vat`) for parties, or Internal Reference / HSN for products.
3. **Tier 3 (Scoped Name)**: Exact / case-insensitive name match scoped to the active company.

### 6. Conflict Resolution
- If an entity has direction `both` and changes occur simultaneously in both systems:
  - If **Source of Truth** is `Tally`, the Tally version overwrites Odoo.
  - If **Source of Truth** is `Odoo`, the Odoo version overwrites Tally.

---

## 6. Troubleshooting & FAQ

#### Q: The agent says "Connection Refused on 127.0.0.1:9000".
- **Fix**: Check that TallyPrime is open. Verify in `F1: Help -> Settings -> Connectivity` that Tally acts as `Both` or `Server` with port `9000`. Restart TallyPrime as Administrator.

#### Q: The agent connects but says "Company Not Open / Found".
- **Fix**: Check `tally_company` in Odoo Instance settings. It must match the company name open in TallyPrime character-for-character.

#### Q: How do I view sync errors or audit logs?
- **Fix**: Navigate to **Invoicing -> Configuration -> Tally Integration -> Sync Logs**. You can group by Entity, Status (`success`, `warning`, `error`), and inspect exact XML payloads and failure tracebacks.

#### Q: Does this module conflict with third-party custom modules?
- **Fix**: No. All outbound hooks are wrapped in defensive `try...except` and guarded by `tally_no_sync` context flags. All mapping data is stored in dedicated tables without polluting standard Odoo models.

---

## 7. Git Branches & Odoo App Store Compatibility

To ensure seamless indexing by the **Odoo App Store** crawler and smooth maintenance across versions:

| Branch Name | Purpose | Target Odoo Version |
| :--- | :--- | :--- |
| **`main`** | **Primary Development Branch**. Contains latest stable code, CI tests, docs, and agent scripts. | Active Dev |
| **`19.0`** | **Official Release Branch** for Odoo 19. Crawled by Odoo App Store (`version: 19.0.x.x.x`). | Odoo 19.0 |
| **`20.0`** *(Upcoming)* | **Release Branch** for Odoo 20 compatibility once released. | Odoo 20.0 |

### Branching Workflow:
1. Developers work on `main` (or feature branches merged to `main`).
2. When ready for release/update, `main` is fast-forwarded or merged into `19.0`.
3. Odoo App Store automatically detects the update on branch `19.0` and makes it available to users.

---

## License & Support
- **License**: LGPL-3
- **Author & Vendor**: [Scidecs](https://www.scidecs.com)
- **Support & Customizations**: Reach out via [https://www.scidecs.com](https://www.scidecs.com) or submit issues on [GitHub](https://github.com/scidecs/odoo-tally).
