# Live Odoo–TallyPrime Explainer Video

This folder contains the reproducible source and narration for the Scidecs Odoo 19 to TallyPrime
explainer. The centre of the video is a **real live workflow**, not a screenshot slideshow:

1. A synthetic stock item is created and saved through the standard Odoo product form.
2. The exact record is shown on both sides during the synchronization handoff.
3. TallyPrime is navigated live to Stock Items, where the new item appears.
4. The synchronized Tally master is opened to verify its name and SKU/part number.

Only the disposable `Scidecs Demo Pvt Ltd` company and synthetic `VID260906` product are shown. The
capture excludes credentials, private network addresses, customer records and Chrome Remote Desktop
connection details.

## Source files

- `explainer_scenes.txt` — editable scene titles, visual modes and voice-over copy.
- `source/odoo_product_create.mp4` — live Odoo form interaction.
- `source/tally_stock_item_arrival.mp4` — live TallyPrime navigation and synchronized result.
- `source/tally_stock_item_detail.mp4` — live TallyPrime master verification.

The short source clips contain no audio. They are retained so the final video can be rebuilt and the
recording evidence can be audited without access to the original test machines.

## Build

On macOS with `ffmpeg`, ImageMagick and the system `say` command installed, run:

```bash
./scripts/build_explainer_video.sh
```

The build generates:

- `Docs/media/scidecs_odoo_tally_live_sync_explainer.mp4`
- `Docs/media/scidecs_odoo_tally_live_sync_explainer.srt`
- `Docs/media/scidecs_odoo_tally_live_sync_explainer_cover.jpg`

The MP4 uses H.264 video, AAC narration and an embedded English subtitle track. The standalone SRT
supports YouTube accessibility and translation workflows. Always review the rendered video and its
captions before publication.

## Publication notes

The video demonstrates one safe Odoo-to-Tally transaction while explaining the connector's wider
bidirectional architecture. It must not be described as a client acceptance test or a scale benchmark.
Upload the approved MP4 to the official Scidecs channel, add the SRT as English captions, and link the
canonical public video from the Odoo Apps listing and Scidecs product page.
