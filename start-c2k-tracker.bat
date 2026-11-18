@echo off
title Coast to Kosciuszko 240km // 3D Live Broadcast Tracker
cd /d "%~dp0"
echo Starting local C2K 3D Broadcast server on http://localhost:8240 ...
start "" "http://localhost:8240"
python -m http.server 8240
