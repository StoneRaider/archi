@echo off
rem Lance Archi (n8n + serveur + boite Docker) avec les reglages du fichier .env
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lancer_archi.ps1" %*
pause
