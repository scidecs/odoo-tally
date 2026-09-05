# Support and Consulting Model

## 1. Principle

The connector is free software. Scidecs monetizes optional expertise and accountable delivery, not
access to the code.

## 2. Free community offering

Included without a license fee:

- LGPL-3 source code.
- Odoo module and optional local agent.
- Architecture, technical, installation, security, test and FAQ documentation.
- Automated test suite and reference validation report.
- Community issue reporting and contributions through GitHub.
- Updates Scidecs chooses to publish for the supported community release.

The free offering does not include a guaranteed response time, remote access, customer data repair,
configuration responsibility, custom TDL support, migration execution, training or production SLA.

## 3. Optional professional services

### Readiness assessment

Deliverables may include system/version inventory, network topology, entity/direction matrix,
source-of-truth decisions, gap assessment, volume estimate, security review and UAT plan.

### Implementation and secure deployment

Includes module installation, direct/agent topology, TLS/proxy/firewall guidance, company binding,
roles, schedules, monitoring and operational handover.

### Accounting and master mapping

Includes chart-of-accounts/group mapping, party identity, GST ledger patterns, products/UoMs,
godowns, cost centres, bank/cash journals, bill allocations and exception decisions.

### Migration and reconciliation

Includes controlled historical extraction/import, batch execution, record-count and financial
reconciliation, exception register, repeat-pull checks and approved cutover.

### UAT and training

Includes scenario design, finance/operations walkthroughs, incident/retry training, sign-off evidence
and administrator documentation adapted to the customer.

### Managed support

May include an agreed response window, monitoring review, incident triage, version upgrades,
configuration assistance and periodic health checks. Exact coverage belongs in a signed statement of
work/SLA.

### Custom development

Examples include customer TDL/voucher structures, additional entities, workflow extensions,
notifications and reporting. MRP, statutory APIs, orders/logistics, assets and landed costs are
separate scoped modules—not informal additions to the standard connector.

## 4. Engagement lifecycle

1. **Discover:** collect versions, workflows, data and business ownership.
2. **Design:** approve topology, scope, mapping, security, acceptance and rollback.
3. **Configure:** install in staging and establish masters/policy.
4. **Validate:** run automated checks, customer UAT, reconciliation and fault recovery.
5. **Cut over:** back up, freeze agreed inputs, synchronize, reconcile and activate schedules.
6. **Operate:** monitor queue/quarantine/health and follow incident runbooks.
7. **Improve:** prioritize reusable upstream fixes or separately scoped customer extensions.

## 5. Customer responsibilities

- Maintain valid Odoo and Tally licenses/environments where applicable.
- Provide authorized subject-matter experts for finance, inventory, Odoo and Tally.
- Disclose custom TDL, voucher types, ledgers and fiscal controls.
- Provide representative sanitized data or secure access.
- Approve direction/source-of-truth decisions.
- Maintain backups and authorize rollback/accounting corrections.
- Complete and sign UAT before production.
- Operate secure network and secret-management controls.

## 6. Scidecs responsibilities in a paid engagement

Only as defined in the signed scope, Scidecs may be responsible for configuration, documented
mapping, agreed test execution, defect correction, reconciliation support, training, cutover and SLA
response. Work outside the signed entity/version/data boundary is a change request.

## 7. Support request checklist

Provide:

- Odoo version/build, edition and hosting.
- Connector version/commit.
- TallyPrime release and company mode.
- Direct or agent topology.
- Entity, direction and source-of-truth setting.
- Timestamp, GUID/AlterID or Odoo record reference.
- Queue/log/quarantine error text.
- Sanitized XML fragment when relevant.
- Expected versus actual result.
- Reproduction steps and business urgency.

Do not email raw database dumps, credentials or unrestricted accounting exports. Agree a secure
transfer route first.

## 8. Severity model for contracted support

| Severity | Example |
|---|---|
| Critical | Active incorrect postings or complete production sync outage with no workaround |
| High | Core entity blocked or materially wrong, controlled workaround available |
| Medium | Isolated record/configuration issue or non-critical degradation |
| Low | Question, documentation improvement or enhancement request |

Response/resolution targets are not implied by this document; they must be stated in the customer's
contract/SLA.

## 9. Warranty and claims

LGPL software is provided under its license terms. A successful reference validation is not a
guarantee for every customized Tally company. Scidecs will not describe custom/unverified features as
standard. Production acceptance must cite exact versions, configuration, dataset and UAT results.

## 10. Contact

For optional consultation or a scoped support plan, contact
[hello@scidecs.com](mailto:hello@scidecs.com).
