#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scene_file="$repo_dir/Docs/video/explainer_scenes.txt"
source_dir="$repo_dir/Docs/video/source"
output_dir="$repo_dir/Docs/media"
asset_dir="$repo_dir/tally_integration/static/description/assets"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/odoo-tally-video-v2.XXXXXX")"
edge_tts_bin="${EDGE_TTS_BIN:-$(command -v edge-tts || true)}"
voice_name="${VOICE_NAME:-en-IN-NeerjaNeural}"
voice_rate="${VOICE_RATE:-+20%}"
voice_pitch="${VOICE_PITCH:--2Hz}"
font_regular="${VIDEO_FONT_REGULAR:-/System/Library/Fonts/Supplemental/Arial.ttf}"
font_bold="${VIDEO_FONT_BOLD:-/System/Library/Fonts/Supplemental/Arial Bold.ttf}"
navy="0x08162F"

cleanup() { rm -rf "$work_dir"; }
trap cleanup EXIT

for tool in ffmpeg ffprobe magick; do
    command -v "$tool" >/dev/null || { printf 'Required tool not found: %s\n' "$tool" >&2; exit 1; }
done
[[ -n "$edge_tts_bin" ]] || { printf 'Install edge-tts: python3 -m pip install edge-tts\n' >&2; exit 1; }
for file in "$font_regular" "$font_bold" "$scene_file" "$asset_dir/scidecs_mark.png" "$asset_dir/odoo_logo.png" "$asset_dir/tallyprime_logo.png" \
    "$source_dir/odoo_product_create.mp4" "$source_dir/odoo_entity_configuration.mp4" "$source_dir/odoo_sync_now.mp4" \
    "$source_dir/odoo_sync_logs.mp4" "$source_dir/odoo_outbound_queue.mp4" "$source_dir/tally_company_features.mp4" \
    "$source_dir/tally_stock_item_walkthrough.mp4" "$source_dir/tally_stock_item_detail_v2.mp4" "$source_dir/tally_receipt_voucher.mp4"; do
    [[ -f "$file" ]] || { printf 'Required source not found: %s\n' "$file" >&2; exit 1; }
done

mkdir -p "$output_dir"
: >"$work_dir/concat.txt"
: >"$work_dir/explainer.srt"

format_srt_time() {
    local ms="$1"
    printf '%02d:%02d:%02d,%03d' "$((ms / 3600000))" "$(((ms % 3600000) / 60000))" "$(((ms % 60000) / 1000))" "$((ms % 1000))"
}

make_brand_overlay() {
    local title="$1" overlay="$2" split="${3:-no}"
    magick -size 1920x1080 xc:none -fill '#08162FF2' -stroke none \
        -draw 'rectangle 0,0 1920,98 rectangle 0,1034 1920,1080' -fill '#44D0C5' -draw 'rectangle 0,98 1920,104' \
        -fill white -font "$font_bold" -pointsize 34 -annotate +58+63 "$title" \
        -fill '#C9D7F0' -font "$font_regular" -pointsize 20 -annotate +58+1064 'LIVE TEST ENVIRONMENT  /  SCIDECS.COM' "$work_dir/overlay_base.png"
    magick "$asset_dir/scidecs_mark.png" -resize 48x48 "$work_dir/mark.png"
    magick "$asset_dir/odoo_logo.png" -resize 112x38 "$work_dir/odoo.png"
    magick "$asset_dir/tallyprime_logo.png" -resize 140x38 "$work_dir/tally.png"
    magick "$work_dir/overlay_base.png" "$work_dir/mark.png" -geometry +1650+24 -composite \
        "$work_dir/odoo.png" -geometry +1712+17 -composite "$work_dir/tally.png" -geometry +1712+57 -composite "$overlay"
    if [[ "$split" == yes ]]; then
        magick "$overlay" -fill '#44D0C5' -draw 'rectangle 22,150 960,198' -fill '#F6C453' -draw 'rectangle 960,150 1898,198' \
            -fill '#08162F' -font "$font_bold" -pointsize 23 -annotate +50+182 'ODOO 19  /  EVENT & ACKNOWLEDGEMENT' \
            -annotate +988+182 'TALLYPRIME  /  RESULT' "$overlay"
    fi
}

