# Contributing

Thank you for improving Tally Prime Integration for Odoo 19.

## Before opening a change

1. Search existing issues and documentation.
2. Keep the change within the supported scope described in [README.md](README.md).
3. Do not commit credentials, customer data, database dumps, private network addresses, or generated evidence artifacts.
4. Add or update tests for changed behavior.
5. Update the relevant architecture, technical, operations, FAQ, or marketing document when public behavior changes.

## Local validation

Run the release checks from the repository root:

```bash
./scripts/run_stage_checks.sh
python3 -m pytest -q tests
```

For integration changes, also install or upgrade the module in a clean Odoo 19 database and complete the applicable UAT scenarios in [Docs/TESTING_AND_VALIDATION.md](Docs/TESTING_AND_VALIDATION.md).

## Change design

- Preserve stable functional boundaries: transport, mapping, orchestration, identity, queueing, and monitoring.
- Keep business rules configurable where companies can legitimately differ.
- Preserve idempotency, echo suppression, company isolation, and transaction boundaries.
- Treat Tally XML and webhook payloads as untrusted input.
- Do not silently expand the supported functional scope.

## Documentation and claims

Public claims must be specific, reproducible, and supported by tests or validation evidence. Do not claim unlimited scale, arbitrary third-party compatibility, or support for features listed as exclusions.

## Security reports

Do not disclose exploitable issues in a public issue. Send a concise report to `hello@scidecs.com`, including affected versions, reproduction steps, impact, and any suggested mitigation. See [Docs/SECURITY.md](Docs/SECURITY.md).

## License

Contributions are accepted under the repository's [LGPL-3.0 license](LICENSE).
