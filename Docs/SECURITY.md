# Security Guide

## 1. Security objective

Protect accounting data, credentials, company boundaries, and production books while allowing
recoverable data exchange between Odoo and TallyPrime.

## 2. Trust boundaries

| Boundary | Risk | Required control |
|---|---|---|
| Odoo ↔ Tally direct | Tally gateway lacks native internet-grade authentication | Private route/VPN or HTTPS authenticated proxy plus allow-list |
| Agent ↔ Odoo | Stolen token permits connector API access | HTTPS, secret storage, rotation and instance deactivation |
| Agent ↔ local Tally | Any local/LAN caller may reach gateway | Host firewall and trusted subnet/process account |
| User ↔ Odoo UI | Configuration or replay misuse | Tally User/Manager groups and company record rules |
| Restored Odoo database | Staging could push production data | Database UUID clone guard and inactive schedules during restore |
| Logs/payloads/backups | Accounting/PII exposure | Least privilege, retention, encryption and no public repository inclusion |

## 3. Network requirements

- Never publish raw `http://host:9000` on the open internet.
- Prefer site-to-site VPN/private peering.
- If using a reverse proxy, terminate TLS with a valid certificate, authenticate requests and
  allow-list Odoo egress addresses where stable.
- If using an authenticated tunnel, protect its credentials and restrict the destination.
- Use outbound HTTPS for the agent's Odoo calls.
- Restrict local Tally port access to the agent/approved hosts.

TLS verification should remain enabled. Disabling it is acceptable only for an isolated,
documented test and never as a silent production workaround.

## 4. Secrets

Secrets include the agent token, proxy/basic credentials, header secrets, database credentials,
Tally backups and accounting XML.

- Do not commit them to Git.
- Store them in the Odoo database fields protected by manager access and in an OS/service secret
  store on the agent host.
- Avoid process arguments when the platform exposes arguments to other users.
- Rotate agent tokens after staff/vendor changes, suspected exposure or environment cloning.
- Revoke by regenerating the token or deactivating the instance.

## 5. Odoo authorization

- Tally User receives operational read access.
- Tally Manager receives configuration and retry/quarantine mutation rights.
- Multi-company record rules restrict instances, entity configs, mappings, queues, logs,
  quarantine and discovered companies to allowed companies.
- Agent controller operations authenticate a token, validate the bound environment and require an
  active instance before `sudo()` model access is used.

Review memberships quarterly and before cutover.

## 6. Data integrity controls

- One active instance per Odoo company prevents ambiguous routing.
- Database UUID binding prevents restored clones from automatically delivering to the original
  endpoint.
- Stable GUIDs and idempotency keys make retry safe.
- Content hashes and last-origin tracking reduce feedback loops.
- AlterID watermarks move only after safe consumption.
- Poison payloads are retained in quarantine instead of silently discarded.
- Accounting entries and Stock Journals are balanced by transformation/tests.
- Automated-valuation inventory adjustment is off by default to avoid duplicate value.

## 7. Privacy and retention

Payloads and logs may contain names, addresses, GSTIN/PAN, transaction narration, amounts and product
details. Apply the organization's retention and access policy.

- Set operational log retention to the minimum useful period.
- Resolve and periodically archive/delete quarantine records according to incident/audit policy.
- Encrypt backups and restrict download access.
- Redact customer data before sharing support evidence.
- Never publish database dumps or real accounting XML with the open-source module.

## 8. Threat scenarios

### Unauthorized gateway write

Impact: forged masters/vouchers in Tally. Controls: no public raw port, authenticated proxy/VPN,
source allow-list and Tally backup/audit review.

### Stolen agent token

Impact: attacker can read leased outbound payloads and submit inbound data for the bound instance.
Controls: HTTPS, token rotation, least-privilege host, monitoring and inactive instance on incident.

### Replay

Impact: duplicate delivery attempts. Controls: stable GUID, mapping, content hash, idempotency key and
Tally Alter semantics. Monitor unexpected duplicate business records during UAT.

### Cross-company access

Impact: accounting data leaks or wrong-company posts. Controls: company fields, global rules,
instance binding and one active instance per company.

### Malformed payload denial of service

Impact: an entity watermark stalls. Controls: parser sanitation, per-record savepoints, attempt
threshold, durable quarantine and targeted retry.

### Environment clone

Impact: staging records reach production Tally. Controls: database UUID guard plus deployment process
that disables schedules/agents before restore.

## 9. Incident response

1. Disable the affected instance and stop the agent/schedule.
2. Preserve logs, queue/quarantine rows, relevant XML and timestamps securely.
3. Rotate tokens/proxy credentials if exposure is possible.
4. Identify the last known correct Odoo/Tally backups.
5. Reconcile unauthorized or missing business documents with finance approval.
6. Correct configuration/code in staging and rerun UAT.
7. Resume one direction at a time while monitoring.
8. Document root cause and preventive action.

Do not delete evidence or reverse posted accounting entries without the finance team's approved
accounting correction procedure.

## 10. Security deployment checklist

- [ ] Raw Tally port is not publicly reachable.
- [ ] TLS is valid and verification enabled where HTTPS is used.
- [ ] Agent/proxy tokens are in approved secret storage.
- [ ] Tally User/Manager groups are reviewed.
- [ ] Multi-company test proves isolation.
- [ ] Database clone guard is exercised.
- [ ] Backups are encrypted and restore-tested.
- [ ] Logs/quarantine retention is approved.
- [ ] Monitoring alerts on failed queue, quarantine and lost heartbeat.
- [ ] Customer data is absent from the public repository/release package.
