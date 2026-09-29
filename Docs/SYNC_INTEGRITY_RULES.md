# Sync Integrity Rules

How the connector keeps Odoo and TallyPrime identical, and the TallyPrime behaviours those rules
are built on. Every behaviour below was verified against a live TallyPrime gateway; the related
automated test is named where one exists.

## 1. Verified TallyPrime behaviours

| # | Behaviour | Consequence for the connector |
|---|---|---|
| T1 | Masters are identified by **name**. A `GUID` sent on import is not used as the identity; Tally keeps it as `REMOTEALTGUID`. | Masters are matched by name; our GUID is only an echo marker. |
| T2 | Re-sending a master with a new name and `ACTION="Create"` creates a **second** master. A rename needs `NAME="<current name>" ACTION="Alter"` plus `NAME.LIST`. | Renames address the name Tally currently holds (`tally.mapping.tally_name`). |
| T3 | A plain collection export returns only `NAME` and `PARENT`. | Every export fetches `GUID, AlterID, MasterID, RemoteAltGUID` and business fields explicitly. |
| T4 | Tally assigns its own GUID **and voucher number** to imported vouchers (automatic numbering). The `REMOTEID` we send is stored and matched on re-import. | Identity is read back after every push and stored on the mapping. |
| T5 | The import reply's `LASTVCHID` is the MasterID of the voucher just created or altered. | Used to bind Tally's identity to the pushed record. |
| T6 | The **Day Book** export ignores `SVFROMDATE/SVTODATE` and returns only Tally's current date. | Vouchers are pulled from a Voucher collection filtered by `$AlterID` (or `$Date` on the first sync). |
| T7 | Editing a voucher keeps its GUID and MasterID and increases its AlterID. | An inbound record whose AlterID is at or below the mapped one is an echo and is skipped. |
| T8 | `TAGNAME="Voucher Number"` addressing (Alter/Cancel) matches **date + number across all voucher types**: a Journal alter changed *Sales 1* in testing. `TAGNAME="MasterID"`, `TAGNAME="GUID"` and `REMOTEID+VCHKEY` with `ACTION="Alter"` silently **create** a new voucher. | Odoo-created vouchers are altered/cancelled by `REMOTEID`. Tally-typed vouchers are addressed by number only after a live check that exactly one voucher has that date and number. |
| T9 | `ACTION="Cancel"` keeps the voucher (number, zero value, `ISCANCELLED`); a later Alter/re-import restores it. Re-importing with `<ISCANCELLED>Yes` is ignored. | Odoo reset-to-draft, cancel and delete become a Tally cancel; re-post restores. |
| T10 | A master `ACTION="Delete"` with an empty body crashed TallyPrime (c0000005) and wiped its application settings. Two messages creating the same master in one import raise an internal-error dialog and stop the XML server until closed. | The connector never sends master deletes and never batches two messages for the same master name (case-insensitive). |
| T11 | Voucher exports can repeat lines in `ALLLEDGERENTRIES` and `LEDGERENTRIES`, and in `ALLINVENTORYENTRIES` and `INVENTORYENTRIESIN/OUT`. | Exactly one list is read per voucher. |
| T12 | Voucher and master GUIDs are `<company guid>-<MasterID in hex>`; masters and vouchers have separate MasterID sequences, so a voucher and a master can share a GUID. | Identity lookups are always scoped to master entity / voucher family. |
| T13 | `OPENINGBALANCE`/`AMOUNT`: **negative = debit** (`$$IsDr` confirms). | All amounts are converted with this single rule. |
| T14 | TallyPrime Educational accepts only the 1st, 2nd and 31st of a month and reports other dates as "Voucher date is missing". | Enable *Tally Educational Mode* on test instances only. |

## 2. Identity model (`tally.mapping`)

| Field | Meaning |
|---|---|
| `remote_id` | GUID Odoo sends; Tally's `REMOTEALTGUID` for Odoo-created objects. Stable forever. |
| `tally_guid`, `tally_masterid` | Tally's own identity, bound after a push or taken from the pulled record. |
| `tally_alterid` | Tally revision already reflected in Odoo (echo/change detection). |
| `tally_name` | Name Tally currently uses (rename addressing, ledger names in vouchers). |
| `tally_voucher_type/number/date` | How Tally addresses a voucher. |
| `odoo_fingerprint` | Accounting content of the Odoo document at the last sync. |

Inbound resolution order: Tally GUID → `REMOTEALTGUID` = our remote id → (masters only) unbound
name pushed by Odoo. A record never re-points to an Odoo record already linked to another Tally
object; that raises an error instead of merging two documents.

## 3. Direction and ownership

* **Echo**: a pulled revision at or below `tally_alterid` is skipped; a pushed record is bound
  immediately, so its read-back never imports a copy.
* **Masters** are written back only when a field Tally stores changes (name, GSTIN, address,
  prices, …), never on side effects such as customer rank updates.
* **Documents created in Tally** are written back only when their accounting content
  (`odoo_fingerprint`) changes in Odoo and the entity policy allows Odoo edits. Simply posting an
  imported draft sends nothing.
* **Source of truth `tally` / `tally_master`**: Odoo edits of Tally-owned records are never sent.
  **`odoo`**: Tally edits are recorded (revision bound) but not applied.

## 4. Posting rules (Tally → Odoo)

* One amount rule everywhere: Tally amount = −(Odoo balance).
* Invoices use Odoo taxes only when they reproduce the Tally voucher exactly (total and each GST
  ledger). Otherwise the voucher is booked line for line, with every tax ledger posted to its own
  account. A "Tally Voucher Reconciliation" line is a last resort and is logged.
* Each Tally tax ledger maps to a tax of the same name posting to an account of the same name.
  Existing Odoo taxes are reused by component and rate only in *Map to existing CoA* mode.
* Party vs account vs tax classification follows the Tally group hierarchy (custom sub-groups of
  Sundry Debtors/Creditors stay parties; Duties & Taxes children are taxes).
* Cash/bank sales and purchases (party ledger is Cash or a bank) and non-standard receipts and
  payments (expense paid directly, TDS split, several parties) are imported as journal entries.
* Tally's reserved *Profit & Loss A/c* ledger is equity in Odoo.
* Orders, delivery/receipt notes, memorandum, reversing, optional and payroll vouchers are not
  imported; user-defined voucher types are routed through their parent type.
* A posted Odoo document changed in Tally is reset, rewritten and re-posted; reconciliations are
  restored where amounts still allow. Locked periods raise a visible sync error.

## 5. Posting rules (Odoo → Tally)

* Masters are pushed before vouchers; each voucher is sent on its own so its Tally identity can
  be bound from `LASTVCHID`.
* Voucher lines reference the Tally names of the mapped party, account, tax and stock item.
* Payments are re-sent after reconciliation so Tally's bill-wise references match.
* Odoo clearing accounts (outstanding receipts/payments, transfer, suspense) are not pushed:
  Tally posts payments straight to the bank ledger. Odoo bank balance plus these clearing
  accounts equals the Tally bank ledger.
* Bank-statement entries are not replicated; reconcile the bank in the system that owns it.

## 6. Operating notes

* Keep one active instance per Odoo company; shared contacts are sent to every company's Tally.
* The daily deletion reconcile flags (never deletes) Odoo records whose Tally object is gone.
* After a TallyPrime internal error, close the dialog on the Tally machine; the queue retries.
