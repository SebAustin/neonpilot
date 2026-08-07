#!/usr/bin/env bash
# neonpilot demo video -- assembly script (ffmpeg only, no drawtext/libass required).
#
# Pipeline (video-as-code, reproducible from source):
#   1. Record raw footage with VHS (real CLI execution, no fabricated output):
#        vhs tapes/02-probe.tape      (~1 min)
#        vhs tapes/03-optimize.tape   (~2-3 min -- the real staged sweep)
#        vhs tapes/04-report.tape     (~10s -- point it at the run dir tape 03 just printed)
#        vhs tapes/05-compare.tape    (~30s)
#   2. Run this script: bash assemble.sh
#      It captures the HTML report screenshot (headless Chrome), builds each of the 6
#      segments (title card / probe / optimize / report / compare / close card), burns in
#      captions (rendered as PNGs by make_caption.py/make_card.py and composited with
#      ffmpeg's `overlay` filter -- this ffmpeg build has no drawtext/libass, see
#      make_caption.py's docstring), and concatenates everything into neonpilot-demo.mp4.
#
# Resumability: step 1's raw *-raw.mp4 files and the report screenshot are treated as
# expensive, already-completed inputs -- this script errors out with a clear pointer back to
# the missing tape instead of silently re-recording (re-running the optimize sweep costs
# real minutes and produces a *different* real run every time). Re-run this script freely;
# it only touches gitignored segments/, assets/, and tmp/ output.
#
# Segment target durations (seconds) -- sum is 168s = 2:48, 2s under the 2:50 hard cap. Each
# segment is force-trimmed/padded to its target via `force_duration` so the final total is
# exact regardless of small VHS/ffmpeg timing jitter on a re-recording.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

RUN_DIR="${NEONPILOT_DEMO_RUN_DIR:-$HOME/.neonpilot/runs/20260806T122814Z}"
REPO_URL="github.com/SebAustin/neonpilot"

TITLE_DUR=12
PROBE_DUR=33
OPTIMIZE_DUR=55
REPORT_DUR=25
COMPARE_DUR=28
CLOSE_DUR=15

FPS=25
VCODEC_ARGS=(-c:v libx264 -profile:v high -pix_fmt yuv420p -r "$FPS")
ACODEC_ARGS=(-c:a aac -ar 48000 -ac 2 -b:a 128k)

mkdir -p segments assets tmp tmp/captions

log() { printf '\n=== %s ===\n' "$1"; }

require_file() {
  local path="$1" hint="$2"
  if [[ ! -s "$path" ]]; then
    echo "error: missing required input: $path" >&2
    echo "  -> $hint" >&2
    exit 1
  fi
}

# Pads (freeze-frame clone of the last real frame) or trims a video to exactly $2 seconds
# and attaches silent AAC audio. This is the last step before caption overlay for every
# segment, so the final concatenated duration is deterministic.
force_duration() {
  local in="$1" target="$2" out="$3"
  ffmpeg -y -v error -i "$in" \
    -f lavfi -i "anullsrc=r=48000:cl=stereo" \
    -filter_complex "[0:v]tpad=stop_mode=clone:stop_duration=${target}[vpad]" \
    -map "[vpad]" -map 1:a \
    -t "$target" "${VCODEC_ARGS[@]}" "${ACODEC_ARGS[@]}" -shortest "$out"
}

# Renders a lower-third caption PNG (idempotent -- keyed by a short slug, not by content hash,
# so re-running with edited caption text just re-renders it).
caption_png() {
  local slug="$1" text="$2"
  local out="tmp/captions/${slug}.png"
  python3 make_caption.py "$text" "$out"
  echo "$out"
}

################################################################################
# Segment 1: title card
################################################################################
log "1/6 title card"
python3 make_card.py tmp/title-card.png \
  --line "neonpilot" \
  --sub "auto-tune llama.cpp for the Arm chip you actually have" \
  --accent "$REPO_URL"

ffmpeg -y -v error -loop 1 -i tmp/title-card.png \
  -f lavfi -i "anullsrc=r=48000:cl=stereo" \
  -vf "fade=t=in:st=0:d=0.6,fade=t=out:st=$((TITLE_DUR - 1)):d=0.6,format=yuv420p" \
  -r "$FPS" "${VCODEC_ARGS[@]}" "${ACODEC_ARGS[@]}" -t "$TITLE_DUR" \
  segments/01-title-final.mp4