make_editorial_card() {
    local mode="$1" title="$2" card="$3"
    magick -size 1920x1080 xc:'#08162F' -fill '#102340' -draw 'polygon 1160,0 1920,0 1920,610 1510,740' \
        -fill '#0D3350' -draw 'polygon 0,720 610,600 820,1080 0,1080' -fill '#44D0C5' -draw 'rectangle 76,92 210,100' \
        -fill '#44D0C5' -font "$font_bold" -pointsize 24 -kerning 7 -annotate +76+150 'SCIDECS CONNECT' \
        -fill white -font "$font_bold" -pointsize 68 -annotate +76+252 "$title" "$card"
    if [[ "$mode" == operations ]]; then
        magick "$card" -fill '#FFFFFFF2' -draw 'roundrectangle 76,354 618,788 28,28 roundrectangle 689,354 1231,788 28,28 roundrectangle 1302,354 1844,788 28,28' \
            -fill '#44D0C5' -font "$font_bold" -pointsize 22 -annotate +116+415 '01  MASTERS' -fill '#B04A99' -annotate +729+415 '02  VOUCHERS' \
            -fill '#E3A72F' -annotate +1342+415 '03  INVENTORY' -fill '#08162F' -pointsize 34 -annotate +116+477 'Structured once.' \
            -annotate +729+477 'Posted with context.' -annotate +1342+477 'Moved with traceability.' -font "$font_regular" -pointsize 26 -fill '#40506A' \
            -annotate +116+548 'Parties, ledgers, products\nunits, taxes, godowns\nand cost centres' \
            -annotate +729+548 'Sales, purchases, returns\nreceipts, payments, journals\ncontra and GST ledgers' \
            -annotate +1342+548 'Opening stock, adjustments\nwarehouse transfers\nand Stock Journal allocations' \
            -fill white -font "$font_bold" -pointsize 28 -annotate +110+944 '20 SYNC ENTITY TYPES' -fill '#44D0C5' -annotate +560+944 'NATIVE TALLY XML' \
            -fill white -annotate +1010+944 'DIRECT OR PRIVATE-LAN AGENT' "$card"
    else
        magick "$card" -fill '#FFFFFFF2' -draw 'roundrectangle 76,354 1210,800 30,30' -fill '#44D0C5' -draw 'roundrectangle 1284,354 1844,800 30,30' \
            -fill '#08162F' -font "$font_bold" -pointsize 70 -annotate +1340+500 'SAFE' -pointsize 38 -annotate +1340+570 'TO REPLAY' -annotate +1340+630 'EASY TO AUDIT' \
            -fill '#08162F' -font "$font_bold" -pointsize 31 -annotate +122+435 '01  Durable queue + idempotency' \
            -annotate +122+525 '02  GUID / AlterID identity mapping' -annotate +122+615 '03  Logs, retry evidence + quarantine' \
            -annotate +122+705 '04  Watermarks, echo protection + conflict policy' -fill '#C9D7F0' -font "$font_regular" -pointsize 25 \
            -annotate +78+946 'A FAILED RECORD BECOMES VISIBLE WORK — NOT SILENT DATA LOSS.' "$card"
    fi
}

render_card() {
    local mode="$1" duration="$2" title="$3" out="$4"
    local card="$work_dir/$mode.png"
    make_editorial_card "$mode" "$title" "$card"
    ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i "$card" -t "$duration" \
        -vf "zoompan=z='min(zoom+0.00018,1.018)':d=1:s=1920x1080:fps=30,fade=t=in:st=0:d=0.25,fade=t=out:st=$(awk -v d="$duration" 'BEGIN{print d-0.25}'):d=0.25" \
        -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$out"
}

source_for_mode() {
    case "$1" in
        odoo_config) echo "$source_dir/odoo_entity_configuration.mp4" ;;
        odoo_live) echo "$source_dir/odoo_product_create.mp4" ;;
        odoo_queue) echo "$source_dir/odoo_outbound_queue.mp4" ;;
        odoo_logs) echo "$source_dir/odoo_sync_logs.mp4" ;;
        tally_config) echo "$source_dir/tally_company_features.mp4" ;;
        tally_stock_detail) echo "$source_dir/tally_stock_item_detail_v2.mp4" ;;
        tally_voucher) echo "$source_dir/tally_receipt_voucher.mp4" ;;
        *) return 1 ;;
    esac
}

render_live() {
    local mode="$1" duration="$2" title="$3" out="$4" source
    local overlay="$work_dir/${mode}_overlay.png"
    source="$(source_for_mode "$mode")"
    make_brand_overlay "$title" "$overlay"
    ffmpeg -hide_banner -loglevel error -y -i "$source" -loop 1 -i "$overlay" -t "$duration" \
        -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=120,trim=duration=${duration},setpts=PTS-STARTPTS[base];[base][1:v]overlay=0:0[v]" \
        -map '[v]' -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$out"
}

