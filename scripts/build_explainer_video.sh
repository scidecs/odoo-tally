#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
scene_file="$repo_dir/Docs/video/explainer_scenes.txt"
source_dir="$repo_dir/Docs/video/source"
output_dir="$repo_dir/Docs/media"
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/odoo-tally-live-video.XXXXXX")"
voice_name="${VOICE_NAME:-Tara}"
voice_rate="${VOICE_RATE:-184}"
font_regular="${VIDEO_FONT_REGULAR:-/System/Library/Fonts/Supplemental/Arial.ttf}"
font_bold="${VIDEO_FONT_BOLD:-/System/Library/Fonts/Supplemental/Arial Bold.ttf}"
navy="0x08162F"
teal="0x44D0C5"

cleanup() { rm -rf "$work_dir"; }
trap cleanup EXIT

for tool in ffmpeg ffprobe say magick; do
    command -v "$tool" >/dev/null || { printf 'Required tool not found: %s\n' "$tool" >&2; exit 1; }
done
for file in "$font_regular" "$font_bold" "$scene_file" \
    "$source_dir/odoo_product_create.mp4" \
    "$source_dir/tally_stock_item_arrival.mp4" \
    "$source_dir/tally_stock_item_detail.mp4"; do
    test -f "$file" || { printf 'Required video source not found: %s\n' "$file" >&2; exit 1; }
done

mkdir -p "$output_dir"
: >"$work_dir/concat.txt"
: >"$work_dir/explainer.srt"

format_srt_time() {
    local total_ms="$1"
    printf '%02d:%02d:%02d,%03d' "$((total_ms / 3600000))" \
        "$(((total_ms % 3600000) / 60000))" "$(((total_ms % 60000) / 1000))" "$((total_ms % 1000))"
}

make_brand_overlay() {
    local title="$1" overlay="$2" split="${3:-no}"
    magick -size 1920x1080 xc:none \
        -fill '#08162FF5' -stroke none -draw 'rectangle 0,0 1920,92 rectangle 0,1036 1920,1080' \
        -fill white -font "$font_bold" -pointsize 38 -annotate +56+60 "$title" \
        -fill '#44D0C5' -pointsize 25 -annotate +1750+58 'SCIDECS' \
        -fill white -font "$font_regular" -pointsize 22 -annotate +54+1067 'Free LGPL-3 connector  |  scidecs.com' "$overlay"
    if [[ "$split" == "yes" ]]; then
        magick "$overlay" \
            -fill '#6C63FF' -draw 'rectangle 22,154 960,205' \
            -fill '#44D0C5' -draw 'rectangle 960,154 1898,205' \
            -fill white -font "$font_bold" -pointsize 25 -annotate +50+188 'ODOO 19 - SOURCE' \
            -fill '#08162F' -annotate +988+188 'TALLYPRIME - SYNCHRONIZED' "$overlay"
    fi
}

