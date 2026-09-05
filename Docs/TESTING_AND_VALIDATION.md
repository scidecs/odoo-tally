# Testing and Validation

## 1. Validation philosophy

Compilation and XML parsing prove syntax, not business correctness. A release gate combines:

1. Static checks.
2. Standalone transformation tests.
3. Fresh target-version Odoo installation.
4. Odoo transactional tests.
5. Real Tally transport and round-trip verification.
6. Customer-specific UAT and reconciliation.

No test environment proves universal compatibility with every Tally customization. Claims must name
the tested scope and dataset.

## 2. Stage checks

```bash
./scripts/run_stage_checks.sh
python3 -m pytest -q tests
```

The stage script compiles Python, parses every addon XML file, validates key manifest fields,
confirms every manifest data file exists, and checks the Apps description for missing local images,
missing alt text, external image assets and JavaScript.

## 3. Odoo transactional test command

Use a disposable database and the actual Odoo 19 runtime:

```bash
odoo-bin \
  -d odootally_test \
  --test-enable \
  --test-tags=/tally_integration \
  --stop-after-init \
  -i tally_integration
```

Delete the disposable database after recording the result. Expected exception traces from poison
record tests are not failures; the final Odoo test summary is authoritative.

## 4. Automated coverage

Current regression coverage includes:

- Failed batches do not advance watermarks.
- The same poison revision is quarantined at the threshold.
- Targeted retry rewinds only the affected entity.
- Odoo-origin acknowledgement resolves a stale failure.
- Workflow echo events do not return to Tally.
- Odoo/Tally source policy is respected.
- Stable mappings and outbound GUID identity.
- Product create enqueues exactly once.
- Product stock group/category retention.
- Zero closing stock remains zero.
- Repeated total stock pulls preserve secondary-location quantity and total idempotency.
- Dated standard cost/price lists.
- Outbound payment queue behavior.
- Opening-balance balancing.
- Inbound and outbound Stock Journal transfer behavior.
- Stock Journal IN/source negative and OUT/destination positive structure.
- Sales, purchase and both return payload balance with tax.
- XML attribute escaping and parser normalization.

## 5. Reference live scenario

The validated `RT260904F` scenario used:

- 15 products across three categories.
- Purchases and sales.
- Purchase return and sales return.
- CGST and SGST at 9% each.
- Customer receipt and vendor payment.
- Balanced journal voucher.
- Internal transfer of five products between two godowns.

Recorded result:

- 39 initial outbound acknowledgements, 0 failed.
- Exactly 15 scenario products and 10 scenario transaction vouchers in Tally.
- 220 records processed in clean recovery.
- 205 identity mappings and zero sync errors.
- 15/15 products, 6 invoice/note documents, 2 payments, 1 journal and 1 transfer recovered.
- Repeat pull did not change expected counts, totals or quantities.
- Tally→Odoo price change verified and restored.
- Odoo→Tally price change verified and restored.
- Native Stock Journal diagnostic accepted and re-exported with correct tags/signs.

See `tally_integration/FINAL_VALIDATION_REPORT.md` for evidence filenames and backup locations used in
the development environment. Database dumps and accounting XML must not be included in a public
Odoo Apps release.

## 6. Portable live test setup

The live utilities require an Odoo source checkout and a local Odoo config. Do not edit a personal
absolute path into the repository.

```bash
export ODOO_SRC=/path/to/odoo-src
python3 scripts/live_roundtrip_scenario.py --help
```

The scenario script is destructive by design. Use only with an explicitly disposable/backed-up
Tally company and Odoo database. Its default fixture names are not client data.

## 7. Customer UAT acceptance matrix

| Area | Acceptance evidence |
|---|---|
| Connectivity | Protected route/agent stable for the agreed window |
| Masters | Counts and sampled identities/hierarchies match |
| GST | Correct component, rate, sign, taxable base and total |
| Sales/purchase | Document count, date, party, lines and totals match |
| Returns | Correct note type, signs, products, tax and reference |
| Payments | Direction, journal/ledger, amount and bill reference match |
| Journals/contras | Debits equal credits and intended accounts match |
| Inventory | Product, UoM, quantity, cost/price and godown match |
| Internal transfer | Source decreases, destination increases, total unchanged |
| Repeat pull | No duplicate and no numerical drift |
| Bidirectional edit | Declared ownership and echo behavior match policy |
| Failure recovery | Offline queue retry and poison quarantine demonstrated |
| Fresh recovery | Required supported history is reproducible from Tally |
| Performance | Agreed volume completes inside operational window |
| Security | Token, gateway, ACL and backup controls approved |

## 8. Reconciliation queries

For each UAT batch compare:

- Count by document type and date.
- Sum of untaxed, tax and total amounts.
- Debit/credit balance by journal.
- Quantity by product and internal location.
- Product cost, selling price, SKU, UoM, HSN and category.
- Payment amount/direction and outstanding-reference allocation.
- Queue failed/pending age, quarantine count and error logs.

Use tolerances only where currency/UoM rounding policy explicitly permits them.

## 9. Negative tests

Include:

- Tally closed or host unreachable.
- Wrong company name.
- Invalid token and inactive instance.
- Closed fiscal period.
- Missing ledger/product/UoM dependency.
- Unsupported/non-standard voucher structure.
- Malformed XML/control entities.
- Duplicate delivery.
- Agent crash after work lease.
- Database clone restored in a different environment.
- Simultaneous edits under each source policy.

## 10. Scale and soak gate

Before unsupervised enterprise use:

- Test at least 10,000 representative vouchers or the customer's larger real peak.
- Include the customer's full master cardinality and largest Day Book window.
- Run repeated agent/gateway restarts.
- Introduce intermittent network failure.
- Run multiple days with production-like schedules.
- Record throughput, peak memory, oldest pending age and error/quarantine rate.

This gate is not replaced by the functional 15-product scenario.

## 11. Release sign-off

Sign-off should name:

- Exact code commit and Odoo/Tally versions.
- Company configuration and custom TDL/voucher types.
- Enabled directions/source policies.
- Dataset/date range and record counts.
- Test results and accepted exceptions.
- Backup/rollback identifiers.
- Business, finance, Odoo and Tally approvers.

The publishable claim is “validated for the documented scenario and ready for customer UAT,” not
“zero errors for every possible Tally database.”
