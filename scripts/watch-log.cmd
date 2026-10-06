@echo off
rem Show the Homyy log live (Ctrl+C or closing the window does not stop Homyy).
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -Encoding UTF8 -Wait -Tail 30 \"%~dp0..\agent\homyy.log\""
