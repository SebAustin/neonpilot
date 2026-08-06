# neonpilot demo video — segment 5: `neonpilot compare` (the two real M1 Max load-regime runs)
#
# Deviation from the literal DEMO-SCRIPT.md command: --out points at launch/video/tmp (gitignored
# scratch space) instead of defaulting into docs/results/m1-max-loaded-20260720/, so recording
# this video never writes generated compare.md/compare.html into a committed docs directory.
# The inputs (both run_dir arguments) are the real, already-committed case-study artifacts.

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
Type "cd '/Users/sebastienhenry/Documents/Hackathons/Arm Create- AI Optimization Challenge/neonpilot' && clear && mkdir -p launch/video/tmp/compare-out"
Enter
Sleep 500ms
Show

Type "uv run neonpilot compare docs/results/m1-max-loaded-20260720 docs/results/m1-max-moderate-load-20260806 --out launch/video/tmp/compare-out"
Enter
Sleep 1500ms
Type "sed -n '19,38p' launch/video/tmp/compare-out/compare.md"
Enter
Sleep 8s
