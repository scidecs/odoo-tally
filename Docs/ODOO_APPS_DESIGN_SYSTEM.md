# Odoo Apps Listing Design System

This document defines the visual, content and search system for the Scidecs Odoo Tally Connector
listing. It exists so future releases extend one coherent page instead of introducing unrelated
sections, colors or card patterns.

## Design benchmark and original direction

The September 2026 audit compared the live Scidecs listing with established Odoo Apps publishers and
reviewed integration-dashboard work on Freepik, Behance and Dribbble. The strongest recurring pattern
was product-led composition: a decisive outcome headline, a real interface as the dominant visual,
small integration marks, restrained depth and repeated spacing.

The implementation translates the section discipline associated with modern Bootstrap 4 SaaS
templates and modular design-block libraries into scanner-safe Odoo markup. It does not load or copy
a third-party theme, Tailwind runtime, external stylesheet, icon kit or JavaScript. The Scidecs
implementation uses those principles without copying another publisher's artwork:

- real Odoo and TallyPrime screens are the proof layer;
- light lavender separates the integration story from Odoo's white marketplace shell;
- Scidecs navy communicates control and reliability;
- teal identifies synchronization and successful flow;
- Odoo purple identifies the operations side;
- Tally amber identifies the accounting side;
- every feature card uses an eyebrow, outcome heading and concise evidence statement;
- high-design compositions are local PNG assets so Odoo's sanitizer cannot remove their layout.

## Visual tokens

| Token | Value | Use |
|---|---:|---|
| Ink navy | `#101B44` | Headlines, architecture and reliability surfaces |
| Sync teal | `#44D0C5` | Flow, success, synchronization and evidence |
| Odoo purple | `#5A43E8` | Operations, navigation and primary accents |
| Tally amber | `#F6C453` | Accounting, vouchers and GST accents |
| Lavender canvas | `#F7F7FF` | Primary section background |
| Mint canvas | `#EFFBF8` | Reliability and recovery background |
| Warm canvas | `#FFF9EA` | Tally and accounting background |
| Body text | `#4A5473` | Supporting copy |

The spacing rhythm is 24 pixels inside small components, 32 pixels inside large cards and 48–80
pixels between major content groups. Large radii are reserved for section shells and screenshot
frames; small radii are used inside those shells. The listing uses Bootstrap 4 grid, spacing,
typography, card, badge, table and button utilities, supplemented only by restrained inline visual
tokens. No external CSS or JS is required.

## Page architecture

1. Product-led visual hero using the real Odoo control centre and correct platform marks.
2. Four-item trust strip for license, coverage, GST and live validation.
3. Outcome-led problem statement followed by four consistent value cards.
4. Master, sales, purchase, inventory and finance capability composition.
5. Explicit 20-entity direction and mapping matrix.
6. Architecture visual explaining Odoo, the control plane and TallyPrime.
7. Four-step configuration narrative with real Odoo screens.
8. Secure direct and private-LAN deployment patterns.
9. Odoo dashboard, agent, configuration, discovery and mapping proof.
10. Queue, audit, analytics, identity and quarantine proof.
11. Native Odoo products, invoices, bills, settlements, journals and transfers.
12. Live TallyPrime master, GST, return, settlement and Stock Journal evidence.
13. Round-trip metrics and honest controlled-UAT boundary.
14. Reliability controls and buyer FAQ.
15. Designed YouTube poster near the bottom as final workflow proof.
16. Free-software positioning, optional expertise and permitted contact routes.

## Video behavior

Odoo Apps strips a raw YouTube iframe from `static/description/index.html`. A rescan can therefore show
the title and fallback link while leaving an empty area where the player was expected. The supported
listing pattern is a local poster image inside an anchor to the canonical YouTube URL. The poster is
always visible because it ships inside `static/description`; clicking it opens the public video.

The video belongs near the bottom, after features, architecture, screenshots, validation and FAQ but
before the final CTA. Do not reintroduce an iframe, JavaScript player, modal or non-YouTube host.

## Search language

Use important terms naturally in the manifest name, summary, description, headings, captions and image
alternative text. Do not add a keyword dump.

Primary terms:

- Odoo Tally Connector
- Odoo Tally Integration
- TallyPrime Integration for Odoo 19
- Odoo to Tally sync
- Tally to Odoo sync
- bidirectional Tally synchronization

Intent and feature terms:

- GST invoice synchronization
- Tally sales invoice and purchase bill import
- customer, vendor and product sync
- inventory and warehouse transfer synchronization
- Tally Stock Journal to Odoo transfer
- receipt, payment, journal and contra voucher sync
- Tally XML gateway
- Tally private-LAN agent
- Odoo Tally sync logs, retry and quarantine

## Rebuild and quality checks

Run:

```bash
./scripts/build_store_visuals.sh
./scripts/run_stage_checks.sh
python3 -m pytest -q tests
```

Every local image must exist and carry descriptive English alternative text. The page must contain no
JavaScript, iframe, external stylesheet or remotely loaded visual. Links are limited to canonical
YouTube, `mailto:` and Odoo-owned pages. The corporate URL is supplied through the manifest
`website` field and shown as plain text in the description because other external links are
invalidated by the marketplace.
