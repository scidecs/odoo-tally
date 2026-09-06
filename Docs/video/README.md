# Live Odoo–TallyPrime Explainer Video

This folder contains the reproducible source and narration for the Scidecs Odoo 19 to TallyPrime
explainer. The centre of the video is a **real live workflow**, not a screenshot slideshow:

1. Odoo's per-entity direction and source-of-truth configuration is shown live.
2. TallyPrime's Accounts with Inventory and GST company configuration is verified live.
3. A synthetic stock item is created through the standard Odoo product form.
4. The actual event is shown in Odoo's durable queue and acknowledged state.
5. TallyPrime is navigated to Stock Items and the synchronized SKU is opened.
6. A live Tally receipt and Odoo's searchable inbound success log provide transaction evidence.

Only the disposable `Scidecs Demo Pvt Ltd` company and synthetic `VID260906` product are shown. The
capture excludes credentials, private network addresses, customer records and Chrome Remote Desktop
connection details.

## Source files

- `explainer_scenes.txt` — editable scene titles, visual modes and voice-over copy.
- `source/odoo_product_create.mp4` — live Odoo form interaction.
- `source/odoo_entity_configuration.mp4` — live ownership and direction configuration.
- `source/odoo_sync_now.mp4` — live synchronization action.
- `source/odoo_outbound_queue.mp4` — acknowledged Odoo-to-Tally events.
- `source/odoo_sync_logs.mp4` — searchable Tally-to-Odoo success evidence.
- `source/tally_company_features.mp4` — live Tally accounts, inventory and GST settings.
- `source/tally_stock_item_walkthrough.mp4` — Tally Stock Items navigation and result.
- `source/tally_stock_item_detail_v2.mp4` — synchronized name and part-number verification.
- `source/tally_receipt_voucher.mp4` — isolated synthetic receipt voucher.

The short source clips contain no audio. They are retained so the final video can be rebuilt and the
recording evidence can be audited without access to the original test machines.

## Build

Install `edge-tts` for the professional neural narration, then run:

```bash
python3 -m pip install edge-tts
./scripts/build_explainer_video.sh
```

The default narrator is Microsoft `en-IN-NeerjaNeural` with restrained pacing and post-production
EQ, compression and loudness normalization. `VOICE_NAME`, `VOICE_RATE`, `VOICE_PITCH` and
`EDGE_TTS_BIN` can be overridden for approved localization or brand-voice variants.

The build generates:

- `Docs/media/scidecs_odoo_tally_live_sync_explainer.mp4`
- `Docs/media/scidecs_odoo_tally_live_sync_explainer.srt`
- `Docs/media/scidecs_odoo_tally_live_sync_explainer_cover.jpg`

The MP4 uses H.264 video, AAC narration and an embedded English subtitle track. The standalone SRT
supports YouTube accessibility and translation workflows. Always review the rendered video and its
captions before publication.

## Publication notes

The video demonstrates safe live master and voucher evidence across both applications while explaining
the connector's wider bidirectional architecture. It must not be described as a client acceptance test
or a scale benchmark.
Upload the approved MP4 to the official Scidecs channel, add the SRT as English captions, and link the
canonical public video from the Odoo Apps listing and Scidecs product page.