################################################################################
# Segment 2: probe
################################################################################
log "2/6 probe"
require_file segments/02-probe-raw.mp4 "run: vhs tapes/02-probe.tape"

force_duration segments/02-probe-raw.mp4 "$PROBE_DUR" tmp/02-probe-timed.mp4

CAP_PROBE=$(caption_png probe \
  "Probes your Arm CPU: NEON, dotprod, i8mm, SME2 -- and which llama.cpp fast paths engage.")

# Caption window is deliberately short (2s-12s, not the whole 33s) -- the ISA/fast-path
# tables run all the way to the bottom of the frame, so the lower-third caption box would
# otherwise sit over the last couple of table rows for the whole segment. This way the
# caption reads, then gets out of the way and leaves the real table fully visible.
ffmpeg -y -v error -i tmp/02-probe-timed.mp4 -i "$CAP_PROBE" \
  -filter_complex "[0:v][1:v]overlay=0:0:enable='between(t,2,12)',format=yuv420p[vout]" \
  -map "[vout]" -map 0:a "${VCODEC_ARGS[@]}" -c:a copy \
  segments/02-probe-final.mp4

################################################################################
# Segment 3: optimize (real ~90s sweep, speed-ramped in post)
################################################################################
log "3/6 optimize"
require_file segments/03-optimize-raw.mp4 "run: vhs tapes/03-optimize.tape (real ~2-3 min sweep)"

D3=$(ffprobe -v error -show_entries format=duration -of csv=p=0 segments/03-optimize-raw.mp4)
# Calibrated split points for this recording (TypingSpeed=50ms/char, fixed Sleep buffers make
# these deterministic run-to-run to within a fraction of a second): T1 is the end of the
# "start" 1x window (command finishes typing + the header/warning lines render); T2 is the
# start of the "end" 1x window, computed relative to the clip's *end* so it stays correct even
# if the real sweep's wall-clock time drifts a little on a re-recording.
T1=6.5
T2=$(python3 -c "print(max($T1 + 1, $D3 - 6.9))")
SPEED=5

ffmpeg -y -v error -i segments/03-optimize-raw.mp4 -filter_complex "
  [0:v]trim=0:${T1},setpts=PTS-STARTPTS[p1];
  [0:v]trim=${T1}:${T2},setpts=(PTS-STARTPTS)/${SPEED}[p2];
  [0:v]trim=${T2}:${D3},setpts=PTS-STARTPTS[p3];
  [p1][p2][p3]concat=n=3:v=1:a=0[vout]
" -map "[vout]" "${VCODEC_ARGS[@]}" -an tmp/03-optimize-ramped.mp4

force_duration tmp/03-optimize-ramped.mp4 "$OPTIMIZE_DUR" tmp/03-optimize-timed.mp4

# Stage captions tile across the sped-up middle window [T1, T2] in the *ramped* output's own
# timeline: output middle duration = (T2-T1)/SPEED, starting right at T1.
MID_START="$T1"
MID_DUR=$(python3 -c "print(($T2 - $T1) / $SPEED)")
MID_Q=$(python3 -c "print($MID_DUR / 4)")
A0=$(python3 -c "print($MID_START)")
A1=$(python3 -c "print($MID_START + $MID_Q)")
A2=$(python3 -c "print($MID_START + 2*$MID_Q)")
A3=$(python3 -c "print($MID_START + 3*$MID_Q)")
A4=$(python3 -c "print($MID_START + 4*$MID_Q)")

CAP_OPT_INTRO=$(caption_png opt-intro \
  "uv run neonpilot optimize -- a staged sweep, not a brute-force grid.")
CAP_OPT_A=$(caption_png opt-stage-a "Stage A: sweep thread count")
CAP_OPT_B=$(caption_png opt-stage-b "Stage B: flash-attention x KV-cache type")
CAP_OPT_C=$(caption_png opt-stage-c "Stage C: batch / ubatch size")
CAP_OPT_CONFIRM=$(caption_png opt-confirm "Confirm: baseline vs. winner, back-to-back")
CAP_OPT_HONEST=$(caption_png opt-honest \
  "Honest by design: this real run tripped the low-reps warning AND the statistical-caution flag -- both shown above, neither hidden.")

