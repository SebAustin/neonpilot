# neonpilot demo video — segment 3: `neonpilot optimize` (the staged sweep, real run)
#
# This is a genuine ~90s `neonpilot optimize` run against the tiny SmolLM2-135M model
# (--budget 120 --reps 2, deviating from DEMO-SCRIPT.md's --budget 180/--reps 3 purely for
# recording time; see the producer's deviation notes). Nothing here is scripted or faked —
# assemble.sh speed-ramps the real dead-air middle in post (ffmpeg setpts), it does not alter
# what the CLI actually printed.
#
# Note: the current CLI prints a header + warning line immediately, then nothing until the
# final summary (no live per-trial table exists in this build) — so the "middle" of this
# recording is a genuinely idle terminal, not a redacted live table. Captions carry the
# stage-by-stage narrative (A: threads -> B: attention/KV-cache -> C: batch -> confirm) over
# that real dead air instead.

Output "segments/03-optimize-raw.mp4"

Set Shell "zsh"
Set FontSize 24
Set FontFamily "Menlo"
Set Width 1920
Set Height 1080
Set Padding 40
Set Theme "Dracula"
Set TypingSpeed 50ms

Hide
Type "cd '/Users/sebastienhenry/Documents/Hackathons/Arm Create- AI Optimization Challenge/neonpilot' && clear"
Enter
Sleep 500ms
Show

Type "uv run neonpilot optimize ~/.neonpilot/models/SmolLM2-135M-Instruct-Q4_K_M.gguf --budget 120 --reps 2"
Enter
Sleep 2s
Wait+Screen@200s /run dir:/
Sleep 4s
