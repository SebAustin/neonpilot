# neonpilot demo video — segment 4: `neonpilot report`
#
# Renders report.md + report.html from the real run recorded in segment 3
# (~/.neonpilot/runs/latest at recording time -- resolved explicitly below so this tape stays
# reproducible even after newer runs exist). The HTML report itself is captured separately via
# headless Chrome (see assemble.sh) for the Ken Burns pan portion of this segment.

Output "segments/04-report-raw.mp4"

Set Shell "zsh"
Set FontSize 26
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

Type "uv run neonpilot report --run-dir ~/.neonpilot/runs/20260806T122814Z"
Enter
Sleep 5s
