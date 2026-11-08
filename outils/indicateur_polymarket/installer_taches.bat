@echo off
title Indicateur Polymarket - taches de nuit
rem Installe les deux passages de nuit de l'indicateur Polymarket (lecture seule des cotes publiques) : 2 h et 6 h.
rem Chaque passage note les gros mouvements pour le brief de 14 h et envoie une alerte Telegram seulement si c'est tres fort.
if defined ARCHI_PYW (set "PYW=%ARCHI_PYW%") else (set "PYW=pythonw")
set OUTIL=%~dp0indicateur_polymarket.py
schtasks /create /tn "Archi - Polymarket 2h" /tr "\"%PYW%\" \"%OUTIL%\" --passe" /sc daily /st 02:00 /f
if %ERRORLEVEL% neq 0 goto rate
schtasks /create /tn "Archi - Polymarket 6h" /tr "\"%PYW%\" \"%OUTIL%\" --passe" /sc daily /st 06:00 /f
if %ERRORLEVEL% neq 0 goto rate
echo.
echo Taches installees : chaque nuit a 2 h et a 6 h.
exit /b 0
:rate
echo ERREUR : la tache n a pas pu etre creee.
exit /b 1
