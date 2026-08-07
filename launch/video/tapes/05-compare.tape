# neonpilot demo video — segment 5: `neonpilot compare` (Apple M5 Pro vs. Apple M1 Max —
# cross-generation, real hardware)
#
# The literal DEMO-SCRIPT.md command, run for real: A = the just-landed Apple M5 Pro idle
# run (docs/results/m5-pro-idle-20260807/ -- i8mm/SME/SME2/BF16 all probed TRUE), B = the
# already-committed Apple M1 Max moderate-load run (docs/results/m1-max-moderate-load-20260806/
# -- same four features probed FALSE). --out points at launch/video/tmp/compare-m5 (gitignored
# scratch space) instead of a committed docs directory, so recording this video never writes
# generated compare.md/compare.html anywhere git-tracked. Both run_dir inputs are real,
# already-committed case-study artifacts -- nothing here is fabricated.
#
# Same GGUF (qwen2.5-3b-instruct-q4_k_m) on both machines, so this is an apples-to-apples
# cross-generation comparison, not just a load-regime comparison like the segment this replaces.

Output "segments/05-compare-raw.mp4"

Set Shell "zsh"
Set FontSize 24
Set FontFamily "Menlo"
Set Width 1920
Set Height 1080
Set Padding 40
Set Theme "Dracula"
Set TypingSpeed 45ms

Hide
Type "cd '/Users/sebastienhenry/Documents/Hackathons/Arm Create- AI Optimization Challenge/neonpilot' && clear"
Enter
Sleep 500ms
Show

Type "uv run neonpilot compare docs/results/m5-pro-idle-20260807 docs/results/m1-max-moderate-load-20260806 --out launch/video/tmp/compare-m5"
Enter
Sleep 1200ms

# Beat 1: the ISA feature table -- SME2/i8mm/BF16 probed true on the M5 Pro, false on the M1
# Max. Caption overlay window in assemble.sh is timed to this block (~t=9.7s-14.5s).
Type "sed -n '5,17p' launch/video/tmp/compare-m5/compare.md"
Enter
Sleep 4500ms

# Beat 2: M5 Pro throughput verdict -- idle machine, defaults already optimal, +0.0%, tuning
# preset REFUSED. Caption overlay window ~t=16.6s-22.5s.
Type "sed -n '19,29p' launch/video/tmp/compare-m5/compare.md"
Enter
Sleep 5500ms

# Beat 3: M1 Max throughput verdict -- loaded machine, +81.6% by adapting. Caption overlay
# window ~t=24.6s-29.5s.
Type "sed -n '31,39p' launch/video/tmp/compare-m5/compare.md"
Enter
Sleep 6s