make_card() {
    local mode="$1" title="$2" card="$3"
    magick -size 1920x1080 xc:'#08162F' -fill white -font "$font_bold" -pointsize 58 \
        -annotate +70+100 "$title" -fill '#44D0C5' -font "$font_bold" -pointsize 28 \
        -gravity northeast -annotate +55+42 'SCIDECS' -gravity northwest "$card"
    case "$mode" in
        architecture)
            magick "$card" \
                -stroke '#44D0C5' -strokewidth 4 -fill '#102948' -draw 'roundrectangle 110,330 460,520 24,24' \
                -stroke '#8E88FF' -fill '#172453' -draw 'roundrectangle 685,330 1235,520 24,24' \
                -stroke '#44D0C5' -fill '#102948' -draw 'roundrectangle 1460,330 1810,520 24,24' \
                -stroke none -fill white -font "$font_bold" -pointsize 52 -annotate +170+435 'ODOO 19' \
                -pointsize 46 -annotate +755+435 'DURABLE QUEUE' -annotate +1492+435 'TALLYPRIME' \
                -fill '#44D0C5' -pointsize 34 -annotate +500+430 '<  EVENTS' -annotate +1260+430 'NATIVE XML  >' \
                -fill '#C9D7F0' -font "$font_regular" -pointsize 34 -annotate +235+680 'Direct gateway or private-LAN agent   |   Per-entity ownership   |   Serialized bidirectional flow' "$card"
            ;;
        operations)
            magick "$card" -fill '#44D0C5' -font "$font_bold" -pointsize 38 \
                -annotate +120+310 'MASTERS' -annotate +710+310 'VOUCHERS' -annotate +1320+310 'INVENTORY' \
                -fill white -font "$font_regular" -pointsize 32 \
                -annotate +120+390 'Partners  |  Accounts  |  Products' -annotate +120+455 'Units  |  Categories  |  Taxes' -annotate +120+520 'Godowns  |  Cost centres' \
                -annotate +710+390 'Sales  |  Purchases  |  Returns' -annotate +710+455 'Payments  |  Receipts  |  Journals' -annotate +710+520 'Contra and GST structures' \
                -annotate +1320+390 'Opening stock  |  Adjustments' -annotate +1320+455 'Warehouse transfers' -annotate +1320+520 'Stock Journal allocations' \
                -stroke '#29466F' -strokewidth 3 -fill none -draw 'roundrectangle 80,245 625,610 20,20 roundrectangle 670,245 1260,610 20,20 roundrectangle 1280,245 1840,610 20,20' "$card"
            ;;
        reliability)
            magick "$card" -stroke none -fill '#44D0C5' -draw 'circle 180,340 235,340 circle 180,510 235,510 circle 180,680 235,680' \
                -fill '#08162F' -font "$font_bold" -pointsize 42 -annotate +168+355 '1' -annotate +168+525 '2' -annotate +168+695 '3' \
                -fill white -pointsize 42 -annotate +290+355 'Durable queue and idempotency' -annotate +290+525 'GUID / AlterID identity mapping' -annotate +290+695 'Logs, retry evidence and quarantine' \
                -fill '#C9D7F0' -font "$font_regular" -pointsize 38 -annotate +1190+530 'Recoverable.\nObservable.\nControlled.' "$card"
            ;;
        *) printf 'Unknown card mode: %s\n' "$mode" >&2; exit 1 ;;
    esac
}

render_card() {
    local mode="$1" duration="$2" title="$3" out="$4"
    local card="$work_dir/${mode}.png"
    make_card "$mode" "$title" "$card"
    ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i "$card" -t "$duration" \
        -vf "zoompan=z='min(zoom+0.00025,1.025)':d=1:s=1920x1080:fps=30,fade=t=in:st=0:d=0.25,fade=t=out:st=$(awk -v d="$duration" 'BEGIN{print d-0.25}'):d=0.25" \
        -an -c:v libx264 -preset medium -crf 21 -pix_fmt yuv420p "$out"
}

render_live() {
    local mode="$1" duration="$2" title="$3" out="$4" source
    local overlay="$work_dir/${mode}_overlay.png"
    case "$mode" in
        odoo_live) source="$source_dir/odoo_product_create.mp4" ;;
        tally_live) source="$source_dir/tally_stock_item_detail.mp4" ;;
        *) printf 'Unknown live mode: %s\n' "$mode" >&2; exit 1 ;;
    esac
    make_brand_overlay "$title" "$overlay"
    ffmpeg -hide_banner -loglevel error -y -i "$source" -loop 1 -i "$overlay" -t "$duration" \
        -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=60,trim=duration=${duration},setpts=PTS-STARTPTS[base];[base][1:v]overlay=0:0[v]" \
        -map '[v]' -an -c:v libx264 -preset medium -crf 21 -pix_fmt yuv420p "$out"
}

render_split() {
    local duration="$1" title="$2" out="$3" overlay="$work_dir/split_overlay.png"
    make_brand_overlay "$title" "$overlay" yes
    ffmpeg -hide_banner -loglevel error -y \
        -sseof -0.10 -i "$source_dir/odoo_product_create.mp4" -i "$source_dir/tally_stock_item_arrival.mp4" -loop 1 -i "$overlay" \
        -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=60,scale=938:528,setsar=1[left];[1:v]tpad=stop_mode=clone:stop_duration=60,trim=duration=${duration},setpts=PTS-STARTPTS,scale=938:528,setsar=1[right];color=c=${navy}:s=1920x1080:r=30:d=${duration}[bg];[bg][left]overlay=22:205[tmp];[tmp][right]overlay=960:205[tmp2];[tmp2][2:v]overlay=0:0[v]" \
        -map '[v]' -t "$duration" -an -c:v libx264 -preset medium -crf 21 -pix_fmt yuv420p "$out"
}