render_split() {
    local duration="$1" title="$2" out="$3" overlay="$work_dir/split_overlay.png"
    make_brand_overlay "$title" "$overlay" yes
    ffmpeg -hide_banner -loglevel error -y -i "$source_dir/odoo_sync_now.mp4" -i "$source_dir/tally_stock_item_walkthrough.mp4" -loop 1 -i "$overlay" \
        -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=120,scale=938:528,setsar=1[left];[1:v]tpad=stop_mode=clone:stop_duration=120,scale=938:528,setsar=1[right];color=c=${navy}:s=1920x1080:r=30:d=${duration}[bg];[bg][left]overlay=22:198[tmp];[tmp][right]overlay=960:198[tmp2];[tmp2][2:v]overlay=0:0[v]" \
        -map '[v]' -t "$duration" -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$out"
}

render_banner() {
    local duration="$1" title="$2" out="$3" banner="$repo_dir/tally_integration/static/description/raw_banner.png" overlay="$work_dir/banner_overlay.png"
    make_brand_overlay "$title" "$overlay"
    ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i "$banner" -loop 1 -i "$overlay" -t "$duration" \
        -filter_complex "[0:v]scale=1920:960:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=${navy},zoompan=z='min(zoom+0.00022,1.022)':d=1:s=1920x1080:fps=30[base];[base][1:v]overlay=0:0,fade=t=in:st=0:d=0.3,fade=t=out:st=$(awk -v d="$duration" 'BEGIN{print d-0.3}'):d=0.3[v]" \
        -map '[v]' -an -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p "$out"
}

scene_number=0
timeline_ms=0
while IFS='|' read -r scene_id scene_title scene_mode narration <&3; do
    [[ -z "$scene_id" || "$scene_id" == \#* ]] && continue
    scene_number=$((scene_number + 1))
    voice_file="$work_dir/scene_$scene_id.mp3"
    visual_file="$work_dir/scene_${scene_id}_visual.mp4"
    segment_file="$work_dir/scene_$scene_id.mp4"
    "$edge_tts_bin" --voice "$voice_name" --rate="$voice_rate" --pitch="$voice_pitch" --text "$narration" --write-media "$voice_file"
    speech_seconds="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$voice_file")"
    clip_seconds="$(awk -v d="$speech_seconds" 'BEGIN{printf "%.3f", d+0.75}')"
    clip_ms="$(awk -v d="$clip_seconds" 'BEGIN{printf "%d", d*1000}')"
    case "$scene_mode" in
        intro|outro) render_banner "$clip_seconds" "$scene_title" "$visual_file" ;;
        operations|reliability) render_card "$scene_mode" "$clip_seconds" "$scene_title" "$visual_file" ;;
        split_live) render_split "$clip_seconds" "$scene_title" "$visual_file" ;;
        *) render_live "$scene_mode" "$clip_seconds" "$scene_title" "$visual_file" ;;
    esac
    ffmpeg -hide_banner -loglevel error -y -i "$visual_file" -i "$voice_file" -t "$clip_seconds" \
        -map 0:v:0 -map 1:a:0 -af "highpass=f=75,acompressor=threshold=-18dB:ratio=2.2:attack=15:release=180,loudnorm=I=-16:TP=-1.5:LRA=8,apad=pad_dur=0.75" \
        -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 -shortest "$segment_file"
    printf "file '%s'\n" "$segment_file" >>"$work_dir/concat.txt"
    { printf '%d\n' "$scene_number"; printf '%s --> %s\n' "$(format_srt_time "$((timeline_ms + 120))")" "$(format_srt_time "$((timeline_ms + clip_ms - 250))")"; printf '%s\n\n' "$narration"; } >>"$work_dir/explainer.srt"
    timeline_ms=$((timeline_ms + clip_ms))
done 3<"$scene_file"

base_video="$work_dir/base.mp4"
final_video="$output_dir/scidecs_odoo_tally_live_sync_explainer.mp4"
subtitle_file="$output_dir/scidecs_odoo_tally_live_sync_explainer.srt"
cover_file="$output_dir/scidecs_odoo_tally_live_sync_explainer_cover.jpg"
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$work_dir/concat.txt" -c copy "$base_video"
cp "$work_dir/explainer.srt" "$subtitle_file"
ffmpeg -hide_banner -loglevel error -y -i "$base_video" -i "$subtitle_file" -map 0:v:0 -map 0:a:0 -map 1:0 \
    -c:v copy -c:a copy -c:s mov_text -metadata:s:s:0 language=eng -metadata:s:s:0 title="English" -movflags +faststart "$final_video"
magick "$repo_dir/tally_integration/static/description/raw_banner.png" -resize 1920x1080 -background '#08162F' -gravity center -extent 1920x1080 -quality 92 "$cover_file"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$final_video"
printf 'Created %s\nCreated %s\nCreated %s\n' "$final_video" "$subtitle_file" "$cover_file"
