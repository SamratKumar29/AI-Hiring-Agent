@echo off
rem Double-click to start the AI Hiring Agent web interface (runs inside WSL). Close this window to stop it.
wsl.exe -e bash -lc "cd \"$(wslpath -a '%~dp0')\" && ./start_ui.sh"