ffmpeg -y -v error -i tmp/03-optimize-timed.mp4 \
  -i "$CAP_OPT_INTRO" -i "$CAP_OPT_A" -i "$CAP_OPT_B" -i "$CAP_OPT_C" -i "$CAP_OPT_CONFIRM" -i "$CAP_OPT_HONEST" \
  -filter_complex "
    [0:v][1:v]overlay=0:0:enable='between(t,0.5,${A0})'[v1];
    [v1][2:v]overlay=0:0:enable='between(t,${A0},${A1})'[v2];
    [v2][3:v]overlay=0:0:enable='between(t,${A1},${A2})'[v3];
    [v3][4:v]overlay=0:0:enable='between(t,${A2},${A3})'[v4];
    [v4][5:v]overlay=0:0:enable='between(t,${A3},${A4})'[v5];
    [v5][6:v]overlay=0:0:enable='between(t,${A4},${OPTIMIZE_DUR}-1)',format=yuv420p[vout]
  " -map "[vout]" -map 0:a "${VCODEC_ARGS[@]}" -c:a copy \
  segments/03-optimize-final.mp4

################################################################################
# Segment 4: report (terminal command + Ken Burns pan over the real HTML report)
################################################################################
log "4/6 report"
require_file segments/04-report-raw.mp4 "run: vhs tapes/04-report.tape"

INTRO_DUR=8
KENBURNS_DUR=$((REPORT_DUR - INTRO_DUR))

