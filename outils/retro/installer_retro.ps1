# installer_retro.ps1 - installe les moteurs d'analyse pour l'outil retro.
# On NE FAIT QUE telecharger des outils libres. Rien de secret n'est lu ni ecrit.
# Rapport : .local\install_retro.txt
$ErrorActionPreference = "Continue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ici = Split-Path -Parent $MyInvocation.MyCommand.Path
$moteurs = Join-Path $ici "moteurs"
$localdir = Join-Path $ici ".local"
New-Item -ItemType Directory -Force -Path $moteurs, $localdir | Out-Null
$log = Join-Path $localdir "install_retro.txt"
Start-Transcript -Path $log -Force | Out-Null

function Etape($t){ Write-Host ""; Write-Host ("===== " + $t + " =====") }
function OK($t){ Write-Host ("[OK] " + $t) }
function KO($t){ Write-Host ("[ECHEC] " + $t) }
function Dossier($parent, $motif){
  Get-ChildItem $parent -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -like $motif } | Select-Object -First 1
}

Write-Host ("Installateur retro - " + (Get-Date))

# --- 1. Node 24 portable (pour REA, sans toucher au Node global) ---
Etape "1. Node 24 portable"
$nodeHome = $null
$d = Dossier (Join-Path $moteurs "node") "node-v24*"
if ($d) { $nodeHome = $d.FullName; OK ("Deja present : " + $nodeHome) }
else {
  try {
    $idx = Invoke-RestMethod -UseBasicParsing "https://nodejs.org/dist/index.json"
    $v = ($idx | Where-Object { $_.version -like "v24.*" } | Select-Object -First 1).version
    $url = "https://nodejs.org/dist/$v/node-$v-win-x64.zip"
    $zip = Join-Path $env:TEMP ("node-" + $v + ".zip")
    Write-Host ("Telechargement " + $url)
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
    New-Item -ItemType Directory -Force -Path (Join-Path $moteurs "node") | Out-Null
    Expand-Archive -Path $zip -DestinationPath (Join-Path $moteurs "node") -Force
    Remove-Item $zip -Force
    $d = Dossier (Join-Path $moteurs "node") "node-v24*"
    if ($d) { $nodeHome = $d.FullName; OK ("Installe : " + $nodeHome) }
  } catch { KO ("Node : " + $_.Exception.Message) }
}
$nodeExe = $null; $npmCmd = $null
if ($nodeHome) { $nodeExe = Join-Path $nodeHome "node.exe"; $npmCmd = Join-Path $nodeHome "npm.cmd"; $env:Path = $nodeHome + ";" + $env:Path }
if ($nodeExe -and (Test-Path $nodeExe)) { Write-Host ("Version Node : " + (& $nodeExe -v)) }

# --- 2. Bibliotheques Python du venv ---
Etape "2. Bibliotheques Python d'analyse (venv d'Archi)"
$py = Join-Path $env:USERPROFILE ".n8n\assistant\assistant-main\venv\Scripts\python.exe"
if (-not (Test-Path $py)) { KO ("Python du venv introuvable : " + $py) }
else {
  & $py -m pip install --upgrade pip 2>&1 | Out-Host
  & $py -m pip install --upgrade pefile lief capstone pyinstxtractor-ng 2>&1 | Out-Host
  if ($LASTEXITCODE -eq 0) { OK "pefile, lief, capstone, pyinstxtractor-ng" } else { KO "pip a renvoye une erreur (voir au dessus)" }
}

# --- 3. REA en local, sans Node global ---
Etape "3. REA (Reverse Engineer Anything) en local"
$reaDir = Join-Path $moteurs "rea"
$reaMjs = Join-Path $reaDir "node_modules\rea-agents\scripts\rea.mjs"
if (-not $npmCmd -or -not (Test-Path $npmCmd)) { KO "npm portable indisponible : etape REA sautee (voir etape 1)" }
elseif (Test-Path $reaMjs) { OK "REA deja installe" }
else {
  New-Item -ItemType Directory -Force -Path $reaDir | Out-Null
  Push-Location $reaDir
  if (-not (Test-Path (Join-Path $reaDir "package.json"))) { & $npmCmd init -y 2>&1 | Out-Host }
  Write-Host "Installation de rea-agents (quelques minutes)..."
  & $npmCmd install rea-agents --no-fund --no-audit 2>&1 | Out-Host
  Pop-Location
  if (Test-Path $reaMjs) { OK "rea-agents installe" } else { KO "rea.mjs introuvable apres installation" }
}