render_banner() {
    local duration="$1" title="$2" out="$3" banner="$repo_dir/tally_integration/static/description/raw_banner.png" overlay="$work_dir/banner_overlay.png"
    make_brand_overlay "$title" "$overlay"
    ffmpeg -hide_banner -loglevel error -y -loop 1 -framerate 30 -i "$banner" -loop 1 -i "$overlay" -t "$duration" \
        -filter_complex "[0:v]scale=1920:960:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=${navy},zoompan=z='min(zoom+0.0003,1.03)':d=1:s=1920x1080:fps=30[base];[base][1:v]overlay=0:0,fade=t=in:st=0:d=0.35,fade=t=out:st=$(awk -v d="$duration" 'BEGIN{print d-0.35}'):d=0.35[v]" \
        -map '[v]' -an -c:v libx264 -preset medium -crf 21 -pix_fmt yuv420p "$out"
}

scene_number=0
timeline_ms=0
while IFS='|' read -r scene_id scene_title scene_mode narration <&3; do
    [[ -z "$scene_id" || "$scene_id" == \#* ]] && continue
    scene_number=$((scene_number + 1))
    voice_file="$work_dir/scene_${scene_id}.aiff"
    visual_file="$work_dir/scene_${scene_id}_visual.mp4"
    segment_file="$work_dir/scene_${scene_id}.mp4"
    say -v "$voice_name" -r "$voice_rate" -o "$voice_file" "$narration"
    speech_seconds="$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$voice_file")"
    clip_seconds="$(awk -v d="$speech_seconds" 'BEGIN{printf "%.3f", d+0.70}')"
    clip_ms="$(awk -v d="$clip_seconds" 'BEGIN{printf "%d", d*1000}')"

    case "$scene_mode" in
        intro|outro) render_banner "$clip_seconds" "$scene_title" "$visual_file" ;;
        architecture|operations|reliability) render_card "$scene_mode" "$clip_seconds" "$scene_title" "$visual_file" ;;
        odoo_live|tally_live) render_live "$scene_mode" "$clip_seconds" "$scene_title" "$visual_file" ;;
        split_live) render_split "$clip_seconds" "$scene_title" "$visual_file" ;;
        *) printf 'Unknown scene mode: %s\n' "$scene_mode" >&2; exit 1 ;;
    esac

    ffmpeg -hide_banner -loglevel error -y -i "$visual_file" -i "$voice_file" -t "$clip_seconds" \
        -map 0:v:0 -map 1:a:0 -af "highpass=f=80,lowpass=f=12000,loudnorm=I=-16:TP=-1.5:LRA=11,apad=pad_dur=0.70" \
        -c:v copy -c:a aac -b:a 160k -ar 48000 -ac 2 -shortest "$segment_file"
    printf "file '%s'\n" "$segment_file" >>"$work_dir/concat.txt"
    {
        printf '%d\n' "$scene_number"
        printf '%s --> %s\n' "$(format_srt_time "$((timeline_ms + 120))")" "$(format_srt_time "$((timeline_ms + clip_ms - 250))")"
        printf '%s\n\n' "$narration"
    } >>"$work_dir/explainer.srt"
    timeline_ms=$((timeline_ms + clip_ms))
done 3<"$scene_file"

base_video="$work_dir/explainer-base.mp4"
final_video="$output_dir/scidecs_odoo_tally_live_sync_explainer.mp4"
subtitle_file="$output_dir/scidecs_odoo_tally_live_sync_explainer.srt"
cover_file="$output_dir/scidecs_odoo_tally_live_sync_explainer_cover.jpg"
ffmpeg -hide_banner -loglevel error -y -f concat -safe 0 -i "$work_dir/concat.txt" -c copy "$base_video"
cp "$work_dir/explainer.srt" "$subtitle_file"
ffmpeg -hide_banner -loglevel error -y -i "$base_video" -i "$subtitle_file" \
    -map 0:v:0 -map 0:a:0 -map 1:0 -c:v copy -c:a copy -c:s mov_text \
    -metadata:s:s:0 language=eng -metadata:s:s:0 title="English" -movflags +faststart "$final_video"
magick "$repo_dir/tally_integration/static/description/raw_banner.png" -resize 1920x1080 \
    -background '#08162F' -gravity center -extent 1920x1080 -quality 92 "$cover_file"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$final_video"
printf 'Created %s\nCreated %s\nCreated %s\n' "$final_video" "$subtitle_file" "$cover_file"