if [[ ! -s assets/report-screenshot.png ]]; then
  require_file "$RUN_DIR/report.html" \
    "run 'uv run neonpilot report --run-dir $RUN_DIR' first (or set NEONPILOT_DEMO_RUN_DIR)"
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  require_file "$CHROME" "install Google Chrome, or supply assets/report-screenshot.png manually"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --window-size=1920,4200 \
    --screenshot="$(pwd)/tmp/report-full.png" --virtual-time-budget=3000 \
    "file://$RUN_DIR/report.html" >/dev/null 2>&1
  # Crop off the blank tail below the report's real content (found via a non-background-pixel
  # scan) so the Ken Burns pan doesn't spend time panning across empty space.
  LAST_ROW=$(python3 -c "
from PIL import Image
im = Image.open('tmp/report-full.png').convert('RGB')
w, h = im.size
bg = im.getpixel((5, 5))
px = im.load()
last = 200
for y in range(h - 1, -1, -1):
    if any(px[x, y] != bg for x in range(0, w, 20)):
        last = y
        break
print(min(h, last + 50))
")
  ffmpeg -y -v error -i tmp/report-full.png -vf "crop=1920:${LAST_ROW}:0:0" assets/report-screenshot.png
fi

SHOT_H=$(python3 -c "from PIL import Image; print(Image.open('assets/report-screenshot.png').size[1])")
ZOOM_W=2150
ZOOM_H=$(python3 -c "print(round($SHOT_H * $ZOOM_W / 1920))")
PAN_RANGE=$((ZOOM_H - 1080))
ZOOM_X=$(( (ZOOM_W - 1920) / 2 ))

ffmpeg -y -v error -i segments/04-report-raw.mp4 -t "$INTRO_DUR" \
  -vf "format=yuv420p" "${VCODEC_ARGS[@]}" -an tmp/04-report-intro.mp4

ffmpeg -y -v error -loop 1 -t "$KENBURNS_DUR" -i assets/report-screenshot.png \
  -vf "scale=${ZOOM_W}:${ZOOM_H},crop=1920:1080:${ZOOM_X}:'(${PAN_RANGE})*t/${KENBURNS_DUR}',format=yuv420p" \
  -r "$FPS" "${VCODEC_ARGS[@]}" -an tmp/04-report-kenburns.mp4

printf "file '04-report-intro.mp4'\nfile '04-report-kenburns.mp4'\n" > tmp/04-report-concat.txt
ffmpeg -y -v error -f concat -safe 0 -i tmp/04-report-concat.txt -c copy tmp/04-report-content.mp4

force_duration tmp/04-report-content.mp4 "$REPORT_DUR" tmp/04-report-timed.mp4

CAP_REPORT=$(caption_png report \
  "Self-contained report -- including recorded measurement conditions.")

# Caption window covers the terminal intro + the first few seconds of the Ken Burns pan only
# (not the full 25s) -- the pan keeps scrolling real report content under a fixed caption
# position, so a short window keeps the caption from sitting over the chart/table rows for
# most of the pan.
ffmpeg -y -v error -i tmp/04-report-timed.mp4 -i "$CAP_REPORT" \
  -filter_complex "[0:v][1:v]overlay=0:0:enable='between(t,1,11)',format=yuv420p[vout]" \
  -map "[vout]" -map 0:a "${VCODEC_ARGS[@]}" -c:a copy \
  segments/04-report-final.mp4

################################################################################
# Segment 5: compare (Apple M5 Pro vs. Apple M1 Max -- cross-generation, real hardware)
################################################################################
log "5/6 compare"
require_file segments/05-compare-raw.mp4 "run: vhs tapes/05-compare.tape"

force_duration segments/05-compare-raw.mp4 "$COMPARE_DUR" tmp/05-compare-timed.mp4

# Three caption beats, timed to the tape's fixed Type/Sleep buffers (TypingSpeed=45ms/char,
# deterministic run-to-run): the ISA feature table, then each machine's throughput verdict,
# in the order they scroll into view.
CAP_COMPARE_ISA=$(caption_png compare-isa \
  "M5 Pro: SME2, i8mm, BF16 -- probed, not assumed")
CAP_COMPARE_M5=$(caption_png compare-m5 \
  "Idle M5: defaults win -- neonpilot reports +0.0% rather than faking a speedup")
CAP_COMPARE_M1=$(caption_png compare-m1 \
  "Loaded M1 Max: +81.6% by adapting. Honest both ways.")

ffmpeg -y -v error -i tmp/05-compare-timed.mp4 \
  -i "$CAP_COMPARE_ISA" -i "$CAP_COMPARE_M5" -i "$CAP_COMPARE_M1" \
  -filter_complex "
    [0:v][1:v]overlay=0:0:enable='between(t,9.5,13.3)'[v1];
    [v1][2:v]overlay=0:0:enable='between(t,16.0,20.6)'[v2];
    [v2][3:v]overlay=0:0:enable='between(t,23.4,${COMPARE_DUR}-0.3)',format=yuv420p[vout]
  " -map "[vout]" -map 0:a "${VCODEC_ARGS[@]}" -c:a copy \
  segments/05-compare-final.mp4

################################################################################
# Segment 6: close card
################################################################################
log "6/6 close card"
python3 make_card.py tmp/close-card.png \
  --line "neonpilot" \
  --sub "Arm AI Optimization Challenge 2026 -- Mobile AI track" \
  --sub "Apache-2.0 -- $REPO_URL" \
  --accent "make benchmark"

ffmpeg -y -v error -loop 1 -i tmp/close-card.png \
  -f lavfi -i "anullsrc=r=48000:cl=stereo" \
  -vf "fade=t=in:st=0:d=0.6,fade=t=out:st=$((CLOSE_DUR - 1)):d=0.6,format=yuv420p" \
  -r "$FPS" "${VCODEC_ARGS[@]}" "${ACODEC_ARGS[@]}" -t "$CLOSE_DUR" \
  segments/06-close-final.mp4

################################################################################
# Final concat
################################################################################
log "concat -> neonpilot-demo.mp4"
SEG_DIR="$(pwd)/segments"
printf "file '%s/01-title-final.mp4'\nfile '%s/02-probe-final.mp4'\nfile '%s/03-optimize-final.mp4'\nfile '%s/04-report-final.mp4'\nfile '%s/05-compare-final.mp4'\nfile '%s/06-close-final.mp4'\n" \
  "$SEG_DIR" "$SEG_DIR" "$SEG_DIR" "$SEG_DIR" "$SEG_DIR" "$SEG_DIR" > tmp/final-concat.txt

ffmpeg -y -v error -f concat -safe 0 -i tmp/final-concat.txt -c copy neonpilot-demo.mp4

log "done"
ffprobe -v error -show_entries format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate \
  -of default=noprint_wrappers=1 neonpilot-demo.mp4
