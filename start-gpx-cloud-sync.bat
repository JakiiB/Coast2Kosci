@echo off
title Coast2Kosci - Google Drive GPX Cloud Sync
cd /d "%~dp0"
echo Starting C2K Google Drive GPX Watcher (Crew + Simon)...
python scripts\sync_gpx_folder.py --watch --interval 20
pause
