@echo off
rem Controle qu'Archi marche vraiment sur ce PC, de bout en bout (a lancer pendant qu'Archi tourne).
title Verifier Archi
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\verifier.ps1" %*
echo.
pause