# --- 4. Moteur Android (jadx-headless-mcp, pour les APK) ---
Etape "4. Moteur Android (jadx-headless-mcp)"
$jadxDir = Join-Path $moteurs "jadx"
$jadxJar = Join-Path $jadxDir "jadx-headless-mcp-0.7.1-all.jar"
$jadxSha = "6e5eacf500b64292bfb73c49797c1958f6ee44646e43e868039ae7feb573ff75"
New-Item -ItemType Directory -Force -Path $jadxDir | Out-Null
if (Test-Path $jadxJar) { OK "Deja present : jadx-headless-mcp 0.7.1" }
else {
  $u = "https://github.com/1013503897/jadx-headless-mcp/releases/download/v0.7.1/jadx-headless-mcp-0.7.1-all.jar"
  Write-Host ("Telechargement " + $u)
  try { Invoke-WebRequest -UseBasicParsing -Uri $u -OutFile $jadxJar } catch { KO ("jadx : " + $_.Exception.Message) }
}
if (Test-Path $jadxJar) {
  $h = (Get-FileHash -Algorithm SHA256 $jadxJar).Hash.ToLowerInvariant()
  if ($h -eq $jadxSha) { OK "JAR verifie (SHA-256 conforme a REA)" }
  else { KO ("SHA-256 different - JAR supprime (attendu " + $jadxSha + ")"); Remove-Item $jadxJar -Force }
}

# --- 5. Raccourcis (ecrits seulement s'ils manquent) ---
Etape "5. Raccourcis rea.cmd / rea-setup.cmd"
$reacmd = @'
@echo off
setlocal
set "RETRO=%~dp0"
set "NODE="
for /d %%N in ("%RETRO%node\node-v24*") do set "NODE=%%N\node.exe"
set "REAMJS=%RETRO%rea\node_modules\rea-agents\scripts\rea.mjs"
if exist "%RETRO%jadx\jadx-headless-mcp-0.7.1-all.jar" set "REA_JADX_MCP_JAR=%RETRO%jadx\jadx-headless-mcp-0.7.1-all.jar"
for /d %%D in ("%RETRO%ghidra\ghidra_*") do set "GHIDRA_INSTALL_DIR=%%D"
for /d %%J in ("%RETRO%jdk\jdk-21*") do set "JAVA_HOME=%%J"
if not defined NODE (
  echo [ERREUR] Node portable introuvable. Relance installer_retro.bat.
  exit /b 1
)
"%NODE%" "%REAMJS%" %*
'@
$reasetup = @'
@echo off
setlocal
set "RETRO=%~dp0"
set "NODE="
for /d %%N in ("%RETRO%node\node-v24*") do set "NODE=%%N\node.exe"
set "REAMJS=%RETRO%rea\node_modules\rea-agents\scripts\rea.mjs"
if exist "%RETRO%jadx\jadx-headless-mcp-0.7.1-all.jar" set "REA_JADX_MCP_JAR=%RETRO%jadx\jadx-headless-mcp-0.7.1-all.jar"
for /d %%D in ("%RETRO%ghidra\ghidra_*") do set "GHIDRA_INSTALL_DIR=%%D"
for /d %%J in ("%RETRO%jdk\jdk-21*") do set "JAVA_HOME=%%J"
if not defined NODE (
  echo [ERREUR] Node portable introuvable. Relance installer_retro.bat.
  exit /b 1
)
echo IMPORTANT : ferme completement Claude Desktop AVANT de continuer.
pause
"%NODE%" "%REAMJS%" setup %*
pause
'@
if (-not (Test-Path (Join-Path $moteurs "rea.cmd"))) { Set-Content -Path (Join-Path $moteurs "rea.cmd") -Value $reacmd -Encoding ascii; OK "rea.cmd cree" } else { OK "rea.cmd deja present" }
if (-not (Test-Path (Join-Path $moteurs "rea-setup.cmd"))) { Set-Content -Path (Join-Path $moteurs "rea-setup.cmd") -Value $reasetup -Encoding ascii; OK "rea-setup.cmd cree" } else { OK "rea-setup.cmd deja present" }

# --- Diagnostic ---
Etape "Diagnostic REA (rea doctor)"
if ($nodeExe -and (Test-Path $reaMjs)) { & $nodeExe $reaMjs doctor --json 2>&1 | Out-Host }

Etape "FIN"
Write-Host "Android (APK) : pret si l'etape 4 est [OK]."
Write-Host "Connecter REA a l'expert : lance moteurs\rea-setup.cmd (ferme Claude Desktop avant)."
Write-Host "Moteur natif (Ghidra, pour les .exe) : lance installer_ghidra.bat (gros telechargement)."
Stop-Transcript | Out-Null
