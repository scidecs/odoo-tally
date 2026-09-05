# Odoo Apps Publishing Guide

Last reviewed: 2026-09-05

## 1. Release objective

Publish `tally_integration` as a free LGPL-3 Odoo 19 app while keeping the repository useful to
implementers and keeping customer data, credentials and local paths out of the public release.

## 2. Official requirements used

Odoo's [Apps Vendor Guidelines](https://apps.odoo.com/apps/vendor-guidelines) state that listing data
comes from `__manifest__.py` and `static/description/`, require accurate English descriptions, and
prohibit misleading features, JavaScript, harmful styling and unauthorized external promotional
links. The guidelines say an app is free when `price` is not set and recommend LGPL-3 for open-source
apps.

Odoo's [Module Manifest documentation](https://www.odoo.com/documentation/19.0/developer/reference/backend/module.html)
defines manifest keys, dependencies, license, semantic version, application and installability.

This checklist is a repository aid, not a substitute for re-reading the current guidelines before
submission.

## 3. Repository/branch structure

- `main`: current stable development and documentation.
- `19.0`: Odoo 19 release branch submitted to the Apps repository scanner.
- Module directory at branch root: `tally_integration/`.
- The module manifest version starts with `19.0`.

Before publishing, fast-forward `19.0` from the approved `main` commit and push both branches. Do not
mix code for another Odoo major version into `19.0`.

## 4. Manifest checklist

- [x] Explicit name no longer than 25 characters: `Tally Prime Integration`.
- [x] Version: Odoo-major plus semantic module version.
- [x] License: `LGPL-3`.
- [x] Complete dependency list.
- [x] Author and maintainer: Scidecs.
- [x] Support email: `hello@scidecs.com`.
- [x] Website: Scidecs.
- [x] `application=True`, `installable=True`, `auto_install=False`.
- [x] Store images declared from `static/description/`.
- [x] No price field, so the app is free under the current vendor guidelines.
- [ ] Increment version for every released schema/data update.

## 5. Description-page checklist

- [x] English content.
- [x] `static/description/index.html` exists.
- [x] No JavaScript, injected widgets or modals.
- [x] Bootstrap-compatible classes and local images only.
- [x] Accurate supported/excluded scope.
- [x] Free-license and optional-support model stated factually.
- [x] Local icon and banner.
- [x] Added 28 sanitized Odoo 19 UI screenshots covering every connector view and key synchronized results.
- [ ] Render and inspect the page in the Apps preview.
- [x] Confirmed all 29 local image references exist and every image has descriptive alt text.

TallyPrime desktop screenshots remain a separate evidence task because they require authorized
access to the Windows host. Follow `Docs/TALLY_SCREENSHOT_CAPTURE_GUIDE.md`; never substitute a
mockup for a real Tally screen.

Do not put competitor comparisons in the store page. Keep the dated, source-based comparison in
`Docs/PRODUCT_AND_MARKETING.md`.

## 6. Public-release hygiene

Exclude:

- Database dumps and Odoo filestore backups.
- Real Tally XML/accounting exports.
- Tokens, passwords, hostnames and customer IP addresses.
- Customer/company names and GST/PAN data.
- Personal absolute development paths.
- Runtime logs, caches and generated test artifacts.

The committed test fixture names are synthetic Scidecs demo data. Live evidence files remain outside
the repository; the publishable validation report contains only summarized counts and behavior.

## 7. Technical release gate

Run from repository root:

```bash
./scripts/run_stage_checks.sh
python3 -m pytest -q tests
```

Then run a clean target Odoo 19 install with post-install tests on a disposable database. For a
release involving transformation or transport, also run the controlled Tally UAT.

Required results:

- No Python compilation errors.
- Every XML and manifest data path valid.
- No Odoo registry/view/security errors.
- Automated tests green.
- No legacy customer names or internal development paths.
- No uncommitted files.
- README links resolve inside GitHub.

## 8. Release procedure

1. Pull/fetch and confirm the expected remote state.
2. Review `git diff`, scope table, exclusions and changelog/report.
3. Run static, standalone and clean Odoo tests.
4. Confirm sanitized store assets and manifest.
5. Commit on `main` with a release-oriented message.
6. Push `main`.
7. Fast-forward `19.0` to the same approved commit and push it.
8. In the Odoo Apps publisher dashboard, register/select the GitHub repository and `19.0` branch.
9. Wait for scan; resolve every manifest/dependency/license/HTML warning.
10. Inspect the live listing as a buyer would.
11. Download the store package and install it in a clean Odoo 19 database.
12. Record the published URL, commit and verification date.

## 9. Store copy policy

Allowed and recommended:

- Concrete supported features.
- Deployment topologies and security warning.
- Honest live-validation statement.
- Explicit exclusions.
- “Free LGPL-3” and optional support contact.

Avoid:

- “100% compatible with all Tally companies.”
- “Official” unless an affiliation is verified and current.
- Unverified scale/throughput numbers.
- Claims that other modules are defective or inferior.
- External store links or cross-promotion.
- Screenshots containing customer data.

## 10. Version and maintenance policy

- Bugfix without schema/data change: increment bugfix component for a public release.
- Schema or loaded XML/CSV change: increment module version and require `-u tally_integration`.
- New Odoo major: create a dedicated major branch and validate on that runtime.
- Keep name/technical name consistent across versions.
- Update `Docs/IMPLEMENTATION_STATUS.md`, tests and store scope together.

## 11. After publication

- Monitor scan errors, issues and comments.
- Answer questions using `Docs/FAQ.md` and the exact supported boundary.
- Triage reproducible generic defects separately from customer configuration/customization.
- Upstream reusable fixes with regression tests.
- Never diagnose from unrestricted customer backups in a public issue.
- Revalidate the Apps guidelines before each major publication.

For the listing redesign, conversion plan and compliant Scidecs authority strategy, follow
[Odoo Apps Growth and Listing Redesign Roadmap](ODOO_APPS_GROWTH_ROADMAP.md).
