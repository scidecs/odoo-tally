# Live integrity harness

Scenario runner used to validate a release (and a customer UAT) against a real TallyPrime
gateway. After every step it compares **every Tally ledger closing balance** with the matching
Odoo partner/account balance, checks for duplicate or unlinked documents and failed queue items,
and runs a second sync cycle that must change nothing (idempotency).

| Scenario | What it proves |
|---|---|
| `s1` | Both systems new: Odoo and Tally documents in both directions, edits, cancellations and renames on both sides. |
| `s2` | Tally already in use, Odoo new: full onboarding pull, then continued two-way sync. |
| `s3` | Odoo already in use, Tally new: *Push Existing Odoo Data*, then continued two-way sync. |
| `s4` | Two Odoo companies and two Tally companies: isolation and shared-contact placement (`TALLY_CO="A|B"`). |
| `agent_setup`, `agent_tally`, `agent_audit` | Building blocks for the same checks through the on-premise agent. |

Use a **disposable** Tally company and a disposable Odoo database: the scenarios create, edit,
cancel and rename real vouchers and masters on both sides. TallyPrime Educational accepts only the
1st, 2nd and 31st of a month; the harness dates its documents accordingly.

```bash
SCENARIO=s1 TALLY_CO="My Test Co" PREFIX=T1 TALLY_HOST=192.168.1.20 REPORT=/tmp/s1.json \
  odoo-bin shell -c odoo.conf -d test_db --no-http < scripts/integrity/harness.py
```

The JSON report lists each audit step with the issues found; a release requires zero.
