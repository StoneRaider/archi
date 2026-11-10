@echo off
rem Installe Archi en un double-clic. Tout se pose dans UN dossier (voir README.md) ; rien n'est installe pour tout Windows.
title Installer Archi
cd /d "%~dp0"
if not exist "%~dp0installer\installer.ps1" goto pas_decompresse
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0installer\installer.ps1" %*
echo.
pause
exit /b

:pas_decompresse
echo.
echo  Decompresse d'abord TOUT le ZIP : clic droit sur le ZIP, puis "Extraire tout".
echo  Ensuite, relance installation.bat depuis le dossier extrait.
echo.
pause
exit /b 1
