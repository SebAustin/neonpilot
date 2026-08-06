# neonpilot demo video — segment 2: `neonpilot probe`
#
# Real CLI execution, no fabricated output. Recorded on the Apple M1 Max reference machine.
# Post-processed by assemble.sh (trim/pad to the segment's 33s slot in the final cut, plus
# burned captions) — this tape only captures the raw footage.

Output "segments/02-probe-raw.mp4"

Set Shell "zsh"
Set FontSize 26
Set FontFamily "Menlo"
Set Width 1920
Set Height 1080
Set Padding 40
Set Theme "Dracula"
Set TypingSpeed 50ms

# Hidden setup: cd into the repo and clear scrollback. Not part of the demo narrative, so it
# is excluded from the recording entirely (VHS Hide/Show), not just visually trimmed later.
Hide
Type "cd '/Users/sebastienhenry/Documents/Hackathons/Arm Create- AI Optimization Challenge/neonpilot' && clear"
Enter
Sleep 500ms
Show

Type "uv run neonpilot probe"
Enter
Sleep 24s
