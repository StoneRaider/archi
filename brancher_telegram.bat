@echo off
rem Branche un bot Telegram personnel sur Archi, pas a pas (2 minutes). En option : Archi marche sans.
title Brancher Telegram sur Archi
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\telegram.ps1"
echo.
pause
